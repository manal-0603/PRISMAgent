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

st.set_page_config(page_title="SysRev Agents", page_icon="📑", layout="wide")
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
chips = [("Started", manifest["created"][:16].replace("T", " ")),
         ("Mode", "autonomous" if manifest["options"]["auto_approve"] else "human-in-the-loop")]
if models:
    chips.append(("Models", " · ".join(dict.fromkeys(m.split("/")[-1] for m in models.values()))))
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

tabs = st.tabs([":material/dashboard: Overview", ":material/assignment: Protocol", ":material/search: Search",
                ":material/filter_alt: Screening", ":material/menu_book: Studies", ":material/article: Report",
                ":material/verified: Quality", ":material/history: Audit trail", ":material/monitoring: Evaluation"])

# ---- Overview ---------------------------------------------------------------
with tabs[0]:
    if not flow:
        html(ui.empty("The overview fills in as soon as the first records are retrieved."))
    else:
        identified = sum(flow["identified"].values())
        checklist = f"{result['prisma_items_reported']}/{result['prisma_items_total']}" if result else "—"
        html(ui.tiles([
            {"label": "Records identified", "value": identified, "note": f"{len(flow['identified'])} databases"},
            {"label": "Screened", "value": flow["records_screened"], "note": "title and abstract"},
            {"label": "Full texts assessed", "value": flow["reports_assessed"],
             "note": f"{flow['assessed_on_abstract_only']} on abstract only" if flow["assessed_on_abstract_only"] else "all in full text"},
            {"label": "Studies included", "value": flow["studies_included"], "lead": True},
            {"label": "Reviewer agreement", "value": kappa(agreement_ta), "unit": "κ",
             "note": agreement_ta["interpretation"] if agreement_ta else "not screened yet"},
            {"label": "PRISMA items", "value": checklist, "note": "reported, 2020 checklist"},
        ]))

        left, right = st.columns(2, gap="medium")
        unique = identified - flow["duplicates_removed"]
        reasons = "; ".join(f"{n} × {reason.split(':')[0]}" for reason, n in flow["reports_excluded"].items())
        funnel = [
            {"name": "Identified", "value": identified,
             "note": " · ".join(f"{DISPLAY_NAME.get(k, k)} {v}" for k, v in flow["identified"].items()),
             "tip": "Records returned by the database searches."},
            {"name": "After de-duplication", "value": unique, "note": f"{flow['duplicates_removed']} duplicates merged",
             "tip": "Matched on DOI, PubMed id, arXiv id, then title."},
            {"name": "Screened", "value": flow["records_screened"], "note": f"{flow['removed_by_automation']} below the relevance cap",
             "tip": "Records are ranked by hybrid retrieval against the question; the rest are reported as removed by automation."},
            {"name": "Sought in full text", "value": flow["reports_sought"], "note": f"{flow['records_excluded']} excluded on title/abstract",
             "tip": "Two reviewers on different models; conflicts are adjudicated."},
            {"name": "Assessed for eligibility", "value": flow["reports_assessed"], "note": f"{flow['reports_not_retrieved']} not retrieved",
             "tip": "Passages relevant to each criterion are retrieved from the full text."},
            {"name": "Included", "value": flow["studies_included"], "key": True,
             "note": f"{sum(flow['reports_excluded'].values())} excluded with reasons", "tip": f"Exclusion reasons: {reasons or 'none'}."},
        ]
        with left:
            html(ui.card("Study selection", ui.bars(funnel), "Number of records at each PRISMA stage"))
        timings = json.loads((run_dir / "timings.json").read_text()) if (run_dir / "timings.json").exists() else {}
        time_rows = [{"name": STAGE_LONG[s], "value": round(timings[s] / 60, 1), "label": f"{timings[s] / 60:.1f} min",
                      "tip": f"{timings[s]:.0f} seconds of wall-clock time, mostly waiting for the API rate limit."}
                     for s in ORDER if s in timings and s in STAGE_LONG and timings[s] >= 1]
        with right:
            total_minutes = sum(timings.values()) / 60
            body = ui.bars(time_rows) if time_rows else ui.empty("No timing yet.")
            html(ui.card("Where the time went", body, f"Minutes per stage · {total_minutes:.1f} min in total"))

        st.write("")
        c1, c2, c3 = st.columns(3, gap="medium")
        with c1:
            levels = [appraisals[e["rid"]]["overall"] for e in extractions if e["rid"] in appraisals]
            body = ui.segbar({level: levels.count(level) for level in ui.STATUS}) if levels else ui.empty("Not appraised yet.")
            html(ui.card("Risk of bias", body, f"Overall judgement of the {len(levels)} included studies"))
        with c2:
            flags = [i["quote_verified"] for e in extractions for i in e["items"] + e.get("effects", []) if i["quote_verified"] is not None]
            body = (ui.meter(sum(flags), len(flags), "supporting quotations found word for word in the source text")
                    if flags else ui.empty("Nothing extracted yet."))
            html(ui.card("Evidence grounding", body, "Every extracted value must quote its source"))
        with c3:
            if qa:
                n_issues = len(qa["issues"])
                rounds = qa["checks"].get("round", 1)
                unsupported = qa["checks"].get("unsupported_statements", 0)
                body = (
                    f'<div class="figure">{n_issues} <small>issue{"s" if n_issues != 1 else ""} after {rounds} round{"s" if rounds != 1 else ""}</small></div>'
                    f'<div style="height:10px"></div><div class="badges">'
                    f'{ui.pill(f"{n_issues} still open" if n_issues else "No open issue", "warn" if n_issues else "good")}'
                    f'{ui.tag(f"{unsupported} unsupported statements")}{ui.tag("round " + str(qa["checks"].get("round", 1)))}</div>'
                )
            else:
                body = ui.empty("The critic has not reviewed a draft yet.")
            html(ui.card("Critic", body, "A second model checks every claim against its evidence"))

        if (run_dir / "prisma_flow.png").exists():
            st.write("")
            with st.expander("PRISMA 2020 flow diagram", icon=":material/account_tree:"):
                _, centre, _ = st.columns([1, 5, 1])
                centre.image(str(run_dir / "prisma_flow.png"))

        meta = latest(run_dir, "manuscript_meta")
        if meta and meta.get("themes"):
            st.write("")
            tone = {"high": "good", "moderate": "info", "low": "warn", "very low": "crit"}
            items = []
            for theme in meta["themes"]:
                syn = meta["syntheses"].get(theme["name"], {})
                certainty = syn.get("certainty")
                badge = ui.pill(f"Certainty: {certainty}", tone.get(certainty, "plain")) if certainty else ""
                items.append(ui.row(
                    f'<div class="crit-id">{len(theme["study_ids"])}</div>',
                    f"<b>{ui.e(theme['name'])}</b><div class=\"muted\">{ui.e(syn.get('certainty_rationale') or theme['description'])}</div>",
                    badge,
                ))
            html(ui.card("Themes of the synthesis", ui.rows(items),
                         "Number of studies per theme and certainty of the evidence (automated, GRADE-inspired)"))

