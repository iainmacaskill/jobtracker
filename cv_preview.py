"""Render a generated CV (.docx) as Markdown for an in-app preview.

This is a content preview, not a layout-faithful one: browsers can't render
.docx natively and a PDF conversion would need LibreOffice. Headings, bullets,
bold runs and tables survive; fonts, margins and page breaks don't. Use the
download button next to the preview for the real file.
"""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

import config

# Folders searched, in order, for a filename recorded in the CV version column.
SEARCH_DIRS: tuple[Path, ...] = tuple(
    p for p in (config.RESUME_DIR, config.CV_DIR, config.COVER_LETTER_DIR) if p
)


def find_cv(filename: str | None) -> Path | None:
    """Locate a CV by bare filename in the known output folders (no path traversal)."""
    name = Path(str(filename or "")).name.strip()
    if not name:
        return None
    for d in SEARCH_DIRS:
        candidate = Path(d) / name
        if candidate.is_file():
            return candidate
    return None


def _runs_md(paragraph: Paragraph) -> str:
    """Paragraph text with bold/italic runs mapped to Markdown, whitespace kept."""
    out: list[str] = []
    for run in paragraph.runs:
        text = run.text.replace("\t", "  ·  ")
        if not text.strip():
            out.append(text)
            continue
        if run.bold:
            text = f"**{text.strip()}**" + (" " if text.endswith(" ") else "")
        elif run.italic:
            text = f"*{text.strip()}*" + (" " if text.endswith(" ") else "")
        out.append(text)
    return "".join(out).strip()


def _paragraph_md(p: Paragraph) -> str | None:
    text = _runs_md(p)
    if not text:
        return None
    style = (p.style.name if p.style is not None else "") or ""
    if style == "Title" or style == "Heading 1":
        return f"## {p.text.strip()}"
    if style.startswith("Heading"):
        return f"### {p.text.strip()}"
    if "List" in style:
        return f"- {text}"
    if style == "Intense Quote":
        return f"**{p.text.strip()}**"
    # cv_builder headings are plain paragraphs set entirely in bold caps.
    if p.runs and all(r.bold for r in p.runs if r.text.strip()) and p.text.isupper():
        return f"### {p.text.strip().title()}"
    return text


def _table_md(t: Table) -> str:
    lines: list[str] = []
    for row in t.rows:
        for cell in row.cells:
            for p in cell.paragraphs:
                md = _paragraph_md(p)
                if md:
                    # cv_builder pre-pends its own glyph inside the cell text.
                    md = md.lstrip("- ").lstrip("▪•· ")
                    lines.append(f"- {md}")
    return "\n".join(lines)


def docx_to_markdown(path: Path | str) -> str:
    """Walk the document body in order, converting paragraphs and tables."""
    doc = Document(str(path))
    blocks: list[str] = []
    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            md = _paragraph_md(Paragraph(child, doc))
            if md:
                blocks.append(md)
        elif child.tag == qn("w:tbl"):
            md = _table_md(Table(child, doc))
            if md:
                blocks.append(md)
    return "\n\n".join(blocks)
