"""Shared fixtures.

`calls` replaces the LLM-backed agents by small fakes that write the same artifacts, in a temporary
runs folder: the tests then exercise the real orchestration without a network or an API key.
"""

from __future__ import annotations

import pytest

from sysrev import context
from sysrev.agents import critic as critic_agent
from sysrev.agents import extraction as extraction_agent
from sysrev.agents import planner, retrieval, screening, search_strategy, synthesis
from sysrev.agents.planner import ReviewPlan
from sysrev.config import get_settings
from sysrev.models import (
    Criterion,
    DomainJudgement,
    ExtractedItem,
    Extraction,
    Protocol,
    QAIssue,
    QAReport,
    Record,
    ReviewerVote,
    RiskOfBias,
    ScreeningDecision,
    SearchStrategy,
)
from sysrev.tools.prisma import PRISMA_2020_ITEMS, PrismaFlow


@pytest.fixture
def calls(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    get_settings.cache_clear()
    context._contexts.clear()
    counter: dict[str, int] = {}

    def count(name: str) -> int:
        counter[name] = counter.get(name, 0) + 1
        return counter[name]

    def vote(decision: str) -> ReviewerVote:
        return ReviewerVote(decision=decision, criteria=["E1"] if decision == "exclude" else [], rationale="because", confidence=0.9)

    def fake_protocol(ctx, question, feedback="", previous=None):
        n = count("protocol")
        protocol = Protocol(
            title=f"Fake topic: a systematic review (v{n})", research_question=question, rationale="r", objectives=["o"],
            framework="PICO", framework_elements={"Population": "p"}, inclusion_criteria=[Criterion(id="I1", text="in")],
            exclusion_criteria=[Criterion(id="E1", text="out")], study_designs=["any"], databases=["pubmed"],
            outcomes=["x"], data_items=["item"], risk_of_bias_approach="rob", synthesis_plan="narrative",
        )
        ctx.store.save("protocol", protocol, agent="planner", note=feedback)
        return protocol

    def fake_plan(ctx, protocol):
        plan = ReviewPlan(briefs=[])
        ctx.store.save("plan", plan)
        return plan

    def fake_strategy(ctx, protocol, plan=None):
        count("strategy")
        strategy = SearchStrategy(concepts=[], queries={"pubmed": "q"}, rationale="r", hit_counts={"pubmed": 4})
        ctx.store.save("search_strategy", strategy)
        return strategy

    def fake_retrieval(ctx, protocol, strategy):
        records = [Record(rid=f"R000{i}", title=f"Study {i}", authors=[f"Author{i}, A"], year=2020 + i, doi=f"10.1/{i}") for i in (1, 2, 3)]
        ctx.store.save_lines("records", records)
        ctx.store.save("screening_pool", [r.rid for r in records])
        ctx.store.save("search_log", {"identified": {"pubmed": 4}, "errors": {}, "total_hits": {"pubmed": 4}})
        flow = PrismaFlow(identified={"pubmed": 4}, duplicates_removed=1, records_screened=3)
        ctx.store.save("prisma_flow", flow)
        return flow

    def decision(rid, stage, final):
        return ScreeningDecision(
            rid=rid, stage=stage, reviewer_a=vote(final), reviewer_b=vote(final), agreed=True, final=final,
            resolved_by="consensus", final_rationale="both agree", exclusion_reason="E1: out" if final == "exclude" else "",
        )

    agreement = {"n": 3, "raw_agreement": 1.0, "cohen_kappa": 1.0, "interpretation": "almost perfect", "conflicts": 0,
                 "resolved_by": {"consensus": 3, "adjudicator": 0, "human": 0}}

    def fake_screen_ta(ctx, protocol, records, plan=None):
        decisions = [decision(r.rid, "title_abstract", "exclude" if r.rid == "R0003" else "include") for r in records]
        ctx.store.save_lines("screening_title_abstract", decisions)
        ctx.store.save("agreement_title_abstract", agreement)
        return decisions

    def fake_screen_ft(ctx, protocol, records, provenance, plan=None):
        decisions = [decision(r.rid, "full_text", "exclude" if r.rid == "R0002" else "include") for r in records]
        ctx.store.save_lines("screening_full_text", decisions)
        ctx.store.save("agreement_full_text", agreement)
        return decisions

    def fake_extract(ctx, protocol, records, plan=None):
        extractions = [
            Extraction(rid=r.rid, study_design="cohort", items=[ExtractedItem(field="item", value="v", quote="a quote", quote_verified=True)],
                       key_findings=["finding"]) for r in records
        ]
        appraisals = [
            RiskOfBias(rid=r.rid, tool="JBI checklist", domains=[DomainJudgement(domain="d", judgement="low", justification="j")],
                       overall="low", overall_justification="fine") for r in records
        ]
        ctx.store.save_lines("extractions", extractions)
        ctx.store.save_lines("risk_of_bias", appraisals)
        return extractions, appraisals

    def fake_write(ctx, issues=None, plan=None):
        n = count("write")
        filler = " ".join(["word"] * 15)
        text = f"# Fake topic: a systematic review\n\n## Abstract\n{filler}"
        for item in PRISMA_2020_ITEMS[2:]:
            for section in item["sections"]:
                text += f"\n\n### {section}\n{filler}"
        included = [e.rid for e in ctx.store.load_lines("extractions", Extraction)]
        ctx.store.save("manuscript_meta", {"cited": included, "unknown_citations": [], "included": included, "themes": [],
                                           "syntheses": {}, "revision_issues": [i.model_dump() for i in (issues or [])], "draft": n})
        ctx.store.write_text("report_draft.md", text)
        return text

    def fake_review(ctx, round_no):
        count("critic")
        issues = [QAIssue(severity="major", area="discussion", description="overstated")] if round_no == 1 else []
        revise = bool(issues) and round_no <= ctx.options.qa_max_rounds  # same rule as the real critic
        report = QAReport(verdict="revise" if revise else "pass", issues=issues, checks={"round": round_no})
        ctx.store.save("qa_report", report)
        return report

    monkeypatch.setattr(planner, "generate_protocol", fake_protocol)
    monkeypatch.setattr(planner, "make_plan", fake_plan)
    monkeypatch.setattr(search_strategy, "design_strategy", fake_strategy)
    monkeypatch.setattr(retrieval, "run_retrieval", fake_retrieval)
    monkeypatch.setattr(retrieval, "fetch_fulltexts", lambda ctx, records: {})
    monkeypatch.setattr(screening, "screen_title_abstract", fake_screen_ta)
    monkeypatch.setattr(screening, "screen_full_text", fake_screen_ft)
    monkeypatch.setattr(extraction_agent, "extract_and_appraise", fake_extract)
    monkeypatch.setattr(synthesis, "write_report", fake_write)
    monkeypatch.setattr(critic_agent, "review", fake_review)
    yield counter
    get_settings.cache_clear()
    context._contexts.clear()