# ---- Protocol ---------------------------------------------------------------
with tabs[1]:
    if not protocol:
        html(ui.empty("The Planner agent has not written the protocol yet."))
    else:
        versions = len(list(run_dir.glob("protocol_v*.json")))
        defs = "".join(f'<div class="def"><b>{ui.e(k)}</b><span>{ui.e(v)}</span></div>' for k, v in protocol["framework_elements"].items())
        html(ui.card(protocol["title"], f'<div class="defs">{defs}</div>',
                     f"{protocol['framework']} framework · version {versions} · "
                     f"{', '.join(DISPLAY_NAME.get(d, d) for d in protocol['databases'])}"))
        st.write("")
        c1, c2 = st.columns(2, gap="medium")
        inc = [ui.row(f'<div class="crit-id">{ui.e(c["id"])}</div>', ui.e(c["text"])) for c in protocol["inclusion_criteria"]]
        exc = [ui.row(f'<div class="crit-id">{ui.e(c["id"])}</div>', ui.e(c["text"])) for c in protocol["exclusion_criteria"]]
        with c1:
            html(ui.card("Inclusion criteria", ui.rows(inc), "A record must meet all of them"))
        with c2:
            html(ui.card("Exclusion criteria", ui.rows(exc), "Any one of them excludes a record"))
        st.write("")
        c1, c2 = st.columns(2, gap="medium")
        with c1:
            body = '<div class="badges">' + "".join(ui.tag(i) for i in protocol["data_items"]) + "</div>"
            body += '<div style="height:14px"></div><div class="muted"><b>Outcomes</b> · ' + ui.e("; ".join(protocol["outcomes"])) + "</div>"
            html(ui.card("Data to extract", body, "Read from every included study, each with a supporting quotation"))
        with c2:
            body = (f'<div class="muted"><b>Study designs</b> · {ui.e(", ".join(protocol["study_designs"]))}</div><div style="height:8px"></div>'
                    f'<div class="muted"><b>Risk of bias</b> · {ui.e(protocol["risk_of_bias_approach"])}</div><div style="height:8px"></div>'
                    f'<div class="muted"><b>Synthesis</b> · {ui.e(protocol["synthesis_plan"])}</div>')
            html(ui.card("Methods planned", body, "Fixed before the search is run"))
        plan = latest(run_dir, "plan")
        if plan and plan["briefs"]:
            st.write("")
            briefs = [ui.row(ui.tag(b["stage"].replace("_", " ")), ui.e(b["guidance"])) for b in plan["briefs"]]
            html(ui.card("Briefs from the coordinator", ui.rows(briefs), "Topic-specific instructions the Planner gives to each agent"))

