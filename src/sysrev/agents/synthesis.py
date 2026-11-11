"""Synthesis & Writing agent.

Division of labour, chosen for accuracy:

* everything that is a *fact about the review process* (methods, counts, tables,
  PRISMA flow, references) is rendered deterministically from the run artifacts —
  an LLM never gets the chance to misreport a number;
* the LLM writes only the interpretive parts (rationale, thematic synthesis,
  discussion, abstract), from evidence cards and retrieved passages, and must cite
  a record id after every claim. Citations are validated and renumbered in code.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from ..context import RunContext
from ..llm import LLMError
from ..models import Extraction, Protocol, QAIssue, Record, RiskOfBias, ScreeningDecision, SearchStrategy, Theme
from ..rag.index import format_passages
from ..sources.connectors import DISPLAY_NAME
from ..tools import stats
from ..tools.export import format_reference, md_table, write_csv
from ..tools.prisma import PrismaFlow
from .extraction import ROB_USE, quote_stats
from .planner import ReviewPlan, load_template

AGENT = "synthesis_writing"
CITE = re.compile(r"\[\s*(R\d{4}(?:\s*[;,]\s*R\d{4})*)\s*\]")


# --------------------------------------------------------------------------- #
# LLM output schemas
# --------------------------------------------------------------------------- #


class ThemeList(BaseModel):
    themes: list[Theme]


class ThemeSynthesis(BaseModel):
    narrative: str = Field(description="150-300 words. Every sentence that states a finding ends with citations like [R0012] or [R0012; R0034]")
    certainty: Literal["high", "moderate", "low", "very low"]
    certainty_rationale: str = Field(description="One or two sentences: risk of bias, inconsistency, indirectness, imprecision")


class Discussion(BaseModel):
    summary_of_evidence: str = Field(description="150-250 words interpreting the main findings, with [R0000] citations")
    limitations_of_evidence: str = Field(description="80-160 words on weaknesses of the included studies, with citations")
    implications: str = Field(description="80-160 words on implications for practice and future research")


class AbstractText(BaseModel):
    background: str
    objectives: str
    methods: str
    results: str
    conclusions: str


class OutcomeGroup(BaseModel):
    label: str = Field(description="Common outcome name")
    measure: str = Field(description="Shared effect measure, e.g. OR, sensitivity")
    effect_ids: list[int] = Field(description="Indexes of the effect estimates that can be pooled together")


class OutcomeGroups(BaseModel):
    groups: list[OutcomeGroup]


# --------------------------------------------------------------------------- #
# Evidence cards
# --------------------------------------------------------------------------- #


def _trim(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def effect_text(effect) -> str:
    ci = f" (95% CI {effect.ci_low} to {effect.ci_high})" if effect.ci_low is not None and effect.ci_high is not None else ""
    n = f", n={effect.n}" if effect.n else ""
    return f"{effect.outcome}: {effect.measure} = {effect.value}{ci}{n}"


def study_card(rec: Record, ext: Extraction, rob: RiskOfBias | None, full: bool = False) -> str:
    lines = [
        f"[{rec.rid}] {rec.short_ref()} — {_trim(rec.title, 140)}",
        f"  Design: {ext.study_design} | Sample: {ext.sample_size} | Country: {ext.country} | "
        f"Risk of bias: {rob.overall + ' (' + rob.tool + ')' if rob else 'not assessed'} | Read from: {ext.basis.replace('_', ' ')}",
        "  Findings: " + " ".join(_trim(f, 260) for f in ext.key_findings[: 5 if full else 3]),
    ]
    if ext.effects:
        lines.append("  Effects: " + "; ".join(effect_text(e) for e in ext.effects[: 6 if full else 3]))
    if full:
        items = [f"{i.field}: {_trim(i.value, 110)}" for i in ext.items if i.value.lower() != "not reported"]
        if items:
            lines.append("  Data items: " + " | ".join(items[:8]))
        if rob:
            lines.append("  Main validity concern: " + _trim(rob.overall_justification, 220))
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Quantitative synthesis preparation
# --------------------------------------------------------------------------- #


def prepare_meta_analysis(ctx: RunContext, records: dict[str, Record], extractions: list[Extraction]) -> dict:
    rows = []
    for ext in extractions:
        for effect in ext.effects:
            rows.append(
                {
                    "id": len(rows), "rid": ext.rid, "study": records[ext.rid].short_ref(), "outcome": effect.outcome,
                    "measure": effect.measure, "value": effect.value, "ci_low": effect.ci_low, "ci_high": effect.ci_high,
                    "n": effect.n, "quote_verified": effect.quote_verified,
                }
            )
    write_csv(ctx.store.path("effects.csv"), rows)
    result: dict = {"n_effects": len(rows), "pooled": [], "note": ""}
    poolable = [r for r in rows if r["ci_low"] is not None and r["ci_high"] is not None]
    if len({r["rid"] for r in poolable}) < 2:
        result["note"] = (
            "Fewer than two studies reported an effect estimate with a confidence interval, "
            "so no quantitative pooling was attempted."
        )
        ctx.store.save("meta_analysis", result, agent=AGENT)
        return result

    listing = "\n".join(f"{r['id']}: [{r['rid']}] {r['outcome']} — {r['measure']} = {r['value']}" for r in poolable)
    system = (
        "You prepare a meta-analysis. Group the effect estimates below that could legitimately be pooled: "
        "same outcome construct AND same effect measure, from different studies. Do not force groups: "
        "estimates that are not comparable must be left out. Return [] if nothing is comparable."
    )
    try:
        groups = ctx.llm.structured(ctx.settings.role("utility"), system, listing, OutcomeGroups, agent=f"{AGENT}:meta", max_tokens=900).groups
    except LLMError:
        groups = []
    by_id = {r["id"]: r for r in poolable}
    for group in groups:
        seen, effects = set(), []
        log_scale = group.measure.upper() in stats.RATIO_MEASURES
        for eid in group.effect_ids:
            row = by_id.get(eid)
            if not row or row["rid"] in seen:  # one estimate per study
                continue
            converted = stats.effect_from_ci(row["value"], row["ci_low"], row["ci_high"], row["measure"])
            if converted:
                seen.add(row["rid"])
                effects.append(stats.StudyEffect(f"{row['study']} [{row['rid']}]", *converted))
        pooled = stats.pool(effects, log_scale=log_scale)
        if pooled:
            result["pooled"].append(
                {"outcome": group.label, "measure": group.measure, "studies": [e.label for e in effects], **pooled.as_dict()}
            )
    if not result["pooled"]:
        result["note"] = (
            "The reported effect estimates were too heterogeneous in outcome or measure to be pooled; "
            "effects.csv lists every estimate for a future meta-analysis."
        )
    ctx.store.save("meta_analysis", result, agent=AGENT)
    return result


# --------------------------------------------------------------------------- #
# Evidence map
# --------------------------------------------------------------------------- #


def _design_family(design: str) -> str:
    d = design.lower()
    for key, label in [
        ("random", "Randomised trial"), ("cohort", "Cohort"), ("case-control", "Case-control"),
        ("cross-sectional", "Cross-sectional"), ("diagnostic", "Diagnostic accuracy"), ("qualitative", "Qualitative"),
        ("simulation", "Simulation / benchmark"), ("benchmark", "Simulation / benchmark"),
        ("retrospective", "Retrospective evaluation"), ("evaluation", "Evaluation study"),
        ("validation", "Evaluation study"), ("comparative", "Comparative study"), ("case", "Case study / series"),
        ("mixed", "Mixed methods"), ("survey", "Survey"), ("experiment", "Experimental study"),
    ]:
        if key in d:
            return label
    return "Other"


def evidence_map(ctx: RunContext, themes: list[Theme], extractions: dict[str, Extraction], rob: dict[str, RiskOfBias]) -> list[dict]:
    families = sorted({_design_family(e.study_design) for e in extractions.values()})
    rows = []
    for theme in themes:
        row: dict = {"theme": theme.name}
        for family in families:
            row[family] = sum(1 for rid in theme.study_ids if rid in extractions and _design_family(extractions[rid].study_design) == family)
        levels = [rob[rid].overall for rid in theme.study_ids if rid in rob]
        row["studies"] = len(theme.study_ids)
        row["low risk of bias"] = levels.count("low")
        row["high risk of bias"] = levels.count("high")
        rows.append(row)
    write_csv(ctx.store.path("evidence_map.csv"), rows)
    if not rows or not families:
        return rows

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    grid = [[row[f] for f in families] for row in rows]
    fig, ax = plt.subplots(figsize=(1.6 + 1.5 * len(families), 1.2 + 0.62 * len(rows)), dpi=160)
    image = ax.imshow(grid, cmap="Blues", vmin=0, vmax=max(max(r) for r in grid) or 1, aspect="auto")
    ax.set_xticks(range(len(families)), families, rotation=25, ha="right", fontsize=8)
    ax.set_yticks(range(len(rows)), [_trim(r["theme"], 46) for r in rows], fontsize=8)
    top = max(max(r) for r in grid) or 1
    for y, line in enumerate(grid):
        for x, value in enumerate(line):
            if value:
                ax.text(x, y, str(value), ha="center", va="center", fontsize=9,
                        color="white" if value > top * 0.55 else "#12263f")
    ax.set_title("Evidence map: number of included studies by theme and design", fontsize=9.5)
    fig.colorbar(image, ax=ax, shrink=0.8, label="studies")
    fig.savefig(ctx.store.path("evidence_map.png"), bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return rows


# --------------------------------------------------------------------------- #
# LLM-written parts
# --------------------------------------------------------------------------- #


def _feedback(issues: list[QAIssue], area: str) -> str:
    relevant = [i for i in issues if i.area == area or i.area == "report"]
    if not relevant:
        return ""
    lines = "\n".join(f"- ({i.severity}) {i.description} {('Fix: ' + i.suggested_fix) if i.suggested_fix else ''}" for i in relevant)
    return f"\n\nThe quality-assurance reviewer found these problems in your previous draft. Correct them:\n{lines}"


def identify_themes(ctx: RunContext, protocol: Protocol, cards: dict[str, str]) -> list[Theme]:
    if len(cards) <= 2:
        return [Theme(name="Findings of the included studies", description="All included studies.", study_ids=list(cards))]
    system = (
        "You are synthesising a systematic review. Group the included studies into 2-5 themes (fewer themes "
        "when there are fewer than ten studies; never a theme with a single study if it fits elsewhere) that answer "
        "the review question (by intervention type, outcome, population or method — whichever organises the "
        "evidence best). Every study id must appear in at least one theme; a study may appear in two. "
        "Theme names are short noun phrases."
    )
    user = f"Review question: {protocol.research_question}\n\nIncluded studies:\n" + "\n".join(cards.values())
    try:
        themes = ctx.llm.structured(ctx.settings.role("writer"), system, user, ThemeList, agent=AGENT, max_tokens=1300).themes
    except LLMError:
        themes = []
    known = set(cards)
    for theme in themes:
        theme.study_ids = [rid for rid in dict.fromkeys(theme.study_ids) if rid in known]
    themes = [t for t in themes if t.study_ids]
    covered = {rid for t in themes for rid in t.study_ids}
    missing = [rid for rid in cards if rid not in covered]
    if missing:
        themes.append(Theme(name="Other findings", description="Studies not covered by the themes above.", study_ids=missing))
    return themes


def theme_evidence(ctx: RunContext, protocol: Protocol, theme: Theme, full_cards: dict[str, str]) -> str:
    """Evidence given to the writer for one theme (and, identically, to the critic)."""
    passages = ctx.index.search(f"{theme.name}. {theme.description}", k=4, rids=theme.study_ids, kind="fulltext")
    passages = ctx.index.compress(f"{theme.name} {protocol.research_question}", passages, 2200)
    return (
        "Evidence cards:\n" + "\n\n".join(full_cards[rid] for rid in theme.study_ids if rid in full_cards)
        + (f"\n\nSupporting passages (label = study id:source:chunk):\n{format_passages(passages)}" if passages else "")
    )


def synthesise_theme(ctx: RunContext, protocol: Protocol, theme: Theme, full_cards: dict[str, str],
                     issues: list[QAIssue], guidance: str) -> ThemeSynthesis:
    system = (
        "You write the narrative synthesis of one theme of a systematic review (PRISMA 2020, SWiM guidance).\n"
        "- Use ONLY the evidence cards and passages provided. No outside knowledge, no invented numbers.\n"
        "- Every sentence that reports a finding must end with the ids of the studies it comes from, "
        "in square brackets: [R0012] or [R0012; R0034]. Only cite ids that appear in the cards.\n"
        "- Compare the studies: where they agree, where they conflict, and plausible reasons (design, "
        "sample, measures, risk of bias). Give sample sizes and effect sizes when the cards have them.\n"
        "- Weigh studies by their risk of bias; say when evidence rests on abstracts only.\n"
        "- Then rate the certainty of the body of evidence for this theme (GRADE-inspired): start from "
        "'high' for randomised evidence and 'low' for observational evidence, and downgrade for risk of "
        "bias, inconsistency, indirectness or imprecision.\n"
        f"{guidance}"
    )
    user = (
        f"Review question: {protocol.research_question}\nTheme: {theme.name} — {theme.description}\n\n"
        + theme_evidence(ctx, protocol, theme, full_cards)
        + _feedback(issues, f"synthesis:{theme.name}")
    )
    return ctx.llm.structured(ctx.settings.role("writer"), system, user, ThemeSynthesis, agent=AGENT, max_tokens=1500)


def write_rationale(ctx: RunContext, protocol: Protocol, issues: list[QAIssue]) -> str:
    background = ctx.index.search(protocol.research_question, k=8, kind="abstract")
    background = ctx.index.compress(protocol.research_question, background, 5200)
    system = (
        "You write the 'Rationale' paragraph of a systematic review introduction (120-200 words): what is "
        "already known, what is uncertain, and why this review is needed. Use ONLY the abstracts provided "
        "as sources and cite the record id after each claim, e.g. [R0012]. Do not describe the results of "
        "this review. Plain prose, no headings."
    )
    user = (
        f"Review question: {protocol.research_question}\nProtocol rationale: {protocol.rationale}\n\n"
        f"Abstracts retrieved by the search:\n{format_passages(background)}{_feedback(issues, 'rationale')}"
    )
    return ctx.llm.text(ctx.settings.role("writer"), system, user, agent=AGENT, max_tokens=900)


# --------------------------------------------------------------------------- #
# Deterministic sections
# --------------------------------------------------------------------------- #


def _ref(rec: Record) -> str:
    return f"{rec.short_ref()} [{rec.rid}]"


def methods_sections(ctx: RunContext, protocol: Protocol, strategy: SearchStrategy, flow: PrismaFlow,
                     agreement_ta: dict, agreement_ft: dict, human: list[dict]) -> dict[str, str]:
    opts = ctx.options
    models = ctx.manifest["llm"].get("task_models") or ctx.settings.task_models()  # as recorded when the run started
    search_log = ctx.store.load("search_log")
    failed = search_log.get("errors", {})
    created = ctx.manifest["created"][:10]
    years = (
        f"Records published from {protocol.date_from or 'inception'} to {protocol.date_to or 'the search date'} were eligible. "
        if (protocol.date_from or protocol.date_to) else "No publication-date limit was applied. "
    )
    eligibility = (
        f"The review question was structured with the {protocol.framework} framework: "
        + "; ".join(f"**{k}**: {v}" for k, v in protocol.framework_elements.items()) + ".\n\n"
        + "Inclusion criteria:\n" + "\n".join(f"- {c.id}. {c.text}" for c in protocol.inclusion_criteria) + "\n\n"
        + "Exclusion criteria:\n" + "\n".join(f"- {c.id}. {c.text}" for c in protocol.exclusion_criteria) + "\n\n"
        + f"Eligible study designs: {', '.join(protocol.study_designs)}. {years}"
        + f"Languages: {', '.join(protocol.languages)}."
    )
    sources = (
        f"The following bibliographic databases were searched on {created} through their public APIs: "
        + ", ".join(f"{DISPLAY_NAME.get(db, db)} ({flow.identified.get(db, 0)} records retrieved)" for db in strategy.queries) + ". "
        + (
            "The search of " + ", ".join(f"{DISPLAY_NAME.get(db, db)} failed ({err.split(':')[0]})" for db, err in failed.items())
            + " and returned no records; this is a limitation of the present run. " if failed else ""
        )
        + "No trial registers, grey-literature sources or reference lists were searched, and no study authors were contacted."
    )
    capped = [db for db, n in strategy.hit_counts.items() if n and n > flow.identified.get(db, 0) and db not in failed]
    search = (
        "The Search Strategy agent derived concept blocks from the protocol ("
        + "; ".join(f"*{c.name}*" for c in strategy.concepts)
        + "), wrote one query per database in its native syntax, and refined each query against the live "
        "database until the number of hits was manageable. " + strategy.rationale.strip() + " "
        + (
            f"For {', '.join(DISPLAY_NAME.get(db, db) for db in capped)} the query matched more records than the per-database "
            f"retrieval limit ({opts.max_per_source}); the most relevant records according to the database's own ranking were "
            f"retrieved (total hits: {', '.join(f'{DISPLAY_NAME.get(db, db)} {strategy.hit_counts[db]}' for db in capped)}). " if capped else ""
        )
        + "The full search strings are given in Appendix A."
    )
    human_modes = {h["checkpoint"]: h for h in human}
    oversight = (
        "A human reviewer inspected and approved the protocol and search strategy, the screening decisions and the final report at dedicated checkpoints."
        if human and all(h.get("mode") == "human" for h in human)
        else "The run was executed in autonomous mode: the human checkpoints (protocol and search strategy, screening decisions, final report) were auto-approved and no human verified the decisions."
        if human and all(h.get("mode") == "auto" for h in human)
        else "Human checkpoints: " + "; ".join(f"{name}: {h.get('mode')}" for name, h in human_modes.items()) + "."
    )
    automation = ""
    if flow.removed_by_automation:
        automation = (
            f"Before screening, {flow.removed_by_automation} records were removed by automation tools ("
            + "; ".join(f"{reason}: {n}" for reason, n in flow.automation_detail.items())
            + f"). The relevance-ranking cap keeps the {opts.max_screen} records ranked highest against the review "
            "question by hybrid dense (sentence-embedding) and sparse (BM25) retrieval with reciprocal rank fusion. "
        )
    selection = (
        "Records were de-duplicated automatically (matching on DOI, PubMed id, arXiv id, exact normalised title, "
        "then fuzzy title similarity of at least 95% with publication years at most one apart). " + automation
        + f"Titles and abstracts were then screened independently by two AI reviewers built on different language "
        f"models (reviewer A: {models['reviewer_a']}; reviewer B: {models['reviewer_b']}), each applying the eligibility "
        "criteria without access to the other's votes. Records were excluded only when both reviewers excluded "
        f"them or when an adjudicator agent ({models['adjudicator']}), given both rationales, decided so; unclear "
        "records were carried forward. Full texts were sought for all retained records from open-access sources "
        "(Europe PMC, arXiv, publisher open-access PDFs). For each report, the passages most relevant to each "
        "eligibility criterion were retrieved from the full text (hybrid retrieval, cross-encoder re-ranking) and "
        "assessed by the same two independent reviewers, with adjudication of disagreements. "
        + (
            "When no open-access full text could be retrieved, eligibility was assessed on the abstract alone and the study is flagged accordingly. "
            if opts.fulltext_fallback == "abstract"
            else "Reports without a retrievable open-access full text were excluded as 'not retrieved'. "
        )
        + f"Inter-reviewer agreement was Cohen's kappa = {agreement_ta.get('cohen_kappa')} ({agreement_ta.get('interpretation')}) "
        f"at title/abstract stage and {agreement_ft.get('cohen_kappa')} ({agreement_ft.get('interpretation')}) at full-text stage. "
        + oversight
    )
    collection = (
        f"Data were extracted by an Extraction agent ({models['extractor']}) into a structured form. For each study the "
        "agent received the abstract and the full-text passages retrieved for every data item, and had to supply a "
        "verbatim supporting quotation for every extracted value. Each quotation was then checked programmatically "
        "against the source text; values whose quotation could not be located are flagged as unverified in the "
        "evidence tables. Extraction was performed once (not in duplicate)."
    )
    items = (
        "Outcomes sought: " + "; ".join(protocol.outcomes) + ". All results compatible with each outcome were sought. "
        "Other data items: study design; country; sample size; " + "; ".join(protocol.data_items)
        + "; limitations reported by the authors; funding. Items that a report did not state were recorded as 'Not reported'; no assumptions were made about missing information."
    )
    rob = (
        protocol.risk_of_bias_approach.strip() + " In practice, an Appraisal agent "
        f"({models['appraiser']}) selected for each study the tool matching its design among "
        + ", ".join(f"{name} ({use})" for name, use in ROB_USE.items())
        + ", judged every domain as low, some concerns, high or unclear with a written justification, and the overall "
        "judgement was derived by rule (any high domain: high; otherwise any concern or unclear domain: some concerns; "
        "all domains unclear: unclear; else low). Appraisal was performed once per study by one automated assessor."
    )
    effect = (
        "Effect measures were recorded as reported by the study authors (for example odds ratios, risk ratios, mean "
        "differences, or performance metrics such as sensitivity and specificity), with 95% confidence intervals "
        "where available. No effect measure was re-computed from raw data."
    )
    synthesis = (
        protocol.synthesis_plan.strip() + " All included studies were eligible for the narrative synthesis. Studies were "
        "tabulated by characteristics, risk of bias and individual results, then grouped into themes by the Synthesis "
        f"agent ({models['writer']}); a narrative synthesis was written per theme from the extracted data and retrieved "
        f"passages. {critic_statement(ctx, models['critic'])} "
        "For quantitative synthesis, effect estimates with confidence intervals were grouped by outcome and measure; "
        "where at least two studies reported comparable estimates they were pooled with inverse-variance weighting under "
        "a DerSimonian-Laird random-effects model (ratio measures on the log scale), with heterogeneity summarised by "
        "Cochran's Q, I² and tau². Heterogeneity was otherwise explored narratively by comparing study designs, samples "
        "and risk of bias. No sensitivity analyses were planned."
    )
    certainty = (
        "Risk of bias due to missing results (reporting bias) was not assessed formally: no funnel plots or "
        "small-study tests were produced. Certainty in the body of evidence for each theme was rated by the Synthesis "
        "agent with a GRADE-inspired approach (high, moderate, low, very low), considering risk of bias, inconsistency, "
        "indirectness and imprecision; these ratings are automated and indicative."
    )
    return {
        "2.1 Eligibility criteria": eligibility,
        "2.2 Information sources": sources,
        "2.3 Search strategy": search,
        "2.4 Selection process": selection,
        "2.5 Data collection process": collection,
        "2.6 Data items": items,
        "2.7 Risk of bias assessment": rob,
        "2.8 Effect measures": effect,
        "2.9 Synthesis methods": synthesis,
        "2.10 Reporting bias and certainty assessment": certainty,
    }


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" + ("" if n == 1 else "s")


def _and(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def qa_status(ctx: RunContext) -> dict:
    """What the Critic did so far in this run (empty before its first review)."""
    store = ctx.store
    rounds = store.version_count("qa_report")
    if not rounds:
        return {}
    first, last = store.load("qa_report", version=1), store.load("qa_report")
    writer_areas = ("synthesis:", "discussion", "abstract", "rationale", "report")
    return {
        "rounds": rounds,
        "raised_first": sum(i["area"].startswith(writer_areas) for i in first["issues"]),
        "open_last": sum(i["area"].startswith(writer_areas) for i in last["issues"]),
        "revised": store.version_count("manuscript_meta") > 1 and any(m.get("revision_issues") for m in [store.load("manuscript_meta")]),
        "skipped": any(e["action"] == "revision_skipped" for e in ctx.audit.read()),
    }


def critic_statement(ctx: RunContext, critic_model: str) -> str:
    status = qa_status(ctx)
    base = f"Every statement of the draft is checked against its evidence by a Critic agent running on a different model ({critic_model})"
    if not status:
        return base + ", whose objections are returned to the writer for revision."
    text = base + f". It reviewed the manuscript in {_count(status['rounds'], 'round')} and raised {_count(status['raised_first'], 'issue')} on the first draft"
    if status["revised"]:
        return text + (
            f"; the writer revised the manuscript in response, after which {_count(status['open_last'], 'issue')} remained "
            "(listed in qa_report.md)."
        )
    if status["skipped"]:
        return text + (
            ". The revision round could not be run because the daily quota of the writing model was exhausted, so these "
            "issues remain unresolved in the present version and are listed in qa_report.md."
        )
    return text + (" (listed in qa_report.md)." if status["raised_first"] else ".")


def selection_results(flow: PrismaFlow, excluded_ft: list[ScreeningDecision]) -> str:
    reasons = "; ".join(f"{reason} (n = {n})" for reason, n in flow.reports_excluded.items()) or "none"
    text = (
        f"The searches retrieved {flow.identified_total} records ("
        + ", ".join(f"{DISPLAY_NAME.get(db, db)}: {n}" for db, n in flow.identified.items()) + "). "
        f"After removal of {flow.duplicates_removed} duplicates and {flow.removed_by_automation} records marked "
        f"ineligible by automation tools, {flow.records_screened} records were screened on title and abstract and "
        f"{flow.records_excluded} were excluded. {flow.reports_sought} reports were sought for retrieval, "
        f"{flow.reports_not_retrieved} were not retrieved, and {flow.reports_assessed} were assessed for eligibility"
        + (f" ({flow.assessed_on_abstract_only} of them on the abstract only, because no open-access full text was available)" if flow.assessed_on_abstract_only else "")
        + f". {sum(flow.reports_excluded.values())} reports were excluded at this stage: {reasons}. "
        f"{flow.studies_included} studies were included in the review (Figure 1). "
    )
    if excluded_ft:
        text += "Reports excluded at full-text stage are listed with their reasons in Appendix B."
    return text + "\n\n![Figure 1. PRISMA 2020 flow diagram](prisma_flow.png)"


def limitations_of_process(ctx: RunContext, flow: PrismaFlow, extractions: list[Extraction], human: list[dict]) -> str:
    opts = ctx.options
    search_log = ctx.store.load("search_log")
    q = quote_stats(extractions)
    points = [
        "Screening, data extraction and risk-of-bias appraisal were performed by large language models. Although "
        "screening used two independent models with adjudication, LLM reviewers can share systematic errors, and "
        "extraction and appraisal were each done by a single automated assessor.",
        "Only databases with open APIs were searched; Embase, Scopus, Web of Science, trial registers and grey "
        "literature were not, so relevant studies may have been missed.",
    ]
    if search_log.get("errors"):
        points.append("The search of " + ", ".join(search_log["errors"]) + " failed during this run and contributed no records.")
    if flow.automation_detail.get("relevance-ranking cap"):
        points.append(
            f"{flow.automation_detail['relevance-ranking cap']} records were not screened because of the relevance-ranking cap "
            f"({opts.max_screen} records); eligible studies ranked below the cap would have been missed."
        )
    if flow.assessed_on_abstract_only:
        points.append(
            f"{flow.assessed_on_abstract_only} reports had no open-access full text and were assessed, and where included extracted, "
            "from the abstract alone, which limits the detail and reliability of their data and appraisal."
        )
    if q["quotes_checked"]:
        points.append(
            f"Of {q['quotes_checked']} supporting quotations supplied by the Extraction agent, {q['quotes_verified']} "
            f"({q['verification_rate']:.0%}) were located in the source text; the remaining values are flagged as unverified."
        )
    status = qa_status(ctx)
    if status.get("skipped") and not status.get("revised"):
        points.append(
            f"The Critic agent raised {_count(status['raised_first'], 'issue')} about the narrative, discussion or abstract that could not be "
            "corrected because the daily model quota was exhausted before the revision round; they are listed in qa_report.md and "
            "the affected statements should be read with caution."
        )
    if human and all(h.get("mode") == "auto" for h in human):
        points.append("No human verified the protocol, screening decisions or extracted data in this run; the results should be treated as a draft requiring expert verification.")
    points.append("The review was not prospectively registered, and reporting bias and certainty of evidence were assessed only informally.")
    return "\n".join(f"- {p}" for p in points)


# --------------------------------------------------------------------------- #
# Citations
# --------------------------------------------------------------------------- #


def number_citations(text: str, records: dict[str, Record]) -> tuple[str, list[str], list[str]]:
    """Replace [R0012; R0034] by [1, 2]. Returns (text, cited ids in order, unknown ids)."""
    ids = r"R\d{4}(?:\s*[;,]\s*R\d{4})*"
    text = re.sub(r"(R\d{4}):(?:fulltext|abstract):\d+", r"\1", text)
    text = text.replace("【", "[").replace("】", "]")  # some models cite with CJK brackets
    text = re.sub(rf"\(\s*({ids})\s*\)", r"[\1]", text)  # (R0001; R0002) -> [R0001; R0002]
    text = re.sub(r"\]\s*\[(?=R\d{4})", "; ", text)  # [R0001][R0002] -> [R0001; R0002]
    text = re.sub(r"(?<![\[;,\s\d])\s*\b(R\d{4})\b(?![^\[\]]*\])", r" [\1]", text)  # bare id in prose
    order: list[str] = []
    unknown: list[str] = []

    def replace(match: re.Match) -> str:
        numbers = []
        for rid in re.findall(r"R\d{4}", match.group(1)):
            if rid not in records:
                unknown.append(rid)
                continue
            if rid not in order:
                order.append(rid)
            numbers.append(order.index(rid) + 1)
        return "[" + ", ".join(str(n) for n in sorted(set(numbers))) + "]" if numbers else ""

    return CITE.sub(replace, text), order, unknown


# --------------------------------------------------------------------------- #
# Orchestration of the writing stage
# --------------------------------------------------------------------------- #


def write_report(ctx: RunContext, issues: list[QAIssue] | None = None, plan: ReviewPlan | None = None) -> str:
    """Build (or revise, when `issues` are given) the manuscript. Returns the Markdown text."""
    issues = issues or []
    store = ctx.store
    protocol = store.load("protocol", Protocol)
    strategy = store.load("search_strategy", SearchStrategy)
    flow = store.load("prisma_flow", PrismaFlow)
    records = {r.rid: r for r in store.load_lines("records", Record)}
    extractions = store.load_lines("extractions", Extraction)
    rob = {r.rid: r for r in store.load_lines("risk_of_bias", RiskOfBias)}
    ft_decisions = store.load_lines("screening_full_text", ScreeningDecision)
    agreement_ta, agreement_ft = store.load("agreement_title_abstract"), store.load("agreement_full_text")
    human = store.load("human_checkpoints") if store.exists("human_checkpoints") else []
    template = load_template(ctx.options.protocol_template)
    admin = template.get("administrative") or {}
    guidance = f"Coordinator guidance: {plan.guidance_for('synthesis_writing')}" if plan else ""
    ext_by_id = {e.rid: e for e in extractions}
    included = [rid for rid in ext_by_id]

    cards = {rid: study_card(records[rid], ext_by_id[rid], rob.get(rid)) for rid in included}
    full_cards = {rid: study_card(records[rid], ext_by_id[rid], rob.get(rid), full=True) for rid in included}

    # ---- themes, narrative synthesis, certainty ----------------------------
    if store.exists("themes"):
        themes = [Theme.model_validate(t) for t in store.load("themes")]
    else:
        themes = identify_themes(ctx, protocol, cards) if included else []
        store.save("themes", [t.model_dump() for t in themes], agent=AGENT)
    previous = store.load("manuscript_meta")["syntheses"] if store.exists("manuscript_meta") else {}
    syntheses: dict[str, ThemeSynthesis] = {}
    for theme in themes:
        try:
            syntheses[theme.name] = synthesise_theme(ctx, protocol, theme, full_cards, issues, guidance)
        except LLMError as exc:
            ctx.audit.log(AGENT, "llm_failure", theme=theme.name, error=str(exc)[:300])
            if theme.name in previous:  # a failed revision must not delete the existing narrative
                syntheses[theme.name] = ThemeSynthesis.model_validate(previous[theme.name])
    meta = prepare_meta_analysis(ctx, records, extractions) if included else {"n_effects": 0, "pooled": [], "note": "No studies were included."}
    map_rows = evidence_map(ctx, themes, ext_by_id, rob) if included else []

    # ---- other LLM-written parts ---------------------------------------------
    rationale = write_rationale(ctx, protocol, issues)
    theme_digest = "\n\n".join(f"Theme: {name}\n{syn.narrative}\nCertainty: {syn.certainty} — {syn.certainty_rationale}" for name, syn in syntheses.items())
    rob_counts = {level: sum(1 for r in rob.values() if r.overall == level) for level in ("low", "some concerns", "high", "unclear")}
    facts = (
        f"Review question: {protocol.research_question}\nStudies included: {len(included)}\n"
        f"Risk of bias (overall): {rob_counts}\nStudies read from abstract only: {sum(1 for e in extractions if e.basis == 'abstract')}"
    )
    if included:
        discussion = ctx.llm.structured(
            ctx.settings.role("writer"),
            "You write the Discussion of a systematic review (PRISMA 2020 item 23). Interpret the findings in "
            "light of the evidence only; do not introduce facts that are not in the material given. Keep the "
            "[R0000] citations when you refer to specific studies. Be measured: match the strength of each "
            "statement to the certainty of the evidence. Do not discuss limitations of the review process "
            "(another section covers them).",
            f"{facts}\n\nThematic synthesis:\n{theme_digest}{_feedback(issues, 'discussion')}",
            Discussion, agent=AGENT, max_tokens=1700,
        )
    else:
        discussion = Discussion(
            summary_of_evidence="No study met the eligibility criteria, so no evidence could be synthesised.",
            limitations_of_evidence="Not applicable: no studies were included.",
            implications="The absence of eligible studies indicates an evidence gap; primary research addressing the review question is needed.",
        )
    abstract = ctx.llm.structured(
        ctx.settings.role("writer"),
        "You write the structured abstract of a systematic review (PRISMA 2020 for Abstracts), 250-300 words "
        "in total. Use only the facts given, quote the numbers exactly, no citations, no new claims.",
        f"{facts}\nObjectives: {'; '.join(protocol.objectives)}\n"
        f"Databases searched: {', '.join(strategy.queries)} (search date {ctx.manifest['created'][:10]})\n"
        f"Eligibility: {'; '.join(c.text for c in protocol.inclusion_criteria)}\n"
        f"Flow: {flow.identified_total} records identified, {flow.records_screened} screened, "
        f"{flow.reports_assessed} reports assessed, {flow.studies_included} studies included.\n"
        "Methods facts: dual independent screening by two AI reviewers with adjudication; structured extraction with "
        "verified quotations; risk of bias with design-specific tools; narrative synthesis by theme.\n\n"
        f"Thematic synthesis:\n{theme_digest}\n\nDiscussion summary: {discussion.summary_of_evidence}"
        f"{_feedback(issues, 'abstract')}",
        AbstractText, agent=AGENT, max_tokens=1300,
    )

    abstract.methods = (
        f"We searched {_and([DISPLAY_NAME.get(db, db) for db in strategy.queries])} on {ctx.manifest['created'][:10]}. "
        f"Of {flow.identified_total} records identified, {flow.records_screened} were screened on title and abstract by two "
        f"independent AI reviewers with adjudication of disagreements, {flow.reports_assessed} reports were assessed for "
        f"eligibility and {flow.studies_included} studies were included. Data were extracted with supporting quotations that "
        "were verified automatically against the source, risk of bias was appraised with design-specific tools, and findings "
        "were synthesised narratively by theme."
    )

    # ---- tables ----------------------------------------------------------------
    key_items = protocol.data_items[:4]

    def item_value(ext: Extraction, name: str) -> str:
        for item in ext.items:
            if item.field.strip().lower() == name.strip().lower():
                flag = "" if item.quote_verified in (True, None) else " (unverified)"
                return _trim(item.value, 90) + flag
        return "Not reported"

    characteristics = [
        {
            "Study": _ref(records[e.rid]), "Design": _trim(e.study_design, 60), "Country": _trim(e.country, 40),
            "Sample": _trim(e.sample_size, 60), **{_trim(name, 40): item_value(e, name) for name in key_items},
            "Source read": e.basis.replace("_", " "),
        }
        for e in extractions
    ]
    rob_rows = [
        {
            "Study": _ref(records[r.rid]), "Tool": r.tool, "Overall": r.overall,
            "Domain judgements": "; ".join(f"{d.domain}: {d.judgement}" for d in r.domains),
            "Main concern": _trim(r.overall_justification, 220),
        }
        for r in rob.values() if r.rid in ext_by_id
    ]
    results_rows = [
        {
            "Study": _ref(records[e.rid]),
            "Key findings": " ".join(_trim(f, 240) for f in e.key_findings[:4]),
            "Effect estimates": "; ".join(effect_text(x) + ("" if x.quote_verified in (True, None) else " (unverified)") for x in e.effects) or "None reported",
        }
        for e in extractions
    ]
    evidence_rows = [
        {
            "rid": e.rid, "study": records[e.rid].short_ref(), "title": records[e.rid].title, "doi": records[e.rid].doi,
            "design": e.study_design, "country": e.country, "sample_size": e.sample_size, "basis": e.basis,
            **{f"item: {i.field}": i.value for i in e.items},
            **{f"quote: {i.field}": i.quote for i in e.items},
            **{f"verified: {i.field}": i.quote_verified for i in e.items},
            "key_findings": " | ".join(e.key_findings), "limitations": e.limitations_reported, "funding": e.funding,
            "rob_tool": rob[e.rid].tool if e.rid in rob else "", "rob_overall": rob[e.rid].overall if e.rid in rob else "",
        }
        for e in extractions
    ]
    write_csv(store.path("evidence_table.csv"), evidence_rows)

    # ---- results of syntheses -------------------------------------------------
    synthesis_parts = []
    for theme in themes:
        syn = syntheses.get(theme.name)
        if not syn:
            continue
        studies = ", ".join(f"[{rid}]" for rid in theme.study_ids)
        synthesis_parts.append(
            f"**{theme.name}** ({len(theme.study_ids)} studies: {studies}). {syn.narrative.strip()}"
        )
    if meta["pooled"]:
        pooled_rows = [
            {
                "Outcome": p["outcome"], "Measure": p["measure"], "Studies (k)": p["k"],
                "Random-effects estimate (95% CI)": f"{p['random_effects']} ({p['random_ci'][0]} to {p['random_ci'][1]})",
                "I² (%)": p["I2_percent"], "tau²": p["tau2"],
            }
            for p in meta["pooled"]
        ]
        synthesis_parts.append(
            "**Quantitative synthesis (exploratory).** Comparable effect estimates were pooled with a random-effects model "
            "(Table 4). These pooled values are exploratory: study comparability was judged automatically and must be "
            "verified before any inferential use.\n\n*Table 4. Exploratory random-effects pooling.*\n\n" + md_table(pooled_rows)
        )
    else:
        synthesis_parts.append(f"**Quantitative synthesis.** {meta['note']} {meta['n_effects']} effect estimates were extracted in total (effects.csv).")
    if map_rows and store.path("evidence_map.png").exists():
        synthesis_parts.append("![Figure 2. Evidence map of included studies by theme and study design](evidence_map.png)")
    if not included:
        synthesis_parts = ["No study met the eligibility criteria; no synthesis could be performed."]

    certainty_rows = [
        {"Theme": t.name, "Studies": len(t.study_ids), "Certainty": syntheses[t.name].certainty, "Rationale": syntheses[t.name].certainty_rationale}
        for t in themes if t.name in syntheses
    ]

    # ---- assemble ----------------------------------------------------------------
    methods = methods_sections(ctx, protocol, strategy, flow, agreement_ta, agreement_ft, human)
    excluded_ft = [d for d in ft_decisions if d.final == "exclude"]
    amendments = store.version_count("protocol") - 1
    parts: list[str] = [
        f"# {protocol.title}",
        "## Abstract",
        f"**Background:** {abstract.background}\n\n**Objectives:** {abstract.objectives}\n\n**Methods:** {abstract.methods}\n\n"
        f"**Results:** {abstract.results}\n\n**Conclusions:** {abstract.conclusions}",
        "## 1. Introduction",
        "### 1.1 Rationale", rationale,
        "### 1.2 Objectives",
        f"This review addresses the question: *{protocol.research_question}* Specific objectives:\n"
        + "\n".join(f"- {o}" for o in protocol.objectives),
        "## 2. Methods",
        "This review is reported according to the PRISMA 2020 statement. It was conducted by a multi-agent AI pipeline "
        "whose every decision is logged; the completed PRISMA checklist is in Appendix C.",
    ]
    for heading, body in methods.items():
        parts += [f"### {heading}", body]
    parts += [
        "## 3. Results",
        "### 3.1 Study selection", selection_results(flow, excluded_ft),
        "### 3.2 Study characteristics",
        (f"Table 1 summarises the {len(included)} included studies. The complete extraction form, with the supporting "
         "quotation for every value, is provided in evidence_table.csv.\n\n*Table 1. Characteristics of included studies.*\n\n"
         + md_table(characteristics)) if included else "No studies were included.",
        "### 3.3 Risk of bias in studies",
        (f"Overall risk of bias was judged low in {rob_counts['low']} studies, some concerns in {rob_counts['some concerns']}, "
         f"high in {rob_counts['high']} and unclear in {rob_counts['unclear']} (Table 2).\n\n*Table 2. Risk of bias in included studies.*\n\n"
         + md_table(rob_rows)) if included else "Not applicable: no studies were included.",
        "### 3.4 Results of individual studies",
        ("*Table 3. Results of individual studies.*\n\n" + md_table(results_rows)) if included else "Not applicable: no studies were included.",
        "### 3.5 Results of syntheses", "\n\n".join(synthesis_parts),
        "### 3.6 Reporting biases and certainty of evidence",
        "Reporting bias was not assessed formally; selective publication of favourable results cannot be excluded. "
        + ("Certainty of evidence per theme is shown in Table 5.\n\n*Table 5. Certainty of evidence by theme (automated, GRADE-inspired).*\n\n" + md_table(certainty_rows)
           if certainty_rows else "Certainty of evidence could not be rated because no studies were included."),
        "## 4. Discussion",
        "### 4.1 Summary of evidence", discussion.summary_of_evidence,
        "### 4.2 Limitations of the evidence", discussion.limitations_of_evidence,
        "### 4.3 Limitations of the review process", limitations_of_process(ctx, flow, extractions, human),
        "### 4.4 Implications", discussion.implications,
        "## 5. Other information",
        "### 5.1 Registration and protocol",
        f"{admin.get('registration', 'This review was not registered.')} "
        + (f"The protocol was amended {amendments} time(s) after human feedback, before the searches were run; every version is kept (protocol_v1.json to protocol_v{amendments + 1}.json)."
           if amendments > 0 else "No amendments were made to the protocol after it was generated."),
        "### 5.2 Support", admin.get("support", "No external funding was received for this review."),
        "### 5.3 Competing interests", admin.get("competing_interests", "The authors declare no competing interests."),
        "### 5.4 Availability of data, code and other materials",
        "All materials are stored in the run directory and can be shared: the protocol (protocol_v*.json), search strings and "
        "hit counts (search_strategy_v*.json), every retrieved record (records_raw.jsonl, records.jsonl), all screening "
        "decisions with both reviewers' rationales (screening_title_abstract.jsonl, screening_full_text.jsonl), extracted data "
        "with supporting quotations (extractions.jsonl, evidence_table.csv), risk-of-bias judgements (risk_of_bias.jsonl), "
        "effect estimates (effects.csv), the complete audit trail (audit.jsonl) and the trace of every model call "
        "(llm_trace.jsonl). The pipeline source code is available in the project repository.",
    ]
    body = "\n\n".join(parts)

    # ---- citations and back matter --------------------------------------------------
    body, cited, unknown = number_citations(body, records)
    references = "\n".join(f"{i}. {format_reference(records[rid])}" for i, rid in enumerate(cited, start=1))
    appendix_a = "\n\n".join(
        f"**{DISPLAY_NAME.get(db, db)}** ({strategy.hit_counts.get(db, 'n/a')} hits; {flow.identified.get(db, 0)} records retrieved)\n\n```\n{query}\n```"
        for db, query in strategy.queries.items()
    )
    appendix_b = md_table(
        [{"Report": f"{records[d.rid].short_ref()}. {_trim(records[d.rid].title, 110)}", "Reason for exclusion": d.exclusion_reason,
          "Assessed on": d.basis.replace("_", " ")} for d in excluded_ft]
    ) if excluded_ft else "No reports were excluded at full-text stage."
    body += (
        f"\n\n## References\n\n{references or 'No references.'}"
        f"\n\n## Appendix A. Search strategies\n\n{appendix_a}"
        f"\n\n## Appendix B. Reports excluded at full-text stage\n\n{appendix_b}"
    )

    store.save(
        "manuscript_meta",
        {
            "cited": cited, "unknown_citations": sorted(set(unknown)), "included": included,
            "themes": [t.model_dump() for t in themes],
            "syntheses": {name: syn.model_dump() for name, syn in syntheses.items()},
            "discussion": discussion.model_dump(), "rationale": rationale, "revision_issues": [i.model_dump() for i in issues],
        },
        agent=AGENT, note="revision" if issues else "first draft",
    )
    store.write_text("report_draft.md", body, agent=AGENT)
    ctx.audit.log(AGENT, "manuscript_written", words=len(body.split()), references=len(cited),
                  unknown_citations=len(set(unknown)), revision=bool(issues))
    return body
