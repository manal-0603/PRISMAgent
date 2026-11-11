"""Typed data model shared by every agent.

Every artifact written to a run directory is one of these models, which is what
makes a run auditable and re-loadable.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# Bibliographic records
# --------------------------------------------------------------------------- #


class Record(BaseModel):
    """One bibliographic record, possibly merged from several databases."""

    rid: str = ""  # stable internal id (R0001…), assigned after deduplication
    title: str
    abstract: str = ""
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str = ""
    doi: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    arxiv_id: str | None = None
    openalex_id: str | None = None
    s2_id: str | None = None
    url: str | None = None
    pdf_url: str | None = None
    pub_type: str = ""
    cited_by: int | None = None
    sources: list[str] = Field(default_factory=list)

    def short_ref(self) -> str:
        first = self.authors[0].split(",")[0].strip() if self.authors else "Anon"  # authors are "Surname, Given"
        et_al = " et al." if len(self.authors) > 1 else ""
        return f"{first}{et_al} ({self.year or 'n.d.'})"


# --------------------------------------------------------------------------- #
# Protocol (PRISMA-P aligned)
# --------------------------------------------------------------------------- #


class Criterion(BaseModel):
    id: str = Field(description="Short id such as I1, I2 (inclusion) or E1, E2 (exclusion)")
    text: str = Field(description="One precise, checkable eligibility rule")


class Protocol(BaseModel):
    title: str = Field(description="Title of the review, identifying it as a systematic review")
    research_question: str
    rationale: str = Field(description="Why this review is needed (2-4 sentences)")
    objectives: list[str]
    framework: str = Field(description="Question framework used: PICO, PECO, PCC, SPIDER…")
    framework_elements: dict[str, str] = Field(
        description="Framework element name -> definition, e.g. Population, Intervention, Comparator, Outcome"
    )
    inclusion_criteria: list[Criterion]
    exclusion_criteria: list[Criterion]
    study_designs: list[str] = Field(description="Eligible study designs")
    date_from: int | None = Field(default=None, description="Earliest publication year, or null")
    date_to: int | None = Field(default=None, description="Latest publication year, or null")
    languages: list[str] = Field(default_factory=lambda: ["English"])
    databases: list[str] = Field(
        description="Subset of: pubmed, europepmc, openalex, arxiv, semantic_scholar"
    )
    outcomes: list[str] = Field(description="Outcomes / data items of interest")
    data_items: list[str] = Field(description="Fields to extract from every included study")
    risk_of_bias_approach: str = Field(description="Appraisal tool(s) and how they are applied")
    synthesis_plan: str = Field(description="Planned narrative and, if applicable, quantitative synthesis")
    meta_analysis_planned: bool = False


# --------------------------------------------------------------------------- #
# Search strategy
# --------------------------------------------------------------------------- #


class Concept(BaseModel):
    name: str = Field(description="Concept block, e.g. the population or the intervention")
    free_text_terms: list[str] = Field(description="Synonyms, spelling variants, truncations")
    controlled_terms: list[str] = Field(
        default_factory=list, description="MeSH headings for this concept (PubMed), if any"
    )


class SearchStrategy(BaseModel):
    concepts: list[Concept]
    queries: dict[str, str] = Field(description="database name -> executable query string")
    rationale: str = Field(description="How the strategy balances sensitivity and precision")
    hit_counts: dict[str, int] = Field(default_factory=dict)
    refinement_log: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Screening
# --------------------------------------------------------------------------- #

Decision = Literal["include", "exclude", "unsure"]


class ReviewerVote(BaseModel):
    decision: Decision
    criteria: list[str] = Field(
        default_factory=list, description="Ids of the criteria that drove the decision (e.g. E2, I1)"
    )
    rationale: str = Field(description="One or two sentences justifying the decision")
    confidence: float = Field(default=0.5, ge=0, le=1)


class ScreeningDecision(BaseModel):
    rid: str
    stage: Literal["title_abstract", "full_text"]
    reviewer_a: ReviewerVote
    reviewer_b: ReviewerVote
    agreed: bool
    final: Literal["include", "exclude"]
    resolved_by: Literal["consensus", "adjudicator", "human"]
    final_rationale: str
    exclusion_reason: str = ""  # criterion id used for PRISMA "reports excluded, with reasons"
    basis: Literal["abstract", "full_text"] = "abstract"
    evidence: list[str] = Field(default_factory=list)  # chunk ids shown to reviewers


# --------------------------------------------------------------------------- #
# Extraction and appraisal
# --------------------------------------------------------------------------- #


class ExtractedItem(BaseModel):
    field: str = Field(description="Name of the data item")
    value: str = Field(description="Extracted value, or 'Not reported'")
    quote: str = Field(
        default="", description="Verbatim sentence from the provided text supporting the value"
    )
    quote_verified: bool | None = None  # set by the pipeline, never by the model


class EffectEstimate(BaseModel):
    outcome: str
    measure: str = Field(description="e.g. OR, RR, HR, MD, SMD, accuracy, sensitivity, proportion")
    value: float
    ci_low: float | None = None
    ci_high: float | None = None
    n: int | None = Field(default=None, description="Sample size behind this estimate")
    quote: str = Field(default="", description="Verbatim sentence reporting the estimate")
    quote_verified: bool | None = None


class Extraction(BaseModel):
    rid: str
    study_design: str
    country: str = "Not reported"
    sample_size: str = "Not reported"
    items: list[ExtractedItem]
    key_findings: list[str]
    effects: list[EffectEstimate] = Field(default_factory=list)
    limitations_reported: str = "Not reported"
    funding: str = "Not reported"
    basis: Literal["abstract", "full_text"] = "abstract"


class DomainJudgement(BaseModel):
    domain: str
    judgement: Literal["low", "some concerns", "high", "unclear"]
    justification: str
    quote: str = ""


class RiskOfBias(BaseModel):
    rid: str
    tool: str
    domains: list[DomainJudgement]
    overall: Literal["low", "some concerns", "high", "unclear"]
    overall_justification: str


# --------------------------------------------------------------------------- #
# Synthesis and QA
# --------------------------------------------------------------------------- #


class Theme(BaseModel):
    name: str
    description: str
    study_ids: list[str] = Field(description="Record ids (R0001…) of the studies in this theme")


class QAIssue(BaseModel):
    severity: Literal["critical", "major", "minor"]
    area: str
    description: str
    suggested_fix: str = ""


class QAReport(BaseModel):
    verdict: Literal["pass", "revise"]
    issues: list[QAIssue] = Field(default_factory=list)
    checks: dict[str, object] = Field(default_factory=dict)
