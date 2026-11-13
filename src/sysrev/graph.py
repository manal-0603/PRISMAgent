"""LangGraph workflow: a coordinator routing work to the specialist agents.

                      ┌──────────────────────────────────────────────────┐
                      │                   coordinator                    │
                      └──────────────────────────────────────────────────┘
        protocol → search_strategy → [human: protocol] → retrieval → screen_title_abstract
        → [human: screening] → screen_full_text → extraction → synthesis ⇄ critic
        → [human: report] → finalize

Every stage node returns to the coordinator, which picks the next unfinished stage.
Two loops exist: the human can send the protocol back for revision, and the critic
can send the manuscript back to the writer. The graph state is tiny (ids, progress,
feedback); all data lives in the run directory. A SQLite checkpointer persists the
state after every node, so a run can be interrupted for human review, or crash,
and be resumed later from the same point.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from typing import Any, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from .agents import critic as critic_agent
from .agents import extraction as extraction_agent
from .agents import planner, retrieval, screening, search_strategy, synthesis
from .agents.planner import ReviewPlan
from .context import RunContext, RunOptions, get_context, new_run_id
from .llm import QuotaExhausted
from .models import Protocol, QAIssue, ScreeningDecision, SearchStrategy
from .tools.export import markdown_to_docx, to_bibtex, write_csv
from .tools.prisma import PrismaFlow, checklist_markdown, validate_checklist

ORDER = [
    "protocol", "search_strategy", "review_protocol", "retrieval", "screen_title_abstract", "review_screening",
    "screen_full_text", "extraction", "synthesis", "critic", "review_report", "finalize",
]


class ReviewState(TypedDict, total=False):
    run_id: str
    question: str
    done: list[str]  # completed stages
    next: str  # stage chosen by the coordinator
    protocol_feedback: str  # change request from the human reviewer
    qa_round: int
    qa_issues: list[dict]  # issues the writer must address in the next revision
    summary: dict  # headline numbers of each stage, for display


def _done(state: ReviewState, *add: str, remove: tuple[str, ...] = ()) -> list[str]:
    return [s for s in state.get("done", []) if s not in remove] + list(add)


def _summary(state: ReviewState, **values: Any) -> dict:
    return {**state.get("summary", {}), **values}


def _plan(ctx: RunContext) -> ReviewPlan | None:
    return ctx.store.load("plan", ReviewPlan) if ctx.store.exists("plan") else None


def _record_checkpoint(ctx: RunContext, name: str, mode: str, decision: dict) -> None:
    history = ctx.store.load("human_checkpoints") if ctx.store.exists("human_checkpoints") else []
    history = [h for h in history if h["checkpoint"] != name]
    history.append({"checkpoint": name, "mode": mode, "action": decision.get("action", "approve"),
                    "feedback": decision.get("feedback", ""), "ts": time.strftime("%Y-%m-%dT%H:%M:%S")})
    ctx.store.save("human_checkpoints", history, agent="human" if mode == "human" else "system")
    ctx.audit.log("human" if mode == "human" else "system", "checkpoint", checkpoint=name, mode=mode,
                  decision=decision.get("action", "approve"), feedback=decision.get("feedback", ""),
                  overrides=decision.get("overrides", {}))


def _ask_human(ctx: RunContext, name: str, payload: dict) -> tuple[dict, str]:
    """Pause the graph for human review, unless the run is in autonomous mode."""
    if ctx.options.auto_approve:
        return {"action": "approve"}, "auto"
    decision = interrupt({"checkpoint": name, **payload})
    return (decision if isinstance(decision, dict) else {"action": "approve"}), "human"


# --------------------------------------------------------------------------- #
# Coordinator
# --------------------------------------------------------------------------- #


def coordinator(state: ReviewState) -> dict:
    ctx = get_context(state["run_id"])
    done = state.get("done", [])
    nxt = next((stage for stage in ORDER if stage not in done), "end")
    ctx.audit.log("coordinator", "route", next=nxt, completed=done, qa_round=state.get("qa_round", 0))
    return {"next": nxt}


# --------------------------------------------------------------------------- #
# Stage nodes
# --------------------------------------------------------------------------- #


def protocol_node(state: ReviewState) -> dict:
    ctx = get_context(state["run_id"])
    feedback = state.get("protocol_feedback", "")
    previous = ctx.store.load("protocol", Protocol) if feedback and ctx.store.exists("protocol") else None
    protocol = planner.generate_protocol(ctx, state["question"], feedback=feedback, previous=previous)
    planner.make_plan(ctx, protocol)
    return {
        "done": _done(state, "protocol"), "protocol_feedback": "",
        "summary": _summary(state, protocol={"title": protocol.title, "databases": protocol.databases,
                                             "criteria": len(protocol.inclusion_criteria) + len(protocol.exclusion_criteria)}),
    }


def search_strategy_node(state: ReviewState) -> dict:
    ctx = get_context(state["run_id"])
    protocol = ctx.store.load("protocol", Protocol)
    strategy = search_strategy.design_strategy(ctx, protocol, _plan(ctx))
    return {"done": _done(state, "search_strategy"), "summary": _summary(state, search={"hits": strategy.hit_counts})}


def review_protocol_node(state: ReviewState) -> dict:
    ctx = get_context(state["run_id"])
    protocol = ctx.store.load("protocol", Protocol)
    strategy = ctx.store.load("search_strategy", SearchStrategy)
    decision, mode = _ask_human(ctx, "protocol", {
        "instructions": "Approve the protocol and search strategy, request changes (free text), or supply an edited protocol.",
        "protocol": protocol.model_dump(), "search_strategy": strategy.model_dump(),
    })
    _record_checkpoint(ctx, "protocol_and_search", mode, decision)
    if decision.get("action") == "revise" and decision.get("feedback"):
        return {"done": _done(state, remove=("protocol", "search_strategy")), "protocol_feedback": decision["feedback"]}
    if decision.get("protocol"):  # protocol edited by hand: validate, version, and redo the search strategy
        edited = Protocol.model_validate(decision["protocol"])
        ctx.store.save("protocol", edited, agent="human", note="edited by human reviewer")
        return {"done": _done(state, remove=("search_strategy",))}
    return {"done": _done(state, "review_protocol")}


def retrieval_node(state: ReviewState) -> dict:
    ctx = get_context(state["run_id"])
    flow = retrieval.run_retrieval(ctx, ctx.store.load("protocol", Protocol), ctx.store.load("search_strategy", SearchStrategy))
    return {"done": _done(state, "retrieval"), "summary": _summary(state, retrieval={
        "identified": flow.identified, "duplicates": flow.duplicates_removed,
        "removed_by_automation": flow.removed_by_automation, "to_screen": flow.records_screened})}


def _flow_after_title_abstract(ctx: RunContext) -> PrismaFlow:
    flow = ctx.store.load("prisma_flow", PrismaFlow)
    decisions = ctx.store.load_lines("screening_title_abstract", ScreeningDecision)
    flow.records_excluded = sum(d.final == "exclude" for d in decisions)
    flow.reports_sought = sum(d.final == "include" for d in decisions)
    ctx.store.save("prisma_flow", flow, agent="system")
    return flow


def screen_title_abstract_node(state: ReviewState) -> dict:
    ctx = get_context(state["run_id"])
    records = retrieval.load_records(ctx)
    pool = [records[rid] for rid in ctx.store.load("screening_pool")]
    screening.screen_title_abstract(ctx, ctx.store.load("protocol", Protocol), pool, _plan(ctx))
    flow = _flow_after_title_abstract(ctx)
    agreement = ctx.store.load("agreement_title_abstract")
    return {"done": _done(state, "screen_title_abstract"), "summary": _summary(state, title_abstract={
        "screened": flow.records_screened, "excluded": flow.records_excluded, "retained": flow.reports_sought,
        "kappa": agreement["cohen_kappa"], "conflicts": agreement["conflicts"]})}


def review_screening_node(state: ReviewState) -> dict:
    ctx = get_context(state["run_id"])
    records = retrieval.load_records(ctx)
    decisions = ctx.store.load_lines("screening_title_abstract", ScreeningDecision)
    rows = [
        {"rid": d.rid, "title": records[d.rid].title, "final": d.final, "resolved_by": d.resolved_by,
         "a": d.reviewer_a.decision, "b": d.reviewer_b.decision, "rationale": d.final_rationale}
        for d in decisions
    ]
    decision, mode = _ask_human(ctx, "screening", {
        "instructions": "Approve the title/abstract decisions, or override some: {'overrides': {'R0012': 'include'}}.",
        "agreement": ctx.store.load("agreement_title_abstract"), "decisions": rows,
    })
    _record_checkpoint(ctx, "screening", mode, decision)
    if decision.get("overrides"):
        screening.apply_overrides(ctx, "screening_title_abstract", decision["overrides"], ctx.store.load("protocol", Protocol))
        _flow_after_title_abstract(ctx)
    return {"done": _done(state, "review_screening")}


def screen_full_text_node(state: ReviewState) -> dict:
    ctx = get_context(state["run_id"])
    protocol = ctx.store.load("protocol", Protocol)
    records = retrieval.load_records(ctx)
    retained = [records[d.rid] for d in ctx.store.load_lines("screening_title_abstract", ScreeningDecision) if d.final == "include"]
    provenance = retrieval.fetch_fulltexts(ctx, retained)
    decisions = screening.screen_full_text(ctx, protocol, retained, provenance, _plan(ctx))
    flow = ctx.store.load("prisma_flow", PrismaFlow)
    flow.reports_sought = len(retained)
    flow.reports_not_retrieved = len(retained) - len(decisions)
    flow.reports_assessed = len(decisions)
    flow.assessed_on_abstract_only = sum(d.basis == "abstract" for d in decisions)
    reasons: dict[str, int] = {}
    for d in decisions:
        if d.final == "exclude":
            reasons[d.exclusion_reason] = reasons.get(d.exclusion_reason, 0) + 1
    flow.reports_excluded = dict(sorted(reasons.items(), key=lambda kv: -kv[1]))
    flow.studies_included = sum(d.final == "include" for d in decisions)
    ctx.store.save("prisma_flow", flow, agent="system")
    return {"done": _done(state, "screen_full_text"), "summary": _summary(state, full_text={
        "assessed": flow.reports_assessed, "full_text_available": flow.reports_assessed - flow.assessed_on_abstract_only,
        "included": flow.studies_included, "kappa": ctx.store.load("agreement_full_text")["cohen_kappa"]})}


def extraction_node(state: ReviewState) -> dict:
    ctx = get_context(state["run_id"])
    records = retrieval.load_records(ctx)
    included = [records[d.rid] for d in ctx.store.load_lines("screening_full_text", ScreeningDecision) if d.final == "include"]
    extractions, appraisals = extraction_agent.extract_and_appraise(ctx, ctx.store.load("protocol", Protocol), included, _plan(ctx))
    return {"done": _done(state, "extraction"), "summary": _summary(state, extraction={
        "studies": len(extractions), "appraised": len(appraisals), **extraction_agent.quote_stats(extractions)})}


def synthesis_node(state: ReviewState) -> dict:
    ctx = get_context(state["run_id"])
    issues = [QAIssue.model_validate(i) for i in state.get("qa_issues", [])]
    try:
        text = synthesis.write_report(ctx, issues, _plan(ctx))
    except QuotaExhausted as exc:
        if not (issues and ctx.store.path("report_draft.md").exists()):
            raise  # no draft yet: stop here, the run is resumed when the quota is back
        # A revision could not be afforded. Keep the reviewed draft and finish: the QA report
        # still lists the unresolved issues, so nothing is hidden.
        ctx.audit.log("coordinator", "revision_skipped", reason=str(exc)[:300], unresolved_issues=len(issues))
        return {"done": _done(state, "synthesis", "critic"), "qa_issues": [],
                "summary": _summary(state, manuscript={"revision": "skipped: LLM quota exhausted"})}
    return {"done": _done(state, "synthesis"), "summary": _summary(state, manuscript={"words": len(text.split())})}


def critic_node(state: ReviewState) -> dict:
    ctx = get_context(state["run_id"])
    round_no = state.get("qa_round", 0) + 1
    report = critic_agent.review(ctx, round_no)
    summary = _summary(state, qa={"round": round_no, "verdict": report.verdict, "issues": len(report.issues)})
    if report.verdict == "revise":
        fixable = [i.model_dump() for i in report.issues if i.area.startswith(critic_agent.WRITER_AREAS)]
        return {"done": _done(state, remove=("synthesis",)), "qa_round": round_no, "qa_issues": fixable, "summary": summary}
    return {"done": _done(state, "critic"), "qa_round": round_no, "qa_issues": [], "summary": summary}


def review_report_node(state: ReviewState) -> dict:
    ctx = get_context(state["run_id"])
    qa = ctx.store.load("qa_report")
    decision, mode = _ask_human(ctx, "report", {
        "instructions": "Approve the manuscript, or request a revision with free-text feedback.",
        "qa_report": qa, "draft_file": str(ctx.store.path("report_draft.md")),
    })
    _record_checkpoint(ctx, "final_report", mode, decision)
    if decision.get("action") == "revise" and decision.get("feedback"):
        issue = QAIssue(severity="major", area="report", description=f"Human reviewer: {decision['feedback']}")
        return {"done": _done(state, remove=("synthesis", "critic")), "qa_issues": [issue.model_dump()],
                "qa_round": ctx.options.qa_max_rounds}  # one human-requested revision, then back here
    return {"done": _done(state, "review_report")}


def finalize_node(state: ReviewState) -> dict:
    ctx = get_context(state["run_id"])
    store = ctx.store
    flow = store.load("prisma_flow", PrismaFlow)
    records = retrieval.load_records(ctx)
    meta = store.load("manuscript_meta")
    flow.to_png(store.path("prisma_flow.png"))
    store.write_text("prisma_flow.mmd", flow.to_mermaid())
    # The human checkpoints are only complete now: rebuild the manuscript so that the
    # Methods describe the oversight that really took place (LLM parts come from cache).
    issues = [QAIssue.model_validate(i) for i in meta.get("revision_issues", [])]
    draft = synthesis.write_report(ctx, issues, _plan(ctx))
    checklist = validate_checklist(draft)
    report = (
        draft + "\n\n## Appendix C. PRISMA 2020 checklist\n\n"
        "Completeness of reporting was checked automatically against the PRISMA 2020 checklist.\n\n" + checklist_markdown(checklist)
    )
    store.write_text("report.md", report)
    markdown_to_docx(report, store.path("report.docx"), base_dir=ctx.run_dir)
    meta = store.load("manuscript_meta")
    cited = [records[rid] for rid in meta["cited"]]
    store.write_text("references.bib", to_bibtex(cited))
    write_csv(store.path("included_studies.csv"), [
        {"rid": rid, "authors": "; ".join(records[rid].authors[:10]), "year": records[rid].year, "title": records[rid].title,
         "venue": records[rid].venue, "doi": records[rid].doi, "url": records[rid].url, "sources": "; ".join(records[rid].sources)}
        for rid in meta["included"]
    ])
    result = {
        "run_id": ctx.run_id, "question": state["question"], "flow": flow.model_dump(), "flow_errors": flow.check(),
        "agreement_title_abstract": store.load("agreement_title_abstract"),
        "agreement_full_text": store.load("agreement_full_text"),
        "qa": store.load("qa_report")["checks"], "qa_verdict": store.load("qa_report")["verdict"],
        "prisma_items_reported": sum(r["reported"] for r in checklist), "prisma_items_total": len(checklist),
        "timings_seconds": ctx.timer.read(), "llm_usage": usage_from_trace(ctx),
        "human_checkpoints": store.load("human_checkpoints"),
    }
    store.save("result", result, agent="system")
    ctx.audit.log("system", "run_finished", included=flow.studies_included)
    return {"done": _done(state, "finalize"), "summary": _summary(state, finished=True)}


def usage_from_trace(ctx: RunContext) -> dict:
    """Aggregate the LLM trace of the run: calls, cache hits, tokens and seconds per model."""
    file = ctx.run_dir / "llm_trace.jsonl"
    totals: dict[str, dict] = {}
    if file.exists():
        for line in file.open(encoding="utf-8"):
            entry = json.loads(line)
            t = totals.setdefault(entry["model"], {"calls": 0, "cached": 0, "input_tokens": 0, "output_tokens": 0, "seconds": 0.0})
            t["calls"] += 1
            t["cached"] += int(entry["cached"])
            t["input_tokens"] += entry["input_tokens"]
            t["output_tokens"] += entry["output_tokens"]
            t["seconds"] = round(t["seconds"] + entry["seconds"], 1)
    return totals


NODES: dict[str, Callable[[ReviewState], dict]] = {
    "protocol": protocol_node,
    "search_strategy": search_strategy_node,
    "review_protocol": review_protocol_node,
    "retrieval": retrieval_node,
    "screen_title_abstract": screen_title_abstract_node,
    "review_screening": review_screening_node,
    "screen_full_text": screen_full_text_node,
    "extraction": extraction_node,
    "synthesis": synthesis_node,
    "critic": critic_node,
    "review_report": review_report_node,
    "finalize": finalize_node,
}
HUMAN_NODES = {"review_protocol", "review_screening", "review_report"}


def _instrument(name: str, fn: Callable[[ReviewState], dict]) -> Callable[[ReviewState], dict]:
    """Time each stage and log its start, end and failures in the audit trail."""
    if name in HUMAN_NODES:  # waiting for a human is not pipeline time, and interrupts re-enter the node
        return fn

    def wrapped(state: ReviewState) -> dict:
        ctx = get_context(state["run_id"])
        ctx.audit.log("coordinator", "stage_started", stage=name)
        started = time.perf_counter()
        try:
            out = fn(state)
        except Exception as exc:
            ctx.audit.log("coordinator", "stage_failed", stage=name, error=f"{type(exc).__name__}: {exc}"[:500])
            raise
        seconds = time.perf_counter() - started
        ctx.timer.add(name, seconds)
        ctx.audit.log("coordinator", "stage_completed", stage=name, seconds=round(seconds, 1))
        return out

    return wrapped


def build_graph(checkpointer: Any = None):
    graph = StateGraph(ReviewState)
    graph.add_node("coordinator", coordinator)
    for name, fn in NODES.items():
        graph.add_node(name, _instrument(name, fn))
        graph.add_edge(name, "coordinator")
    graph.add_edge(START, "coordinator")
    graph.add_conditional_edges("coordinator", lambda s: s["next"], {**{name: name for name in NODES}, "end": END})
    return graph.compile(checkpointer=checkpointer)


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #


class ReviewRunner:
    """Start, pause and resume a review. One instance per run."""

    def __init__(self, run_id: str):
        self.ctx = get_context(run_id)
        self.run_id = run_id
        connection = sqlite3.connect(self.ctx.run_dir / "checkpoints.sqlite", check_same_thread=False)
        self.graph = build_graph(SqliteSaver(connection))
        self.config = {"configurable": {"thread_id": run_id}, "recursion_limit": 120}

    @classmethod
    def create(cls, question: str, options: RunOptions | None = None) -> ReviewRunner:
        run_id = new_run_id(question)
        get_context(run_id).init_manifest(question, options or RunOptions())
        return cls(run_id)

    def pending(self) -> dict | None:
        """The human-review request the graph is waiting on, if any."""
        snapshot = self.graph.get_state(self.config)
        for task in snapshot.tasks:
            if task.interrupts:
                return task.interrupts[0].value
        return None

    def finished(self) -> bool:
        snapshot = self.graph.get_state(self.config)
        return bool(snapshot.values) and not snapshot.next

    def state(self) -> dict:
        return dict(self.graph.get_state(self.config).values)

    def rebuild_outputs(self) -> None:
        """Regenerate the final report and exports of a finished run (LLM parts come from the cache)."""
        finalize_node(self.state())

    def reopen_for_revision(self) -> int:
        """Send a finished run back to the writer with the issues the Critic left open.

        Used when a revision round was skipped (quota exhausted). Returns the number of issues.
        """
        state = self.state()
        qa = self.ctx.store.load("qa_report")
        issues = [i for i in qa["issues"] if i["area"].startswith(critic_agent.WRITER_AREAS)]
        if issues:
            self.ctx.audit.log("coordinator", "revision_reopened", issues=len(issues))
            self.graph.update_state(
                self.config,
                {"done": [s for s in state.get("done", []) if s not in ("synthesis", "critic", "review_report", "finalize")],
                 "qa_issues": issues},
                as_node="finalize",  # the coordinator runs next and routes to the writer
            )
        return len(issues)

    def advance(self, resume: dict | None = None, on_update: Callable[[str, dict], None] | None = None) -> dict | None:
        """Run until the next human checkpoint or the end.

        `resume` is the human decision answering the pending checkpoint. Returns the
        next pending checkpoint payload, or None when the review is finished.
        """
        snapshot = self.graph.get_state(self.config)
        if resume is not None:
            payload: Any = Command(resume=resume)
        elif snapshot.values:
            payload = None  # continue an interrupted / crashed run from its last checkpoint
        else:
            payload = {"run_id": self.run_id, "question": self.ctx.question, "done": [], "qa_round": 0, "summary": {}}
        for update in self.graph.stream(payload, self.config, stream_mode="updates"):
            for node, values in update.items():
                if on_update and node not in ("coordinator", "__interrupt__") and isinstance(values, dict):
                    on_update(node, values.get("summary", {}))
        return self.pending()
