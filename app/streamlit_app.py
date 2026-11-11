"""Streamlit interface: start a review, answer the human checkpoints, browse every artifact.

    streamlit run app/streamlit_app.py
    RUNS_DIR=examples streamlit run app/streamlit_app.py     # browse the exported demonstration
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

import ui  # noqa: E402  (design tokens and HTML components, next to this file)
from sysrev.config import get_settings  # noqa: E402
from sysrev.context import RunOptions, get_context  # noqa: E402
from sysrev.graph import ORDER, ReviewRunner  # noqa: E402
from sysrev.sources.connectors import DISPLAY_NAME  # noqa: E402

st.set_page_config(page_title="PRISMAgent", page_icon="📑", layout="wide")
st.markdown(ui.CSS, unsafe_allow_html=True)

STAGES = {
    "protocol": ("Protocol", "agent"), "search_strategy": ("Search strategy", "agent"),
    "review_protocol": ("Approve protocol", "human"), "retrieval": ("Retrieval", "agent"),
    "screen_title_abstract": ("Title / abstract", "agent"), "review_screening": ("Check screening", "human"),
    "screen_full_text": ("Full text", "agent"), "extraction": ("Extraction", "agent"),
    "synthesis": ("Synthesis", "agent"), "critic": ("Critic", "agent"),
    "review_report": ("Approve report", "human"), "finalize": ("Exports", "agent"),
}
STAGE_LONG = {
    "protocol": "Protocol", "search_strategy": "Search strategy", "retrieval": "Retrieval and de-duplication",
    "screen_title_abstract": "Title / abstract screening", "screen_full_text": "Full-text retrieval and screening",
    "extraction": "Extraction and appraisal", "synthesis": "Synthesis and writing", "critic": "Quality assurance",
    "finalize": "Exports",
}
CHECKPOINT_STAGE = {"protocol_and_search": "review_protocol", "screening": "review_screening", "final_report": "review_report"}


def html(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def kappa(agreement: dict | None) -> str:
    value = (agreement or {}).get("cohen_kappa")
    return f"{value:.2f}" if value is not None else "—"


# --------------------------------------------------------------------------- #
# Background jobs and data access
# --------------------------------------------------------------------------- #


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
           "finished": (started and runner.finished()) or exported, "error": None}
    jobs()[run_id] = job
    return job


def latest(run_dir: Path, name: str):
    files = sorted(run_dir.glob(f"{name}_v*.json"), key=lambda p: int(p.stem.rsplit("_v", 1)[1]))
    return json.loads(files[-1].read_text(encoding="utf-8")) if files else None


def lines(run_dir: Path, name: str) -> list[dict]:
    path = run_dir / f"{name}.jsonl"
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()] if path.exists() else []


def short_ref(record: dict) -> str:
    authors = record.get("authors") or []
    first = authors[0].split(",")[0].strip() if authors else "Anon"
    return f"{first}{' et al.' if len(authors) > 1 else ''} ({record.get('year') or 'n.d.'})"


def render_markdown(text: str, base: Path) -> None:
    """st.markdown cannot show local images: split the text around image tags."""
    for part in re.split(r"(!\[.*?\]\(.*?\))", text):
        image = re.match(r"!\[(.*?)\]\((.*?)\)", part)
        if image and (base / image.group(2)).exists():
            st.image(str(base / image.group(2)), caption=image.group(1))
        elif part.strip():
            st.markdown(part)


# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #

settings = get_settings()
runs = sorted(
    (p.parent.name for p in settings.runs_dir.glob("*/manifest.json") if not p.parent.name.startswith("benchmark-")),
    reverse=True,
)

with st.sidebar:
    html(ui.brand())
    if runs:
        html('<div class="side-label">Review</div>')
        default = st.session_state.get("run_id", runs[0])

        def run_label(name: str) -> str:
            question = json.loads((settings.runs_dir / name / "manifest.json").read_text())["question"]
            return question if len(question) <= 54 else question[:53] + "…"

        run_id = st.selectbox("Review", runs, index=runs.index(default) if default in runs else 0,
                              format_func=run_label, label_visibility="collapsed")
        st.session_state["run_id"] = run_id

    html('<div class="side-label">New review</div>')
    with st.expander("Start from a question", expanded=not runs):
        question = st.text_area("Research question", height=120, label_visibility="collapsed",
                                placeholder="e.g. Does remote monitoring reduce readmissions in adults with heart failure?")
        auto = st.toggle("Autonomous mode", value=False, help="Skip the three human checkpoints. The report will say so.")
        c1, c2 = st.columns(2)
        max_per_source = c1.number_input("Per database", 20, 2000, 60, step=10, help="Records fetched from each database")
        max_screen = c2.number_input("Screened", 10, 2000, 50, step=10, help="Maximum records sent to screening")
        fallback = st.selectbox("If no open full text", ["abstract", "exclude"],
                                format_func=lambda v: "Assess on the abstract" if v == "abstract" else "Exclude as not retrieved")
        if st.button("Start review", type="primary", disabled=not question.strip(), width="stretch"):
            runner = ReviewRunner.create(question.strip(), RunOptions(
                auto_approve=auto, max_per_source=int(max_per_source), max_screen=int(max_screen), fulltext_fallback=fallback))
            launch(runner.run_id)
            st.session_state["run_id"] = runner.run_id
            st.rerun()
    html(
        '<div class="side-foot">Seven agents coordinated with LangGraph, grounded by hybrid retrieval over '
        "PubMed, Europe PMC, OpenAlex, arXiv and Semantic Scholar. Every decision is logged.</div>"
    )

if not runs:
    html(ui.hero("Start your first systematic review", ("", "No review yet"), []))
    html(ui.empty("Type a research question in the sidebar. The agents write the protocol, search the literature, "
                  "screen, extract, appraise and draft a PRISMA 2020 manuscript."))
    st.stop()

ctx = get_context(run_id)
run_dir = ctx.run_dir
job = job_for(run_id)
manifest = ctx.manifest
audit = lines(run_dir, "audit")

# --------------------------------------------------------------------------- #
# Hero and progress
# --------------------------------------------------------------------------- #

completed = [e["stage"] for e in audit if e["action"] == "stage_completed"]
completed += [CHECKPOINT_STAGE[e["checkpoint"]] for e in audit if e["action"] == "checkpoint" and e["checkpoint"] in CHECKPOINT_STAGE]
started = [e["stage"] for e in audit if e["action"] == "stage_started"]
current = next((s for s in reversed(started) if started.count(s) > completed.count(s)), None)
pending = job["pending"] if not job["running"] else None
if pending:
    current = {"protocol": "review_protocol", "screening": "review_screening", "report": "review_report"}[pending["checkpoint"]]

if job["error"]:
    state = ("err", "Stopped on an error")
elif job["running"]:
    state = ("run", f"Running · {STAGE_LONG.get(current, 'starting')}")
elif pending:
    state = ("wait", "Waiting for your review")
elif job["finished"]:
    state = ("done", "Finished")
else:
    state = ("", "Paused")

models = manifest["llm"].get("task_models", {})
chips = [("Mode", "autonomous" if manifest["options"]["auto_approve"] else "human-in-the-loop"),
         ("Started", manifest["created"][:10])]
html(ui.hero(manifest["question"], state, chips))

active = job["running"] or bool(pending)
steps = []
for n, stage in enumerate(ORDER, start=1):
    name, kind = STAGES[stage]
    is_now = active and stage == current
    done = (stage in completed or job["finished"]) and not is_now
    steps.append({"name": name, "kind": kind, "n": n, "state": "now" if is_now else ("done" if done else "todo")})
html(ui.stepper(steps))

if job["error"]:
    st.error(job["error"])
    if st.button("Resume from the last checkpoint", type="primary"):
        launch(run_id)
        st.rerun()
elif not job["running"] and not pending and not job["finished"]:
    if st.button("Resume this review", type="primary"):
        launch(run_id)
        st.rerun()

# --------------------------------------------------------------------------- #
# Human checkpoints
# --------------------------------------------------------------------------- #

if pending and pending["checkpoint"] == "protocol":
    html('<div class="callout"><h3>Checkpoint 1 · Approve the protocol and the search strategy</h3>'
         "<p>Approve as is, edit the protocol yourself, or describe the changes and let the Planner agent revise it.</p></div>")
    left, right = st.columns([5, 6], gap="large")
    edited = left.text_area("Protocol (editable JSON)", json.dumps(pending["protocol"], indent=2, ensure_ascii=False), height=520)
    strategy = pending["search_strategy"]
    right.dataframe(pd.DataFrame([{"Database": DISPLAY_NAME.get(db, db), "Hits": strategy["hit_counts"].get(db), "Query": q}
                                  for db, q in strategy["queries"].items()]), hide_index=True, width="stretch")
    right.caption(strategy["rationale"])
    feedback = right.text_area("Changes you want", height=110, placeholder="e.g. Restrict to adults; add terms for telemonitoring")
    b1, b2, b3 = right.columns(3)
    if b1.button("Approve", type="primary", width="stretch"):
        launch(run_id, {"action": "approve"})
        st.rerun()
    if b2.button("Request changes", disabled=not feedback.strip(), width="stretch"):
        launch(run_id, {"action": "revise", "feedback": feedback.strip()})
        st.rerun()
    if b3.button("Save my edits", width="stretch"):
        try:
            launch(run_id, {"action": "approve", "protocol": json.loads(edited)})
            st.rerun()
        except json.JSONDecodeError as exc:
            st.error(f"Invalid JSON: {exc}")

elif pending and pending["checkpoint"] == "screening":
    a = pending["agreement"]
    html('<div class="callout"><h3>Checkpoint 2 · Check the title/abstract decisions</h3>'
         "<p>Change any decision in the “Final” column, then approve. Your overrides are logged and reported.</p></div>")
    html(ui.tiles([
        {"label": "Records screened", "value": a["n"]},
        {"label": "Retained for full text", "value": sum(d["final"] == "include" for d in pending["decisions"]), "lead": True},
        {"label": "Reviewer agreement", "value": kappa(a), "unit": "κ", "note": a["interpretation"]},
        {"label": "Conflicts adjudicated", "value": a["conflicts"]},
    ]))
    frame = pd.DataFrame(pending["decisions"])
    only = st.toggle("Only retained and adjudicated records", value=True)
    view = frame[(frame["final"] == "include") | (frame["resolved_by"] != "consensus")] if only else frame
    edited_view = st.data_editor(
        view, hide_index=True, width="stretch", height=440,
        disabled=["rid", "title", "resolved_by", "a", "b", "rationale"],
        column_config={
            "rid": "ID", "title": st.column_config.TextColumn("Title", width="large"), "resolved_by": "Resolved by",
            "a": "Reviewer A", "b": "Reviewer B", "rationale": st.column_config.TextColumn("Rationale", width="large"),
            "final": st.column_config.SelectboxColumn("Final", options=["include", "exclude"]),
        },
    )
    original = dict(zip(frame["rid"], frame["final"]))
    overrides = {r["rid"]: r["final"] for _, r in edited_view.iterrows() if r["final"] != original[r["rid"]]}
    if st.button(f"Approve with {len(overrides)} override(s)" if overrides else "Approve", type="primary"):
        launch(run_id, {"action": "approve", "overrides": overrides})
        st.rerun()

elif pending and pending["checkpoint"] == "report":
    pending_qa = pending["qa_report"]
    html('<div class="callout"><h3>Checkpoint 3 · Approve the manuscript</h3>'
         f"<p>The Critic agent leaves {len(pending_qa['issues'])} issue(s) open; see the Quality tab. "
         "Approve to export, or ask the Writing agent for a revision.</p></div>")
    feedback = st.text_area("Revision request (optional)", height=90)
    b1, b2, _ = st.columns([1, 1, 3])
    if b1.button("Approve and export", type="primary", width="stretch"):
        launch(run_id, {"action": "approve"})
        st.rerun()
    if b2.button("Request revision", disabled=not feedback.strip(), width="stretch"):
        launch(run_id, {"action": "revise", "feedback": feedback.strip()})
        st.rerun()

# --------------------------------------------------------------------------- #
# Artifacts
# --------------------------------------------------------------------------- #

flow = latest(run_dir, "prisma_flow")
protocol = latest(run_dir, "protocol")
strategy = latest(run_dir, "search_strategy")
result = latest(run_dir, "result")
qa = latest(run_dir, "qa_report")
records = {r["rid"]: r for r in lines(run_dir, "records")}
extractions = lines(run_dir, "extractions")
appraisals = {r["rid"]: r for r in lines(run_dir, "risk_of_bias")}
agreement_ta = latest(run_dir, "agreement_title_abstract")
agreement_ft = latest(run_dir, "agreement_full_text")

tabs = st.tabs([":material/dashboard: Overview", ":material/assignment: Protocol", ":material/filter_alt: Screening",
                ":material/menu_book: Studies", ":material/article: Report", ":material/verified: Quality"])

# The interface shows the headline first; everything else is one click away, in an expander.

# ---- Overview ---------------------------------------------------------------
with tabs[0]:
    if not flow:
        html(ui.empty("The overview fills in as soon as the first records are retrieved."))
    else:
        identified = sum(flow["identified"].values())
        html(ui.tiles([
            {"label": "Records identified", "value": identified},
            {"label": "Screened", "value": flow["records_screened"]},
            {"label": "Studies included", "value": flow["studies_included"], "lead": True},
            {"label": "Reviewer agreement", "value": kappa(agreement_ta), "unit": "κ",
             "note": agreement_ta["interpretation"] if agreement_ta else ""},
        ]))

        left, right = st.columns([3, 2], gap="medium")
        unique = identified - flow["duplicates_removed"]
        reasons = "; ".join(f"{n} × {reason.split(':')[0]}" for reason, n in flow["reports_excluded"].items())
        funnel = [
            {"name": "Identified", "value": identified,
             "tip": "Records returned by the searches: " + ", ".join(f"{DISPLAY_NAME.get(k, k)} {v}" for k, v in flow["identified"].items()) + "."},
            {"name": "After de-duplication", "value": unique, "tip": f"{flow['duplicates_removed']} duplicates merged."},
            {"name": "Screened", "value": flow["records_screened"],
             "tip": f"{flow['removed_by_automation']} records ranked below the relevance cap were not screened."},
            {"name": "Sought in full text", "value": flow["reports_sought"],
             "tip": f"{flow['records_excluded']} records excluded on title and abstract."},
            {"name": "Assessed for eligibility", "value": flow["reports_assessed"],
             "tip": f"{flow['assessed_on_abstract_only']} assessed on the abstract only; {flow['reports_not_retrieved']} not retrieved."},
            {"name": "Included", "value": flow["studies_included"], "key": True,
             "tip": f"{sum(flow['reports_excluded'].values())} reports excluded with reasons: {reasons or 'none'}."},
        ]
        with left:
            html(ui.card("Study selection", ui.bars(funnel)))
        with right:
            blocks = []
            levels = [appraisals[e["rid"]]["overall"] for e in extractions if e["rid"] in appraisals]
            if levels:
                blocks.append(ui.mini("Risk of bias", ui.segbar({level: levels.count(level) for level in ui.STATUS})))
            flags = [i["quote_verified"] for e in extractions for i in e["items"] + e.get("effects", []) if i["quote_verified"] is not None]
            if flags:
                blocks.append(ui.mini("Quotations found in the source", ui.compact_meter(sum(flags), len(flags)),
                                      f"<b>{sum(flags) / len(flags):.0%}</b>"))
            if qa:
                n_issues = len(qa["issues"])
                blocks.append(ui.mini("Critic", "", ui.pill(f"{n_issues} open issue{'s' if n_issues != 1 else ''}" if n_issues else "No open issue",
                                                            "warn" if n_issues else "good")))
            html(ui.card("Quality at a glance", "".join(blocks) if blocks else ui.empty("Available after extraction.")))

        meta = latest(run_dir, "manuscript_meta")
        if meta and meta.get("themes"):
            st.write("")
            tone = {"high": "good", "moderate": "info", "low": "warn", "very low": "crit"}
            items = []
            for theme in meta["themes"]:
                certainty = meta["syntheses"].get(theme["name"], {}).get("certainty")
                badge = ui.pill(f"Certainty: {certainty}", tone.get(certainty, "plain")) if certainty else ""
                items.append(ui.row(f'<div class="crit-id">{len(theme["study_ids"])}</div>', f"<b>{ui.e(theme['name'])}</b>", badge))
            html(ui.card("Themes of the synthesis", ui.rows(items)))

        if (run_dir / "prisma_flow.png").exists():
            st.write("")
            with st.expander("PRISMA 2020 flow diagram", icon=":material/account_tree:"):
                _, centre, _ = st.columns([1, 5, 1])
                centre.image(str(run_dir / "prisma_flow.png"))

# ---- Protocol ---------------------------------------------------------------
with tabs[1]:
    if not protocol:
        html(ui.empty("The Planner agent has not written the protocol yet."))
    else:
        defs = "".join(f'<div class="def"><b>{ui.e(k)}</b><span>{ui.e(v)}</span></div>' for k, v in protocol["framework_elements"].items())
        html(ui.card(protocol["title"], f'<div class="defs">{defs}</div>'))
        st.write("")

        def criterion(c: dict) -> str:
            badge = ui.tag("full text only") if c.get("full_text_only") else ""
            return ui.row(f'<div class="crit-id">{ui.e(c["id"])}</div>', ui.e(c["text"]), badge)

        c1, c2 = st.columns(2, gap="medium")
        with c1:
            html(ui.card("Inclusion criteria", ui.rows([criterion(c) for c in protocol["inclusion_criteria"]])))
        with c2:
            html(ui.card("Exclusion criteria", ui.rows([criterion(c) for c in protocol["exclusion_criteria"]])))
        st.write("")

        if strategy:
            hits = " · ".join(f"{DISPLAY_NAME.get(db, db)} {strategy['hit_counts'].get(db, '?')}" for db in strategy["queries"])
            with st.expander(f"Search strategy — {hits} hits", icon=":material/search:"):
                for i, c in enumerate(strategy["concepts"], start=1):
                    html(f"<b>Concept {i} · {ui.e(c['name'])}</b><div style='height:6px'></div><div class='badges'>"
                         + "".join(ui.tag(term) for term in c["free_text_terms"])
                         + "".join(ui.pill(term, "info") for term in c["controlled_terms"]) + "</div><div style='height:14px'></div>")
                for db, query in strategy["queries"].items():
                    st.caption(f"{DISPLAY_NAME.get(db, db)} · {strategy['hit_counts'].get(db, '?')} hits")
                    st.code(query, language=None, wrap_lines=True)
                st.caption(f"The agent tested {len(strategy['refinement_log'])} queries on the live databases before settling on these.")
        with st.expander("Data to extract and planned methods", icon=":material/checklist:"):
            html('<div class="badges">' + "".join(ui.tag(i) for i in protocol["data_items"]) + "</div>")
            st.markdown(f"**Outcomes** · {'; '.join(protocol['outcomes'])}")
            st.markdown(f"**Study designs** · {', '.join(protocol['study_designs'])}")
            st.markdown(f"**Risk of bias** · {protocol['risk_of_bias_approach']}")
            st.markdown(f"**Synthesis** · {protocol['synthesis_plan']}")
        plan = latest(run_dir, "plan")
        if plan and plan["briefs"]:
            with st.expander("Briefs from the coordinator to the other agents", icon=":material/hub:"):
                for brief in plan["briefs"]:
                    st.markdown(f"**{brief['stage'].replace('_', ' ').capitalize()}** · {brief['guidance']}")

# ---- Screening --------------------------------------------------------------
with tabs[2]:
    stage_defs = [("screening_title_abstract", "Title and abstract", agreement_ta), ("screening_full_text", "Full text", agreement_ft)]
    available = [(key, label, agreement) for key, label, agreement in stage_defs if lines(run_dir, key)]
    if not available:
        html(ui.empty("No screening decision yet."))
    else:
        choice = st.segmented_control("Stage", [label for _, label, _ in available], default=available[0][1], label_visibility="collapsed")
        key, label, agreement = next(item for item in available if item[1] == (choice or available[0][1]))
        decisions = lines(run_dir, key)
        included = sum(d["final"] == "include" for d in decisions)
        html(ui.tiles([
            {"label": "Assessed", "value": len(decisions)},
            {"label": "Included", "value": included, "lead": True},
            {"label": "Excluded", "value": len(decisions) - included},
            {"label": "Reviewer agreement", "value": kappa(agreement), "unit": "κ",
             "note": f"{agreement['conflicts']} conflict{'s' if agreement['conflicts'] != 1 else ''} adjudicated" if agreement else ""},
        ]))
        with_rationales = st.toggle("Show the reviewers' rationales", value=False)
        table = pd.DataFrame([{
            "ID": d["rid"], "Title": records.get(d["rid"], {}).get("title", ""), "Final": d["final"],
            "Reviewer A": d["reviewer_a"]["decision"], "Reviewer B": d["reviewer_b"]["decision"], "Resolved by": d["resolved_by"],
            **({"Why": d["final_rationale"], "Exclusion reason": d["exclusion_reason"]} if with_rationales else {}),
        } for d in decisions])
        st.dataframe(table, hide_index=True, width="stretch", height=430,
                     column_config={"Title": st.column_config.TextColumn(width="large"), "Why": st.column_config.TextColumn(width="large")})
        conflicts = [d for d in decisions if d["resolved_by"] != "consensus"]
        if conflicts:
            with st.expander(f"The {len(conflicts)} disagreement{'s' if len(conflicts) != 1 else ''} and how they were settled",
                             icon=":material/balance:"):
                for d in conflicts:
                    a, b = d["reviewer_a"], d["reviewer_b"]
                    html(f'<div style="margin:6px 0 8px"><b>{ui.e(d["rid"])} · {ui.e(records.get(d["rid"], {}).get("title", "")[:120])}</b></div>'
                         f'<div class="badges" style="margin-bottom:8px">{ui.decision_pill(d["final"])}{ui.tag("resolved by " + d["resolved_by"])}</div>')
                    ca, cb = st.columns(2)
                    ca.markdown(f"**Reviewer A** · {a['decision']}  \n{a['rationale']}")
                    cb.markdown(f"**Reviewer B** · {b['decision']}  \n{b['rationale']}")
                    st.markdown(f"**Decision** · {d['final_rationale']}")
                    st.divider()

# ---- Studies ----------------------------------------------------------------
with tabs[3]:
    if not extractions:
        html(ui.empty("No study has been extracted yet."))
    else:
        for e in extractions:
            record, rob = records[e["rid"]], appraisals.get(e["rid"])
            flags = [i["quote_verified"] for i in e["items"] + e.get("effects", []) if i["quote_verified"] is not None]
            badges = []
            if rob:
                badges.append(ui.rob_pill(rob["overall"]))
            if flags:
                badges.append(ui.pill(f"{sum(flags)}/{len(flags)} quotations verified", "good" if all(flags) else "warn"))
            if e["basis"] == "abstract":
                badges.append(ui.tag("abstract only"))
            html(f'<div class="study"><h4>{ui.e(record["title"])}</h4><div class="by">{ui.e(short_ref(record))} · '
                 f'{ui.e(record.get("venue") or "")}</div><div class="badges">{"".join(badges)}</div></div>')
            with st.expander("Extracted data, findings and appraisal"):
                st.caption(f"{e['study_design']} · {e['sample_size']} · {e['rid']}")
                st.markdown("**Key findings**\n" + "\n".join(f"- {finding}" for finding in e["key_findings"]))
                st.dataframe(pd.DataFrame([{
                    "Data item": i["field"], "Value": i["value"], "Supporting quotation": i["quote"],
                    "Found in source": {True: "yes", False: "no", None: "—"}[i["quote_verified"]],
                } for i in e["items"]]), hide_index=True, width="stretch",
                    column_config={"Value": st.column_config.TextColumn(width="medium"),
                                   "Supporting quotation": st.column_config.TextColumn(width="large")})
                if rob:
                    st.markdown(f"**Risk of bias · {rob['tool']}** — {rob['overall_justification']}")
                    st.dataframe(pd.DataFrame([{"Domain": d["domain"], "Judgement": d["judgement"], "Justification": d["justification"]}
                                               for d in rob["domains"]]), hide_index=True, width="stretch")

# ---- Report -----------------------------------------------------------------
with tabs[4]:
    report = run_dir / "report.md" if (run_dir / "report.md").exists() else run_dir / "report_draft.md"
    if not report.exists():
        html(ui.empty("The manuscript appears here once the Writing agent has produced a draft."))
    else:
        text = report.read_text(encoding="utf-8")
        d1, d2, d3, info = st.columns([1, 1, 1, 4])
        d1.download_button("Markdown", report.read_bytes(), file_name="report.md", icon=":material/download:", width="stretch")
        if (run_dir / "report.docx").exists():
            d2.download_button("Word", (run_dir / "report.docx").read_bytes(), file_name="report.docx",
                               icon=":material/download:", width="stretch")
        if (run_dir / "references.bib").exists():
            d3.download_button("BibTeX", (run_dir / "references.bib").read_bytes(), file_name="references.bib",
                               icon=":material/download:", width="stretch")
        info.caption(f"{len(text.split()):,} words · {'final version' if report.name == 'report.md' else 'draft under review'}")
        _, middle, _ = st.columns([1, 6, 1])
        with middle:
            render_markdown(text, run_dir)

# ---- Quality ----------------------------------------------------------------
with tabs[5]:
    if not qa:
        html(ui.empty("The Critic agent reviews the manuscript once a draft exists."))
    else:
        checks = qa["checks"]
        quotes = checks.get("extraction_quotes") or {}
        rounds = checks.get("round", 1)
        html(ui.tiles([
            {"label": "Open issues", "value": len(qa["issues"]), "lead": True, "note": f"after {rounds} critic round{'s' if rounds != 1 else ''}"},
            {"label": "Quotations verified", "value": f"{quotes['verification_rate']:.0%}" if quotes.get("verification_rate") is not None else "—",
             "note": f"{quotes.get('quotes_verified', 0)} of {quotes.get('quotes_checked', 0)}"},
            {"label": "PRISMA items", "value": f"{checks.get('prisma_items_reported', '—')}/{checks.get('prisma_items_total', '—')}",
             "note": "reported"},
            {"label": "Unknown citations", "value": len(checks.get("unknown_citations") or [])},
        ]))
        if not qa["issues"]:
            html(ui.empty("The critic found no issue."))
        severity_icon = {"critical": ":material/error:", "major": ":material/warning:", "minor": ":material/info:"}
        for issue in sorted(qa["issues"], key=lambda i: ["critical", "major", "minor"].index(i["severity"])):
            area = issue["area"].split(":", 1)[-1]
            summary = issue["description"].split(" — ")[0].replace("Unsupported statement: ", "")
            summary = summary if len(summary) <= 92 else summary[:91] + "…"
            with st.expander(f"{issue['severity'].capitalize()} · {area} · {summary}", icon=severity_icon[issue["severity"]]):
                st.markdown(issue["description"])
                if issue.get("suggested_fix"):
                    st.markdown(f"**Suggested fix** · {issue['suggested_fix']}")

    evaluation = latest(run_dir, "evaluation")
    if evaluation or job["finished"]:
        st.write("")
        with st.expander("Evaluation: completeness, accuracy, consistency, time", icon=":material/monitoring:"):
            if not evaluation:
                if st.button("Compute the evaluation", type="primary"):
                    from sysrev.evaluation.run_metrics import evaluate_run

                    evaluate_run(ctx)
                    st.rerun()
            else:
                t = evaluation["time"]

                def listing(section: dict) -> str:
                    return ui.rows([ui.row("", f'<span class="muted">{ui.e(k.replace("_", " ").capitalize().replace("Prisma", "PRISMA").replace("cohen", "Cohen"))}</span>',
                                           f"<b>{ui.e(v)}</b>") for k, v in section.items() if k != "note"])

                c1, c2 = st.columns(2, gap="medium")
                with c1:
                    html(ui.card("Completeness", listing(evaluation["completeness"])))
                    st.write("")
                    html(ui.card("Inter-agent consistency", listing(evaluation["consistency"])))
                with c2:
                    html(ui.card("Accuracy and grounding", listing(evaluation["accuracy"])))
                    st.write("")
                    timings = json.loads((run_dir / "timings.json").read_text()) if (run_dir / "timings.json").exists() else {}
                    time_rows = [{"name": STAGE_LONG[s], "value": round(timings[s] / 60, 1), "label": f"{timings[s] / 60:.1f} min"}
                                 for s in ORDER if s in timings and s in STAGE_LONG and timings[s] >= 1]
                    html(ui.card("Machine time per stage", ui.bars(time_rows),
                                 f"{t['pipeline_hours']:.2f} h in total, against an estimated {t['manual_person_hours_estimate']:.0f} person-hours by hand"))
                st.caption(t["note"])
    if audit:
        with st.expander(f"Audit trail — {len(audit)} events", icon=":material/history:"):
            frame = pd.DataFrame([{
                "#": e["seq"], "Time": e["ts"][11:19], "Agent": e["agent"], "Action": e["action"].replace("_", " "),
                "Details": json.dumps({k: v for k, v in e.items() if k not in ("seq", "ts", "agent", "action")},
                                      ensure_ascii=False, default=str)[:400],
            } for e in audit])
            agents = st.multiselect("Filter by agent", sorted(frame["Agent"].unique()), placeholder="All agents")
            st.dataframe(frame[frame["Agent"].isin(agents)] if agents else frame, hide_index=True, width="stretch", height=460,
                         column_config={"Details": st.column_config.TextColumn(width="large")})
            st.caption("Full prompts and responses of every model call are in llm_trace.jsonl in the run folder.")

if job["running"]:
    time.sleep(4)
    st.rerun()
