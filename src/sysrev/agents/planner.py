"""Coordinator / Planner agent.

1. Turns a free-text question into a PRISMA-P aligned protocol, honouring the
   configurable template (`config/protocol_template.yaml`).
2. Decomposes the review into stages and writes a short brief for each downstream
   agent (what to watch for on *this* topic). The briefs are injected in the
   prompts of the other agents.
3. Revises the protocol when the human reviewer asks for changes.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from ..context import RunContext
from ..models import Criterion, Protocol
from ..sources.connectors import SOURCES

AGENT = "planner"

STAGES = [
    "search_strategy",
    "retrieval",
    "title_abstract_screening",
    "full_text_screening",
    "extraction_appraisal",
    "synthesis_writing",
    "quality_assurance",
]


class StageBrief(BaseModel):
    stage: str = Field(description=f"One of: {', '.join(STAGES)}")
    objective: str = Field(description="What this stage must achieve for this review")
    guidance: str = Field(description="Topic-specific pitfalls and decision rules for the agent in charge (2-4 sentences)")


class ReviewPlan(BaseModel):
    briefs: list[StageBrief]

    def guidance_for(self, stage: str) -> str:
        return next((b.guidance for b in self.briefs if b.stage == stage), "")


SYSTEM = """You are the lead methodologist of a systematic review team. You write review \
protocols that follow PRISMA-P 2015 and PRISMA 2020.

Rules:
- Be specific to the research question; never write generic boilerplate.
- Eligibility criteria must be precise and checkable from a title and abstract. Use ids I1, I2… \
for inclusion and E1, E2… for exclusion.
- `databases` must be chosen among: {databases}.
- `data_items` are what must be read out of each study (population, intervention, comparator, \
methods, results…), 5-9 items. Do not list bibliographic fields (authors, year, title, journal, DOI), \
study design, country, sample size or funding: the pipeline records those automatically.
- Follow the template below. Values under `fixed` are imposed: copy them into the protocol and add \
to them only where the field is a list. Text under `guidance` tells you how to write a field.

Template:
{template}"""


def load_template(path: str) -> dict:
    file = Path(path)
    if not file.exists():
        return {"fixed": {}, "guidance": {}, "administrative": {}}
    return yaml.safe_load(file.read_text(encoding="utf-8")) or {}


def _apply_fixed(protocol: Protocol, fixed: dict) -> Protocol:
    """Enforce template constraints deterministically (never trust the model for this)."""
    data = protocol.model_dump()
    for key in ("framework", "date_from", "date_to"):
        if fixed.get(key) not in (None, "", []):
            data[key] = fixed[key]
    for key in ("languages", "databases", "study_designs"):
        if fixed.get(key):
            data[key] = list(fixed[key])
    for key in ("data_items",):
        for item in fixed.get(key) or []:
            if item not in data[key]:
                data[key].append(item)
    for key, prefix in (("inclusion_criteria", "I"), ("exclusion_criteria", "E")):
        merged: list[str] = []
        for text in [c["text"] for c in data[key]] + list(fixed.get(key) or []):
            # the model usually copies the imposed criteria itself, with small rewordings
            if not any(fuzz.ratio(text.lower(), kept.lower()) >= 85 for kept in merged):
                merged.append(text)
        data[key] = [{"id": f"{prefix}{i}", "text": text} for i, text in enumerate(merged, start=1)]
    automatic = ("author", "year", "title", "journal", "doi", "publication date", "study design", "country", "sample size", "funding")
    data["data_items"] = [item for item in data["data_items"] if not item.strip().lower().startswith(automatic)] or data["data_items"]
    data["databases"] = [d for d in dict.fromkeys(data["databases"]) if d in SOURCES] or ["openalex", "europepmc"]
    return Protocol.model_validate(data)


def generate_protocol(ctx: RunContext, question: str, feedback: str = "", previous: Protocol | None = None) -> Protocol:
    template = load_template(ctx.options.protocol_template)
    system = SYSTEM.format(
        databases=", ".join(SOURCES),
        template=yaml.safe_dump({k: template.get(k, {}) for k in ("fixed", "guidance")}, sort_keys=False),
    )
    user = f"Research question / topic:\n{question}\n\nWrite the full protocol."
    if previous and feedback:
        user = (
            f"Research question / topic:\n{question}\n\nCurrent protocol (JSON):\n{previous.model_dump_json()}\n\n"
            f"The human reviewer requests these changes:\n{feedback}\n\n"
            "Return the complete revised protocol. Change only what the feedback requires."
        )
    protocol = ctx.llm.structured(ctx.settings.role("planner"), system, user, Protocol, agent=AGENT, max_tokens=2600)
    protocol = _apply_fixed(protocol, template.get("fixed") or {})
    if ctx.options.databases:
        protocol.databases = [d for d in ctx.options.databases if d in SOURCES]
    ctx.store.save("protocol", protocol, agent=AGENT, note="revised after human feedback" if feedback else "initial")
    ctx.audit.log(
        AGENT, "protocol_generated", framework=protocol.framework, databases=protocol.databases,
        n_inclusion=len(protocol.inclusion_criteria), n_exclusion=len(protocol.exclusion_criteria),
        feedback=feedback,
    )
    return protocol


def make_plan(ctx: RunContext, protocol: Protocol) -> ReviewPlan:
    system = (
        "You coordinate a team of AI agents conducting a systematic review. Decompose the review into "
        f"these stages, in this order: {', '.join(STAGES)}. For each stage write the objective and "
        "topic-specific guidance for the agent in charge: typical false positives to reject at screening, "
        "terms that are ambiguous in this field, which data items are hard to find, what makes studies "
        "non-comparable. Be concrete, at most 60 words of guidance per stage; do not restate the protocol."
    )
    user = f"Protocol:\n{protocol_brief(protocol)}"
    plan = ctx.llm.structured(ctx.settings.role("planner"), system, user, ReviewPlan, agent=AGENT, max_tokens=1500)
    plan.briefs = [b for b in plan.briefs if b.stage in STAGES]
    ctx.store.save("plan", plan, agent=AGENT)
    return plan


def protocol_brief(protocol: Protocol, with_data_items: bool = False) -> str:
    """Compact text rendering of the protocol used in downstream prompts."""
    lines = [
        f"Review question: {protocol.research_question}",
        f"Framework ({protocol.framework}): "
        + "; ".join(f"{k} = {v}" for k, v in protocol.framework_elements.items()),
        "Eligible study designs: " + ", ".join(protocol.study_designs),
    ]
    if protocol.date_from or protocol.date_to:
        lines.append(f"Publication years: {protocol.date_from or 'any'} to {protocol.date_to or 'present'}")
    lines.append("Inclusion criteria:")
    lines += [f"  {c.id}. {c.text}" for c in protocol.inclusion_criteria]
    lines.append("Exclusion criteria:")
    lines += [f"  {c.id}. {c.text}" for c in protocol.exclusion_criteria]
    if with_data_items:
        lines.append("Outcomes of interest: " + "; ".join(protocol.outcomes))
        lines.append("Data items to extract: " + "; ".join(protocol.data_items))
    return "\n".join(lines)


def criteria_by_id(protocol: Protocol) -> dict[str, Criterion]:
    return {c.id: c for c in protocol.inclusion_criteria + protocol.exclusion_criteria}
