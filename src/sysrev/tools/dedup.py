"""Deterministic de-duplication of records retrieved from several databases.

Matching cascade (first hit wins), each merge is logged with its reason:

1. identical DOI
2. identical PubMed id
3. identical arXiv id
4. identical normalised title
5. fuzzy title match (>= 95 % similarity) with publication years at most one apart
   and the same numbers in both titles (so "part 1" and "part 2" stay separate)
"""

from __future__ import annotations

import re
import unicodedata

from rapidfuzz import fuzz

from ..models import Record


def norm_title(title: str) -> str:
    text = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text)).strip()


def _merge(keep: Record, other: Record) -> Record:
    """Fill the gaps of `keep` with `other`, keeping the richest abstract."""
    data = keep.model_dump()
    for key, value in other.model_dump().items():
        if key == "sources":
            data["sources"] = sorted(set(data["sources"]) | set(value))
        elif key == "abstract":
            if len(value or "") > len(data["abstract"] or ""):
                data["abstract"] = value
        elif key == "authors":
            if not data["authors"]:
                data["authors"] = value
        elif key == "doi":
            # prefer the journal DOI over an arXiv/preprint DOI
            if value and (not data["doi"] or "arxiv" in data["doi"]) and "arxiv" not in value:
                data["doi"] = value
            elif value and not data["doi"]:
                data["doi"] = value
        elif data.get(key) in (None, "", []) and value not in (None, "", []):
            data[key] = value
    return Record.model_validate(data)


def deduplicate(records: list[Record], fuzzy_threshold: float = 95.0) -> tuple[list[Record], list[dict]]:
    """Return (unique records with ids R0001…, merge log)."""
    unique: list[Record] = []
    by_doi: dict[str, int] = {}
    by_pmid: dict[str, int] = {}
    by_arxiv: dict[str, int] = {}
    by_title: dict[str, int] = {}
    log: list[dict] = []

    def index(rec: Record, pos: int) -> None:
        if rec.doi:
            by_doi[rec.doi] = pos
        if rec.pmid:
            by_pmid[rec.pmid] = pos
        if rec.arxiv_id:
            by_arxiv[rec.arxiv_id] = pos
        title = norm_title(rec.title)
        if title:
            by_title[title] = pos

    for rec in records:
        title = norm_title(rec.title)
        pos, reason = None, ""
        if rec.doi and rec.doi in by_doi:
            pos, reason = by_doi[rec.doi], "doi"
        elif rec.pmid and rec.pmid in by_pmid:
            pos, reason = by_pmid[rec.pmid], "pmid"
        elif rec.arxiv_id and rec.arxiv_id in by_arxiv:
            pos, reason = by_arxiv[rec.arxiv_id], "arxiv_id"
        elif title and title in by_title:
            pos, reason = by_title[title], "title_exact"
        elif len(title) >= 25:
            for i, other in enumerate(unique):
                if rec.year and other.year and abs(rec.year - other.year) > 1:
                    continue
                other_title = norm_title(other.title)
                if abs(len(other_title) - len(title)) > 12:
                    continue
                # "… part 1" / "… part 2", "phase 2" / "phase 3": different numbers = different reports
                if re.findall(r"\d+", title) != re.findall(r"\d+", other_title):
                    continue
                if fuzz.ratio(title, other_title) >= fuzzy_threshold:
                    pos, reason = i, "title_fuzzy"
                    break

        if pos is None:
            unique.append(rec)
            index(rec, len(unique) - 1)
        else:
            log.append(
                {
                    "duplicate_title": rec.title,
                    "duplicate_sources": rec.sources,
                    "merged_into_title": unique[pos].title,
                    "reason": reason,
                }
            )
            unique[pos] = _merge(unique[pos], rec)
            index(unique[pos], pos)

    for i, rec in enumerate(unique, start=1):
        rec.rid = f"R{i:04d}"
    return unique, log
