"""Critic / Quality-Assurance agent.

Combines rule-based checks (which cannot hallucinate) with LLM audits run on a
*different* model from the one that produced the work:

rule-based
  * PRISMA flow arithmetic                    * PRISMA 2020 checklist coverage
  * citation integrity                        * share of uncited sentences
  * verification rate of extraction quotes    * included studies missing data

LLM audits
  * faithfulness of each thematic narrative against its evidence
  * overstatement in the discussion / abstract
  * re-screening of a random sample of excluded records (false-exclusion audit)
  * eligibility audit of the included studies against the protocol

Issues in writer-owned areas trigger a revision round; issues that only a human
can settle (screening, extraction) are reported, never silently "fixed".
"""

from __future__ import annotations

import random
import re

from pydantic import BaseModel, Field

from ..context import RunContext
from ..llm import LLMError
from ..models import Extraction, Protocol, QAIssue, QAReport, Record, RiskOfBias, ScreeningDecision, Theme
from ..rag.index import split_sentences
from ..tools.prisma import PrismaFlow, validate_checklist
from .extraction import quote_stats
from .planner import protocol_brief
from .screening import TA_SYSTEM, BatchVotes, _record_block
from .synthesis import study_card, theme_evidence

AGENT = "critic"
WRITER_AREAS = ("synthesis:", "discussion", "abstract", "rationale", "report")


class Unsupported(BaseModel):
    claim: str = Field(description="The sentence or number from the draft that is not supported")
    problem: str = Field(description="Why: absent from the evidence, contradicted, wrong number, wrong study cited")
    fix: str = Field(description="How to correct it using the evidence")


class Faithfulness(BaseModel):
    unsupported: list[Unsupported]


class Overstatement(BaseModel):
    section: str = Field(description="'discussion' or 'abstract'")
    claim: str
    problem: str
    fix: str


class Overstatements(BaseModel):
    problems: list[Overstatement]


class EligibilityFlag(BaseModel):
    rid: str
    criterion: str = Field(description="Id of the criterion that seems violated")
    reason: str


class EligibilityFlags(BaseModel):
    flags: list[EligibilityFlag]


def uncited_ratio(narrative: str) -> float:
    sentences = [s for s in split_sentences(narrative) if len(s.split()) >= 6]
    if not sentences:
        return 0.0
    return sum(1 for s in sentences if not re.search(r"R\d{4}", s)) / len(sentences)


