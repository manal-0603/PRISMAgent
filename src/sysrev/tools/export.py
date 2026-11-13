"""Export utilities: BibTeX, CSV and a small Markdown -> DOCX converter."""

from __future__ import annotations

import csv
import re
from pathlib import Path

from ..models import Record

# --------------------------------------------------------------------------- #
# References
# --------------------------------------------------------------------------- #


def bibtex_key(rec: Record) -> str:
    first = rec.authors[0].split(",")[0] if rec.authors else "anon"
    word = next((w for w in re.findall(r"[A-Za-z]{4,}", rec.title)), "untitled")
    return re.sub(r"[^A-Za-z0-9]", "", f"{first}{rec.year or ''}{word}").lower()


def _bib_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("&", "\\&").replace("%", "\\%")


def to_bibtex(records: list[Record]) -> str:
    entries, seen = [], {}
    for rec in records:
        key = bibtex_key(rec)
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:
            key += chr(ord("a") + seen[key] - 1)
        kind = "misc" if rec.venue.lower() in ("", "arxiv") else "article"
        fields = {
            "title": _bib_escape(rec.title),
            "author": " and ".join(_bib_escape(a) for a in rec.authors),
            "year": str(rec.year or ""),
            "journal" if kind == "article" else "howpublished": _bib_escape(rec.venue),
            "doi": rec.doi or "",
            "url": rec.url or "",
            "note": f"review-id: {rec.rid}",
        }
        body = ",\n".join(f"  {k} = {{{v}}}" for k, v in fields.items() if v)
        entries.append(f"@{kind}{{{key},\n{body}\n}}")
    return "\n\n".join(entries) + "\n"


def vancouver_name(author: str) -> str:
    """'Smith, Jane Ann' -> 'Smith JA'."""
    surname, _, given = author.partition(",")
    given = given.strip()
    if not given:
        return surname.strip()
    initials = given.replace(".", "") if given.replace(".", "").replace("-", "").isupper() and len(given) <= 5 else "".join(
        part[0].upper() for part in re.split(r"[\s.\-]+", given) if part
    )
    return f"{surname.strip()} {initials}"


def format_reference(rec: Record) -> str:
    """Vancouver-like reference line."""
    authors = [vancouver_name(a) for a in rec.authors[:6]]
    names = ", ".join(authors) + (", et al" if len(rec.authors) > 6 else "")
    parts = [f"{names}." if names else "", f"{rec.title.rstrip('.')}."]
    if rec.venue:
        parts.append(f"{rec.venue}.")
    if rec.year:
        parts.append(f"{rec.year}.")
    if rec.doi:
        parts.append(f"https://doi.org/{rec.doi}")
    elif rec.url:
        parts.append(rec.url)
    return " ".join(p for p in parts if p)


def write_csv(path: Path, rows: list[dict]) -> Path:
    if not rows:
        path.write_text("", encoding="utf-8")
        return path
    columns = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    return path


def md_table(rows: list[dict], columns: list[str] | None = None) -> str:
    if not rows:
        return "_No data._"
    columns = columns or list(rows[0])

    def cell(value: object) -> str:
        return str(value if value not in (None, "") else "-").replace("|", "/").replace("\n", " ")

    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    lines += ["| " + " | ".join(cell(row.get(c)) for c in columns) + " |" for row in rows]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Markdown -> DOCX (headings, paragraphs, lists, tables, images, bold/italic)
# --------------------------------------------------------------------------- #

_INLINE = re.compile(r"(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)")


def _add_inline(paragraph, text: str) -> None:
    for part in _INLINE.split(text):
        if not part:
            continue
        if part.startswith("**"):
            paragraph.add_run(part[2:-2]).bold = True
        elif part.startswith("*"):
            paragraph.add_run(part[1:-1]).italic = True
        elif part.startswith("`"):
            paragraph.add_run(part[1:-1]).font.name = "Courier New"
        else:
            paragraph.add_run(part)


def markdown_to_docx(markdown: str, path: Path, base_dir: Path | None = None) -> Path:
    from docx import Document
    from docx.shared import Inches, Pt

    doc = Document()
    doc.styles["Normal"].font.size = Pt(10.5)
    lines = markdown.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if stripped.startswith("```"):
            block = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            i += 1
            if block and not block[0].lstrip().startswith("flowchart"):
                run = doc.add_paragraph().add_run("\n".join(block))
                run.font.name, run.font.size = "Courier New", Pt(8.5)
            continue
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            doc.add_heading(stripped.lstrip("#").strip(), level=min(level, 4) if level > 1 else 0)
            i += 1
            continue
        image = re.match(r"!\[(.*?)\]\((.*?)\)", stripped)
        if image:
            target = (base_dir or path.parent) / image.group(2)
            if target.exists():
                doc.add_picture(str(target), width=Inches(6.0))
                if image.group(1):
                    doc.add_paragraph(image.group(1)).italic = True
            i += 1
            continue
        if stripped.startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                if not re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i]):
                    rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            width = max(len(r) for r in rows)
            table = doc.add_table(rows=len(rows), cols=width)
            table.style = "Light Grid Accent 1"
            for r, row in enumerate(rows):
                for c in range(width):
                    cell = table.cell(r, c)
                    cell.text = ""
                    _add_inline(cell.paragraphs[0], row[c] if c < len(row) else "")
                    for run in cell.paragraphs[0].runs:
                        run.font.size = Pt(8)
                        if r == 0:
                            run.bold = True
            doc.add_paragraph()
            continue
        bullet = re.match(r"^\s*[-*]\s+(.*)", line)
        numbered = re.match(r"^\s*\d+\.\s+(.*)", line)
        if bullet or numbered:
            style = "List Bullet" if bullet else "List Number"
            _add_inline(doc.add_paragraph(style=style), (bullet or numbered).group(1))
            i += 1
            continue
        paragraph = [stripped]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"^\s*(#|\||[-*]\s|\d+\.\s|```|!\[)", lines[i]):
            paragraph.append(lines[i].strip())
            i += 1
        _add_inline(doc.add_paragraph(), " ".join(paragraph))
    doc.save(str(path))
    return path
