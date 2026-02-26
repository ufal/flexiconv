"""
hOCR to TEITOK-style TEI conversion.

Produces TEI that mimics the original (pb, p, lb, tok with bbox; punctuation split
from words). Header is homogenized with other flexiconv formats (notesStmt, revisionDesc).
Designed so that in principle pagesXML → FPM → hOCR could work (FPM would carry bbox/structure).
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Optional

from lxml import etree

from ..core.model import Document

# Match bbox in hOCR title: bbox x0 y0 x1 y1
BBOX_RE = re.compile(r"bbox\s+([0-9.]+\s+[0-9.]+\s+[0-9.]+\s+[0-9.]+)")
# Match image reference in page title
IMAGE_RE = re.compile(r'image\s+"?([^";]+)"?')
# Trailing/leading punctuation (Unicode-aware: \P{L}\P{N} = not letter/number, or ASCII fallback)
try:
    TRAILING_PUNCT_RE = re.compile(r"^(.*)(\P{L}\P{N}+)$")
    LEADING_PUNCT_RE = re.compile(r"^(\P{L}\P{N}+)(.*)$")
except re.error:
    TRAILING_PUNCT_RE = re.compile(r"^(.*)([^\w\s]+)$")
    LEADING_PUNCT_RE = re.compile(r"^([^\w\s]+)(.*)$")


def _has_class(el: etree._Element, part: str) -> bool:
    c = el.get("class") or ""
    return part in c


def _next_is_ocr_word(el: etree._Element | None) -> bool:
    """True if el is a span with class ocrx_word (next token will be a new word)."""
    if el is None:
        return False
    tag = (el.tag or "").split("}")[-1]
    return tag == "span" and _has_class(el, "ocrx_word")


def _is_structural_block(el: etree._Element) -> bool:
    """True if element is a block that gets a newline after it for readability (p, pb). Not lb."""
    tag = (el.tag or "").split("}")[-1]
    return tag in ("p", "pb")


def _is_tok_el(el: etree._Element) -> bool:
    """True if element is a <tok> (not gtok)."""
    tag = (el.tag or "").split("}")[-1]
    return tag == "tok"


def _get_bbox(title: str) -> str:
    m = BBOX_RE.search(title or "")
    if not m:
        return ""
    bbox = m.group(1)
    # Original script strips decimals; we keep them for precision
    return bbox


def _get_facs(title: str, strippath: bool = False) -> str:
    m = IMAGE_RE.search(title or "")
    if not m:
        return ""
    facs = m.group(1).strip('"')
    if strippath:
        facs = os.path.basename(facs)
    return facs


def _text_content(el: etree._Element) -> str:
    return "".join(el.itertext()) if el.itertext else (el.text or "")


from .teitok_xml import _ensure_tei_header


def _split_punct(text: str) -> list[tuple[str, bool]]:
    """Return [(segment, is_punct), ...] so we can emit separate tok for punctuation."""
    out: list[tuple[str, bool]] = []
    s = text
    while s:
        m = LEADING_PUNCT_RE.match(s)
        if m:
            out.append((m.group(1), True))
            s = m.group(2)
            continue
        m = TRAILING_PUNCT_RE.match(s)
        if m:
            out.append((m.group(1), False))
            out.append((m.group(2), True))
            s = ""
            continue
        out.append((s, False))
        break
    return out


def _emit_truncation_tok(
    parent_tei: etree._Element,
    part1_text: str,
    part1_bbox: str,
    line_bbox: str,
    part2_span: etree._Element,
    saved_tail: str,
) -> None:
    """Emit <tok><gtok>part1</gtok><lb/><gtok>part2</gtok></tok> for hyphen truncation."""
    tok = etree.SubElement(parent_tei, "tok")
    tok.tail = saved_tail
    g1 = etree.SubElement(tok, "gtok")
    if part1_bbox:
        g1.set("bbox", part1_bbox)
    g1.text = part1_text
    lb = etree.SubElement(tok, "lb")
    if line_bbox:
        lb.set("bbox", line_bbox)
    g2 = etree.SubElement(tok, "gtok")
    title2 = part2_span.get("title") or ""
    bbox2 = _get_bbox(title2)
    if bbox2:
        g2.set("bbox", bbox2)
    g2.text = _text_content(part2_span).strip()


def _process_word_span(
    span: etree._Element,
    parent: etree._Element,
    *,
    split_punct: bool = True,
) -> None:
    title = span.get("title") or ""
    bbox = _get_bbox(title)
    text = _text_content(span).strip()
    if not split_punct:
        if not text:
            return
        tok = etree.SubElement(parent, "tok")
        if bbox:
            tok.set("bbox", bbox)
        tok.text = text
        return

    segments = _split_punct(text)
    for seg, is_punct in segments:
        if not seg:
            continue
        tok = etree.SubElement(parent, "tok")
        # Only word segments get bbox; punctuation split off has no bbox (TEITOK convention).
        if bbox and not is_punct:
            tok.set("bbox", bbox)
        tok.text = seg


def _process_children(
    parent_hocr: etree._Element,
    parent_tei: etree._Element,
    *,
    split_punct: bool = True,
    line_span: Optional[etree._Element] = None,
    hyphen_truncation: bool = False,
) -> None:
    for ch in parent_hocr:
        tag = ch.tag if isinstance(ch.tag, str) else (ch.tag or "")
        local = tag.split("}")[-1] if "}" in tag else tag
        if local == "p" and _has_class(ch, "ocr_par"):
            # Newline before this <p> for readability (no newline after <lb/>; see _is_structural_block).
            if len(parent_tei) > 0 and _is_structural_block(parent_tei[-1]):
                parent_tei[-1].tail = "\n  "
            title = ch.get("title") or ""
            p_tei = etree.SubElement(parent_tei, "p")
            if _get_bbox(title):
                p_tei.set("bbox", _get_bbox(title))
            _process_children(ch, p_tei, split_punct=split_punct, hyphen_truncation=hyphen_truncation)
        elif local == "span" and _has_class(ch, "ocr_line"):
            # Newline before <lb/> for readability (not when lb is inside a tok, e.g. truncation).
            if len(parent_tei) > 0 and not _is_tok_el(parent_tei):
                prev_tail = parent_tei[-1].tail or ""
                parent_tei[-1].tail = prev_tail + "\n  "
            lb = etree.SubElement(parent_tei, "lb")
            bbox = _get_bbox(ch.get("title") or "")
            if bbox:
                lb.set("bbox", bbox)
            _process_children(
                ch, parent_tei,
                split_punct=split_punct,
                line_span=ch,
                hyphen_truncation=hyphen_truncation,
            )
        elif local == "span" and _has_class(ch, "ocrx_word"):
            # Hyphen truncation: word- at end of previous line + word at start of this line -> one <tok> with <gtok><lb/><gtok>.
            if hyphen_truncation and line_span is not None and len(line_span) > 0 and ch is line_span[0]:
                if len(parent_tei) > 0 and _is_tok_el(parent_tei[-1]):
                    last_tok = parent_tei[-1]
                    part1_text = (last_tok.text or "").strip()
                    if part1_text.endswith("-"):
                        saved_tail = last_tok.tail or ""
                        part1_bbox = last_tok.get("bbox") or ""
                        line_bbox = _get_bbox(ch.getparent().get("title") or "") if ch.getparent() is not None else ""
                        parent_tei.remove(last_tok)
                        _emit_truncation_tok(
                            parent_tei,
                            part1_text[:-1].rstrip(),
                            part1_bbox,
                            line_bbox,
                            ch,
                            saved_tail,
                        )
                        if len(parent_tei) > 0:
                            next_sib = ch.getnext()
                            parent_tei[-1].tail = " " if _next_is_ocr_word(next_sib) else ""
                        continue
            _process_word_span(ch, parent_tei, split_punct=split_punct)
            # Encode source spacing in TEI tail (FPM representation: space after word when next is word).
            if len(parent_tei) > 0:
                next_sib = ch.getnext()
                parent_tei[-1].tail = " " if _next_is_ocr_word(next_sib) else ""
        else:
            _process_children(ch, parent_tei, split_punct=split_punct, line_span=line_span, hyphen_truncation=hyphen_truncation)


def hocr_to_tei_tree(
    path: str,
    *,
    strippath: bool = False,
    split_punct: bool = True,
    hyphen_truncation: bool = False,
) -> etree._Element:
    """
    Convert an hOCR file to a TEITOK-style TEI element tree.
    Mimics typical hOCR→TEI: pb, p, lb, tok with bbox; punctuation split off words.
    When hyphen_truncation is True, a word ending in hyphen at line end and the next
    line's first word are merged into one <tok><gtok>part1</gtok><lb/><gtok>part2</gtok></tok>.
    """
    with open(path, "rb") as f:
        raw = f.read()
    # Strip default namespace for easier matching (like the Perl script)
    try:
        raw_str = raw.decode("utf-8", errors="replace")
    except Exception:
        raw_str = raw.decode("latin-1", errors="replace")
    raw_str = re.sub(r'\s+xmlns="[^"]*"', "", raw_str, count=1)
    parser = etree.XMLParser(recover=True, remove_blank_text=True)
    try:
        doc = etree.fromstring(raw_str.encode("utf-8"), parser=parser)
    except Exception:
        doc = etree.fromstring(b"<html><body>" + raw_str.encode("utf-8") + b"</body></html>", etree.HTMLParser(encoding="utf-8"))

    # Ensure root is TEI and we have text (body)
    doc.tag = "TEI"
    bodies = doc.xpath("//*[local-name()='body']")
    body = bodies[0] if bodies else doc
    text_el = etree.Element("text")
    when = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    source_filename = os.path.basename(path)
    _ensure_tei_header(doc, source_filename, when)
    # Remove any existing head under TEI
    for head in doc.xpath("//*[local-name()='head']"):
        parent = head.getparent()
        if parent is not None:
            parent.remove(head)
    # Move body content into text
    for child in body:
        text_el.append(child)
    body.getparent().remove(body)
    doc.append(text_el)
    # Now traverse and convert: find all ocr_page, ocr_par, ocr_line, ocrx_word
    # We need to walk in document order and build a new text tree
    new_text = etree.Element("text")
    for div in doc.xpath("//*[local-name()='div'][contains(@class,'ocr_page')]"):
        title = div.get("title") or ""
        pb = etree.SubElement(new_text, "pb")
        bbox = _get_bbox(title)
        facs = _get_facs(title, strippath=strippath)
        if bbox:
            pb.set("bbox", bbox)
        if facs:
            pb.set("facs", facs)
        _process_children(div, new_text, split_punct=split_punct, hyphen_truncation=hyphen_truncation)
    # Replace old text with new
    for old_text in doc.xpath("//*[local-name()='text']"):
        parent = old_text.getparent()
        if parent is not None:
            parent.remove(old_text)
    doc.append(new_text)
    return doc


def load_hocr(
    path: str,
    *,
    doc_id: Optional[str] = None,
    strippath: bool = False,
    split_punct: bool = True,
    hyphen_truncation: bool = False,
) -> Document:
    """
    Load an hOCR file into a pivot Document.
    The TEI tree (with homogenized header) is stored
    in document.meta['_teitok_tei_root'] so that save_teitok writes it verbatim.

    By default, graphical tokens are split into orthographic tokens by separating
    leading/trailing punctuation into their own <tok> elements. Set
    split_punct=False to keep punctuation attached (e.g. for downstream
    tokenization in flexipipe or for closer alignment with FPM bbox data).
    """
    tei_root = hocr_to_tei_tree(
        path, strippath=strippath, split_punct=split_punct, hyphen_truncation=hyphen_truncation
    )
    if doc_id is None:
        doc_id = path
    doc = Document(id=doc_id)
    doc.meta["source_filename"] = os.path.basename(path)
    doc.meta["_teitok_tei_root"] = tei_root
    return doc


def _tei_text_children(tei_el: etree._Element) -> list[etree._Element]:
    """Return direct children of TEI <text> (pb, p, etc.) in document order."""
    text_el = tei_el.xpath("//*[local-name()='text']")
    if not text_el:
        return []
    return list(text_el[0])


def save_hocr(document: Document, path: str, *, facs_base: Optional[str] = None) -> None:
    """
    Write an hOCR file from a Document.

    Uses document.meta["_teitok_tei_root"] when present (e.g. from load_hocr or
    DOCX→TEI), converting pb/p/lb/tok with bbox back to hOCR. This allows
    hOCR → TEI → hOCR round-trip and, in principle, pagesXML → FPM → hOCR once
    a pagesXML loader fills FPM (and optionally _teitok_tei_root) with bbox data.

    If no TEI tree with bbox structure is available, raises ValueError.
    """
    tei_root = document.meta.get("_teitok_tei_root")
    if tei_root is None:
        raise ValueError(
            "save_hocr requires a document with bbox structure (e.g. from load_hocr or "
            "TEITOK TEI with pb/p/lb/tok bbox, or future pagesXML→FPM)."
        )
    body = _tei_to_hocr_body(tei_root, facs_base=facs_base)
    root = etree.Element("html", xmlns="http://www.w3.org/1999/xhtml")
    root.set("{http://www.w3.org/1999/xhtml}lang", "en")
    root.set("lang", "en")
    head = etree.SubElement(root, "head")
    etree.SubElement(head, "title").text = ""
    meta_ct = etree.SubElement(head, "meta")
    meta_ct.set("http-equiv", "Content-Type")
    meta_ct.set("content", "text/html;charset=utf-8")
    meta_ocr = etree.SubElement(head, "meta")
    meta_ocr.set("name", "ocr-system")
    meta_ocr.set("content", "flexiconv")
    meta_cap = etree.SubElement(head, "meta")
    meta_cap.set("name", "ocr-capabilities")
    meta_cap.set("content", "ocr_page ocr_carea ocr_par ocr_line ocrx_word")
    root.append(body)
    tree = etree.ElementTree(root)
    root.set("xmlns", "http://www.w3.org/1999/xhtml")
    tree.write(
        path,
        encoding="utf-8",
        xml_declaration=True,
        pretty_print=True,
        method="xml",
    )


def _tei_to_hocr_body(tei_root: etree._Element, *, facs_base: Optional[str] = None) -> etree._Element:
    """Build hOCR body from TEI text (pb → ocr_page, p → ocr_carea+ocr_par, lb → ocr_line, tok → ocrx_word)."""
    body = etree.Element("body")
    children = _tei_text_children(tei_root)
    page_idx = 0
    for node in children:
        tag = (node.tag or "").split("}")[-1]
        if tag == "pb":
            page_idx += 1
            bbox = node.get("bbox", "")
            facs = node.get("facs", "")
            if facs_base and facs:
                facs = facs_base + os.path.basename(facs)
            title_parts = []
            if facs:
                title_parts.append(f'image "{facs}"')
            if bbox:
                title_parts.append(f"bbox {bbox}")
            title_parts.append("ppageno 0")
            title_parts.append("scan_res 70 70")
            page_div = etree.SubElement(body, "div")
            page_div.set("class", "ocr_page")
            page_div.set("id", f"page_{page_idx}")
            page_div.set("title", "; ".join(title_parts))
            _current_page = page_div
            _par_idx = 0
            _current_par = None
            _current_line = None
            _line_idx = 0  # per-page
            _word_idx = 0  # per-page
        elif tag in ("p", "div") and _current_page is not None:
            _par_idx += 1
            bbox = node.get("bbox", "")
            carea = etree.SubElement(_current_page, "div")
            carea.set("class", "ocr_carea")
            carea.set("id", f"block_{page_idx}_{_par_idx}")
            carea.set("title", f"bbox {bbox}" if bbox else "")
            par = etree.SubElement(carea, "p")
            par.set("class", "ocr_par")
            par.set("id", f"par_{page_idx}_{_par_idx}")
            par.set("lang", "en")
            par.set("title", f"bbox {bbox}" if bbox else "")
            _current_par = par
            _current_line = None
            for ch in node:
                local = (ch.tag or "").split("}")[-1]
                if local == "lb":
                    _line_idx += 1
                    bbox_l = ch.get("bbox", "")
                    span = etree.SubElement(par, "span")
                    span.set("class", "ocr_line")
                    span.set("id", f"line_{page_idx}_{_line_idx}")
                    span.set("title", f"bbox {bbox_l}" if bbox_l else "")
                    _current_line = span
                elif local == "tok":
                    _word_idx += 1
                    if _current_line is None:
                        _line_idx += 1
                        span = etree.SubElement(par, "span")
                        span.set("class", "ocr_line")
                        span.set("id", f"line_{page_idx}_{_line_idx}")
                        span.set("title", "bbox 0 0 0 0")
                        _current_line = span
                    word_span = etree.SubElement(_current_line, "span")
                    word_span.set("class", "ocrx_word")
                    word_span.set("id", f"word_{page_idx}_{_word_idx}")
                    bbox_w = ch.get("bbox", "")
                    word_span.set("title", f"bbox {bbox_w}; x_wconf 90" if bbox_w else "x_wconf 90")
                    word_span.text = (ch.text or "").strip()
            _current_line = None
        else:
            continue
    return body