def review(ctx: RunContext, round_no: int) -> QAReport:
    store = ctx.store
    protocol = store.load("protocol", Protocol)
    flow = store.load("prisma_flow", PrismaFlow)
    records = {r.rid: r for r in store.load_lines("records", Record)}
    extractions = store.load_lines("extractions", Extraction)
    rob = {r.rid: r for r in store.load_lines("risk_of_bias", RiskOfBias)}
    ta = store.load_lines("screening_title_abstract", ScreeningDecision)
    ft = store.load_lines("screening_full_text", ScreeningDecision)
    meta = store.load("manuscript_meta")
    draft = store.path("report_draft.md").read_text(encoding="utf-8")
    issues: list[QAIssue] = []
    checks: dict[str, object] = {"round": round_no}

    # ---- 1. PRISMA flow arithmetic ------------------------------------------
    flow_errors = flow.check()
    checks["prisma_flow_consistent"] = not flow_errors
    issues += [QAIssue(severity="critical", area="flow", description=e) for e in flow_errors]

    # ---- 2. PRISMA 2020 checklist ----------------------------------------------
    checklist = validate_checklist(draft)
    missing = [row for row in checklist if not row["reported"]]
    checks["prisma_items_reported"] = len(checklist) - len(missing)
    checks["prisma_items_total"] = len(checklist)
    for row in missing:
        issues.append(QAIssue(severity="major", area="report", description=f"PRISMA item {row['item']} ({row['topic']}) is not reported."))

    # ---- 3. citations --------------------------------------------------------------
    included = [d.rid for d in ft if d.final == "include"]
    ext_ids = {e.rid for e in extractions}
    checks["unknown_citations"] = meta["unknown_citations"]
    if meta["unknown_citations"]:
        issues.append(QAIssue(
            severity="major", area="report",
            description=f"The draft cites record ids that do not exist: {', '.join(meta['unknown_citations'])}.",
            suggested_fix="Cite only ids present in the evidence cards.",
        ))
    without_data = [rid for rid in included if rid not in ext_ids]
    checks["included_without_extraction"] = without_data
    if without_data:
        issues.append(QAIssue(
            severity="critical", area="extraction",
            description=f"Included studies without extracted data: {', '.join(without_data)}.",
            suggested_fix="Re-run the extraction stage for these studies.",
        ))
    themes = [Theme.model_validate(t) for t in meta["themes"]]
    ratios = {}
    for theme in themes:
        syn = meta["syntheses"].get(theme.name)
        if not syn:
            issues.append(QAIssue(severity="major", area=f"synthesis:{theme.name}", description="No narrative was produced for this theme."))
            continue
        ratio = uncited_ratio(syn["narrative"])
        ratios[theme.name] = round(ratio, 2)
        if ratio > 0.34:
            issues.append(QAIssue(
                severity="major", area=f"synthesis:{theme.name}",
                description=f"{ratio:.0%} of the sentences in this narrative carry no citation.",
                suggested_fix="End every sentence reporting a finding with the ids of the studies it comes from.",
            ))
        cited = set(re.findall(r"R\d{4}", syn["narrative"]))
        never = [rid for rid in theme.study_ids if rid not in cited]
        if never:
            issues.append(QAIssue(
                severity="minor", area=f"synthesis:{theme.name}",
                description=f"Studies assigned to this theme are never cited in its narrative: {', '.join(never)}.",
                suggested_fix="Report what these studies found, or explain why they add nothing.",
            ))
    checks["uncited_sentence_ratio"] = ratios

    # ---- 4. extraction grounding ----------------------------------------------------
    q = quote_stats(extractions)
    checks["extraction_quotes"] = q
    if q["verification_rate"] is not None and q["verification_rate"] < 0.8:
        issues.append(QAIssue(
            severity="major", area="extraction",
            description=f"Only {q['verification_rate']:.0%} of the extraction quotations were found in the source texts.",
            suggested_fix="A human should verify the values flagged 'unverified' in evidence_table.csv.",
        ))

    # ---- 5. faithfulness of the narratives (LLM, different model from the writer) ---
    ext_by_id = {e.rid: e for e in extractions}
    full_cards = {rid: study_card(records[rid], ext_by_id[rid], rob.get(rid), full=True) for rid in ext_by_id}
    unsupported_total = 0
    for theme in themes:
        syn = meta["syntheses"].get(theme.name)
        if not syn:
            continue
        system = (
            "You are the quality-assurance reviewer of a systematic review. Check the draft narrative below "
            "against the evidence it was written from. Report ONLY real problems: a statement that the "
            "evidence does not contain, that contradicts it, a number that differs from the evidence, or a "
            "citation [R0000] of a study that does not support the sentence. Reasonable paraphrase and "
            "comparison between studies are fine. Return an empty list when everything is supported."
        )
        user = f"{theme_evidence(ctx, protocol, theme, full_cards)}\n\nDRAFT NARRATIVE:\n{syn['narrative']}"
        try:
            found = ctx.llm.structured(ctx.settings.role("critic"), system, user, Faithfulness, agent=AGENT, max_tokens=900).unsupported
        except LLMError as exc:
            ctx.audit.log(AGENT, "llm_failure", task="faithfulness", theme=theme.name, error=str(exc)[:300])
            continue
        unsupported_total += len(found)
        for item in found:
            issues.append(QAIssue(
                severity="major", area=f"synthesis:{theme.name}",
                description=f"Unsupported statement: \"{item.claim}\" — {item.problem}", suggested_fix=item.fix,
            ))
    checks["unsupported_statements"] = unsupported_total

    # ---- 6. overstatement in discussion / abstract --------------------------------------
    if themes and ext_by_id:
        digest = "\n\n".join(
            f"Theme: {name}\n{syn['narrative']}\nCertainty: {syn['certainty']}" for name, syn in meta["syntheses"].items()
        )
        abstract = draft.split("## Abstract", 1)[1].split("## 1. Introduction", 1)[0]
        system = (
            "You are the quality-assurance reviewer of a systematic review. Compare the Discussion and the "
            "Abstract with the thematic synthesis they are based on. Report statements that go beyond the "
            "synthesis: conclusions stronger than the stated certainty, causal claims from weak designs, "
            "numbers that do not match, recommendations the evidence cannot carry. Return an empty list if "
            "there are none."
        )
        user = (
            f"THEMATIC SYNTHESIS:\n{digest}\n\nDISCUSSION:\n{meta['discussion']['summary_of_evidence']}\n"
            f"{meta['discussion']['limitations_of_evidence']}\n{meta['discussion']['implications']}\n\nABSTRACT:\n{abstract}"
        )
        try:
            problems = ctx.llm.structured(ctx.settings.role("critic"), system, user, Overstatements, agent=AGENT, max_tokens=900).problems
        except LLMError:
            problems = []
        checks["overstatements"] = len(problems)
        for p in problems:
            area = "abstract" if "abstract" in p.section.lower() else "discussion"
            issues.append(QAIssue(severity="major", area=area, description=f"\"{p.claim}\" — {p.problem}", suggested_fix=p.fix))

    # ---- 7. screening audits (first round only: they do not depend on the draft) ----------
    if round_no == 1:
        issues += _exclusion_audit(ctx, protocol, records, ta, checks)
        issues += _eligibility_audit(ctx, protocol, records, ext_by_id, rob, checks)
    else:
        previous = store.load("qa_report")
        for key in ("exclusion_audit", "eligibility_audit"):
            checks[key] = previous["checks"].get(key)
        issues += [QAIssue.model_validate(i) for i in previous["issues"] if i["area"] == "screening"]

    fixable = [i for i in issues if i.severity in ("critical", "major") and i.area.startswith(WRITER_AREAS)]
    verdict = "revise" if fixable and round_no <= ctx.options.qa_max_rounds else "pass"
    report = QAReport(verdict=verdict, issues=issues, checks=checks)
    store.save("qa_report", report, agent=AGENT, note=f"round {round_no}")
    store.write_text("qa_report.md", qa_markdown(report), agent=AGENT)
    ctx.audit.log(AGENT, "qa_review", round=round_no, verdict=verdict, issues=len(issues), writer_fixable=len(fixable))
    return report