# ---- Search -----------------------------------------------------------------
with tabs[2]:
    if not strategy:
        html(ui.empty("The Search Strategy agent has not run yet."))
    else:
        html(ui.tiles([{"label": DISPLAY_NAME.get(db, db), "value": strategy["hit_counts"].get(db, "—"), "unit": "hits",
                        "note": f"{(flow or {}).get('identified', {}).get(db, 0)} records retrieved"} for db in strategy["queries"]]))
        concept_rows = [ui.row(
            f'<div class="crit-id">{i}</div>',
            f"<b>{ui.e(c['name'])}</b><div style=\"height:6px\"></div><div class=\"badges\">"
            + "".join(ui.tag(t) for t in c["free_text_terms"]) + "".join(ui.pill(t, "info") for t in c["controlled_terms"]) + "</div>",
        ) for i, c in enumerate(strategy["concepts"], start=1)]
        html(ui.card("Concept blocks", ui.rows(concept_rows),
                     "Synonyms are combined with OR inside a block, blocks with AND; blue chips are MeSH headings"))
        st.write("")
        st.markdown("##### Final queries")
        st.caption(strategy["rationale"])
        for db, query in strategy["queries"].items():
            with st.expander(f"{DISPLAY_NAME.get(db, db)} · {strategy['hit_counts'].get(db, '?')} hits"):
                st.code(query, language=None, wrap_lines=True)
        with st.expander(f"Every query the agent tested on the live databases ({len(strategy['refinement_log'])})"):
            st.code("\n\n".join(strategy["refinement_log"]), language=None, wrap_lines=True)

# ---- Screening --------------------------------------------------------------
with tabs[3]:
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
             "note": agreement["interpretation"] if agreement else ""},
            {"label": "Conflicts adjudicated", "value": agreement["conflicts"] if agreement else "—",
             "note": f"raw agreement {agreement['raw_agreement']:.0%}" if agreement else ""},
        ]))
        conflicts = [d for d in decisions if d["resolved_by"] != "consensus"]
        if conflicts:
            st.markdown("##### Disagreements and how they were settled")
            for d in conflicts:
                record = records.get(d["rid"], {})
                with st.expander(f"{d['rid']} · {record.get('title', '')[:110]}"):
                    a, b = d["reviewer_a"], d["reviewer_b"]
                    html(f'<div class="badges" style="margin-bottom:10px">{ui.decision_pill(d["final"])}'
                         f'{ui.tag("resolved by " + d["resolved_by"])}</div>')
                    ca, cb = st.columns(2)
                    ca.markdown(f"**Reviewer A** · {a['decision']}  \n{a['rationale']}")
                    cb.markdown(f"**Reviewer B** · {b['decision']}  \n{b['rationale']}")
                    st.markdown(f"**Decision** · {d['final_rationale']}")
        st.markdown("##### All decisions")
        table = pd.DataFrame([{
            "ID": d["rid"], "Title": records.get(d["rid"], {}).get("title", ""), "Final": d["final"], "Resolved by": d["resolved_by"],
            "Reviewer A": d["reviewer_a"]["decision"], "Reviewer B": d["reviewer_b"]["decision"],
            "Exclusion reason": d["exclusion_reason"], "Read from": d["basis"].replace("_", " "),
            "A rationale": d["reviewer_a"]["rationale"], "B rationale": d["reviewer_b"]["rationale"],
        } for d in decisions])
        st.dataframe(table, hide_index=True, width="stretch", height=420,
                     column_config={"Title": st.column_config.TextColumn(width="large")})

