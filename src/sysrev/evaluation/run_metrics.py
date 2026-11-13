"""Evaluation of one finished review run.

Four families of measures, all computed from the run artifacts:

* completeness   — PRISMA items reported, stages completed, share of data items filled
* accuracy       — grounding of extracted values (verified quotations), citation integrity,
                   statements the Critic found unsupported, optional recall against a gold
                   standard list of studies
* consistency    — agreement between the two independent reviewers (Cohen's kappa), share
                   of conflicts, agreement of the independent exclusion audit
* time           — measured pipeline time per stage against an explicit estimate of the
                   person-time a manual review would need (config/manual_effort.yaml)
"""

from __future__ import annotations

from pathlib import Path

import yaml

from ..context import RunContext
from ..models import Extraction, Record, RiskOfBias, ScreeningDecision
from ..sources.connectors import norm_doi
from ..tools.dedup import norm_title
from ..tools.export import md_table


def manual_effort(flow: dict, n_included: int, path: str = "config/manual_effort.yaml") -> tuple[dict, dict]:
    """Estimated person-hours of a manual review handling the same workload."""
    a = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    reviewers = a["reviewers_per_screening_task"]
    hours = {
        "protocol": a["protocol_hours"],
        "search_strategy": a["search_strategy_hours"],
        "retrieval": a["deduplication_hours"],
        "screen_title_abstract": flow["records_screened"] * a["title_abstract_screening_min_per_record"] * reviewers / 60,
        "screen_full_text": flow["reports_sought"] * a["full_text_retrieval_min_per_report"] / 60
        + flow["reports_assessed"] * a["full_text_screening_min_per_report"] * reviewers / 60,
        "extraction": n_included * (a["data_extraction_min_per_study"] + a["risk_of_bias_min_per_study"]) / 60,
        "synthesis": a["synthesis_and_writing_hours"],
    }
    return {k: round(v, 2) for k, v in hours.items()}, a


def gold_recall(ctx: RunContext, gold_file: Path) -> dict:
    """Recall against a list of studies known to be relevant (one DOI or title per line)."""
    wanted = [line.strip() for line in gold_file.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]
    records = ctx.store.load_lines("records", Record)
    by_doi = {r.doi: r.rid for r in records if r.doi}
    by_title = {norm_title(r.title): r.rid for r in records}
    screened = set(ctx.store.load("screening_pool"))
    ta = {d.rid for d in ctx.store.load_lines("screening_title_abstract", ScreeningDecision) if d.final == "include"}
    included = {d.rid for d in ctx.store.load_lines("screening_full_text", ScreeningDecision) if d.final == "include"}
    rows = []
    for entry in wanted:
        rid = by_doi.get(norm_doi(entry) or "") or by_title.get(norm_title(entry))
        rows.append({
            "gold_study": entry, "rid": rid or "", "retrieved": bool(rid), "screened": rid in screened,
            "kept_at_title_abstract": rid in ta, "included": rid in included,
        })
    n = len(rows) or 1
    return {
        "n_gold": len(rows),
        "search_recall": round(sum(r["retrieved"] for r in rows) / n, 4),
        "recall_after_prioritisation": round(sum(r["screened"] for r in rows) / n, 4),
        "recall_after_title_abstract": round(sum(r["kept_at_title_abstract"] for r in rows) / n, 4),
        "recall_final": round(sum(r["included"] for r in rows) / n, 4),
        "detail": rows,
    }


