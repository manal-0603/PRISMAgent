"""Screening agents (title/abstract and full text).

Dual independent screening is simulated with two *different* language models
(reviewer A and reviewer B) that never see each other's votes. Disagreements go to
an adjudicator who sees both rationales. Every decision stores the criteria ids
and a written rationale, and agreement is measured with Cohen's kappa.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, Field

from ..context import RunContext
from ..llm import LLMError
from ..models import Decision, Protocol, Record, ReviewerVote, ScreeningDecision
from ..rag.index import Chunk, format_passages
from ..tools.stats import cohen_kappa, kappa_label
from .planner import ReviewPlan, criteria_by_id, protocol_brief
from .retrieval import relevance_query

AGENT_TA = "screening_title_abstract"
AGENT_FT = "screening_full_text"
REVIEWERS = {"A": "reviewer_a", "B": "reviewer_b"}  # reviewer name -> task (the model is set in the configuration)


class BatchVote(BaseModel):
    rid: str = Field(description="Record id exactly as given, e.g. R0012")
    decision: Decision
    criteria: list[str] = Field(description="Ids of the criteria that drove the decision, most important first")
    rationale: str = Field(description="One sentence (at most 30 words) citing what in the text justifies the decision")
    confidence: float = Field(ge=0, le=1)


class BatchVotes(BaseModel):
    votes: list[BatchVote]


class Adjudication(BaseModel):
    decision: Decision = Field(description="include or exclude (never unsure)")
    criteria: list[str] = Field(description="Ids of the decisive criteria, most important first")
    rationale: str


# v2 (see docs/evaluation): v1 let reviewers exclude a record when the abstract did not *mention* a
# required feature (e.g. a comparator). Against human screening decisions this cost most of the
# sensitivity, so the rules below make the convention of title/abstract screening explicit.
SCREENING_PROMPT_VERSION = "v2"

TA_SYSTEM = """You are an experienced systematic reviewer screening titles and abstracts. \
You work independently: another reviewer screens the same records separately.

Title/abstract screening only removes records that are obviously irrelevant; eligibility is decided \
later on the full text. An abstract never describes a whole study, so absence of information is not \
evidence of absence.
- "exclude": ONLY when the title/abstract positively shows that the record cannot be eligible: a \
different topic, population or condition; a different intervention or exposure; or a publication type \
the criteria exclude (editorial, review, protocol…). List the decisive criterion ids.
- "unsure": the record is on topic but the abstract does not say whether a criterion is met — for \
example it does not mention a comparator, the study design, the outcomes measured or the sample. \
NEVER exclude for something that is merely not mentioned; such records go to full-text review.
- "include": the record appears to satisfy every inclusion criterion.
Judge each record on its own text only, not on what you may know about the paper, and independently \
of the other records in the batch. Return one vote per record, with its exact id.
{guidance}

{protocol}"""

FT_SYSTEM = """You are an experienced systematic reviewer assessing a full report for \
eligibility. You work independently: another reviewer assesses the same report separately.

You are given the abstract and the passages of the report most relevant to the eligibility criteria \
(retrieved from the {basis}). Decide:
- "include": the report meets every inclusion criterion and no exclusion criterion.
- "exclude": it fails a criterion. Put the single most important criterion id first in `criteria`; \
it becomes the recorded exclusion reason.
- "unsure": the passages do not allow a decision.
Base the decision only on the text provided and quote or paraphrase the decisive passage in the \
rationale. Return exactly one vote.
{guidance}

{protocol}"""

ADJUDICATOR_SYSTEM = """You are the senior reviewer who resolves disagreements between two \
independent screeners in a systematic review ({stage} stage). Read the record, the eligibility \
criteria and both reviewers' votes, then make the final decision: "include" or "exclude".
{rule}
Explain which reviewer's reading of the criteria is correct and why.

