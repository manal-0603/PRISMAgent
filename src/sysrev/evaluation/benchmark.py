"""Screening accuracy against human decisions (SYNERGY / ASReview benchmark datasets).

Each dataset is the labelled record set of a published systematic review: for every
record, whether the human reviewers kept it after title/abstract screening and
whether it was finally included. The benchmark:

1. gives the Planner agent only the published review's title and abstract and lets
   it write the protocol (the agents never see a label);
2. draws a stratified random sample of labelled records (the records humans kept are
   over-sampled, otherwise a sample of 100 would contain one or two of them);
3. runs the same dual-reviewer + adjudicator screening as a real review;
4. reports sensitivity, specificity, kappa between the AI reviewers, kappa against
   the humans, and precision re-weighted to the true prevalence of the dataset.

Datasets: https://github.com/asreview/synergy-dataset (index.json), CC-BY licences.
"""

from __future__ import annotations

import csv
import io
import json
import random
import time
from pathlib import Path

from ..agents import planner, screening
from ..config import get_settings
from ..context import RunOptions, get_context
from ..models import Record
from ..sources.connectors import EPMC, norm_doi
from ..sources.http import SourceError, get_json, get_text
from ..tools.export import md_table
from ..tools.stats import classification_metrics, cohen_kappa, kappa_label

INDEX_URL = "https://raw.githubusercontent.com/asreview/synergy-dataset/master/index.json"


def list_datasets() -> dict[str, str]:
    index = json.loads(get_text(INDEX_URL, cache_dir=get_settings().cache_dir))
    return {name: f"{meta['year']}  {meta['title'][:90]}" for name, meta in index.items()}


def _review_abstract(doi_url: str) -> str:
    doi = norm_doi(doi_url)
    if not doi or not doi.startswith("10."):
        return ""
    try:
        data = get_json(f"{EPMC}/search", {"query": f'DOI:"{doi}"', "format": "json", "resultType": "core", "pageSize": 1},
                        cache_dir=get_settings().cache_dir)
    except SourceError:
        return ""
    results = data.get("resultList", {}).get("result", [])
    return results[0].get("abstractText", "") if results else ""