def _exclusion_audit(ctx: RunContext, protocol: Protocol, records: dict[str, Record], ta: list[ScreeningDecision],
                     checks: dict) -> list[QAIssue]:
    """Re-screen a random sample of excluded records with a third model."""
    excluded = [d.rid for d in ta if d.final == "exclude"]
    sample = random.Random(ctx.options.seed).sample(excluded, min(ctx.options.exclusion_audit_sample, len(excluded)))
    if not sample:
        checks["exclusion_audit"] = {"sampled": 0}
        return []
    system = TA_SYSTEM.format(guidance="", protocol=protocol_brief(protocol, mark_full_text_only=True))
    disagreements: list[tuple[str, str]] = []
    judged = 0
    for start in range(0, len(sample), 5):
        batch = sample[start : start + 5]
        user = "Records to screen:\n\n" + "\n\n".join(_record_block(records[rid]) for rid in batch)
        try:
            votes = ctx.llm.structured(ctx.settings.role("auditor"), system, user, BatchVotes, agent=f"{AGENT}:exclusion_audit", max_tokens=1300).votes
        except LLMError:
            continue
        for vote in votes:
            if vote.rid in batch:
                judged += 1
                if vote.decision == "include":
                    disagreements.append((vote.rid, vote.rationale))
    checks["exclusion_audit"] = {
        "sampled": len(sample), "judged": judged, "auditor_would_include": [rid for rid, _ in disagreements],
        "agreement": round(1 - len(disagreements) / judged, 4) if judged else None,
    }
    return [
        QAIssue(
            severity="major", area="screening",
            description=f"{rid} was excluded at title/abstract stage but an independent auditor would include it: {why}",
            suggested_fix="Human reviewer to re-check this record.",
        )
        for rid, why in disagreements
    ]


def _eligibility_audit(ctx: RunContext, protocol: Protocol, records: dict[str, Record], ext_by_id: dict[str, Extraction],
                       rob: dict[str, RiskOfBias], checks: dict) -> list[QAIssue]:
    """Check the included studies against the protocol, from their extracted data."""
    if not ext_by_id:
        checks["eligibility_audit"] = {"checked": 0}
        return []
    cards = [study_card(records[rid], ext, rob.get(rid)) for rid, ext in ext_by_id.items()]
    flags: list[EligibilityFlag] = []
    system = (
        "You audit the included studies of a systematic review for adherence to the protocol. Using the "
        "extracted data of each study, flag ONLY studies that clearly violate an eligibility criterion (wrong "
        "design, wrong population, not primary research…). Do not flag a study merely because information is "
        "missing. Return an empty list if all studies are consistent with the protocol.\n\n" + protocol_brief(protocol)
    )
    for start in range(0, len(cards), 12):
        try:
            flags += ctx.llm.structured(
                ctx.settings.role("auditor"), system, "Included studies:\n" + "\n".join(cards[start : start + 12]), EligibilityFlags,
                agent=f"{AGENT}:eligibility_audit", max_tokens=900,
            ).flags
        except LLMError:
            continue
    flags = [f for f in flags if f.rid in ext_by_id]
    checks["eligibility_audit"] = {"checked": len(cards), "flagged": [f.rid for f in flags]}
    return [
        QAIssue(
            severity="major", area="screening",
            description=f"Included study {f.rid} may violate criterion {f.criterion}: {f.reason}",
            suggested_fix="Human reviewer to confirm eligibility.",
        )
        for f in flags
    ]


def verdict_label(verdict: str, issues: list) -> str:
    """Readable outcome of a review round.

    The stored verdict only drives the routing: "pass" means "no further automatic revision", which is
    also what happens when the revision rounds are used up. Open issues must not read as a clean pass.
    """
    severities = [i["severity"] if isinstance(i, dict) else i.severity for i in issues]
    serious = sum(s in ("critical", "major") for s in severities)
    if verdict == "revise":
        return "revise — returned to the Writing agent"
    if serious:
        plural = "s" if serious != 1 else ""
        return f"not resolved — {serious} critical or major issue{plural} still open; no further automatic revision"
    return "pass"


def qa_markdown(report: QAReport) -> str:
    lines = ["# Quality-assurance report", "", f"**Verdict:** {verdict_label(report.verdict, report.issues)}", "", "## Checks", ""]
    lines += [f"- **{key}**: {value}" for key, value in report.checks.items()]
    lines += ["", "## Issues", ""]
    if not report.issues:
        lines.append("No issues found.")
    for issue in report.issues:
        fix = f" *Suggested fix:* {issue.suggested_fix}" if issue.suggested_fix else ""
        lines.append(f"- **{issue.severity}** [{issue.area}] {issue.description}{fix}")
    return "\n".join(lines) + "\n"
