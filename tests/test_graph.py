"""Offline integration tests of the LangGraph workflow.

The LLM-backed agents are replaced by small fakes that write the same artifacts,
so these tests exercise the real orchestration: coordinator routing, the three
human checkpoints (interrupt / resume), the protocol-revision loop, the
critic -> writer loop, SQLite checkpointing and resumption in a fresh process.
"""

from __future__ import annotations

import pytest

from sysrev import context, graph
from sysrev.agents import critic as critic_agent
from sysrev.agents import extraction as extraction_agent
from sysrev.agents import planner, retrieval, screening, search_strategy, synthesis
from sysrev.agents.planner import ReviewPlan
from sysrev.config import get_settings
from sysrev.context import RunOptions
from sysrev.models import (
    Criterion, DomainJudgement, ExtractedItem, Extraction, Protocol, QAIssue, QAReport, Record, ReviewerVote,
    RiskOfBias, ScreeningDecision, SearchStrategy,
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


def test_autonomous_run_completes_every_stage(calls):
    runner = graph.ReviewRunner.create("Does X improve Y?", RunOptions(auto_approve=True))
    assert runner.advance() is None and runner.finished()
    state = runner.state()
    assert sorted(state["done"]) == sorted(graph.ORDER)
    # critic asked for one revision: draft, revised draft, then the final rebuild in `finalize`
    assert calls == {"protocol": 1, "strategy": 1, "write": 3, "critic": 2}
    store = runner.ctx.store
    result = store.load("result")
    assert result["flow_errors"] == []
    assert result["flow"]["studies_included"] == 1 and result["flow"]["reports_excluded"] == {"E1: out": 1}
    assert result["prisma_items_reported"] == result["prisma_items_total"] == 42
    assert [c["mode"] for c in result["human_checkpoints"]] == ["auto", "auto", "auto"]
    for name in ("report.md", "report.docx", "references.bib", "prisma_flow.png", "prisma_flow.mmd", "included_studies.csv"):
        assert (runner.ctx.run_dir / name).exists(), name
    assert "Appendix C. PRISMA 2020 checklist" in (runner.ctx.run_dir / "report.md").read_text()
    events = runner.ctx.audit.read()
    actions = [e["action"] for e in events]
    assert actions.count("stage_completed") == 11  # 9 agent stages + one synthesis/critic repeat
    assert "run_finished" in actions
    assert events[-1]["action"] == "route" and events[-1]["next"] == "end"  # the coordinator closes the run


def test_human_checkpoints_loops_and_resume_in_new_process(calls):
    runner = graph.ReviewRunner.create("Does X improve Y?", RunOptions(auto_approve=False))
    run_id = runner.run_id

    pending = runner.advance()
    assert pending["checkpoint"] == "protocol" and pending["protocol"]["title"].endswith("(v1)")

    # checkpoint 1: the human sends the protocol back -> planner and search agent run again
    pending = runner.advance(resume={"action": "revise", "feedback": "narrow the population"})
    assert pending["checkpoint"] == "protocol" and pending["protocol"]["title"].endswith("(v2)")
    assert calls["protocol"] == 2 and calls["strategy"] == 2
    assert runner.ctx.store.version_count("protocol") == 2

    pending = runner.advance(resume={"action": "approve"})
    assert pending["checkpoint"] == "screening" and len(pending["decisions"]) == 3

    # simulate a restart: a brand-new runner must find the pending checkpoint on disk
    context._contexts.clear()
    runner = graph.ReviewRunner(run_id)
    assert runner.pending()["checkpoint"] == "screening"

    # checkpoint 2: the human overrides one exclusion
    pending = runner.advance(resume={"action": "approve", "overrides": {"R0003": "include"}})
    assert pending["checkpoint"] == "report"
    ta = runner.ctx.store.load_lines("screening_title_abstract", ScreeningDecision)
    overridden = next(d for d in ta if d.rid == "R0003")
    assert overridden.final == "include" and overridden.resolved_by == "human"

    # checkpoint 3: one human-requested revision, then approval
    pending = runner.advance(resume={"action": "revise", "feedback": "shorten the discussion"})
    assert pending["checkpoint"] == "report"
    assert runner.advance(resume={"action": "approve"}) is None and runner.finished()

    result = runner.ctx.store.load("result")
    assert result["flow_errors"] == []
    assert result["flow"]["reports_sought"] == 3 and result["flow"]["studies_included"] == 2
    assert [c["mode"] for c in result["human_checkpoints"]] == ["human", "human", "human"]
    audit = runner.ctx.audit.read()
    assert any(e["action"] == "decision_overridden" and e["rid"] == "R0003" for e in audit)
    human_feedback = [e["feedback"] for e in audit if e["action"] == "checkpoint" and e["feedback"]]
    assert human_feedback == ["narrow the population", "shorten the discussion"]


def test_finished_run_can_be_reopened_for_revision(calls):
    runner = graph.ReviewRunner.create("Does X improve Y?", RunOptions(auto_approve=True, qa_max_rounds=0))
    assert runner.advance() is None
    # qa_max_rounds=0: the critic's round-1 issue was reported but no revision was allowed
    assert calls["critic"] == 1 and runner.ctx.store.load("qa_report")["verdict"] == "pass"
    assert len(runner.ctx.store.load("qa_report")["issues"]) == 1
    writes = calls["write"]

    assert runner.reopen_for_revision() == 1
    assert not runner.finished()
    assert runner.advance() is None and runner.finished()
    assert calls["critic"] == 2 and calls["write"] > writes
    meta_versions = runner.ctx.store.version_count("manuscript_meta")
    assert meta_versions >= 3  # first draft, final rebuild, revision (+ its rebuild)
    assert runner.ctx.store.load("qa_report")["issues"] == []  # round 2 of the fake critic is clean
    assert any(e["action"] == "revision_reopened" for e in runner.ctx.audit.read())
    assert runner.reopen_for_revision() == 0  # nothing left to revise
