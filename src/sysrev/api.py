"""HTTP API behind the web interface (web/, Next.js).

    sysrev web            # starts this API and the interface
    sysrev serve          # this API alone, on http://127.0.0.1:8000

The API only listens on the local machine and has no authentication: it is a local tool.
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .config import get_settings
from .context import RunOptions, get_context
from .graph import ORDER, ReviewRunner
from .sources.connectors import DISPLAY_NAME

app = FastAPI(title="PRISMAgent API", docs_url="/api/docs", openapi_url="/api/openapi.json")

STAGES = {
    "protocol": ("Protocol", "agent"), "search_strategy": ("Search", "agent"),
    "review_protocol": ("Approve protocol", "human"), "retrieval": ("Retrieval", "agent"),
    "screen_title_abstract": ("Abstracts", "agent"), "review_screening": ("Check screening", "human"),
    "screen_full_text": ("Full texts", "agent"), "extraction": ("Extraction", "agent"),
    "synthesis": ("Writing", "agent"), "critic": ("Critic", "agent"),
    "review_report": ("Approve report", "human"), "finalize": ("Exports", "agent"),
}
STAGE_LONG = {
    "protocol": "Writing the protocol", "search_strategy": "Designing the search", "retrieval": "Retrieving records",
    "screen_title_abstract": "Screening titles and abstracts", "screen_full_text": "Screening full texts",
    "extraction": "Extracting and appraising", "synthesis": "Writing the manuscript", "critic": "Checking the manuscript",
    "finalize": "Exporting",
}
CHECKPOINT_STAGE = {"protocol": "review_protocol", "screening": "review_screening", "report": "review_report"}
AUDIT_CHECKPOINT_STAGE = {"protocol_and_search": "review_protocol", "screening": "review_screening", "final_report": "review_report"}
DOWNLOADS = {"report.md", "report_draft.md", "report.docx", "references.bib", "prisma_flow.png", "evidence_map.png",
             "evidence_table.csv", "included_studies.csv", "qa_report.md", "evaluation.md"}
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

_jobs: dict[str, dict] = {}
_runners: dict[str, ReviewRunner] = {}
_jobs_lock = threading.Lock()


# --------------------------------------------------------------------------- #
# Runs on disk and background jobs
# --------------------------------------------------------------------------- #


def _run_dir(run_id: str) -> Path:
    """Folder of a run. The id must be the name of an existing run folder (no path tricks)."""
    if not RUN_ID.match(run_id):
        raise HTTPException(404, "Unknown review")
    folder = get_settings().runs_dir / run_id
    if not (folder / "manifest.json").exists():
        raise HTTPException(404, "Unknown review")
    return folder


def _run_ids() -> list[str]:
    folders = get_settings().runs_dir.glob("*/manifest.json")
    return sorted((p.parent.name for p in folders if not p.parent.name.startswith("benchmark-")), reverse=True)


def _launch(run_id: str, resume: dict | None = None) -> None:
    job = {"running": True, "pending": None, "finished": False, "error": None, "elsewhere": False}

    def work() -> None:
        try:
            job["pending"] = ReviewRunner(run_id).advance(resume=resume)
            job["finished"] = job["pending"] is None
        except Exception as exc:  # noqa: BLE001 - shown in the interface; the run can be resumed
            job["error"] = f"{type(exc).__name__}: {exc}"[:600]
        finally:
            job["running"] = False

    with _jobs_lock:
        if _jobs.get(run_id, {}).get("running"):
            raise HTTPException(409, "This review is already running")
        _jobs[run_id] = job
    threading.Thread(target=work, daemon=True).start()


def _active_elsewhere(folder: Path) -> bool:
    """True when another process (the CLI, another interface) is executing this run right now.

    Such a run keeps writing its audit trail. A wait for the model quota is announced with its
    duration, so a silent wait still counts as activity.
    """
    path = folder / "audit.jsonl"
    if not path.exists():
        return False
    tail = path.read_bytes()[-4000:].decode("utf-8", errors="ignore").strip().splitlines()
    try:
        last = json.loads(tail[-1])
        age = time.time() - datetime.fromisoformat(last["ts"]).timestamp()
    except (IndexError, KeyError, ValueError):
        return False
    if last["action"] in ("run_finished", "stage_failed", "checkpoint_requested"):
        return False
    if last["action"] == "llm_rate_limited":
        age -= float(last.get("wait_seconds") or 0)
    return age < 180


def _runner(run_id: str) -> ReviewRunner:
    with _jobs_lock:
        if run_id not in _runners:
            _runners[run_id] = ReviewRunner(run_id)
        return _runners[run_id]


def _job(run_id: str) -> dict:
    """State of a run: the live job if this process runs it, otherwise what its files say."""
    with _jobs_lock:
        live = _jobs.get(run_id)
    if live and (live["running"] or live["error"]):
        return live
    folder = _run_dir(run_id)
    job = {"running": False, "pending": None, "finished": False, "error": None, "elsewhere": False}
    if any(folder.glob("result_v*.json")):  # also true for an exported run, which has no checkpoint database
        job["finished"] = True
    elif (folder / "checkpoints.sqlite").exists():
        runner = _runner(run_id)
        if runner.state():
            job["pending"], job["finished"] = runner.pending(), runner.finished()
        if not job["pending"] and not job["finished"]:
            job["elsewhere"] = _active_elsewhere(folder)  # checked last: a run paused at a checkpoint is not active
    return job


def _latest(folder: Path, name: str) -> Any:
    files = sorted(folder.glob(f"{name}_v*.json"), key=lambda p: int(p.stem.rsplit("_v", 1)[1]))
    return json.loads(files[-1].read_text(encoding="utf-8")) if files else None


def _lines(folder: Path, name: str) -> list[dict]:
    path = folder / f"{name}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def _short_ref(record: dict) -> str:
    authors = record.get("authors") or []
    first = authors[0].split(",")[0].strip() if authors else "Anon"
    return f"{first}{' et al.' if len(authors) > 1 else ''} ({record.get('year') or 'n.d.'})"


def _status(folder: Path, job: dict, audit: list[dict]) -> dict:
    completed = [e["stage"] for e in audit if e["action"] == "stage_completed"]
    completed += [AUDIT_CHECKPOINT_STAGE[e["checkpoint"]] for e in audit
                  if e["action"] == "checkpoint" and e.get("checkpoint") in AUDIT_CHECKPOINT_STAGE]
    started = [e["stage"] for e in audit if e["action"] == "stage_started"]
    current = next((s for s in reversed(started) if started.count(s) > completed.count(s)), None)
    pending = job["pending"] if not job["running"] else None
    if pending:
        current = CHECKPOINT_STAGE.get(pending["checkpoint"], current)

    if job["error"]:
        state, label = "error", "Stopped on an error"
    elif job["running"] or job["elsewhere"]:
        state, label = "running", STAGE_LONG.get(current, "Starting")
    elif pending:
        state, label = "waiting", "Waiting for your review"
    elif job["finished"]:
        state, label = "finished", "Finished"
    else:
        state, label = "paused", "Paused"

    active = state in ("running", "waiting")
    steps = []
    for key in ORDER:
        name, kind = STAGES[key]
        now = active and key == current
        done = (key in completed or state == "finished") and not now
        steps.append({"key": key, "name": name, "kind": kind, "state": "now" if now else ("done" if done else "todo")})

    waits = [e for e in audit[-3:] if e["action"] == "llm_rate_limited" and e.get("wait_seconds", 0) > 60]
    return {"state": state, "label": label, "current": current, "error": job["error"], "steps": steps,
            "waiting_for_quota": bool(waits) and state == "running", "elsewhere": job["elsewhere"]}


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #


@app.get("/api/health")
def health() -> dict:
    settings = get_settings()
    return {"ok": True, "has_key": bool(settings.groq_api_key or settings.llm_provider != "groq"),
            "runs_dir": str(settings.runs_dir)}


@app.get("/api/runs")
def list_runs() -> list[dict]:
    out = []
    for run_id in _run_ids():
        folder = get_settings().runs_dir / run_id
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        job = _job(run_id)
        if job["running"] or job["elsewhere"]:
            state = "running"
        elif job["error"]:
            state = "error"
        elif job["pending"]:
            state = "waiting"
        elif job["finished"]:
            state = "finished"
        else:
            state = "paused"
        flow = _latest(folder, "prisma_flow")
        out.append({"id": run_id, "question": manifest["question"], "created": manifest["created"], "state": state,
                    "included": flow.get("studies_included") if flow and state == "finished" else None})
    return out


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    folder = _run_dir(run_id)
    job = _job(run_id)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    audit = _lines(folder, "audit")
    records = {r["rid"]: r for r in _lines(folder, "records")}
    appraisals = {r["rid"]: r for r in _lines(folder, "risk_of_bias")}

    def decisions(name: str) -> list[dict]:
        return [{
            "rid": d["rid"], "title": records.get(d["rid"], {}).get("title", ""), "final": d["final"],
            "a": d["reviewer_a"]["decision"], "b": d["reviewer_b"]["decision"], "resolved_by": d["resolved_by"],
            "why": d.get("final_rationale") or "", "reason": d.get("exclusion_reason") or "",
            "a_why": d["reviewer_a"].get("rationale", ""), "b_why": d["reviewer_b"].get("rationale", ""),
        } for d in _lines(folder, name)]

    studies = []
    for e in _lines(folder, "extractions"):
        record, rob = records.get(e["rid"], {}), appraisals.get(e["rid"])
        flags = [i["quote_verified"] for i in e["items"] + e.get("effects", []) if i.get("quote_verified") is not None]
        studies.append({
            "rid": e["rid"], "title": record.get("title", e["rid"]), "ref": _short_ref(record), "venue": record.get("venue") or "",
            "url": record.get("url") or (f"https://doi.org/{record['doi']}" if record.get("doi") else ""),
            "design": e.get("study_design") or "", "sample": e.get("sample_size") or "", "basis": e.get("basis") or "",
            "findings": e.get("key_findings") or [],
            "items": [{"field": i["field"], "value": i["value"], "quote": i.get("quote") or "", "verified": i.get("quote_verified")}
                      for i in e["items"]],
            "quotes": {"verified": sum(bool(f) for f in flags), "checked": len(flags)},
            "rob": {"tool": rob["tool"], "overall": rob["overall"], "why": rob.get("overall_justification", ""),
                    "domains": [{"domain": d["domain"], "judgement": d["judgement"], "why": d.get("justification", "")}
                                for d in rob.get("domains", [])]} if rob else None,
        })

    meta = _latest(folder, "manuscript_meta") or {}
    themes = [{"name": t["name"], "studies": len(t.get("study_ids", [])),
               "certainty": (meta.get("syntheses") or {}).get(t["name"], {}).get("certainty")} for t in meta.get("themes") or []]

    report = folder / "report.md" if (folder / "report.md").exists() else folder / "report_draft.md"
    timings = json.loads((folder / "timings.json").read_text()) if (folder / "timings.json").exists() else {}
    strategy = _latest(folder, "search_strategy")
    if strategy:
        strategy["databases"] = [{"key": db, "name": DISPLAY_NAME.get(db, db), "query": query,
                                  "hits": (strategy.get("hit_counts") or {}).get(db)} for db, query in strategy["queries"].items()]
    flow = _latest(folder, "prisma_flow")
    if flow:
        flow["sources"] = [{"name": DISPLAY_NAME.get(k, k), "n": v} for k, v in flow["identified"].items()]

    return {
        "id": run_id,
        "question": manifest["question"],
        "created": manifest["created"],
        "options": manifest["options"],
        "models": manifest["llm"].get("task_models", {}),
        "status": _status(folder, job, audit),
        "pending": job["pending"] if not job["running"] else None,
        "flow": flow,
        "protocol": _latest(folder, "protocol"),
        "strategy": strategy,
        "briefs": (_latest(folder, "plan") or {}).get("briefs") or [],
        "agreement": {"title_abstract": _latest(folder, "agreement_title_abstract"), "full_text": _latest(folder, "agreement_full_text")},
        "screening": {"title_abstract": decisions("screening_title_abstract"), "full_text": decisions("screening_full_text")},
        "studies": studies,
        "themes": themes,
        "qa": _latest(folder, "qa_report"),
        "evaluation": _latest(folder, "evaluation"),
        "timings": [{"key": s, "name": STAGES[s][0], "minutes": round(timings[s] / 60, 1)}
                    for s in ORDER if s in timings and timings[s] >= 1],
        "report": {"file": report.name, "final": report.name == "report.md", "words": len(report.read_text(encoding="utf-8").split())}
                  if report.exists() else None,
        "files": sorted(name for name in DOWNLOADS if (folder / name).exists()),
        "audit_events": len(audit),
    }


@app.get("/api/runs/{run_id}/report")
def get_report(run_id: str) -> dict:
    folder = _run_dir(run_id)
    report = folder / "report.md" if (folder / "report.md").exists() else folder / "report_draft.md"
    if not report.exists():
        raise HTTPException(404, "No manuscript yet")
    return {"markdown": report.read_text(encoding="utf-8")}


@app.get("/api/runs/{run_id}/audit")
def get_audit(run_id: str) -> list[dict]:
    skip = ("seq", "ts", "agent", "action")
    return [{"seq": e["seq"], "time": e["ts"][11:19], "agent": e["agent"], "action": e["action"].replace("_", " "),
             "details": {k: (v if isinstance(v, (int, float, bool)) or v is None else str(v)[:300]) for k, v in e.items() if k not in skip}}
            for e in _lines(_run_dir(run_id), "audit")]


@app.get("/api/runs/{run_id}/files/{name}")
def get_file(run_id: str, name: str) -> FileResponse:
    folder = _run_dir(run_id)
    if name not in DOWNLOADS or not (folder / name).exists():
        raise HTTPException(404, "Unknown file")
    inline = name.endswith(".png")
    return FileResponse(folder / name, filename=None if inline else name)


@app.get("/api/quota")
def quota() -> list[dict]:
    from .llm import DiskCache

    settings = get_settings()
    cache = DiskCache(settings.cache_dir / "llm_cache.sqlite")
    used, left = cache.usage_last_24h(), cache.estimated_available(settings.tokens_per_day)
    tasks = settings.task_models()
    return [{"model": model, "short": model.split("/")[-1], "available": left.get(model, settings.tokens_per_day),
             "per_day": settings.tokens_per_day, "used_24h": used.get(model, {}).get("tokens", 0),
             "tasks": [t for t, m in tasks.items() if m == model]}
            for model in dict.fromkeys([settings.model_primary, settings.model_secondary, settings.model_fast])]


# --------------------------------------------------------------------------- #
# Acting
# --------------------------------------------------------------------------- #


class NewRun(BaseModel):
    question: str = Field(min_length=8, max_length=600)
    auto: bool = False
    max_per_source: int = Field(60, ge=10, le=2000)
    max_screen: int = Field(50, ge=5, le=2000)
    qa_rounds: int = Field(2, ge=0, le=4)
    fulltext_fallback: str = Field("abstract", pattern="^(abstract|exclude)$")


class Decision(BaseModel):
    """Answer to a human checkpoint. Omit `resume` to continue a paused or failed run."""

    resume: dict | None = None


@app.post("/api/runs")
def create_run(body: NewRun) -> dict:
    runner = ReviewRunner.create(body.question.strip(), RunOptions(
        auto_approve=body.auto, max_per_source=body.max_per_source, max_screen=body.max_screen,
        qa_max_rounds=body.qa_rounds, fulltext_fallback=body.fulltext_fallback))
    _launch(runner.run_id)
    return {"id": runner.run_id}


@app.post("/api/runs/{run_id}/advance")
def advance(run_id: str, body: Decision) -> dict:
    folder = _run_dir(run_id)
    job = _job(run_id)
    if any(folder.glob("result_v*.json")) and not (folder / "checkpoints.sqlite").exists():
        raise HTTPException(409, "This review is an exported copy: it can be read but not continued")
    if job["elsewhere"]:
        raise HTTPException(409, "This review is running in another window or terminal")
    if body.resume is not None:
        if not job["pending"]:
            raise HTTPException(409, "This review is not waiting for a decision")
        if body.resume.get("action") not in ("approve", "revise"):
            raise HTTPException(422, "Unknown action")
    elif job["finished"]:
        raise HTTPException(409, "This review is finished")
    _launch(run_id, body.resume)
    return {"ok": True}


@app.post("/api/runs/{run_id}/evaluate")
def evaluate(run_id: str) -> dict:
    from .evaluation.run_metrics import evaluate_run

    _run_dir(run_id)
    evaluate_run(get_context(run_id))
    return {"ok": True}
