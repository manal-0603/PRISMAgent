"""Open-access full-text retrieval and parsing.

Cascade (first success wins):

1. Europe PMC structured full text (JATS XML) when the record has a PMCID
2. Europe PMC lookup by DOI / PMID to discover a PMCID
3. arXiv PDF
4. Open-access PDF location reported by OpenAlex / Semantic Scholar / Europe PMC
5. Unpaywall — only if CONTACT_EMAIL is set, because that API requires an e-mail

Paywalled articles are never fetched: when nothing open is found the record is
reported as "not retrieved" and handled according to the protocol options.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from ..config import Settings
from ..models import Record
from .connectors import EPMC
from .http import SourceError, get_bytes, get_json, get_text

MIN_CHARS = 3000  # anything shorter is not a usable full text


def _tidy(text: str) -> str:
    text = text.replace("­", "").replace("\x00", "")
    text = re.sub(r"-\n(?=[a-z])", "", text)  # undo end-of-line hyphenation
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _strip_references(text: str) -> str:
    """Drop the bibliography so that retrieval is not polluted by cited titles."""
    matches = list(re.finditer(r"\n\s*(references|bibliography|literature cited)\s*\n", text, flags=re.I))
    if matches and matches[-1].start() > len(text) * 0.5:
        return text[: matches[-1].start()]
    return text


_SKIP = {"tex-math", "object-id", "ref-list", "fn-group"}  # LaTeX sources of formulas, ids, bibliographies
_FLOATS = {"table-wrap", "fig"}  # rendered on their own lines, even when nested inside a paragraph


def _tag(node: ET.Element) -> str:
    return node.tag.split("}")[-1]


def _node_text(node: ET.Element, skip: set[str] = _SKIP) -> str:
    """Text of a JATS node without the subtrees listed in `skip`."""
    parts = [node.text or ""]
    for child in node:
        if _tag(child) not in skip:
            parts.append(_node_text(child, skip))
        parts.append(child.tail or "")
    return "".join(parts)


def _floats(node: ET.Element) -> list[ET.Element]:
    """Outermost tables / figures below `node`."""
    found = []
    for child in node:
        if _tag(child) in _FLOATS:
            found.append(child)
        elif _tag(child) not in _SKIP:
            found.extend(_floats(child))
    return found


def jats_to_text(xml: str) -> str:
    root = ET.fromstring(xml)
    body = root.find(".//body")
    if body is None:
        return ""
    lines: list[str] = []

    def clean(node: ET.Element, skip: set[str] = _SKIP) -> str:
        return " ".join(_node_text(node, skip).split())

    def render_float(node: ET.Element) -> None:
        label = next((clean(c) for c in node if _tag(c) == "label"), "")
        caption = next((clean(c) for c in node if _tag(c) == "caption"), "")
        if label or caption:
            lines.append(f"{label}. {caption}".strip(". "))
        for row in node.iter():
            if _tag(row) == "tr":  # one table row per line: a value stays next to its label
                cells = [clean(cell) for cell in row if _tag(cell) in ("td", "th")]
                if any(cells):
                    lines.append(" | ".join(cells))

    def walk(node: ET.Element) -> None:
        tag = _tag(node)
        if tag in _SKIP:
            return
        if tag in _FLOATS:
            render_float(node)
        elif tag == "title":
            lines.append("\n## " + clean(node))
        elif tag == "p":
            text = clean(node, _SKIP | _FLOATS)
            if text:
                lines.append(text)
            for nested in _floats(node):
                render_float(nested)
        else:
            for child in node:
                walk(child)

    walk(body)
    return _tidy("\n".join(lines))


_PDF_HEADING = re.compile(
    r"^\s*(?:\d{1,2}\.?\s+)?(abstract|introduction|background|related work|methods?|materials and methods|methodology|"
    r"experiments?|experimental setup|evaluation|results?|results and discussion|discussion|limitations|"
    r"conclusions?|future work)\s*$",
    flags=re.I | re.M,
)


def pdf_to_text(data: bytes) -> str:
    import pymupdf

    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            if doc.page_count > 80:  # books, theses, proceedings: not a single report
                return ""
            text = "\n".join(page.get_text() for page in doc)
    except Exception:
        return ""
    text = _strip_references(_tidy(text))
    # mark the usual section headings so that chunks know which section they belong to
    return _PDF_HEADING.sub(lambda m: f"\n## {m.group(0).strip()}", text)


def _epmc_fulltext(pmcid: str, s: Settings) -> str:
    try:
        xml = get_text(f"{EPMC}/{pmcid}/fullTextXML", cache_dir=s.cache_dir, retries=2)
        return jats_to_text(xml)
    except (SourceError, ET.ParseError):
        return ""


def _epmc_find_pmcid(rec: Record, s: Settings) -> str | None:
    query = f'DOI:"{rec.doi}"' if rec.doi else (f"EXT_ID:{rec.pmid} AND SRC:MED" if rec.pmid else None)
    if not query:
        return None
    try:
        data = get_json(
            f"{EPMC}/search", {"query": query, "format": "json", "resultType": "lite", "pageSize": 1},
            cache_dir=s.cache_dir, retries=2,
        )
    except SourceError:
        return None
    results = data.get("resultList", {}).get("result", [])
    return results[0].get("pmcid") if results else None


def _unpaywall_pdf(rec: Record, s: Settings) -> str | None:
    if not (s.contact_email and rec.doi):
        return None
    try:
        data = get_json(
            f"https://api.unpaywall.org/v2/{rec.doi}", {"email": s.contact_email},
            cache_dir=s.cache_dir, retries=2,
        )
    except SourceError:
        return None
    return (data.get("best_oa_location") or {}).get("url_for_pdf")


def fetch_fulltext(rec: Record, s: Settings) -> tuple[str, str]:
    """Return (text, provenance). Text is '' when no open full text was found."""
    pmcid = rec.pmcid or _epmc_find_pmcid(rec, s)
    if pmcid:
        text = _epmc_fulltext(pmcid, s)
        if len(text) >= MIN_CHARS:
            return text, f"Europe PMC full text ({pmcid})"

    candidates: list[tuple[str, str]] = []
    if rec.arxiv_id:
        candidates.append((f"https://arxiv.org/pdf/{rec.arxiv_id}", f"arXiv PDF ({rec.arxiv_id})"))
    if rec.pdf_url:
        candidates.append((rec.pdf_url, "open-access PDF"))
    unpaywall = _unpaywall_pdf(rec, s)
    if unpaywall:
        candidates.append((unpaywall, "Unpaywall PDF"))

    for url, label in candidates:
        data = get_bytes(url)
        if data and data[:5] == b"%PDF-":
            text = pdf_to_text(data)
            if len(text) >= MIN_CHARS:
                return text, label
    return "", "not retrieved"