def evaluate_run(ctx: RunContext, gold_file: Path | None = None) -> Path:
    store = ctx.store
    result = store.load("result")
    flow, qa = result["flow"], result["qa"]
    extractions = store.load_lines("extractions", Extraction)
    appraisals = store.load_lines("risk_of_bias", RiskOfBias)
    n_included = flow["studies_included"]

    items = [i for e in extractions for i in e.items]
    filled = [i for i in items if i.value.strip().lower() not in ("not reported", "")]
    completeness = {
        "prisma_items_reported": f"{result['prisma_items_reported']}/{result['prisma_items_total']}",
        "prisma_flow_arithmetic_consistent": not result["flow_errors"],
        "included_studies_with_extraction": f"{len(extractions)}/{n_included}",
        "included_studies_with_risk_of_bias": f"{len(appraisals)}/{n_included}",
        "data_items_reported_by_studies": f"{len(filled)}/{len(items)}",
        "studies_read_from_full_text": f"{sum(e.basis == 'full_text' for e in extractions)}/{len(extractions)}",
    }
    quotes = qa.get("extraction_quotes") or {}
    first_qa = store.load("qa_report", version=1)
    accuracy = {
        "extraction_quotes_verified_in_source": f"{quotes.get('quotes_verified')}/{quotes.get('quotes_checked')}",
        "extraction_quote_verification_rate": quotes.get("verification_rate"),
        "citations_to_unknown_records_final": len(qa.get("unknown_citations") or []),
        "unsupported_statements_found_by_critic_first_draft": first_qa["checks"].get("unsupported_statements"),
        "unsupported_statements_found_by_critic_final_draft": qa.get("unsupported_statements"),
        "critic_rounds": qa.get("round"),
        "eligibility_audit_flagged_included_studies": len((qa.get("eligibility_audit") or {}).get("flagged") or []),
    }
    ta, ft = result["agreement_title_abstract"], result["agreement_full_text"]
    audit = qa.get("exclusion_audit") or {}
    consistency = {
        "title_abstract_cohen_kappa": ta["cohen_kappa"], "title_abstract_interpretation": ta["interpretation"],
        "title_abstract_raw_agreement": ta["raw_agreement"], "title_abstract_conflicts": f"{ta['conflicts']}/{ta['n']}",
        "full_text_cohen_kappa": ft["cohen_kappa"], "full_text_interpretation": ft["interpretation"],
        "full_text_raw_agreement": ft["raw_agreement"], "full_text_conflicts": f"{ft['conflicts']}/{ft['n']}",
        "exclusion_audit_agreement": audit.get("agreement"),
        "exclusion_audit_sample": audit.get("judged"),
    }

    timings = result["timings_seconds"]
    manual, assumptions = manual_effort(flow, n_included)
    rows = []
    for stage, hours in manual.items():
        seconds = timings.get(stage, 0) + (timings.get("critic", 0) + timings.get("finalize", 0) if stage == "synthesis" else 0)
        rows.append({"Stage": stage, "Pipeline (min)": round(seconds / 60, 1), "Manual estimate (person-hours)": hours})
    pipeline_hours = sum(timings.values()) / 3600
    manual_hours = sum(manual.values())
    per_item = sum(manual[k] for k in ("screen_title_abstract", "screen_full_text", "extraction"))
    per_item_pipeline = sum(timings.get(k, 0) for k in ("screen_title_abstract", "screen_full_text", "extraction")) / 3600
    time_savings = {
        "pipeline_hours": round(pipeline_hours, 2),
        "manual_person_hours_estimate": round(manual_hours, 1),
        "reduction_all_tasks": round(1 - pipeline_hours / manual_hours, 4) if manual_hours else None,
        "per_item_tasks_manual_person_hours": round(per_item, 1),
        "per_item_tasks_pipeline_hours": round(per_item_pipeline, 2),
        "reduction_per_item_tasks": round(1 - per_item_pipeline / per_item, 4) if per_item else None,
        "note": "Pipeline time is machine wall-clock time, dominated by API rate limits; it excludes human checkpoint time. "
                "Manual figures are estimates from config/manual_effort.yaml, not measurements.",
    }
    usage = result["llm_usage"]
    recall = gold_recall(ctx, gold_file) if gold_file else None

    evaluation = {
        "run_id": ctx.run_id, "completeness": completeness, "accuracy": accuracy, "consistency": consistency,
        "time": time_savings, "time_by_stage": rows, "manual_effort_assumptions": assumptions, "llm_usage": usage,
        "gold_standard_recall": recall,
    }
    store.save("evaluation", evaluation, agent="evaluation")

    def bullet(section: dict) -> str:
        return "\n".join(f"- **{k.replace('_', ' ')}**: {v}" for k, v in section.items())

    md = [
        f"# Evaluation of run `{ctx.run_id}`", "", f"Question: {result['question']}", "",
        "## Completeness", bullet(completeness), "",
        "## Accuracy and grounding", bullet(accuracy), "",
        "## Inter-agent consistency", bullet(consistency), "",
        "## Time", bullet(time_savings), "", md_table(rows), "",
        "Manual-effort assumptions (edit `config/manual_effort.yaml`):", "",
        "\n".join(f"- {k}: {v}" for k, v in assumptions.items()), "",
        "## LLM usage", md_table([{"model": m, **u} for m, u in usage.items()]), "",
    ]
    if recall:
        md += ["## Recall against the gold-standard list", bullet({k: v for k, v in recall.items() if k != "detail"}), "",
               md_table(recall["detail"]), ""]
    return store.write_text("evaluation.md", "\n".join(md), agent="evaluation")
