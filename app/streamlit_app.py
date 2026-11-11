"""Streamlit interface: start a review, answer the human checkpoints, browse every artifact.

    streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path

import pandas as pd
import streamlit as st

logging.basicConfig(level=logging.WARNING)

from sysrev.config import get_settings  # noqa: E402
from sysrev.context import RunOptions, get_context  # noqa: E402
from sysrev.graph import ORDER, ReviewRunner  # noqa: E402

st.set_page_config(page_title="Systematic review agents", page_icon="📚", layout="wide")

STAGES = {
    "protocol": "Protocol", "search_strategy": "Search strategy", "review_protocol": "Checkpoint 1 · protocol",
    "retrieval": "Retrieval and de-duplication", "screen_title_abstract": "Title/abstract screening",
    "review_screening": "Checkpoint 2 · screening", "screen_full_text": "Full-text screening",
    "extraction": "Extraction and appraisal", "synthesis": "Synthesis and writing", "critic": "Quality assurance",
    "review_report": "Checkpoint 3 · report", "finalize": "Exports",
}


@st.cache_resource
def jobs() -> dict[str, dict]:
    """Background jobs, shared across reruns of the script."""
    return {}


def launch(run_id: str, resume: dict | None = None) -> None:
    job = {"running": True, "pending": None, "finished": False, "error": None}

    def work() -> None:
        try:
            job["pending"] = ReviewRunner(run_id).advance(resume=resume)
            job["finished"] = job["pending"] is None
        except Exception as exc:  # noqa: BLE001 - shown in the UI, the run can be resumed
            job["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            job["running"] = False

    jobs()[run_id] = job
    threading.Thread(target=work, daemon=True).start()


def job_for(run_id: str) -> dict:
    """State of a run: from the live job if any, otherwise from its checkpoint."""
    if run_id in jobs():
        return jobs()[run_id]
    runner = ReviewRunner(run_id)
    started = bool(runner.state())
    # an exported run (examples/…) has its result but no checkpoint database: it is finished
    exported = any(runner.ctx.run_dir.glob("result_v*.json"))
    job = {"running": False, "pending": runner.pending() if started else None,
           "finished": (started and runner.finished()) or exported, "error": None, "idle": True}
    jobs()[run_id] = job
    return job


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def latest(run_dir: Path, name: str):
    files = sorted(run_dir.glob(f"{name}_v*.json"), key=lambda p: int(p.stem.rsplit("_v", 1)[1]))
    return load_json(files[-1]) if files else None


def lines(run_dir: Path, name: str) -> list[dict]:
    path = run_dir / f"{name}.jsonl"
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()] if path.exists() else []


def render_markdown(text: str, base: Path) -> None:
    """st.markdown cannot show local images: split the text around image tags."""
    parts = re.split(r"(!\[.*?\]\(.*?\))", text)
    for part in parts:
        image = re.match(r"!\[(.*?)\]\((.*?)\)", part)
        if image and (base / image.group(2)).exists():
            st.image(str(base / image.group(2)), caption=image.group(1))
        elif part.strip():
            st.markdown(part)


# --------------------------------------------------------------------------- #
# Sidebar: new review / pick a run
# --------------------------------------------------------------------------- #

settings = get_settings()
st.sidebar.title("📚 Systematic review agents")
with st.sidebar.expander("Start a new review", expanded=not any(settings.runs_dir.glob("*/manifest.json"))):
    question = st.text_area("Research question or topic", height=110,
                            placeholder="e.g. Does remote patient monitoring reduce hospital readmissions in heart failure?")
    auto = st.checkbox("Autonomous mode (skip the human checkpoints)", value=False)
    c1, c2 = st.columns(2)
    max_per_source = c1.number_input("Records per database", 20, 2000, 60, step=10)
    max_screen = c2.number_input("Max records screened", 10, 2000, 50, step=10)
    fallback = st.selectbox("If no open-access full text", ["abstract", "exclude"],
                            format_func=lambda v: "assess on the abstract" if v == "abstract" else "exclude as not retrieved")
    if st.button("Start review", type="primary", disabled=not question.strip()):
        runner = ReviewRunner.create(question.strip(), RunOptions(
            auto_approve=auto, max_per_source=int(max_per_source), max_screen=int(max_screen), fulltext_fallback=fallback))
        launch(runner.run_id)
        st.session_state["run_id"] = runner.run_id
        st.rerun()

runs = sorted(
    (p.parent.name for p in settings.runs_dir.glob("*/manifest.json") if not p.parent.name.startswith("benchmark-")),
    reverse=True,
)
if not runs:
    st.info("Enter a research question in the sidebar to start your first review.")
    st.stop()
default = st.session_state.get("run_id", runs[0])
run_id = st.sidebar.selectbox("Review run", runs, index=runs.index(default) if default in runs else 0)
st.session_state["run_id"] = run_id
ctx = get_context(run_id)
run_dir = ctx.run_dir
job = job_for(run_id)

# --------------------------------------------------------------------------- #
# Header and progress
# --------------------------------------------------------------------------- #

st.title(ctx.question if len(ctx.question) < 140 else ctx.question[:140] + "…")
audit = lines(run_dir, "audit")
completed = [e["stage"] for e in audit if e["action"] == "stage_completed"]
completed += [{"protocol_and_search": "review_protocol", "screening": "review_screening", "final_report": "review_report"}[e["checkpoint"]]
              for e in audit if e["action"] == "checkpoint"]
started = [e["stage"] for e in audit if e["action"] == "stage_started"]
current = next((s for s in reversed(started) if s not in completed or started.count(s) > completed.count(s)), None)

if job["error"]:
    st.error(f"The run stopped on an error: {job['error']}")
    if st.button("Resume from the last checkpoint"):
        launch(run_id)
        st.rerun()
elif job["running"]:
    st.info(f"Running — current stage: **{STAGES.get(current, current or 'starting')}**. The page refreshes automatically.")
elif job["pending"]:
    st.warning(f"Waiting for your review — checkpoint: **{job['pending']['checkpoint']}** (see below).")
elif job["finished"]:
    st.success("Review finished.")
else:
    st.info("This run is paused.")
    if st.button("Resume", type="primary"):
        launch(run_id)
        st.rerun()

cols = st.columns(len(ORDER))
for col, stage in zip(cols, ORDER):
    mark = "✅" if stage in completed else ("⏳" if stage == current and job["running"] else "⚪")
    col.markdown(f"<div style='text-align:center;font-size:0.72rem'>{mark}<br>{STAGES[stage]}</div>", unsafe_allow_html=True)
st.divider()

# --------------------------------------------------------------------------- #
# Human checkpoints
# --------------------------------------------------------------------------- #

pending = job["pending"] if not job["running"] else None
if pending and pending["checkpoint"] == "protocol":
    st.subheader("Checkpoint 1 — approve the protocol and the search strategy")
    left, right = st.columns(2)
    edited = left.text_area("Protocol (editable JSON)", json.dumps(pending["protocol"], indent=2, ensure_ascii=False), height=520)
    strategy = pending["search_strategy"]
    right.dataframe(pd.DataFrame([{"database": db, "hits": strategy["hit_counts"].get(db), "query": q}
                                  for db, q in strategy["queries"].items()]), hide_index=True, width="stretch")
    right.caption(strategy["rationale"])
    feedback = right.text_area("Or describe the changes you want; the Planner agent will revise the protocol", height=100)
    b1, b2, b3 = right.columns(3)
    if b1.button("Approve", type="primary"):
        launch(run_id, {"action": "approve"})
        st.rerun()
    if b2.button("Request changes", disabled=not feedback.strip()):
        launch(run_id, {"action": "revise", "feedback": feedback.strip()})
        st.rerun()
    if b3.button("Save my edits"):
        try:
            launch(run_id, {"action": "approve", "protocol": json.loads(edited)})
            st.rerun()
        except json.JSONDecodeError as exc:
            st.error(f"Invalid JSON: {exc}")

elif pending and pending["checkpoint"] == "screening":
    st.subheader("Checkpoint 2 — review the title/abstract screening decisions")
    a = pending["agreement"]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Records screened", a["n"])
    m2.metric("Cohen's kappa (A vs B)", a["cohen_kappa"], a["interpretation"], delta_color="off")
    m3.metric("Conflicts adjudicated", a["conflicts"])
    m4.metric("Retained for full text", sum(d["final"] == "include" for d in pending["decisions"]))
    frame = pd.DataFrame(pending["decisions"])
    only = st.checkbox("Show only retained and adjudicated records", value=True)
    view = frame[(frame["final"] == "include") | (frame["resolved_by"] != "consensus")] if only else frame
    result = st.data_editor(
        view, hide_index=True, width="stretch", height=440,
        disabled=["rid", "title", "resolved_by", "a", "b", "rationale"],
        column_config={"final": st.column_config.SelectboxColumn("final (editable)", options=["include", "exclude"])},
    )
    original = dict(zip(frame["rid"], frame["final"]))
    overrides = {row["rid"]: row["final"] for _, row in result.iterrows() if row["final"] != original[row["rid"]]}
    if st.button(f"Approve ({len(overrides)} override(s))", type="primary"):
        launch(run_id, {"action": "approve", "overrides": overrides})
        st.rerun()

elif pending and pending["checkpoint"] == "report":
    st.subheader("Checkpoint 3 — approve the manuscript")
    qa = pending["qa_report"]
    st.write(f"Critic verdict: **{qa['verdict']}** — {len(qa['issues'])} issue(s) listed in the *Quality assurance* tab.")
    feedback = st.text_area("Request a revision (optional)", height=90)
    b1, b2 = st.columns(2)
    if b1.button("Approve and export", type="primary"):
        launch(run_id, {"action": "approve"})
        st.rerun()
    if b2.button("Request revision", disabled=not feedback.strip()):
        launch(run_id, {"action": "revise", "feedback": feedback.strip()})
        st.rerun()

# --------------------------------------------------------------------------- #
# Artifacts
# --------------------------------------------------------------------------- #

tabs = st.tabs(["Protocol", "Search", "PRISMA flow", "Screening", "Studies", "Report", "Quality assurance", "Audit trail", "Evaluation"])

with tabs[0]:
    protocol = latest(run_dir, "protocol")
    if protocol:
        st.markdown(f"### {protocol['title']}")
        st.caption(f"Version {len(list(run_dir.glob('protocol_v*.json')))} · framework {protocol['framework']}")
        st.table(pd.DataFrame(protocol["framework_elements"].items(), columns=["Element", "Definition"]))
        c1, c2 = st.columns(2)
        c1.markdown("**Inclusion criteria**\n" + "\n".join(f"- **{c['id']}** {c['text']}" for c in protocol["inclusion_criteria"]))
        c2.markdown("**Exclusion criteria**\n" + "\n".join(f"- **{c['id']}** {c['text']}" for c in protocol["exclusion_criteria"]))
        st.markdown("**Data items:** " + "; ".join(protocol["data_items"]))
        plan = latest(run_dir, "plan")
        if plan:
            with st.expander("Coordinator's briefs to the other agents"):
                st.dataframe(pd.DataFrame(plan["briefs"]), hide_index=True, width="stretch")
    else:
        st.caption("Not available yet.")

with tabs[1]:
    strategy = latest(run_dir, "search_strategy")
    if strategy:
        st.dataframe(pd.DataFrame([{"database": db, "hits": strategy["hit_counts"].get(db), "query": q}
                                   for db, q in strategy["queries"].items()]), hide_index=True, width="stretch")
        st.markdown("**Concept blocks**")
        st.dataframe(pd.DataFrame([{"concept": c["name"], "free-text terms": "; ".join(c["free_text_terms"]),
                                    "MeSH": "; ".join(c["controlled_terms"])} for c in strategy["concepts"]]),
                     hide_index=True, width="stretch")
        with st.expander("Every query the agent tested"):
            st.code("\n".join(strategy["refinement_log"]))
    else:
        st.caption("Not available yet.")

with tabs[2]:
    flow = latest(run_dir, "prisma_flow")
    if flow:
        if (run_dir / "prisma_flow.png").exists():
            st.image(str(run_dir / "prisma_flow.png"), width=760)
        st.json(flow, expanded=False)
    else:
        st.caption("Not available yet.")

with tabs[3]:
    records = {r["rid"]: r for r in lines(run_dir, "records")}
    for stage, label in (("screening_title_abstract", "Title / abstract"), ("screening_full_text", "Full text")):
        decisions = lines(run_dir, stage)
        if not decisions:
            continue
        st.markdown(f"#### {label}")
        agreement = latest(run_dir, stage.replace("screening", "agreement"))
        if agreement:
            st.caption(f"kappa = {agreement['cohen_kappa']} ({agreement['interpretation']}), raw agreement "
                       f"{agreement['raw_agreement']}, {agreement['conflicts']} conflicts, resolved by {agreement['resolved_by']}")
        st.dataframe(pd.DataFrame([{
            "rid": d["rid"], "title": records.get(d["rid"], {}).get("title", ""), "final": d["final"],
            "resolved by": d["resolved_by"], "A": d["reviewer_a"]["decision"], "A rationale": d["reviewer_a"]["rationale"],
            "B": d["reviewer_b"]["decision"], "B rationale": d["reviewer_b"]["rationale"],
            "final rationale": d["final_rationale"], "exclusion reason": d["exclusion_reason"], "basis": d["basis"],
        } for d in decisions]), hide_index=True, width="stretch", height=380)
    if not lines(run_dir, "screening_title_abstract"):
        st.caption("Not available yet.")

with tabs[4]:
    extractions = lines(run_dir, "extractions")
    appraisals = {r["rid"]: r for r in lines(run_dir, "risk_of_bias")}
    records = {r["rid"]: r for r in lines(run_dir, "records")}
    if extractions:
        for e in extractions:
            rec, rob = records[e["rid"]], appraisals.get(e["rid"])
            with st.expander(f"{e['rid']} · {rec['title'][:110]} ({rec.get('year')}) · risk of bias: {rob['overall'] if rob else 'n/a'}"):
                st.caption(f"{e['study_design']} · {e['sample_size']} · {e['country']} · read from {e['basis'].replace('_', ' ')}")
                st.dataframe(pd.DataFrame([{"item": i["field"], "value": i["value"], "supporting quote": i["quote"],
                                            "quote found in source": {True: "yes", False: "NO", None: "-"}[i["quote_verified"]]}
                                           for i in e["items"]]), hide_index=True, width="stretch")
                st.markdown("**Key findings**\n" + "\n".join(f"- {f}" for f in e["key_findings"]))
                if rob:
                    st.markdown(f"**Risk of bias ({rob['tool']})**")
                    st.dataframe(pd.DataFrame(rob["domains"]), hide_index=True, width="stretch")
    else:
        st.caption("Not available yet.")

with tabs[5]:
    report = run_dir / "report.md" if (run_dir / "report.md").exists() else run_dir / "report_draft.md"
    if report.exists():
        d1, d2, d3, _ = st.columns([1, 1, 1, 3])
        d1.download_button("Markdown", report.read_bytes(), file_name="report.md")
        if (run_dir / "report.docx").exists():
            d2.download_button("Word (.docx)", (run_dir / "report.docx").read_bytes(), file_name="report.docx")
        if (run_dir / "references.bib").exists():
            d3.download_button("BibTeX", (run_dir / "references.bib").read_bytes(), file_name="references.bib")
        render_markdown(report.read_text(encoding="utf-8"), run_dir)
    else:
        st.caption("Not available yet.")

with tabs[6]:
    qa = latest(run_dir, "qa_report")
    if qa:
        st.markdown(f"**Verdict:** {qa['verdict']} · round {qa['checks'].get('round')}")
        st.json(qa["checks"], expanded=False)
        if qa["issues"]:
            st.dataframe(pd.DataFrame(qa["issues"]), hide_index=True, width="stretch")
    else:
        st.caption("Not available yet.")

with tabs[7]:
    if audit:
        frame = pd.DataFrame([{"seq": e["seq"], "time": e["ts"][11:19], "agent": e["agent"], "action": e["action"],
                               "details": json.dumps({k: v for k, v in e.items() if k not in ("seq", "ts", "agent", "action")},
                                                     ensure_ascii=False, default=str)[:400]} for e in audit])
        agents = st.multiselect("Agents", sorted(frame["agent"].unique()))
        st.dataframe(frame[frame["agent"].isin(agents)] if agents else frame, hide_index=True, width="stretch", height=520)
        st.caption(f"{len(audit)} events · full prompts and responses: {run_dir / 'llm_trace.jsonl'}")

with tabs[8]:
    if (run_dir / "evaluation.md").exists():
        st.markdown((run_dir / "evaluation.md").read_text(encoding="utf-8"))
    elif job["finished"]:
        if st.button("Compute the evaluation"):
            from sysrev.evaluation.run_metrics import evaluate_run

            evaluate_run(ctx)
            st.rerun()
    else:
        st.caption("Available once the review is finished.")

if job["running"]:
    time.sleep(4)
    st.rerun()
