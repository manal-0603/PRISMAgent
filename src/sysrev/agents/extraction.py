"""Extraction & Appraisal agent.

For every included study:

* RAG retrieves the passages relevant to each data item of the protocol;
* the agent fills a structured extraction form and must give a verbatim supporting
  quote for every value;
* the pipeline then checks, without any LLM, that each quote really occurs in the
  source text (`quote_verified`). Unverified quotes are surfaced to the Critic and
  to the human reviewer instead of being silently trusted;
* risk of bias is appraised by a second model with the tool matching the design.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from ..context import RunContext
from ..llm import LLMError
from ..models import DomainJudgement, EffectEstimate, ExtractedItem, Extraction, Protocol, Record, RiskOfBias
from ..rag.index import format_passages
from .planner import ReviewPlan, protocol_brief
from .retrieval import read_fulltext

AGENT = "extraction_appraisal"

ROB_TOOLS: dict[str, list[str]] = {
    "RoB 2": [
        "Randomisation process", "Deviations from intended interventions", "Missing outcome data",
        "Measurement of the outcome", "Selection of the reported result",
    ],
    "ROBINS-I": [
        "Confounding", "Selection of participants", "Classification of interventions",
        "Deviations from intended interventions", "Missing data", "Measurement of outcomes",
        "Selection of the reported result",
    ],
    "QUADAS-2": ["Patient selection", "Index test", "Reference standard", "Flow and timing"],
    "Newcastle-Ottawa Scale": ["Selection", "Comparability", "Outcome or exposure ascertainment"],
    "PROBAST": ["Participants and data sources", "Predictors and model inputs", "Outcome and reference labels", "Analysis"],
    "JBI checklist": [
        "Sample and setting clearly described", "Valid and reliable measurement",
        "Confounding identified and addressed", "Appropriate analysis", "Conclusions supported by the data",
    ],
}
ROB_USE = {
    "RoB 2": "randomised controlled trials",
    "ROBINS-I": "non-randomised studies of interventions",
    "QUADAS-2": "diagnostic test accuracy studies",
    "Newcastle-Ottawa Scale": "cohort and case-control studies",
    "PROBAST": "prediction-model, machine-learning and algorithm evaluation studies",
    "JBI checklist": "cross-sectional, qualitative, case-series and any other design",
}


class ItemDraft(BaseModel):
    field: str = Field(description="Data item name, exactly as listed in the protocol")
    value: str = Field(description="Concise extracted value, or 'Not reported'")
    quote: str = Field(description="One sentence copied verbatim from the text that supports the value; '' if not reported")


class EffectDraft(BaseModel):
    outcome: str
    measure: str = Field(description="OR, RR, HR, MD, SMD, accuracy, sensitivity, specificity, F1, AUC, proportion, kappa…")
    value: float
    ci_low: float | None = Field(default=None, description="Lower bound of the 95% CI if reported")
    ci_high: float | None = Field(default=None, description="Upper bound of the 95% CI if reported")
    n: int | None = Field(default=None, description="Sample size behind this estimate")
    quote: str = Field(default="", description="Sentence copied verbatim from the text that reports this number")


class ExtractionDraft(BaseModel):
    study_design: str = Field(description="Design in standard terms, e.g. 'randomised controlled trial', 'retrospective cohort'")
    country: str = Field(default="Not reported", description="Country/countries or 'Not reported'")
    sample_size: str = Field(default="Not reported", description="Number and unit, e.g. '312 patients', '5 datasets (12,430 records)', or 'Not reported'")
    items: list[ItemDraft]
    key_findings: list[str] = Field(description="2-5 main results as complete sentences, with numbers when reported")
    effects: list[EffectDraft] = Field(default_factory=list, description="Main quantitative results (at most 6); [] if none are reported")
    limitations_reported: str = Field(default="Not reported", description="Limitations acknowledged by the authors, or 'Not reported'")
    funding: str = Field(default="Not reported", description="Funding source, or 'Not reported'")


class RobDraft(BaseModel):
    tool: str = Field(description="Name of the appraisal tool, exactly as listed")
    domains: list[DomainJudgement]
    overall_justification: str = Field(description="2-3 sentences on what most threatens the validity of this study")


EXTRACT_SYSTEM = """You are a data extractor in a systematic review. Fill the extraction form \
for ONE study using ONLY the text provided (abstract and retrieved passages).

