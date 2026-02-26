"""
Markdown (MD) import by converting to HTML and reusing the HTML structure extraction.

Uses the optional dependency 'markdown' to produce HTML; then parses with lxml and
builds the same structure layer as load_html (paragraphs, headings, list items,
blockquotes). No tokenization.

Install with: pip install flexiconv[md]
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from lxml import html as lxml_html

from .html import document_from_html_root

if TYPE_CHECKING:
    from ..core.model import Document


def load_md(path: str, *, doc_id: Optional[str] = None) -> Document:
    """
    Load a Markdown file into a pivot Document.

    Converts MD to HTML via the 'markdown' library, then extracts block-level
    structure (p, h1–h6, li, blockquote, div) into a 'structure' layer, same as
    load_html. Supports CommonMark-style syntax (headings, lists, blockquotes,
    code blocks, etc.) via the markdown extra extensions.

    Requires the optional dependency: pip install flexiconv[md]
    """
    try:
        import markdown
    except ImportError as e:
        raise RuntimeError(
            "Markdown support requires the 'markdown' package. Install with: pip install flexiconv[md]"
        ) from e

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()

    # Extensions for common syntax (tables, fenced code, etc.); output stays HTML.
    html_fragment = markdown.markdown(
        raw,
        extensions=["extra", "nl2br"],
        output_format="html",
    )
    # Wrap in a container so multiple top-level elements are under one root.
    wrapped = f"<div>{html_fragment}</div>"
    root = lxml_html.fromstring(wrapped)

    if doc_id is None:
        doc_id = path
    return document_from_html_root(
        root,
        doc_id=doc_id,
        source_filename=path.split("/")[-1].split("\\")[-1],
    )