# ---- Studies ----------------------------------------------------------------
with tabs[4]:
    if not extractions:
        html(ui.empty("No study has been extracted yet."))
    else:
        for e in extractions:
            record, rob = records[e["rid"]], appraisals.get(e["rid"])
            flags = [i["quote_verified"] for i in e["items"] + e.get("effects", []) if i["quote_verified"] is not None]
            badges = [ui.tag(e["study_design"][:48]), ui.tag("read from " + e["basis"].replace("_", " "))]
            if e["sample_size"].lower() != "not reported":
                badges.append(ui.tag(e["sample_size"][:60]))
            if rob:
                badges.append(ui.rob_pill(rob["overall"]))
            if flags:
                badges.append(ui.pill(f"{sum(flags)}/{len(flags)} quotations verified", "good" if all(flags) else "warn"))
            html(f'<div class="study"><h4>{ui.e(record["title"])}</h4><div class="by">{ui.e(short_ref(record))} · '
                 f'{ui.e(record.get("venue") or "")} · {ui.e(e["rid"])}</div><div class="badges">{"".join(badges)}</div></div>')
            with st.expander("Extracted data, findings and appraisal"):
                st.dataframe(pd.DataFrame([{
                    "Data item": i["field"], "Value": i["value"], "Supporting quotation": i["quote"],
                    "Found in source": {True: "yes", False: "no", None: "—"}[i["quote_verified"]],
                } for i in e["items"]]), hide_index=True, width="stretch",
                    column_config={"Value": st.column_config.TextColumn(width="medium"),
                                   "Supporting quotation": st.column_config.TextColumn(width="large")})
                st.markdown("**Key findings**\n" + "\n".join(f"- {finding}" for finding in e["key_findings"]))
                if rob:
                    st.markdown(f"**Risk of bias · {rob['tool']}** — {rob['overall_justification']}")
                    st.dataframe(pd.DataFrame([{"Domain": d["domain"], "Judgement": d["judgement"], "Justification": d["justification"]}
                                               for d in rob["domains"]]), hide_index=True, width="stretch")

# ---- Report -----------------------------------------------------------------
with tabs[5]:
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
with tabs[6]:
    if not qa:
        html(ui.empty("The Critic agent reviews the manuscript once a draft exists."))
    else:
        checks = qa["checks"]
        quotes = checks.get("extraction_quotes") or {}
        audit_x = checks.get("exclusion_audit") or {}
        html(ui.tiles([
            {"label": "Open issues", "value": len(qa["issues"]), "lead": True,
             "note": f"after {checks.get('round', 1)} critic round{'s' if checks.get('round', 1) != 1 else ''}"},
            {"label": "PRISMA items", "value": f"{checks.get('prisma_items_reported', '—')}/{checks.get('prisma_items_total', '—')}"},
            {"label": "Unsupported claims", "value": checks.get("unsupported_statements", "—"), "note": "not backed by the evidence"},
            {"label": "Quotations verified",
             "value": f"{quotes['verification_rate']:.0%}" if quotes.get("verification_rate") is not None else "—",
             "note": f"{quotes.get('quotes_verified', 0)} of {quotes.get('quotes_checked', 0)}"},
            {"label": "Exclusion audit", "value": f"{audit_x['agreement']:.0%}" if audit_x.get("agreement") is not None else "—",
             "note": f"{audit_x.get('judged', 0)} excluded records re-screened"},
            {"label": "Unknown citations", "value": len(checks.get("unknown_citations") or [])},
        ]))
        if not qa["issues"]:
            html(ui.empty("The critic found no issue."))
        severity_tone = {"critical": "crit", "major": "warn", "minor": "plain"}
        for issue in sorted(qa["issues"], key=lambda i: ["critical", "major", "minor"].index(i["severity"])):
            fix = f'<div class="fix"><b>Suggested fix</b> · {ui.e(issue["suggested_fix"])}</div>' if issue.get("suggested_fix") else ""
            html(f'<div class="issue {issue["severity"]}"><div class="head">'
                 f'{ui.pill(issue["severity"].capitalize(), severity_tone[issue["severity"]])}{ui.tag(issue["area"])}</div>'
                 f'{ui.e(issue["description"])}{fix}</div>')

