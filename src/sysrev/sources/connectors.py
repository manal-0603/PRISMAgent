"""Connectors to the scholarly databases.

Every connector exposes the same two functions:

* ``count(query)``  -> number of hits (used by the Search Strategy agent to tune queries)
* ``search(query, max_results)`` -> list[Record]

All five work without an API key. Keys / a contact e-mail are only sent when the
user has put them in ``.env``.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Callable

from ..config import Settings
from ..models import Record
from .http import SourceError, get_json, get_text


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def _year(value: object) -> int | None:
    match = re.search(r"(19|20)\d{2}", str(value or ""))
    return int(match.group()) if match else None


_PARTICLES = {"van", "von", "de", "der", "den", "del", "della", "di", "da", "dos", "du", "la", "le", "bin", "ibn", "al", "el", "ter", "ten"}


def last_first(name: str) -> str:
    """'Jane A. van der Smith' -> 'van der Smith, Jane A.' (names already holding a comma are kept)."""
    name = _clean(name)
    parts = name.split()
    if "," in name or len(parts) < 2:
        return name
    i = len(parts) - 1
    while i > 1 and parts[i - 1].lower() in _PARTICLES:
        i -= 1
    return f"{' '.join(parts[i:])}, {' '.join(parts[:i])}"


def initials_last(name: str) -> str:
    """Europe PMC style 'Smith JA' -> 'Smith, JA'."""
    name = _clean(name)
    match = re.match(r"^(.*\S)\s+([A-Z][A-Z\-]{0,3})$", name)
    return f"{match.group(1)}, {match.group(2)}" if match else name


def norm_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi.strip(), flags=re.I)
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.I)
    return doi.lower() or None


# --------------------------------------------------------------------------- #
# PubMed (NCBI E-utilities)
# --------------------------------------------------------------------------- #

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def _ncbi_params(s: Settings) -> dict:
    params = {"tool": "sysrev-agents"}
    if s.ncbi_api_key:
        params["api_key"] = s.ncbi_api_key
    if s.contact_email:
        params["email"] = s.contact_email
    return params


def pubmed_count(query: str, s: Settings) -> int:
    data = get_json(
        f"{EUTILS}/esearch.fcgi",
        {"db": "pubmed", "term": query, "retmode": "json", "retmax": 0, **_ncbi_params(s)},
        cache_dir=s.cache_dir,
    )
    return int(data["esearchresult"].get("count", 0))


def pubmed_search(query: str, max_results: int, s: Settings) -> list[Record]:
    data = get_json(
        f"{EUTILS}/esearch.fcgi",
        {
            "db": "pubmed",
            "term": query,
            "retmode": "json",
            "retmax": max_results,
            "sort": "relevance",
            **_ncbi_params(s),
        },
        cache_dir=s.cache_dir,
    )
    ids = data["esearchresult"].get("idlist", [])
    records: list[Record] = []
    for start in range(0, len(ids), 150):
        xml = get_text(
            f"{EUTILS}/efetch.fcgi",
            {"db": "pubmed", "id": ",".join(ids[start : start + 150]), "retmode": "xml", **_ncbi_params(s)},
            cache_dir=s.cache_dir,
        )
        records.extend(_parse_pubmed_xml(xml))
    return records


def _parse_pubmed_xml(xml: str) -> list[Record]:
    out: list[Record] = []
    for art in ET.fromstring(xml).iter("PubmedArticle"):
        title = _clean("".join(art.find(".//ArticleTitle").itertext())) if art.find(".//ArticleTitle") is not None else ""
        parts = []
        for node in art.iter("AbstractText"):
            label = node.get("Label")
            text = _clean("".join(node.itertext()))
            parts.append(f"{label}: {text}" if label else text)
        authors = []
        for author in art.iter("Author"):
            last, fore = author.findtext("LastName"), author.findtext("ForeName")
            if last:
                authors.append(f"{last}, {fore}" if fore else last)
        # only the article's own identifiers (the reference list carries ArticleIds too)
        ids = {
            node.get("IdType"): (node.text or "").strip()
            for node in art.findall("./PubmedData/ArticleIdList/ArticleId")
        }
        year = _year(art.findtext(".//JournalIssue/PubDate/Year")) or _year(
            art.findtext(".//JournalIssue/PubDate/MedlineDate")
        ) or _year(art.findtext(".//ArticleDate/Year"))
        pmid = art.findtext(".//PMID")
        if not title:
            continue
        out.append(
            Record(
                title=title,
                abstract=" ".join(parts),
                authors=authors,
                year=year,
                venue=art.findtext(".//Journal/Title") or "",
                doi=norm_doi(ids.get("doi")),
                pmid=pmid,
                pmcid=ids.get("pmc"),
                url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                pub_type="; ".join(_clean(p.text) for p in art.iter("PublicationType")),
                sources=["pubmed"],
            )
        )
    return out


# --------------------------------------------------------------------------- #
# Europe PMC
# --------------------------------------------------------------------------- #

EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"


def europepmc_count(query: str, s: Settings) -> int:
    data = get_json(
        f"{EPMC}/search",
        {"query": query, "format": "json", "resultType": "idlist", "pageSize": 1},
        cache_dir=s.cache_dir,
    )
    return int(data.get("hitCount", 0))


def europepmc_search(query: str, max_results: int, s: Settings) -> list[Record]:
    records: list[Record] = []
    cursor = "*"
    while len(records) < max_results:
        data = get_json(
            f"{EPMC}/search",
            {
                "query": query,
                "format": "json",
                "resultType": "core",
                "pageSize": min(100, max_results - len(records)),
                "cursorMark": cursor,
            },
            cache_dir=s.cache_dir,
        )
        results = data.get("resultList", {}).get("result", [])
        for item in results:
            if not item.get("title"):
                continue
            pdf = None
            for link in item.get("fullTextUrlList", {}).get("fullTextUrl", []):
                if link.get("documentStyle") == "pdf" and link.get("availabilityCode") in ("OA", "F"):
                    pdf = link.get("url")
                    break
            records.append(
                Record(
                    title=_clean(item["title"]).rstrip("."),
                    abstract=_clean(item.get("abstractText")),
                    authors=[initials_last(a) for a in (item.get("authorString") or "").rstrip(".").split(",") if a.strip()],
                    year=_year(item.get("pubYear")),
                    venue=(item.get("journalInfo", {}).get("journal", {}).get("title"))
                    or item.get("bookOrReportDetails", {}).get("publisher", "")
                    or "",
                    doi=norm_doi(item.get("doi")),
                    pmid=item.get("pmid"),
                    pmcid=item.get("pmcid"),
                    url=f"https://europepmc.org/article/{item.get('source')}/{item.get('id')}",
                    pdf_url=pdf,
                    pub_type="; ".join(item.get("pubTypeList", {}).get("pubType", [])),
                    cited_by=item.get("citedByCount"),
                    sources=["europepmc"],
                )
            )
        next_cursor = data.get("nextCursorMark")
        if not results or not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor
    return records[:max_results]


# --------------------------------------------------------------------------- #
# OpenAlex
# --------------------------------------------------------------------------- #

OPENALEX = "https://api.openalex.org/works"
_OA_FIELDS = (
    "id,doi,title,display_name,publication_year,authorships,primary_location,"
    "best_oa_location,abstract_inverted_index,type,ids,cited_by_count,language"
)


def _openalex_params(s: Settings) -> dict:
    params = {}
    if s.openalex_api_key:
        params["api_key"] = s.openalex_api_key
    if s.contact_email:
        params["mailto"] = s.contact_email
    return params


def _openalex_filter(query: str) -> dict:
    """Boolean search over titles and abstracts, plus an optional year range.

    Queries may carry a year range as a trailing ' || from_year-to_year' hint.
    """
    years = ""
    if "||" in query:
        query, years = (part.strip() for part in query.split("||", 1))
    # a comma separates filters in the OpenAlex syntax, so it cannot appear in the query
    parts = [f"title_and_abstract.search:{query.replace(',', ' ')}"]
    match = re.match(r"(\d{4})?-(\d{4})?", years)
    if match:
        if match.group(1):
            parts.append(f"from_publication_date:{match.group(1)}-01-01")
        if match.group(2):
            parts.append(f"to_publication_date:{match.group(2)}-12-31")
    return {"filter": ",".join(parts)}


def openalex_count(query: str, s: Settings) -> int:
    data = get_json(
        OPENALEX,
        {**_openalex_filter(query), "per-page": 1, "select": "id", **_openalex_params(s)},
        cache_dir=s.cache_dir,
    )
    return int(data["meta"]["count"])


def _abstract_from_inverted_index(index: dict | None) -> str:
    if not index:
        return ""
    positions = [(pos, word) for word, places in index.items() for pos in places]
    return " ".join(word for _, word in sorted(positions))


def openalex_search(query: str, max_results: int, s: Settings) -> list[Record]:
    records: list[Record] = []
    cursor = "*"
    while len(records) < max_results and cursor:
        data = get_json(
            OPENALEX,
            {
                **_openalex_filter(query),
                "sort": "relevance_score:desc",
                "per-page": min(200, max(25, max_results - len(records))),
                "cursor": cursor,
                "select": _OA_FIELDS,
                **_openalex_params(s),
            },
            cache_dir=s.cache_dir,
        )
        results = data.get("results", [])
        for item in results:
            title = _clean(item.get("title") or item.get("display_name"))
            if not title:
                continue
            ids = item.get("ids") or {}
            best = item.get("best_oa_location") or {}
            primary = item.get("primary_location") or {}
            landing = primary.get("landing_page_url") or ""
            arxiv = re.search(r"arxiv\.org/abs/([\w.\-/]+?)(v\d+)?$", landing)
            pmid = ids.get("pmid")
            pmcid = ids.get("pmcid")
            records.append(
                Record(
                    title=title,
                    abstract=_abstract_from_inverted_index(item.get("abstract_inverted_index")),
                    authors=[
                        last_first(a["author"]["display_name"])
                        for a in item.get("authorships", [])
                        if a.get("author", {}).get("display_name")
                    ],
                    year=item.get("publication_year"),
                    venue=((primary.get("source") or {}).get("display_name")) or "",
                    doi=norm_doi(item.get("doi")),
                    pmid=pmid.rsplit("/", 1)[-1] if pmid else None,
                    pmcid=("PMC" + pmcid.rsplit("/", 1)[-1].upper().removeprefix("PMC")) if pmcid else None,
                    arxiv_id=arxiv.group(1) if arxiv else None,
                    openalex_id=item["id"].rsplit("/", 1)[-1],
                    url=landing or item.get("doi") or item["id"],
                    pdf_url=best.get("pdf_url"),
                    pub_type=item.get("type") or "",
                    cited_by=item.get("cited_by_count"),
                    sources=["openalex"],
                )
            )
        cursor = data.get("meta", {}).get("next_cursor")
        if not results:
            break
    return records[:max_results]


# --------------------------------------------------------------------------- #
# arXiv
# --------------------------------------------------------------------------- #

ARXIV = "https://export.arxiv.org/api/query"
_ATOM = {"a": "http://www.w3.org/2005/Atom", "os": "http://a9.com/-/spec/opensearch/1.1/"}


def arxiv_count(query: str, s: Settings) -> int:
    xml = get_text(ARXIV, {"search_query": query, "max_results": 1}, cache_dir=s.cache_dir)
    return int(ET.fromstring(xml).findtext("os:totalResults", default="0", namespaces=_ATOM))


def arxiv_search(query: str, max_results: int, s: Settings) -> list[Record]:
    records: list[Record] = []
    for start in range(0, max_results, 100):
        xml = get_text(
            ARXIV,
            {
                "search_query": query,
                "start": start,
                "max_results": min(100, max_results - start),
                "sortBy": "relevance",
            },
            cache_dir=s.cache_dir,
        )
        entries = ET.fromstring(xml).findall("a:entry", _ATOM)
        for entry in entries:
            abs_url = entry.findtext("a:id", default="", namespaces=_ATOM)
            arxiv_id = re.sub(r"v\d+$", "", abs_url.rsplit("/abs/", 1)[-1])
            doi = entry.findtext("{http://arxiv.org/schemas/atom}doi")
            records.append(
                Record(
                    title=_clean(entry.findtext("a:title", default="", namespaces=_ATOM)),
                    abstract=_clean(entry.findtext("a:summary", default="", namespaces=_ATOM)),
                    authors=[
                        last_first(a.findtext("a:name", default="", namespaces=_ATOM))
                        for a in entry.findall("a:author", _ATOM)
                    ],
                    year=_year(entry.findtext("a:published", default="", namespaces=_ATOM)),
                    venue="arXiv",
                    doi=norm_doi(doi) or f"10.48550/arxiv.{arxiv_id.lower()}",
                    arxiv_id=arxiv_id,
                    url=f"https://arxiv.org/abs/{arxiv_id}",
                    pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
                    pub_type="preprint",
                    sources=["arxiv"],
                )
            )
        if len(entries) < 100:
            break
    return records[:max_results]


# --------------------------------------------------------------------------- #
# Semantic Scholar (bulk search; frequently rate-limited without a key)
# --------------------------------------------------------------------------- #

S2 = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"
_S2_FIELDS = "title,abstract,year,venue,externalIds,authors,openAccessPdf,publicationTypes,citationCount,url"


def _s2_headers(s: Settings) -> dict:
    return {"x-api-key": s.s2_api_key} if s.s2_api_key else {}


def _s2_query(query: str) -> tuple[str, dict]:
    extra = {}
    if "||" in query:
        query, years = (part.strip() for part in query.split("||", 1))
        if re.match(r"(\d{4})?-(\d{4})?$", years):
            extra["year"] = years
    return query, extra


def semantic_scholar_count(query: str, s: Settings) -> int:
    query, extra = _s2_query(query)
    data = get_json(
        S2, {"query": query, "fields": "title", **extra}, headers=_s2_headers(s), cache_dir=s.cache_dir
    )
    return int(data.get("total", 0))


def semantic_scholar_search(query: str, max_results: int, s: Settings) -> list[Record]:
    query, extra = _s2_query(query)
    records: list[Record] = []
    token = None
    while len(records) < max_results:
        params = {"query": query, "fields": _S2_FIELDS, **extra}
        if token:
            params["token"] = token
        data = get_json(S2, params, headers=_s2_headers(s), cache_dir=s.cache_dir)
        for item in data.get("data", []):
            if not item.get("title"):
                continue
            ext = item.get("externalIds") or {}
            records.append(
                Record(
                    title=_clean(item["title"]),
                    abstract=_clean(item.get("abstract")),
                    authors=[last_first(a["name"]) for a in item.get("authors", []) if a.get("name")],
                    year=item.get("year"),
                    venue=item.get("venue") or "",
                    doi=norm_doi(ext.get("DOI")),
                    pmid=str(ext["PubMed"]) if ext.get("PubMed") else None,
                    pmcid=f"PMC{ext['PubMedCentral']}" if ext.get("PubMedCentral") else None,
                    arxiv_id=ext.get("ArXiv"),
                    s2_id=item.get("paperId"),
                    url=item.get("url"),
                    pdf_url=(item.get("openAccessPdf") or {}).get("url") or None,
                    pub_type="; ".join(item.get("publicationTypes") or []),
                    cited_by=item.get("citationCount"),
                    sources=["semantic_scholar"],
                )
            )
        token = data.get("token")
        if not token or not data.get("data"):
            break
    return records[:max_results]


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #

SearchFn = Callable[[str, int, Settings], list[Record]]
CountFn = Callable[[str, Settings], int]

SOURCES: dict[str, tuple[CountFn, SearchFn]] = {
    "pubmed": (pubmed_count, pubmed_search),
    "europepmc": (europepmc_count, europepmc_search),
    "openalex": (openalex_count, openalex_search),
    "arxiv": (arxiv_count, arxiv_search),
    "semantic_scholar": (semantic_scholar_count, semantic_scholar_search),
}

DISPLAY_NAME = {
    "pubmed": "PubMed", "europepmc": "Europe PMC", "openalex": "OpenAlex", "arxiv": "arXiv",
    "semantic_scholar": "Semantic Scholar",
}

QUERY_SYNTAX = {
    "pubmed": (
        "PubMed syntax. Combine concept blocks with AND, synonyms with OR, inside parentheses. "
        'Use field tags: "term"[tiab] for title/abstract, "Heading"[MeSH Terms] for MeSH, '
        "truncation with * (e.g. screen*[tiab]). Add a date limit like "
        'AND ("2018"[dp] : "2026"[dp]) when the protocol has a date range.'
    ),
    "europepmc": (
        'Europe PMC syntax. Boolean AND / OR / NOT with parentheses, phrases in double quotes. Put the '
        'field TITLE_ABS: before EVERY term so that it is searched in title and abstract only, e.g. '
        '(TITLE_ABS:"heart failure" OR TITLE_ABS:HFrEF) AND (TITLE_ABS:telemonitoring); a term without a '
        'field is searched in the full text and returns thousands of irrelevant hits. No truncation. '
        "Date limit: AND PUB_YEAR:[2018 TO 2026]."
    ),
    "openalex": (
        "OpenAlex syntax; the query is matched against titles and abstracts. Uppercase AND / OR / NOT "
        "with parentheses and double-quoted phrases only (no field tags, no truncation, no commas). "
        "Optionally append a year range after ' || ', e.g.  (\"a\" OR \"b\") AND (\"c\") || 2018-2026"
    ),
    "arxiv": (
        'arXiv API syntax. Field prefixes ti: abs: all: with double-quoted phrases, combined with '
        'AND / OR / ANDNOT and parentheses, e.g. (abs:"large language model" OR abs:LLM) AND '
        '(ti:screening OR abs:"systematic review"). No date syntax.'
    ),
    "semantic_scholar": (
        'Semantic Scholar bulk-search syntax. Double-quoted phrases, | for OR, + for AND, '
        "- to negate, parentheses for grouping, * for prefix match, e.g. "
        '("large language model" | LLM) + ("systematic review" | screening). Optionally append '
        "a year range after ' || ', e.g. ... || 2018-2026"
    ),
}


def count_hits(database: str, query: str, settings: Settings) -> int:
    if database not in SOURCES:
        raise SourceError(f"Unknown database '{database}'")
    return SOURCES[database][0](query, settings)


def run_search(database: str, query: str, max_results: int, settings: Settings) -> list[Record]:
    if database not in SOURCES:
        raise SourceError(f"Unknown database '{database}'")
    return SOURCES[database][1](query, max_results, settings)
