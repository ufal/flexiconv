"""
ALTO XML → TEITOK-style TEI conversion.

ALTO (Analyzed Layout and Text Object) encodes OCR text and layout with
<Page>/<PrintSpace>/<TextBlock>/<TextLine>/<String>. This module builds a
TEITOK-style TEI tree with:

- <facsimile>/<surface>/<zone> for pages, text blocks, and lines
- <text> with <pb> (per page), <div> (per TextBlock), <lb> (per TextLine),
  and <tok> (per String, with bbox from HPOS/VPOS/WIDTH/HEIGHT)

The resulting TEI tree is stored in Document.meta["_teitok_tei_root"] so that
save_teitok can write it verbatim. We follow the same general structure as
the PAGE XML converter (page_xml.py).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from lxml import etree

from ..core.model import Document
from .hocr import _split_punct
from .teitok_xml import _ensure_tei_header


def _bbox_from_alto(el: etree._Element) -> str:
    """Convert ALTO HPOS/VPOS/WIDTH/HEIGHT to bbox string 'xmin ymin xmax ymax'."""
    try:
        hpos = float(el.get("HPOS") or "0")
        vpos = float(el.get("VPOS") or "0")
        width = float(el.get("WIDTH") or "0")
        height = float(el.get("HEIGHT") or "0")
    except ValueError:
        return ""
    if width <= 0 or height <= 0:
        return ""
    xmin = int(hpos)
    ymin = int(vpos)
    xmax = int(hpos + width)
    ymax = int(vpos + height)
    return f"{xmin} {ymin} {xmax} {ymax}"


def alto_to_tei_tree(
    path: str,
    *,
    nopunct: bool = False,
) -> etree._Element:
    """
    Convert an ALTO XML file to a TEITOK-style TEI element tree.

    Structure:
    - <facsimile>/<surface>/<zone> elements for Page/TextBlock/TextLine
    - <text> with <pb>, <div>, <lb>, <tok> (per String)

    Punctuation is optionally split off into separate <tok> (without bbox),
    similar to hOCR and PAGE XML handling.
    """
    tree = etree.parse(path)
    root = tree.getroot()
    if root is None or root.tag is None or root.tag.split("}")[-1].lower() != "alto":
        raise ValueError("Not an ALTO document (root element is not <alto>)")

    base = os.path.basename(path)
    stem, _ = os.path.splitext(base)
    when_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    tei = etree.Element("TEI")
    _ensure_tei_header(tei, source_filename=base, when=when_iso)

    facs_el = etree.SubElement(tei, "facsimile")
    text_el = etree.SubElement(tei, "text", id=stem)

    # Optional: try to find a global source image filename in Description/sourceImageInformation/fileName.
    image_url: Optional[str] = None
    file_name_nodes = root.xpath(
        ".//*[local-name()='Description']/*[local-name()='sourceImageInformation']/*[local-name()='fileName']"
    )
    if file_name_nodes:
        image_url = "".join(file_name_nodes[0].itertext()).strip() or None

    page_idx = 0
    line_global_idx = 0

    for page in root.xpath(".//*[local-name()='Page']"):
        page_idx += 1
        page_id = page.get("ID") or f"page-{page_idx}"

        # Prefer per-page image file reference when available; otherwise fall back to global one.
        page_image = image_url
        page_file_nodes = page.xpath(".//*[local-name()='fileName']")
        if page_file_nodes:
            txt = "".join(page_file_nodes[0].itertext()).strip()
            if txt:
                page_image = txt

        facs_id = f"facs-{page_idx}"
        surface = etree.SubElement(facs_el, "surface", id=facs_id)
        if page_image:
            surface.set("facs", page_image)

        pb = etree.SubElement(text_el, "pb", id=page_id)
        if page_image:
            pb.set("facs", page_image)

        # Use PrintSpace when present; otherwise treat the whole Page as a single region.
        print_space_nodes = page.xpath("./*[local-name()='PrintSpace']")
        regions_parent = print_space_nodes[0] if print_space_nodes else page

        block_idx = 0
        for block in regions_parent.xpath("./*[local-name()='TextBlock']"):
            block_idx += 1
            bbox_block = _bbox_from_alto(block)
            facs_block_id = f"{facs_id}.b{block_idx}"
            div_id = f"{page_id}.b{block_idx}"

            # Zone for TextBlock on the facsimile surface.
            zone_block = etree.SubElement(
                surface,
                "zone",
                id=facs_block_id,
                rendition="TextBlock",
            )
            if bbox_block:
                zone_block.set("bbox", bbox_block)

            # Corresponding <div> in the TEI text.
            div = etree.SubElement(text_el, "div", id=div_id, corresp=f"#{facs_block_id}")
            if bbox_block:
                div.set("bbox", bbox_block)

            # TextLines within the block.
            for line in block.xpath("./*[local-name()='TextLine']"):
                bbox_line = _bbox_from_alto(line)

                line_global_idx += 1
                facs_line_id = f"{facs_block_id}.l{line_global_idx}"
                lb_id = f"lb-{page_idx}.{line_global_idx}"

                zone_line = etree.SubElement(
                    surface,
                    "zone",
                    id=facs_line_id,
                    rendition="Line",
                )
                if bbox_line:
                    zone_line.set("bbox", bbox_line)

                # New line break in text, similar to PAGE XML.
                if len(div) == 0:
                    div.text = "\n"
                else:
                    prev = div[-1]
                    prev.tail = (prev.tail or "") + "\n"
                lb = etree.SubElement(div, "lb", id=lb_id, corresp=f"#{facs_line_id}")
                if bbox_line:
                    lb.set("bbox", bbox_line)

                # Strings (words) in reading order.
                strings = line.xpath("./*[local-name()='String']")
                if not strings:
                    continue

                for w_idx, string_el in enumerate(strings, start=1):
                    bbox_word = _bbox_from_alto(string_el)
                    tok_id = string_el.get("ID") or f"w-{page_idx}.{line_global_idx}.{w_idx}"
                    text = string_el.get("CONTENT") or ""
                    text = text.strip()
                    if not text:
                        continue

                    if nopunct:
                        tok = etree.SubElement(div, "tok", id=tok_id, corresp=f"#{facs_line_id}")
                        if bbox_word:
                            tok.set("bbox", bbox_word)
                        tok.text = text
                        if w_idx < len(strings):
                            tok.tail = " "
                    else:
                        segments = _split_punct(text)
                        last_tok_for_word: Optional[etree._Element] = None
                        for seg, is_punct in segments:
                            if not seg:
                                continue
                            tok = etree.SubElement(div, "tok")
                            if not is_punct:
                                tok.set("id", tok_id)
                                tok.set("corresp", f"#{facs_line_id}")
                                if bbox_word:
                                    tok.set("bbox", bbox_word)
                            tok.text = seg
                            last_tok_for_word = tok
                        if last_tok_for_word is not None and w_idx < len(strings):
                            last_tok_for_word.tail = " "

    return tei


def load_alto(
    path: str,
    *,
    doc_id: Optional[str] = None,
    nopunct: bool = False,
) -> Document:
    """Load an ALTO XML file into a pivot Document with TEITOK-style TEI in meta."""
    tei_root = alto_to_tei_tree(path, nopunct=nopunct)
    if doc_id is None:
        doc_id = path
    doc = Document(id=doc_id)
    doc.meta["source_filename"] = os.path.basename(path)
    doc.meta["_teitok_tei_root"] = tei_root
    return doc