# ---- Audit trail --------------------------------------------------------------
with tabs[7]:
    if not audit:
        html(ui.empty("Nothing logged yet."))
    else:
        frame = pd.DataFrame([{
            "#": e["seq"], "Time": e["ts"][11:19], "Agent": e["agent"], "Action": e["action"].replace("_", " "),
            "Details": json.dumps({k: v for k, v in e.items() if k not in ("seq", "ts", "agent", "action")},
                                  ensure_ascii=False, default=str)[:400],
        } for e in audit])
        trace = run_dir / "llm_trace.jsonl"
        html(ui.tiles([
            {"label": "Events logged", "value": len(audit), "lead": True},
            {"label": "Agents involved", "value": frame["Agent"].str.split(":").str[0].nunique()},
            {"label": "Model calls traced", "value": sum(1 for _ in trace.open()) if trace.exists() else "—"},
            {"label": "Human decisions", "value": int((frame["Agent"] == "human").sum())},
        ]))
        agents = st.multiselect("Filter by agent", sorted(frame["Agent"].unique()), placeholder="All agents")
        st.dataframe(frame[frame["Agent"].isin(agents)] if agents else frame, hide_index=True, width="stretch", height=520,
                     column_config={"Details": st.column_config.TextColumn(width="large")})
        st.caption("Full prompts and responses of every model call are in llm_trace.jsonl in the run folder.")

# ---- Evaluation ---------------------------------------------------------------
with tabs[8]:
    evaluation = latest(run_dir, "evaluation")
    if evaluation:
        t = evaluation["time"]
        rate = evaluation["accuracy"].get("extraction_quote_verification_rate")
        html(ui.tiles([
            {"label": "Machine time", "value": f"{t['pipeline_hours']:.2f}", "unit": "h", "lead": True, "note": "incl. rate-limit waits"},
            {"label": "Manual effort", "value": f"{t['manual_person_hours_estimate']:.0f}", "unit": "h",
             "note": "person-hours, estimated"},
            {"label": "PRISMA items", "value": evaluation["completeness"]["prisma_items_reported"]},
            {"label": "Quotations verified", "value": f"{rate:.0%}" if rate is not None else "—"},
            {"label": "Agreement, title/abstract", "value": kappa({"cohen_kappa": evaluation["consistency"]["title_abstract_cohen_kappa"]}), "unit": "κ"},
            {"label": "Agreement, full text", "value": kappa({"cohen_kappa": evaluation["consistency"]["full_text_cohen_kappa"]}), "unit": "κ"},
        ]))

        def listing(section: dict) -> str:
            return ui.rows([ui.row("", f'<span class="muted">{ui.e(k.replace("_", " ").capitalize().replace("Prisma", "PRISMA").replace("cohen", "Cohen"))}</span>', f"<b>{ui.e(v)}</b>")
                            for k, v in section.items() if k != "note"])

        c1, c2 = st.columns(2, gap="medium")
        with c1:
            html(ui.card("Completeness", listing(evaluation["completeness"]), "Is everything a PRISMA review needs present?"))
            st.write("")
            html(ui.card("Inter-agent consistency", listing(evaluation["consistency"]), "Do independent agents reach the same decisions?"))
        with c2:
            html(ui.card("Accuracy and grounding", listing(evaluation["accuracy"]), "Is what the agents wrote supported by the sources?"))
            st.write("")
            effort = [{"name": r["Stage"].replace("_", " ").capitalize(), "value": r["Manual estimate (person-hours)"],
                       "label": f"{r['Manual estimate (person-hours)']:g} h", "note": f"pipeline: {r['Pipeline (min)']} min"}
                      for r in evaluation["time_by_stage"]]
            html(ui.card("Estimated manual effort by stage", ui.bars(effort),
                         "Person-hours a manual review would need for the same workload (estimate)"))
        st.caption(t["note"])
    elif job["finished"]:
        html(ui.empty("The evaluation has not been computed for this review."))
        if st.button("Compute the evaluation", type="primary"):
            from sysrev.evaluation.run_metrics import evaluate_run

            evaluate_run(ctx)
            st.rerun()
    else:
        html(ui.empty("Available once the review is finished."))

if job["running"]:
    time.sleep(4)
    st.rerun()