{protocol}"""


def _record_block(rec: Record, max_abstract: int = 1500) -> str:
    abstract = rec.abstract[:max_abstract] + ("…" if len(rec.abstract) > max_abstract else "")
    # Only PubMed's curated publication types are shown: the "type" labels of the other
    # databases are assigned automatically and often wrong (primary studies tagged "review").
    kind = f" | PubMed publication type: {rec.pub_type}" if "pubmed" in rec.sources and rec.pub_type else ""
    return (
        f"### {rec.rid}\nTitle: {rec.title}\nYear: {rec.year or 'n/a'} | Venue: {rec.venue or 'n/a'}{kind}\n"
        f"Abstract: {abstract or 'NOT AVAILABLE'}"
    )


def _positive(decision: str) -> bool:
    return decision in ("include", "unsure")


def _fallback_vote(reason: str) -> ReviewerVote:
    return ReviewerVote(decision="unsure", criteria=[], rationale=reason, confidence=0.0)


def _vote(batch_vote: BatchVote, valid_ids: set[str]) -> ReviewerVote:
    return ReviewerVote(
        decision=batch_vote.decision,
        criteria=[c for c in batch_vote.criteria if c in valid_ids],
        rationale=batch_vote.rationale,
        confidence=batch_vote.confidence,
    )


# --------------------------------------------------------------------------- #
# Title / abstract
# --------------------------------------------------------------------------- #


def _review_batches(ctx: RunContext, role: str, system: str, records: list[Record], valid_ids: set[str],
                    batch_size: int, agent: str) -> dict[str, ReviewerVote]:
    votes: dict[str, ReviewerVote] = {}

    def ask(batch: list[Record]) -> None:
        user = "Records to screen:\n\n" + "\n\n".join(_record_block(r) for r in batch)
        try:
            out = ctx.llm.structured(role, system, user, BatchVotes, agent=agent, max_tokens=220 * len(batch) + 200)
        except LLMError as exc:
            ctx.audit.log(agent, "llm_failure", rids=[r.rid for r in batch], error=str(exc)[:300])
            return
        wanted = {r.rid for r in batch}
        for item in out.votes:
            if item.rid in wanted and item.rid not in votes:
                votes[item.rid] = _vote(item, valid_ids)

    for start in range(0, len(records), batch_size):
        ask(records[start : start + batch_size])
    for rec in records:  # records the model skipped are asked again one by one
        if rec.rid not in votes:
            ask([rec])
        if rec.rid not in votes:
            votes[rec.rid] = _fallback_vote("No valid model output; sent to the next stage for safety.")
    return votes


def _adjudicate(ctx: RunContext, stage: str, protocol: Protocol, body: str, a: ReviewerVote, b: ReviewerVote,
                valid_ids: set[str], agent: str) -> Adjudication:
    rule = (
        "At the title/abstract stage, exclude only if the abstract positively shows that a criterion is "
        "violated. Information that is merely not mentioned (comparator, design, outcomes) is not a "
        "violation: in that case include, so that the full text is examined."
        if stage == "title/abstract"
        else "At the full-text stage a definite decision is required. If the text provided cannot settle "
        "the point, include and say so, so that a human can verify."
    )
    system = ADJUDICATOR_SYSTEM.format(stage=stage, rule=rule, protocol=protocol_brief(protocol))
    user = (
        f"{body}\n\nReviewer A: {a.decision} (criteria: {', '.join(a.criteria) or 'none'}) — {a.rationale}\n"
        f"Reviewer B: {b.decision} (criteria: {', '.join(b.criteria) or 'none'}) — {b.rationale}"
    )
    try:
        out = ctx.llm.structured(ctx.settings.role("adjudicator"), system, user, Adjudication, agent=agent, max_tokens=700)
    except LLMError as exc:
        return Adjudication(decision="include", criteria=[], rationale=f"Adjudicator failed ({exc}); included for human check.")
    out.criteria = [c for c in out.criteria if c in valid_ids]
    if out.decision == "unsure":
        out.decision = "include"
    return out


def _exclusion_reason(criteria: list[str], protocol: Protocol) -> str:
    known = criteria_by_id(protocol)
    for cid in criteria:
        if cid in known:
            return f"{cid}: {known[cid].text}"
    return "Other / not specified"


def _agreement(decisions: list[ScreeningDecision]) -> dict:
    a = ["include" if _positive(d.reviewer_a.decision) else "exclude" for d in decisions]
    b = ["include" if _positive(d.reviewer_b.decision) else "exclude" for d in decisions]
    kappa = cohen_kappa(a, b)
    n = len(decisions)
    return {
        "n": n,
        "raw_agreement": round(sum(x == y for x, y in zip(a, b)) / n, 4) if n else None,
        "cohen_kappa": round(kappa, 4) if kappa is not None else None,
        "interpretation": kappa_label(kappa),
        "conflicts": sum(x != y for x, y in zip(a, b)),
        "reviewer_a_included": a.count("include"),
        "reviewer_b_included": b.count("include"),
        "resolved_by": {
            how: sum(d.resolved_by == how for d in decisions) for how in ("consensus", "adjudicator", "human")
        },
    }


def screen_title_abstract(ctx: RunContext, protocol: Protocol, records: list[Record],
                          plan: ReviewPlan | None = None) -> list[ScreeningDecision]:
    valid_ids = set(criteria_by_id(protocol))
    guidance = f"Coordinator guidance: {plan.guidance_for('title_abstract_screening')}" if plan else ""
    system = TA_SYSTEM.format(guidance=guidance, protocol=protocol_brief(protocol))
    batch = ctx.options.screen_batch_size

    with ThreadPoolExecutor(max_workers=2) as pool:  # the two reviewers run concurrently and independently
        futures = {
            name: pool.submit(_review_batches, ctx, ctx.settings.role(task), system, records, valid_ids, batch, f"{AGENT_TA}:{name}")
            for name, task in REVIEWERS.items()
        }
        votes = {name: future.result() for name, future in futures.items()}

    decisions: list[ScreeningDecision] = []
    for rec in records:
        a, b = votes["A"][rec.rid], votes["B"][rec.rid]
        agreed = _positive(a.decision) == _positive(b.decision)
        if agreed:
            final = "include" if _positive(a.decision) else "exclude"
            resolved, rationale, criteria = "consensus", f"A: {a.rationale} | B: {b.rationale}", a.criteria or b.criteria
        else:
            verdict = _adjudicate(ctx, "title/abstract", protocol, _record_block(rec), a, b, valid_ids,
                                  f"{AGENT_TA}:adjudicator")
            final, resolved, rationale, criteria = verdict.decision, "adjudicator", verdict.rationale, verdict.criteria
        decisions.append(
            ScreeningDecision(
                rid=rec.rid, stage="title_abstract", reviewer_a=a, reviewer_b=b, agreed=agreed, final=final,
                resolved_by=resolved, final_rationale=rationale,
                exclusion_reason=_exclusion_reason(criteria, protocol) if final == "exclude" else "",
            )
        )
        ctx.audit.log(AGENT_TA, "decision", rid=rec.rid, a=a.decision, b=b.decision, final=final, resolved_by=resolved)

    ctx.store.save_lines("screening_title_abstract", decisions, agent=AGENT_TA)
    ctx.store.save("agreement_title_abstract", _agreement(decisions), agent=AGENT_TA)
    return decisions


# --------------------------------------------------------------------------- #
# Full text
# --------------------------------------------------------------------------- #


def eligibility_evidence(ctx: RunContext, protocol: Protocol, rid: str) -> list[Chunk]:
    """RAG: passages of one report most relevant to each eligibility criterion."""
    queries = [c.text for c in protocol.inclusion_criteria + protocol.exclusion_criteria]
    queries += [f"{name}: {value}" for name, value in protocol.framework_elements.items()]
    queries.append("study design, methods, participants, sample")
    chunks = ctx.index.multi_search(queries, per_query=2, max_chunks=7, rids=[rid], kind="fulltext", fetch_k=14)
    return ctx.index.compress(relevance_query(protocol), chunks, ctx.options.max_fulltext_chars)


def screen_full_text(ctx: RunContext, protocol: Protocol, records: list[Record], provenance: dict[str, str],
                     plan: ReviewPlan | None = None) -> list[ScreeningDecision]:
    valid_ids = set(criteria_by_id(protocol))
    guidance = f"Coordinator guidance: {plan.guidance_for('full_text_screening')}" if plan else ""
    fallback = ctx.options.fulltext_fallback

    # Evidence is prepared up front (single thread), reviewers then run in parallel.
    prepared: dict[str, tuple[str, str, list[str]]] = {}
    not_retrieved: list[Record] = []
    for rec in records:
        has_text = ctx.index.has(rec.rid, "fulltext")
        if not has_text and fallback == "exclude":
            not_retrieved.append(rec)
            continue
        if has_text:
            chunks = eligibility_evidence(ctx, protocol, rec.rid)
            body = f"{_record_block(rec, 1000)}\n\nPassages from the full text:\n{format_passages(chunks)}"
            prepared[rec.rid] = (body, "full_text", [c.id for c in chunks])
        else:
            body = f"{_record_block(rec, 2500)}\n\n(No open-access full text could be retrieved: assess on the abstract.)"
            prepared[rec.rid] = (body, "abstract", [])

    def review(name: str, role: str) -> dict[str, ReviewerVote]:
        out: dict[str, ReviewerVote] = {}
        for rid, (body, basis, _) in prepared.items():
            system = FT_SYSTEM.format(
                basis="full text" if basis == "full_text" else "abstract only (full text unavailable)",
                guidance=guidance, protocol=protocol_brief(protocol),
            )
            try:
                votes = ctx.llm.structured(role, system, body, BatchVotes, agent=f"{AGENT_FT}:{name}", max_tokens=500)
                out[rid] = _vote(votes.votes[0], valid_ids) if votes.votes else _fallback_vote("Empty model output.")
            except LLMError as exc:
                ctx.audit.log(AGENT_FT, "llm_failure", rid=rid, error=str(exc)[:300])
                out[rid] = _fallback_vote("No valid model output.")
        return out

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {name: pool.submit(review, name, ctx.settings.role(task)) for name, task in REVIEWERS.items()}
        votes = {name: future.result() for name, future in futures.items()}

    decisions: list[ScreeningDecision] = []
    for rec in records:
        if rec.rid not in prepared:
            continue
        body, basis, evidence = prepared[rec.rid]
        a, b = votes["A"][rec.rid], votes["B"][rec.rid]
        agreed = a.decision == b.decision and a.decision != "unsure"
        if agreed:
            final, resolved = a.decision, "consensus"
            rationale, criteria = f"A: {a.rationale} | B: {b.rationale}", a.criteria or b.criteria
        else:
            verdict = _adjudicate(ctx, "full-text", protocol, body, a, b, valid_ids, f"{AGENT_FT}:adjudicator")
            final, resolved, rationale, criteria = verdict.decision, "adjudicator", verdict.rationale, verdict.criteria
        decisions.append(
            ScreeningDecision(
                rid=rec.rid, stage="full_text", reviewer_a=a, reviewer_b=b, agreed=agreed, final=final,
                resolved_by=resolved, final_rationale=rationale, basis=basis, evidence=evidence,
                exclusion_reason=_exclusion_reason(criteria, protocol) if final == "exclude" else "",
            )
        )
        ctx.audit.log(AGENT_FT, "decision", rid=rec.rid, a=a.decision, b=b.decision, final=final,
                      resolved_by=resolved, basis=basis, source=provenance.get(rec.rid))

    ctx.store.save_lines("screening_full_text", decisions, agent=AGENT_FT)
    ctx.store.save("reports_not_retrieved", [r.rid for r in not_retrieved], agent=AGENT_FT)
    # at full text, agreement is computed on the definite include/exclude votes
    ctx.store.save("agreement_full_text", _agreement(decisions), agent=AGENT_FT)
    return decisions


# --------------------------------------------------------------------------- #
# Human overrides
# --------------------------------------------------------------------------- #


def apply_overrides(ctx: RunContext, artifact: str, overrides: dict[str, str], protocol: Protocol) -> int:
    """Apply human decisions ({rid: 'include' | 'exclude'}) on top of the agents' decisions."""
    decisions = ctx.store.load_lines(artifact, ScreeningDecision)
    changed = 0
    for decision in decisions:
        new = overrides.get(decision.rid)
        if new in ("include", "exclude") and new != decision.final:
            ctx.audit.log("human", "decision_overridden", rid=decision.rid, stage=decision.stage,
                          previous=decision.final, new=new)
            decision.final, decision.resolved_by = new, "human"
            decision.final_rationale = f"Human reviewer override. Agents had said: {decision.final_rationale}"
            decision.exclusion_reason = "Excluded by human reviewer" if new == "exclude" else ""
            changed += 1
    if changed:
        ctx.store.save_lines(artifact, decisions, agent="human")
    return changed
