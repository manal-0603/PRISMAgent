"""Retrieval agent.

Executes the approved searches, de-duplicates, applies the protocol's date limits,
builds the RAG index over titles/abstracts and — when more records come back than
the screening budget allows — ranks them by hybrid relevance to the review question
and keeps the best ones. Records dropped that way are counted, as PRISMA 2020
requires, under "records marked as ineligible by automation tools".

Later in the review the same agent fetches open-access full texts and adds them to
the index (`fetch_fulltexts`).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from ..context import RunContext
from ..models import Protocol, Record, SearchStrategy
from ..sources.connectors import run_search
from ..sources.fulltext import fetch_fulltext
from ..sources.http import SourceError
from ..tools.dedup import deduplicate
from ..tools.prisma import PrismaFlow

AGENT = "retrieval"


def relevance_query(protocol: Protocol) -> str:
    return protocol.research_question + " " + " ".join(protocol.framework_elements.values())


def run_retrieval(ctx: RunContext, protocol: Protocol, strategy: SearchStrategy) -> PrismaFlow:
    opts = ctx.options
    raw: list[Record] = []
    identified: dict[str, int] = {}
    errors: dict[str, str] = {}

    def search(db: str) -> tuple[str, list[Record], str]:
        try:
            return db, run_search(db, strategy.queries[db], opts.max_per_source, ctx.settings), ""
        except (SourceError, Exception) as exc:  # noqa: BLE001 - one failing source must not stop the review
            return db, [], f"{type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=len(strategy.queries) or 1) as pool:
        for db, records, error in pool.map(search, list(strategy.queries)):
            identified[db] = len(records)
            raw.extend(records)
            if error:
                errors[db] = error
            ctx.audit.log(
                AGENT, "search_executed", database=db, query=strategy.queries[db], retrieved=len(records),
                total_hits=strategy.hit_counts.get(db), error=error,
            )
    ctx.store.save_lines("records_raw", raw, agent=AGENT)
    ctx.store.save("search_log", {"identified": identified, "errors": errors, "total_hits": strategy.hit_counts}, agent=AGENT)

    unique, merge_log = deduplicate(raw)
    ctx.store.save_lines("dedup_log", merge_log, agent=AGENT)
    ctx.audit.log(AGENT, "deduplicated", before=len(raw), after=len(unique), duplicates=len(raw) - len(unique))

    removed: list[dict] = []
    kept: list[Record] = []
    for rec in unique:
        too_old = protocol.date_from and rec.year and rec.year < protocol.date_from
        too_new = protocol.date_to and rec.year and rec.year > protocol.date_to
        if too_old or too_new:
            removed.append({"rid": rec.rid, "title": rec.title, "reason": "outside protocol date range", "year": rec.year})
        else:
            kept.append(rec)

    # RAG index over titles + abstracts of every candidate record
    n_chunks = ctx.index.add_many([(r.rid, r.abstract or r.title, "abstract", r.title) for r in kept])
    ctx.audit.log(AGENT, "index_built", documents=len(kept), new_chunks=n_chunks, kind="abstract")

    if len(kept) > opts.max_screen:
        ranked = ctx.index.search(
            relevance_query(protocol), k=len(kept), kind="abstract", fetch_k=len(kept), rerank=False
        )
        order = list(dict.fromkeys(c.rid for c in ranked))
        order += [r.rid for r in kept if r.rid not in set(order)]
        keep_ids = set(order[: opts.max_screen])
        rank_of = {rid: i + 1 for i, rid in enumerate(order)}
        for rec in kept:
            if rec.rid not in keep_ids:
                removed.append(
                    {"rid": rec.rid, "title": rec.title, "reason": "relevance-ranking cap", "rank": rank_of[rec.rid]}
                )
        kept = [r for r in kept if r.rid in keep_ids]
        ctx.audit.log(AGENT, "prioritised", kept=len(kept), cap=opts.max_screen, method="hybrid dense+BM25 rank fusion")

    ctx.store.save_lines("records", unique, agent=AGENT)
    ctx.store.save_lines("removed_before_screening", removed, agent=AGENT)
    ctx.store.save("screening_pool", [r.rid for r in kept], agent=AGENT)

    detail: dict[str, int] = {}
    for row in removed:
        detail[row["reason"]] = detail.get(row["reason"], 0) + 1
    flow = PrismaFlow(
        identified=identified,
        duplicates_removed=len(raw) - len(unique),
        removed_by_automation=len(removed),
        automation_detail=detail,
        records_screened=len(kept),
    )
    ctx.store.save("prisma_flow", flow, agent=AGENT)
    return flow


def load_records(ctx: RunContext) -> dict[str, Record]:
    return {r.rid: r for r in ctx.store.load_lines("records", Record)}


def fetch_fulltexts(ctx: RunContext, records: list[Record]) -> dict[str, str]:
    """Download, parse and index open-access full texts. Returns rid -> provenance."""
    folder = ctx.run_dir / "fulltext"
    folder.mkdir(exist_ok=True)
    provenance: dict[str, str] = {}

    def fetch(rec: Record) -> tuple[Record, str, str]:
        file = folder / f"{rec.rid}.txt"
        if file.exists():
            first, _, body = file.read_text(encoding="utf-8").partition("\n")
            return rec, body, first.removeprefix("# source: ")
        try:
            text, source = fetch_fulltext(rec, ctx.settings)
        except Exception as exc:  # noqa: BLE001 - a broken PDF must not stop the review
            text, source = "", f"not retrieved ({type(exc).__name__})"
        if text:
            file.write_text(f"# source: {source}\n{text}", encoding="utf-8")
        return rec, text, source

    documents = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for rec, text, source in pool.map(fetch, records):
            provenance[rec.rid] = source
            ctx.audit.log(AGENT, "fulltext_fetch", rid=rec.rid, source=source, chars=len(text))
            if text:
                documents.append((rec.rid, text, "fulltext", rec.title))
    n_chunks = ctx.index.add_many(documents)
    ctx.audit.log(AGENT, "index_built", documents=len(documents), new_chunks=n_chunks, kind="fulltext")
    ctx.store.save("fulltext_provenance", provenance, agent=AGENT)
    return provenance


def read_fulltext(ctx: RunContext, rid: str) -> str:
    file = ctx.run_dir / "fulltext" / f"{rid}.txt"
    return file.read_text(encoding="utf-8").partition("\n")[2] if file.exists() else ""
