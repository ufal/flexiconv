"""ODT (OpenDocument Text) loader.

This provides a basic ODT -> TEITOK-style TEI conversion, similar in spirit to
the DOCX loader but limited to paragraphs and inline text.

Implementation notes:
- Uses odfpy (odf.opendocument.load) to read the .odt file.
- Walks text:P and text:H elements in document order and converts them to
  <p> elements in a TEI body.
- Inline styling (bold/italic/etc.) is currently ignored; content is treated
  as plain text paragraphs suitable for corpus ingestion or further processing.
"""
from __future__ import annotations

import os
from datetime import date
from typing import Optional

from lxml import etree

from ..core.model import Document


def _require_odf():
    try:
        from odf.opendocument import load  # type: ignore
        from odf import text as odf_text  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "ODT support requires the 'odfpy' package. "
            "Install with: pip install 'flexiconv[odt]'"
        ) from exc
    return load, odf_text


def _iter_paragraphs(body, odf_text):
    """Yield (tag, element) for text:P and text:H elements in document order."""
    for elem in body.getElementsByType((odf_text.P, odf_text.H)):
        yield elem.qname[1], elem  # (localname, element)


def odt_to_tei_tree(path: str, *, orgfile: Optional[str] = None) -> etree._Element:
    """Convert an ODT file to a TEITOK-style TEI element tree (no namespace)."""
    load, odf_text = _require_odf()
    odt_doc = load(path)

    basename = os.path.splitext(os.path.basename(path))[0]
    XML_NS = "http://www.w3.org/XML/1998/namespace"

    tei = etree.Element("TEI")
    tei_header = etree.SubElement(tei, "teiHeader")
    text_el = etree.SubElement(tei, "text")
    text_el.set(f"{{{XML_NS}}}space", "preserve")
    text_el.set("id", basename)
    body = etree.SubElement(text_el, "body")

    filedesc = etree.SubElement(tei_header, "fileDesc")
    notesstmt = etree.SubElement(filedesc, "notesStmt")
    note = etree.SubElement(notesstmt, "note")
    note.set("n", "orgfile")
    note.text = orgfile or path
    revisiondesc = etree.SubElement(tei_header, "revisionDesc")
    change = etree.SubElement(revisiondesc, "change")
    change.set("who", "flexiconv")
    change.set("when", str(date.today()))
    change.text = "Converted from ODT file " + path
    titlestmt = etree.SubElement(filedesc, "titleStmt")
    profiledesc = etree.SubElement(tei_header, "profileDesc")

    # Basic metadata from document statistics or properties if present
    meta = getattr(odt_doc, "meta", None)
    if meta is not None:
        title = getattr(meta, "title", None)
        if title:
            t = etree.SubElement(titlestmt, "title")
            t.text = str(title)
        creator = getattr(meta, "initialcreator", None) or getattr(meta, "creator", None)
        if creator:
            a = etree.SubElement(titlestmt, "author")
            a.text = str(creator)
        language = getattr(meta, "language", None)
        if language:
            langusage = etree.SubElement(profiledesc, "langUsage")
            lang = etree.SubElement(langusage, "language")
            lang.text = str(language)

    # Body paragraphs/headings
    text_body = odt_doc.text
    for tag, elem in _iter_paragraphs(text_body, odf_text):
        text_content = "".join(str(n) for n in elem.childNodes if getattr(n, "data", None) is not None)
        if not text_content.strip():
            continue
        p = etree.SubElement(body, "p")
        if tag.lower() == "h":
            p.set("rend", "heading")
        p.text = text_content
        p.tail = "\n"

    return tei


def load_odt(
    path: str,
    *,
    doc_id: Optional[str] = None,
    orgfile: Optional[str] = None,
) -> Document:
    """Load an ODT file into a pivot Document.

    The resulting TEI tree is stored so that saving to TEITOK reproduces that output
    (header and paragraphs). Inline styling is currently ignored.
    """
    tei_root = odt_to_tei_tree(path, orgfile=orgfile or path)
    if doc_id is None:
        doc_id = path
    doc = Document(id=doc_id)
    doc.meta["source_filename"] = os.path.basename(path)
    doc.meta["_teitok_tei_root"] = tei_root
    return doc

