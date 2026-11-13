"""Offline integration tests of the LangGraph workflow.

The LLM-backed agents are replaced by small fakes that write the same artifacts,
so these tests exercise the real orchestration: coordinator routing, the three
human checkpoints (interrupt / resume), the protocol-revision loop, the
critic -> writer loop, SQLite checkpointing and resumption in a fresh process.
"""

from __future__ import annotations

from sysrev import context, graph
from sysrev.context import RunOptions
from sysrev.models import ScreeningDecision


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