Rules:
- Never guess and never use outside knowledge. If the text does not report an item, write \
"Not reported" and leave its quote empty.
- For every reported item, `quote` must be one sentence copied character for character from the \
text. Quotes are checked automatically against the source.
- `items` must contain one entry per data item listed in the protocol, in the same order, using the \
same names.
- Report numbers exactly as written (do not round or convert units).
{guidance}

{protocol}"""

ROB_SYSTEM = """You are a methodologist appraising the risk of bias of ONE study for a \
systematic review, using ONLY the text provided.

1. Choose the appraisal tool that matches the study design:
{tools}
2. Judge every domain of that tool: "low", "some concerns", "high", or "unclear" when the text does \
not give the information needed. Missing information is "unclear", never "low".
3. Justify each judgement in one sentence and, where possible, copy the sentence of the text that \
supports it into `quote`.
Use the domain names exactly as listed.
{guidance}"""


def _normalise(text: str) -> str:
    text = text.lower().replace("[…]", " ").replace("…", " ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9%.<>=+\- ]", " ", text)).strip()


def verify_quote(quote: str, source_normalised: str) -> bool | None:
    """True if `quote` occurs (near-)verbatim in the source. None when there is no quote."""
    q = _normalise(quote)
    if len(q) < 12:
        return None
    if q in source_normalised:
        return True
    return fuzz.partial_ratio(q, source_normalised) >= 92


def _overall(domains: list[DomainJudgement]) -> str:
    judgements = [d.judgement for d in domains]
    if "high" in judgements:
        return "high"
    if judgements and all(j == "unclear" for j in judgements):
        return "unclear"
    if any(j in ("some concerns", "unclear") for j in judgements):
        return "some concerns"
    return "low"


def _evidence(ctx: RunContext, protocol: Protocol, rec: Record, queries: list[str], max_chunks: int, budget: int) -> str:
    abstract = f"ABSTRACT\n{rec.abstract or 'Not available'}"
    if not ctx.index.has(rec.rid, "fulltext"):
        return abstract + "\n\n(No open-access full text was available: only the abstract can be used.)"
    chunks = ctx.index.multi_search(queries, per_query=2, max_chunks=max_chunks, rids=[rec.rid], kind="fulltext", fetch_k=14)
    chunks = ctx.index.compress(" ".join(queries[:6]), chunks, budget)
    return f"{abstract}\n\nPASSAGES FROM THE FULL TEXT\n{format_passages(chunks)}"


def extract_and_appraise(ctx: RunContext, protocol: Protocol, records: list[Record],
                         plan: ReviewPlan | None = None) -> tuple[list[Extraction], list[RiskOfBias]]:
    guidance = f"Coordinator guidance: {plan.guidance_for('extraction_appraisal')}" if plan else ""
    extract_queries = (
        protocol.data_items
        + [f"Results: {outcome} obtained in this study (value, confidence interval)" for outcome in protocol.outcomes]
        + [
            "Methods: study design, setting and procedure", "number of participants, records or datasets analysed (sample size)",
            "Results: table of main results", "Limitations of this study", "Funding statement; country where the study was done",
        ]
    )
    rob_queries = [
        "randomisation, allocation, selection of participants or data", "blinding, reference standard, outcome measurement",
        "missing data, attrition, exclusions", "confounding, comparability, adjustment", "statistical analysis, validation, overfitting",
        "limitations of this study", "pre-registration, protocol, selective reporting",
    ]
    # Retrieval is done once, in the main thread; the two models then work in parallel.
    evidence = {r.rid: _evidence(ctx, protocol, r, extract_queries, 10, ctx.options.max_extraction_chars) for r in records}
    rob_evidence = {r.rid: _evidence(ctx, protocol, r, rob_queries, 7, ctx.options.max_appraisal_chars) for r in records}
    header = {
        r.rid: f"STUDY {r.rid}: {r.title}\nAuthors: {'; '.join(r.authors[:6]) or 'n/a'} | Year: {r.year or 'n/a'} | Venue: {r.venue or 'n/a'}"
        for r in records
    }

    def run_extraction() -> list[Extraction]:
        system = EXTRACT_SYSTEM.format(guidance=guidance, protocol=protocol_brief(protocol, with_data_items=True))
        out = []
        for rec in records:
            basis = "full_text" if ctx.index.has(rec.rid, "fulltext") else "abstract"
            try:
                draft = ctx.llm.structured(
                    ctx.settings.role("extractor"), system, f"{header[rec.rid]}\n\n{evidence[rec.rid]}", ExtractionDraft,
                    agent=f"{AGENT}:extractor", max_tokens=2000,
                )
            except LLMError as exc:
                ctx.audit.log(AGENT, "llm_failure", rid=rec.rid, task="extraction", error=str(exc)[:300])
                continue
            source = _normalise(read_fulltext(ctx, rec.rid) + " " + rec.abstract + " " + rec.title)
            items = [
                ExtractedItem(field=i.field, value=i.value, quote=i.quote, quote_verified=verify_quote(i.quote, source))
                for i in draft.items
            ]
            effects = [
                EffectEstimate(**e.model_dump(), quote_verified=verify_quote(e.quote, source)) for e in draft.effects[:6]
            ]
            extraction = Extraction(
                rid=rec.rid, study_design=draft.study_design, country=draft.country, sample_size=draft.sample_size,
                items=items, key_findings=draft.key_findings, effects=effects,
                limitations_reported=draft.limitations_reported, funding=draft.funding, basis=basis,
            )
            checked = [x.quote_verified for x in items + effects if x.quote_verified is not None]
            ctx.audit.log(AGENT, "extracted", rid=rec.rid, basis=basis, items=len(items), effects=len(effects),
                          quotes_checked=len(checked), quotes_verified=sum(checked))
            out.append(extraction)
        return out

    def run_appraisal() -> list[RiskOfBias]:
        tools = "\n".join(f"   - {name} ({ROB_USE[name]}): domains = {'; '.join(doms)}" for name, doms in ROB_TOOLS.items())
        system = ROB_SYSTEM.format(tools=tools, guidance=guidance)
        out = []
        for rec in records:
            try:
                draft = ctx.llm.structured(
                    ctx.settings.role("appraiser"), system, f"{header[rec.rid]}\n\n{rob_evidence[rec.rid]}", RobDraft,
                    agent=f"{AGENT}:appraiser", max_tokens=1300,
                )
            except LLMError as exc:
                ctx.audit.log(AGENT, "llm_failure", rid=rec.rid, task="risk_of_bias", error=str(exc)[:300])
                continue
            tool = next((t for t in ROB_TOOLS if t.lower() in draft.tool.lower()), "JBI checklist")
            given = {d.domain.lower(): d for d in draft.domains}
            domains = [
                given.get(name.lower())
                or DomainJudgement(domain=name, judgement="unclear", justification="Not assessed by the appraiser.")
                for name in ROB_TOOLS[tool]
            ]
            for domain, name in zip(domains, ROB_TOOLS[tool]):
                domain.domain = name
            rob = RiskOfBias(rid=rec.rid, tool=tool, domains=domains, overall=_overall(domains),
                             overall_justification=draft.overall_justification)
            ctx.audit.log(AGENT, "appraised", rid=rec.rid, tool=tool, overall=rob.overall)
            out.append(rob)
        return out

    with ThreadPoolExecutor(max_workers=2) as pool:
        f_extract, f_rob = pool.submit(run_extraction), pool.submit(run_appraisal)
        extractions, appraisals = f_extract.result(), f_rob.result()

    ctx.store.save_lines("extractions", extractions, agent=AGENT)
    ctx.store.save_lines("risk_of_bias", appraisals, agent=AGENT)
    return extractions, appraisals


def quote_stats(extractions: list[Extraction]) -> dict:
    flags = [x.quote_verified for e in extractions for x in (e.items + e.effects) if x.quote_verified is not None]
    return {
        "quotes_checked": len(flags),
        "quotes_verified": sum(flags),
        "verification_rate": round(sum(flags) / len(flags), 4) if flags else None,
    }
