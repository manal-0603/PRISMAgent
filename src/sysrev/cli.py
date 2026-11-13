"""Command-line interface.

    sysrev run "research question"          start a review (human checkpoints in the terminal)
    sysrev run "research question" --auto   fully autonomous run
    sysrev resume RUN_ID                    continue an interrupted run
    sysrev list                             list runs
    sysrev status RUN_ID                    show progress and headline numbers
    sysrev evaluate RUN_ID                  evaluation report of a finished run
    sysrev benchmark                        screening accuracy against human labels (SYNERGY)
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

import typer

# Keep the terminal readable: third-party libraries log every HTTP request at INFO level.
logging.basicConfig(level=logging.WARNING)
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import get_settings
from .context import RunOptions, get_context

app = typer.Typer(add_completion=False, help="Agentic pipeline for PRISMA 2020 systematic reviews.")
console = Console()

STAGE_LABELS = {
    "protocol": "Protocol written (Planner agent)",
    "search_strategy": "Search strategy designed and tested (Search Strategy agent)",
    "review_protocol": "Checkpoint 1: protocol and search strategy",
    "retrieval": "Records retrieved, de-duplicated and indexed (Retrieval agent)",
    "screen_title_abstract": "Title/abstract screening (two reviewers + adjudicator)",
    "review_screening": "Checkpoint 2: screening decisions",
    "screen_full_text": "Full-text retrieval and screening",
    "extraction": "Data extraction and risk-of-bias appraisal",
    "synthesis": "Synthesis and manuscript (Writing agent)",
    "critic": "Quality assurance (Critic agent)",
    "review_report": "Checkpoint 3: final report",
    "finalize": "Exports written",
}
SUMMARY_KEY = {
    "protocol": "protocol", "search_strategy": "search", "retrieval": "retrieval",
    "screen_title_abstract": "title_abstract", "screen_full_text": "full_text", "extraction": "extraction",
    "synthesis": "manuscript", "critic": "qa",
}


def _on_update(node: str, summary: dict) -> None:
    detail = summary.get(SUMMARY_KEY.get(node, ""), "")
    console.print(f"[green]✓[/green] {STAGE_LABELS.get(node, node)}" + (f"  [dim]{detail}[/dim]" if detail else ""))


# --------------------------------------------------------------------------- #
# Human checkpoints in the terminal
# --------------------------------------------------------------------------- #


def _checkpoint_protocol(payload: dict, run_dir: Path) -> dict:
    p, s = payload["protocol"], payload["search_strategy"]
    body = [f"[bold]{p['title']}[/bold]", f"Question: {p['research_question']}", f"Framework: {p['framework']}"]
    body += [f"  {k}: {v}" for k, v in p["framework_elements"].items()]
    body += ["Inclusion criteria:"] + [f"  {c['id']}. {c['text']}" for c in p["inclusion_criteria"]]
    body += ["Exclusion criteria:"] + [f"  {c['id']}. {c['text']}" for c in p["exclusion_criteria"]]
    body += [f"Designs: {', '.join(p['study_designs'])}", f"Years: {p['date_from'] or 'any'} - {p['date_to'] or 'present'}"]
    console.print(Panel("\n".join(body), title="Checkpoint 1 — protocol", border_style="cyan"))
    table = Table(title="Search strategy", show_lines=True)
    table.add_column("Database"), table.add_column("Hits", justify="right"), table.add_column("Query")
    for db, query in s["queries"].items():
        table.add_row(db, str(s["hit_counts"].get(db, "?")), query)
    console.print(table)
    choice = typer.prompt("[a]pprove, [r]equest changes, [e]dit the protocol file", default="a").strip().lower()
    if choice.startswith("r"):
        return {"action": "revise", "feedback": typer.prompt("What should change?")}
    if choice.startswith("e"):
        file = run_dir / "protocol_edit.json"
        file.write_text(json.dumps(p, indent=2, ensure_ascii=False), encoding="utf-8")
        typer.prompt(f"Edit {file} then press Enter", default="", show_default=False)
        return {"action": "approve", "protocol": json.loads(file.read_text(encoding="utf-8"))}
    return {"action": "approve"}


def _checkpoint_screening(payload: dict, run_dir: Path) -> dict:
    agreement = payload["agreement"]
    console.print(Panel(
        f"Screened: {agreement['n']}   Conflicts: {agreement['conflicts']}   "
        f"Cohen's kappa: {agreement['cohen_kappa']} ({agreement['interpretation']})",
        title="Checkpoint 2 — title/abstract screening", border_style="cyan"))
    table = Table(show_lines=False)
    for col in ("ID", "Final", "A", "B", "Resolved by", "Title"):
        table.add_column(col)
    shown = [d for d in payload["decisions"] if d["final"] == "include" or d["resolved_by"] != "consensus"]
    for d in shown[:60]:
        colour = "green" if d["final"] == "include" else "red"
        table.add_row(d["rid"], f"[{colour}]{d['final']}[/{colour}]", d["a"], d["b"], d["resolved_by"], d["title"][:80])
    console.print(table)
    console.print(f"[dim]Retained and adjudicated records are shown; all decisions with rationales: {run_dir / 'screening_title_abstract.jsonl'}[/dim]")
    text = typer.prompt("Press Enter to approve, or type overrides like R0012=include,R0040=exclude", default="", show_default=False)
    overrides = {}
    for part in text.split(","):
        if "=" in part:
            rid, value = (x.strip() for x in part.split("=", 1))
            if value in ("include", "exclude"):
                overrides[rid.upper()] = value
    return {"action": "approve", "overrides": overrides}


def _checkpoint_report(payload: dict, run_dir: Path) -> dict:
    qa = payload["qa_report"]
    from .agents.critic import verdict_label

    lines = [f"Verdict of the Critic agent: {verdict_label(qa['verdict'], qa['issues'])}", f"Issues: {len(qa['issues'])}"]
    lines += [f"  [{i['severity']}] ({i['area']}) {i['description'][:160]}" for i in qa["issues"][:12]]
    lines.append(f"Draft: {payload['draft_file']}")
    console.print(Panel("\n".join(lines), title="Checkpoint 3 — manuscript", border_style="cyan"))
    choice = typer.prompt("[a]pprove or [r]equest a revision", default="a").strip().lower()
    if choice.startswith("r"):
        return {"action": "revise", "feedback": typer.prompt("What should change?")}
    return {"action": "approve"}


CHECKPOINTS = {"protocol": _checkpoint_protocol, "screening": _checkpoint_screening, "report": _checkpoint_report}


def _drive(run_id: str) -> None:
    from .graph import ReviewRunner

    runner = ReviewRunner(run_id)
    pending = runner.pending() if runner.state() else None
    resume = CHECKPOINTS[pending["checkpoint"]](pending, runner.ctx.run_dir) if pending else None
    while True:
        pending = runner.advance(resume=resume, on_update=_on_update)
        if pending is None:
            break
        resume = CHECKPOINTS[pending["checkpoint"]](pending, runner.ctx.run_dir)
    _print_result(run_id)


def _print_result(run_id: str) -> None:
    ctx = get_context(run_id)
    if not ctx.store.exists("result"):
        console.print("[yellow]The run is not finished.[/yellow]")
        return
    result = ctx.store.load("result")
    flow = result["flow"]
    console.print(Panel(
        f"Records identified: {sum(flow['identified'].values())}   screened: {flow['records_screened']}   "
        f"full-text assessed: {flow['reports_assessed']}   included: {flow['studies_included']}\n"
        f"Kappa title/abstract: {result['agreement_title_abstract']['cohen_kappa']}   "
        f"PRISMA items reported: {result['prisma_items_reported']}/{result['prisma_items_total']}   "
        f"Critic: {len(ctx.store.load('qa_report')['issues'])} issue(s) open after {result['qa'].get('round', 1)} round(s)\n"
        f"Pipeline time: {sum(result['timings_seconds'].values()) / 60:.1f} min\n\n"
        f"Report:  {ctx.run_dir / 'report.md'}\n         {ctx.run_dir / 'report.docx'}\n"
        f"Audit:   {ctx.run_dir / 'audit.jsonl'}",
        title=f"Review finished — {run_id}", border_style="green"))


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


@app.command()
def run(
    question: str = typer.Argument(..., help="Research question or topic"),
    auto: bool = typer.Option(False, "--auto", help="Autonomous mode: auto-approve the human checkpoints"),
    max_per_source: int = typer.Option(60, help="Records fetched per database"),
    max_screen: int = typer.Option(50, help="Maximum records sent to screening (relevance-ranked)"),
    qa_rounds: int = typer.Option(2, help="Maximum critic -> writer revision rounds"),
    databases: Optional[str] = typer.Option(None, help="Comma-separated override, e.g. pubmed,openalex"),
    fulltext_fallback: str = typer.Option("abstract", help="'abstract' or 'exclude' when no open full text exists"),
    template: str = typer.Option("config/protocol_template.yaml", help="Protocol template file"),
) -> None:
    """Start a new systematic review."""
    from .graph import ReviewRunner

    options = RunOptions(
        auto_approve=auto, max_per_source=max_per_source, max_screen=max_screen, fulltext_fallback=fulltext_fallback,
        qa_max_rounds=qa_rounds,
        databases=[d.strip() for d in databases.split(",")] if databases else None, protocol_template=template,
    )
    runner = ReviewRunner.create(question, options)
    console.print(f"Run [bold]{runner.run_id}[/bold] — artifacts in {runner.ctx.run_dir}")
    _drive(runner.run_id)


@app.command()
def resume(run_id: str, auto: Optional[bool] = typer.Option(None, "--auto/--interactive", help="Change the oversight mode")) -> None:
    """Continue a run that was interrupted (checkpoint, crash, rate limit)."""
    ctx = get_context(run_id)
    if not ctx.manifest_path.exists():
        raise typer.BadParameter(f"Unknown run '{run_id}'")
    if auto is not None:
        manifest = ctx.manifest
        manifest["options"]["auto_approve"] = auto
        ctx.manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    _drive(run_id)


@app.command()
def revise(run_id: str) -> None:
    """Send a finished run back to the writer with the issues the Critic left open (e.g. after a quota stop)."""
    from .graph import ReviewRunner

    runner = ReviewRunner(run_id)
    if not runner.finished():
        raise typer.BadParameter("This run is not finished; use `sysrev resume` instead.")
    n = runner.reopen_for_revision()
    if not n:
        console.print("The Critic left no open issue for the writer; nothing to revise.")
        return
    console.print(f"Reopened with {n} issue(s) for the Writing agent.")
    _drive(run_id)


@app.command()
def rebuild(run_id: str) -> None:
    """Regenerate report.md, report.docx and the other exports of a finished run without new model calls."""
    from .graph import ReviewRunner

    ReviewRunner(run_id).rebuild_outputs()
    _print_result(run_id)


EXPORT_SKIP = ("chroma", "fulltext", "checkpoints.sqlite", "protocol_edit.json")


@app.command()
def export(run_id: str, dest: Path) -> None:
    """Copy the shareable artifacts of a run to DEST (no index, no full texts, identifiers scrubbed)."""
    import shutil

    from .llm import scrub

    source = get_context(run_id).run_dir
    dest.mkdir(parents=True, exist_ok=True)
    copied = 0
    for file in sorted(source.iterdir()):
        if file.is_dir() or file.name.startswith(EXPORT_SKIP):
            continue
        if file.suffix in (".json", ".jsonl", ".md", ".csv", ".bib", ".mmd"):
            (dest / file.name).write_text(scrub(file.read_text(encoding="utf-8")), encoding="utf-8")
        else:
            shutil.copy2(file, dest / file.name)
        copied += 1
    console.print(f"{copied} files copied to {dest}")


@app.command("list")
def list_runs() -> None:
    """List the runs stored in the runs directory."""
    table = Table()
    for col in ("Run id", "Question", "Finished"):
        table.add_column(col)
    for folder in sorted(get_settings().runs_dir.iterdir()):
        manifest = folder / "manifest.json"
        if manifest.exists():
            data = json.loads(manifest.read_text())
            table.add_row(folder.name, data["question"][:70], "yes" if list(folder.glob("result_v*.json")) else "no")
    console.print(table)


@app.command()
def status(run_id: str) -> None:
    """Show the progress of a run."""
    from .graph import ReviewRunner

    runner = ReviewRunner(run_id)
    state = runner.state()
    console.print(f"Completed stages: {', '.join(state.get('done', [])) or 'none'}")
    console.print_json(json.dumps(state.get("summary", {}), default=str))
    pending = runner.pending()
    if pending:
        console.print(f"[cyan]Waiting for human review at checkpoint '{pending['checkpoint']}'. Use: sysrev resume {run_id}[/cyan]")
    _print_result(run_id)


@app.command()
def evaluate(
    run_id: str,
    gold: Optional[Path] = typer.Option(None, help="Text file listing known relevant studies (one DOI or title per line)"),
) -> None:
    """Write the evaluation report of a finished run (completeness, consistency, time savings)."""
    from .evaluation.run_metrics import evaluate_run

    path = evaluate_run(get_context(run_id), gold)
    console.print(f"Evaluation written to {path}")


@app.command()
def quota() -> None:
    """Show the tokens and requests sent to the LLM provider over the last 24 hours."""
    from .llm import DiskCache

    settings = get_settings()
    cache = DiskCache(settings.cache_dir / "llm_cache.sqlite")
    used, left = cache.usage_last_24h(), cache.estimated_available(settings.tokens_per_day)
    table = Table(title="LLM quota per model")
    for col in ("Model", "Available now (estimate)", "Used in the last 24 h", "Requests", "Tasks"):
        table.add_column(col)
    tasks = settings.task_models()
    for model in dict.fromkeys([settings.model_primary, settings.model_secondary, settings.model_fast, *used]):
        row = used.get(model, {"requests": 0, "tokens": 0})
        available = left.get(model, settings.tokens_per_day)
        table.add_row(model, f"{available:,} of {settings.tokens_per_day:,}", f"{row['tokens']:,}", str(row["requests"]),
                      ", ".join(t for t, m in tasks.items() if m == model))
    console.print(table)
    console.print(
        "[dim]The provider does not publish the balance: the estimate assumes an allowance of "
        f"{settings.tokens_per_day:,} tokens per model that refills continuously over 24 hours "
        "(Groq free tier; see console.groq.com/settings/limits).[/dim]"
    )


@app.command()
def benchmark(
    dataset: str = typer.Option("", help="SYNERGY dataset name (empty = list the datasets)"),
    n: int = typer.Option(100, help="Number of labelled records to screen"),
    seed: int = typer.Option(13),
) -> None:
    """Measure screening accuracy against human labels from the SYNERGY benchmark."""
    from .evaluation.benchmark import list_datasets, run_benchmark

    if not dataset:
        for name, info in list_datasets().items():
            console.print(f"{name:32s} {info}")
        return
    path = run_benchmark(dataset, n, seed)
    console.print(f"Benchmark report written to {path}")


if __name__ == "__main__":
    app()


@app.command()
def serve(port: int = typer.Option(8000, help="Port of the API"), reload: bool = typer.Option(False, hidden=True)) -> None:
    """Start the HTTP API used by the web interface (local machine only)."""
    import uvicorn

    uvicorn.run("sysrev.api:app", host="127.0.0.1", port=port, reload=reload, log_level="warning")


@app.command()
def web(
    port: int = typer.Option(3000, help="Port of the web interface"),
    api_port: int = typer.Option(8000, help="Port of the API"),
) -> None:
    """Start the web interface: the API and the Next.js application in web/."""
    import os
    import shutil
    import subprocess
    import threading

    import uvicorn

    web_dir = Path(__file__).resolve().parents[2] / "web"
    npm = shutil.which("npm")
    if not npm:
        console.print("[red]Node.js is required for the web interface (https://nodejs.org). The CLI works without it.[/red]")
        raise typer.Exit(1)
    if not (web_dir / "package.json").exists():
        console.print(f"[red]Web application not found in {web_dir}.[/red]")
        raise typer.Exit(1)
    if not (web_dir / "node_modules").exists():
        console.print("Installing the web interface (first start only)…")
        subprocess.run([npm, "install", "--no-audit", "--no-fund"], cwd=web_dir, check=True)

    env = {**os.environ, "SYSREV_API": f"http://127.0.0.1:{api_port}", "PORT": str(port), "NEXT_TELEMETRY_DISABLED": "1"}
    front = subprocess.Popen([npm, "run", "dev", "--", "--port", str(port)], cwd=web_dir, env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    threading.Timer(2.0, lambda: console.print(f"[green]PRISMAgent is running:[/green] http://localhost:{port}   (Ctrl+C to stop)")).start()
    try:
        uvicorn.run("sysrev.api:app", host="127.0.0.1", port=api_port, log_level="warning")
    finally:
        front.terminate()
