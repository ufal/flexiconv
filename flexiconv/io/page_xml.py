"""
PAGE XML (PageXML) to TEITOK-style TEI conversion.

This implements the core mapping:
- <PcGts>/<Page>      -> TEI <pb> with facs (imageFilename)
- <TextRegion>        -> TEI <div> with bbox (from Coords points)
- <TextLine>          -> TEI <lb> with bbox
- <Word>              -> TEI <tok> with bbox (plus optional split-off punctuation <tok> without bbox)

The resulting TEI tree is stored in Document.meta["_teitok_tei_root"] so that save_teitok
can write it verbatim and round-trip behaviour stays close to the original Perl converter.

Non-tokenized lines (TextLine without Word children) and PAGE @custom-based inline
annotations are currently not converted; their text is appended as plain content in the
surrounding <div>. This covers the common "tokenized PAGE with Word elements" case.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from lxml import etree

from ..core.model import Document
from .hocr import _split_punct, _text_content


def _make_bbox_from_points(points: str) -> str:
    """
    Convert PAGE points attribute "x1,y1 x2,y2 ..." to bbox "xmin ymin xmax ymax".
    """
    if not points:
        return ""
    xmin = ymin = 10**12
    xmax = ymax = 0
    for item in points.split():
        try:
            x_str, y_str = item.split(",", 1)
            x = float(x_str)
            y = float(y_str)
        except ValueError:
            continue
        if x < xmin:
            xmin = x
        if x > xmax:
            xmax = x
        if y < ymin:
            ymin = y
        if y > ymax:
            ymax = y
    if xmax < xmin or ymax < ymin:
        return ""
    return f"{int(xmin)} {int(ymin)} {int(xmax)} {int(ymax)}"


def _ensure_simple_header_for_page(
    tei: etree._Element,
    source_filename: Optional[str],
    who: str = "flexiconv",
) -> None:
    """Create a minimal TEI header with a revisionDesc change."""
    header = etree.SubElement(tei, "teiHeader")
    rev = etree.SubElement(header, "revisionDesc")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    change = etree.SubElement(rev, "change", when=today, who=who)
    basename = os.path.splitext(source_filename or "")[0]
    change.text = f"Converted from PageXML file {basename}.xml"


def pagexml_to_tei_tree(
    path: str,
    *,
    strippath: bool = False,
    nopunct: bool = False,
    noretoken: bool = False,  # currently unused; kept for API
) -> etree._Element:
    """
    Convert a PAGE XML file to a TEITOK-style TEI element tree.

    Structure:
    - <facsimile>/<surface>/<zone> elements with points for Page/TextRegion/TextLine/Word
    - <text> with <pb>, <div>, <lb>, <tok>

    Punctuation is optionally split off into separate <tok> (without bbox), similar to hOCR.
    """
    tree = etree.parse(path)
    root = tree.getroot()
    if root is None or root.tag is None or root.tag.split("}")[-1] != "PcGts":
        raise ValueError("Not a PAGE XML (PcGts) document")

    basename = os.path.splitext(os.path.basename(path))[0]

    tei = etree.Element("TEI")
    _ensure_simple_header_for_page(tei, source_filename=basename + ".xml")

    facs_el = etree.SubElement(tei, "facsimile")
    text_el = etree.SubElement(tei, "text")

    fnr = 0  # page counter
    enr = 0  # generic element counter for @id
    lnr = 0  # global line counter

    # Iterate all <Page> elements regardless of namespace.
    for page in root.xpath(".//*[local-name()='Page']"):
        fnr += 1
        facs_id = f"facs-{fnr}"
        enr += 1
        page_id = f"e-{enr}"

        image_url = page.get("imageFilename") or ""
        if image_url and not strippath:
            image_url = f"{basename}/{image_url}"

        # facsimile/surface for this page
        surface = etree.SubElement(facs_el, "surface", id=facs_id)
        if image_url:
            surface.set("facs", image_url)

        # text: page break with facs link
        pb = etree.SubElement(text_el, "pb", id=page_id)
        if image_url:
            pb.set("facs", image_url)

        # Regions
        area_idx = 0
        for area in page.xpath("./*[local-name()='TextRegion']"):
            area_idx += 1
            coords_elems = area.xpath("./*[local-name()='Coords']")
            points = coords_elems[0].get("points") if coords_elems else ""
            bbox = _make_bbox_from_points(points)

            facs_id2 = f"facs-{fnr}.a{area_idx}"
            enr += 1
            div_id = f"e-{enr}"

            # Zone for region
            zone_region = etree.SubElement(
                surface,
                "zone",
                id=facs_id2,
                rendition="TextRegion",
            )
            if points:
                zone_region.set("points", points)

            # Corresponding <div> in text
            div = etree.SubElement(text_el, "div", id=div_id, corresp=f"#{facs_id2}")
            if bbox:
                div.set("bbox", bbox)

            # Lines
            for line in area.xpath("./*[local-name()='TextLine']"):
                coords_line = line.xpath("./*[local-name()='Coords']")
                points_line = coords_line[0].get("points") if coords_line else ""
                bbox_line = _make_bbox_from_points(points_line)

                lnr += 1
                facs_id3 = f"facs-{fnr}.l{lnr}"
                lb_id = f"lb-{fnr}.{lnr}"

                # Zone for line
                zone_line = etree.SubElement(
                    surface,
                    "zone",
                    id=facs_id3,
                    rendition="Line",
                )
                if points_line:
                    zone_line.set("points", points_line)

                # Line break in text: always start a new line before each <lb/> at div level.
                if len(div) == 0:
                    # First child inside this <div>: newline in div.text.
                    div.text = "\n"
                else:
                    # Subsequent lines: put newline in the previous child's tail.
                    prev = div[-1]
                    prev.tail = (prev.tail or "") + "\n"
                lb = etree.SubElement(div, "lb", id=lb_id, corresp=f"#{facs_id3}")
                if bbox_line:
                    lb.set("bbox", bbox_line)

                # Tokenized lines (Word children)
                words = line.xpath("./*[local-name()='Word']")
                if words:
                    wnr = 0
                    for w_idx, word in enumerate(words):
                        coords_word = word.xpath("./*[local-name()='Coords']")
                        points_word = coords_word[0].get("points") if coords_word else ""
                        bbox_word = _make_bbox_from_points(points_word)

                        wnr += 1
                        facs_id4 = f"facs-{fnr}.l{lnr}.w{wnr}"
                        tok_id = f"w-{fnr}.{lnr}.{wnr}"

                        # Zone for word
                        zone_word = etree.SubElement(
                            surface,
                            "zone",
                            id=facs_id4,
                            rendition="Word",
                        )
                        if points_word:
                            zone_word.set("points", points_word)

                        tok_text = ""
                        unicode_elems = word.xpath("./*[local-name()='TextEquiv']/*[local-name()='Unicode']")
                        if unicode_elems:
                            tok_text = _text_content(unicode_elems[0])
                        tok_text = tok_text.strip()
                        if not tok_text:
                            continue

                        if nopunct:
                            tok = etree.SubElement(div, "tok", id=tok_id, corresp=f"#{facs_id4}")
                            if bbox_word:
                                tok.set("bbox", bbox_word)
                            tok.text = tok_text
                            # Space to next word on the same line
                            if w_idx < len(words) - 1:
                                tok.tail = " "
                        else:
                            segments = _split_punct(tok_text)
                            last_tok_for_word: Optional[etree._Element] = None
                            for seg, is_punct in segments:
                                if not seg:
                                    continue
                                # Trailing/leading punctuation as separate <tok> without bbox
                                tok = etree.SubElement(div, "tok")
                                if not is_punct:
                                    tok.set("id", tok_id)
                                    tok.set("corresp", f"#{facs_id4}")
                                    if bbox_word:
                                        tok.set("bbox", bbox_word)
                                tok.text = seg
                                last_tok_for_word = tok
                            # Space after the *word* (after its last segment), to next word on line
                            if last_tok_for_word is not None and w_idx < len(words) - 1:
                                last_tok_for_word.tail = " "
                else:
                    # Non-tokenized lines: append raw line text into the div (no inline markup for now)
                    unicode_elems = line.xpath("./*[local-name()='TextEquiv']/*[local-name()='Unicode']")
                    linetext = _text_content(unicode_elems[0]) if unicode_elems else ""
                    linetext = linetext.strip()
                    if linetext:
                        # Keep a leading space so it doesn't glue to previous token
                        if div.text:
                            div.text += " " + linetext
                        else:
                            div.text = linetext

    return tei


def load_page_xml(
    path: str,
    *,
    doc_id: Optional[str] = None,
    strippath: bool = False,
    nopunct: bool = False,
    noretoken: bool = False,
) -> Document:
    """
    Load a PAGE XML file into a pivot Document.

    - The PAGE → TEI mapping is implemented in pagexml_to_tei_tree().
    - The resulting TEI root is stored in Document.meta['_teitok_tei_root'] so that
      save_teitok can write it verbatim.

    Parameters roughly mirror the PAGE→TEI mapping:
    - strippath: strip directory from facs (imageFilename) paths.
    - nopunct: do not split off punctuation marks.
    - noretoken: reserved for future retokenization/merging across linebreaks.
    """
    tei_root = pagexml_to_tei_tree(
        path,
        strippath=strippath,
        nopunct=nopunct,
        noretoken=noretoken,
    )
    if doc_id is None:
        doc_id = path
    doc = Document(id=doc_id)
    doc.meta["source_filename"] = os.path.basename(path)
    doc.meta["_teitok_tei_root"] = tei_root
    return doc