def run_benchmark(dataset: str, n: int = 100, seed: int = 13, positive_share: float = 0.35) -> Path:
    settings = get_settings()
    index = json.loads(get_text(INDEX_URL, cache_dir=settings.cache_dir))
    if dataset not in index:
        raise ValueError(f"Unknown dataset '{dataset}'. Run `sysrev benchmark` to list them.")
    meta = index[dataset]
    csv.field_size_limit(10**9)
    rows = list(csv.DictReader(io.StringIO(get_text(meta["url"], cache_dir=settings.cache_dir, timeout=180))))
    rows = [r for r in rows if (r.get("abstract") or "").strip() and (r.get("title") or "").strip()]
    reference = "label_abstract_screening" if any(r.get("label_abstract_screening") in ("1", "1.0") for r in rows) else "label_included"

    def flag(row: dict, key: str) -> bool:
        return str(row.get(key, "")).strip() in ("1", "1.0")

    rng = random.Random(seed)
    positives = [r for r in rows if flag(r, reference)]
    negatives = [r for r in rows if not flag(r, reference)]
    n_pos = min(len(positives), round(n * positive_share))
    sample = rng.sample(positives, n_pos) + rng.sample(negatives, min(len(negatives), n - n_pos))
    rng.shuffle(sample)

    run_id = f"benchmark-{dataset}-n{len(sample)}-seed{seed}"
    ctx = get_context(run_id)
    review_abstract = _review_abstract(meta["reference"])
    question = (
        f"Replicate the eligibility criteria of this published systematic review.\nTitle: {meta['title']}\n"
        + (f"Abstract of the review: {review_abstract}" if review_abstract else "")
    )
    if not ctx.manifest_path.exists():
        ctx.init_manifest(question, RunOptions(auto_approve=True, seed=seed))
    started = time.perf_counter()
    protocol = planner.generate_protocol(ctx, question)
    plan = planner.make_plan(ctx, protocol)
    records = [
        Record(rid=f"R{i:04d}", title=row["title"], abstract=row["abstract"], year=int(float(row["year"])) if row.get("year") else None)
        for i, row in enumerate(sample, start=1)
    ]
    decisions = screening.screen_title_abstract(ctx, protocol, records, plan)
    seconds = time.perf_counter() - started

    truth = [flag(row, reference) for row in sample]
    final_included = [flag(row, "label_included") for row in sample]
    ai_final = [d.final == "include" for d in decisions]
    ai_a = [d.reviewer_a.decision != "exclude" for d in decisions]
    ai_b = [d.reviewer_b.decision != "exclude" for d in decisions]

    def metrics(pred: list[bool]) -> dict:
        m = classification_metrics(pred, truth)
        kappa = cohen_kappa(["i" if p else "e" for p in pred], ["i" if t else "e" for t in truth])
        m["kappa_vs_humans"] = round(kappa, 4) if kappa is not None else None
        prevalence = len(positives) / len(rows)
        sens, spec = m["recall_sensitivity"], m["specificity"]
        if sens is not None and spec is not None:
            denominator = sens * prevalence + (1 - spec) * (1 - prevalence)
            m["precision_at_dataset_prevalence"] = round(sens * prevalence / denominator, 4) if denominator else None
            # share of the full dataset a human would no longer need to read
            m["workload_reduction_at_dataset_prevalence"] = round(1 - denominator, 4)
        return m

    final_found = sum(a and f for a, f in zip(ai_final, final_included))
    kappa_ab = cohen_kappa(["i" if p else "e" for p in ai_a], ["i" if p else "e" for p in ai_b])
    report = {
        "dataset": dataset, "review_title": meta["title"], "review_reference": meta["reference"],
        "dataset_records_with_abstract": len(rows), "dataset_prevalence": round(len(positives) / len(rows), 4),
        "reference_label": reference, "sample_size": len(sample), "sample_positives": sum(truth), "seed": seed,
        "screening_prompt_version": screening.SCREENING_PROMPT_VERSION,
        "models": {task: settings.task_model(task) for task in ("planner", "reviewer_a", "reviewer_b", "adjudicator")},
        "pipeline_final": metrics(ai_final), "reviewer_a_alone": metrics(ai_a), "reviewer_b_alone": metrics(ai_b),
        "kappa_between_ai_reviewers": round(kappa_ab, 4) if kappa_ab is not None else None,
        "kappa_between_ai_reviewers_label": kappa_label(kappa_ab),
        "conflicts_sent_to_adjudicator": sum(not d.agreed for d in decisions),
        "full_text_only_criteria": sorted(planner.full_text_only_ids(protocol)),
        "exclusions_blocked_by_guard": ctx.store.load("agreement_title_abstract").get("exclusions_blocked_by_guard", 0),
        "finally_included_studies_in_sample": sum(final_included),
        "finally_included_studies_kept_by_pipeline": final_found,
        "seconds": round(seconds, 1), "seconds_per_record": round(seconds / len(sample), 2),
    }
    errors = [
        {"rid": d.rid, "human": "keep" if t else "exclude", "pipeline": d.final, "finally_included": f,
         "title": rec.title[:110], "rationale": d.final_rationale[:300]}
        for d, t, f, rec in zip(decisions, truth, final_included, records) if (d.final == "include") != t
    ]
    ctx.store.save("benchmark_report", report, agent="evaluation")
    ctx.store.save_lines("benchmark_disagreements", errors, agent="evaluation")

    def row(name: str, m: dict) -> dict:
        return {"Screener": name, "Sensitivity": m["recall_sensitivity"], "Specificity": m["specificity"],
                "Precision (sample)": m["precision"], "F1": m["f1"], "Kappa vs humans": m["kappa_vs_humans"],
                "TP": m["tp"], "FP": m["fp"], "FN": m["fn"], "TN": m["tn"]}

    final = report["pipeline_final"]
    md = [
        f"# Screening benchmark — {dataset}", "",
        f"Review: *{meta['title']}* ({meta['reference']})", "",
        f"- Records with an abstract in the dataset: {len(rows)}; kept by the human reviewers at title/abstract stage: "
        f"{len(positives)} ({len(positives) / len(rows):.1%})",
        f"- Stratified sample screened by the pipeline: {len(sample)} records ({sum(truth)} human-kept, {len(sample) - sum(truth)} human-excluded), seed {seed}",
        f"- Reference standard: `{reference}`. The agents received only the review's title and abstract. "
        f"Screening prompt {screening.SCREENING_PROMPT_VERSION}.", "",
        md_table([row("Pipeline (A + B + adjudicator)", final), row(f"Reviewer A alone ({settings.task_model('reviewer_a')})", report["reviewer_a_alone"]),
                  row(f"Reviewer B alone ({settings.task_model('reviewer_b')})", report["reviewer_b_alone"])]), "",
        f"Adjudicator: {settings.task_model('adjudicator')}. Protocol written by: {settings.task_model('planner')}.", "",
        f"- Agreement between the two AI reviewers: kappa = {report['kappa_between_ai_reviewers']} "
        f"({report['kappa_between_ai_reviewers_label']}); {report['conflicts_sent_to_adjudicator']} conflicts adjudicated",
        f"- Criteria the planner marked as full-text only: {', '.join(report['full_text_only_criteria']) or 'none'}; "
        f"exclusion votes converted to 'unsure' by the code guard: {report['exclusions_blocked_by_guard']}",
        f"- Studies finally included in the published review that were in the sample: {sum(final_included)}; kept by the pipeline: {final_found}",
        f"- Precision re-weighted to the dataset prevalence: {final.get('precision_at_dataset_prevalence')}; "
        f"share of records a human would not need to read: {final.get('workload_reduction_at_dataset_prevalence')}",
        f"- Time: {seconds / 60:.1f} min for {len(sample)} records ({seconds / len(sample):.1f} s per record, including API rate-limit waits; cached calls are instantaneous)", "",
        "Precision in the sample is inflated by over-sampling of human-kept records; use the re-weighted value.", "",
        "## Disagreements with the human reviewers", "",
        md_table(errors, ["rid", "human", "pipeline", "finally_included", "title", "rationale"]) if errors else "None.", "",
    ]
    return ctx.store.write_text("benchmark_report.md", "\n".join(md), agent="evaluation")
