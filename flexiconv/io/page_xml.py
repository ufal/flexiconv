"""
PAGE XML (PageXML) to TEITOK-style TEI conversion.

This implements the core mapping:
- <PcGts>/<Page>      -> TEI <pb> with facs (imageFilename) and corresp to <surface>
- <TextRegion>        -> TEI <div> with bbox (from Coords points)
- <TextLine>          -> TEI <lb> with bbox
- <Word>              -> TEI <tok> with bbox (plus optional split-off punctuation <tok> without bbox)

The resulting TEI tree is stored in Document.meta["_teitok_tei_root"] so that save_teitok
can write it verbatim and round-trip behaviour stays close to the original Perl converter.

Non-tokenized lines (TextLine without Word children) emit plain text after each <lb>.
TextRegion @type and structure {type:…;} from @custom are copied to the TEI <div type="…">.
TextRegions with readingOrder {index:…;} in @custom are emitted in that order.
Other PAGE @custom inline annotations are not converted yet.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from lxml import etree

from ..core.model import Document
from ..mime import path_to_input_format
from .hocr import _split_punct, _text_content

_NATURAL_SORT_RE = re.compile(r"(\d+)")


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


def _parse_page_custom(custom: str) -> dict[str, str]:
    """Parse PAGE @custom chunks like 'readingOrder {index:0;} structure {type:paragraph;}'."""
    out: dict[str, str] = {}
    if not custom:
        return out
    for chunk in custom.split("}"):
        chunk = chunk.strip()
        if not chunk or "{" not in chunk:
            continue
        key, value = chunk.split("{", 1)
        key = key.strip()
        value = value.strip().rstrip(";")
        if key:
            out[key] = value
    return out


def _custom_field_value(custom_map: dict[str, str], field: str, key: str) -> str:
    """Extract a key from a semicolon-separated @custom field (e.g. type from structure)."""
    block = custom_map.get(field, "")
    for item in block.split(";"):
        item = item.strip()
        if item.startswith(f"{key}:"):
            return item[len(key) + 1 :].strip()
    return ""


def _text_region_type(area: etree._Element) -> str:
    """Region type from @type or structure {type:…;} in @custom."""
    direct = (area.get("type") or "").strip()
    if direct:
        return direct
    custom_map = _parse_page_custom(area.get("custom") or "")
    return _custom_field_value(custom_map, "structure", "type")


def _text_region_reading_order(area: etree._Element) -> Optional[int]:
    """readingOrder {index:N;} from @custom, if present."""
    custom_map = _parse_page_custom(area.get("custom") or "")
    raw = _custom_field_value(custom_map, "readingOrder", "index")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _text_regions_in_reading_order(page: etree._Element) -> list[etree._Element]:
    """TextRegion children sorted by readingOrder index when declared, else document order."""
    areas = page.xpath("./*[local-name()='TextRegion']")
    indexed = [(i, area, _text_region_reading_order(area)) for i, area in enumerate(areas)]
    indexed.sort(key=lambda t: (t[2] is None, t[2] if t[2] is not None else t[0], t[0]))
    return [area for _, area, _ in indexed]


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


def _ensure_simple_header_for_merge(
    tei: etree._Element,
    source_paths: list[str],
    who: str = "flexiconv",
) -> None:
    """Create a minimal TEI header when merging multiple PageXML files."""
    header = etree.SubElement(tei, "teiHeader")
    rev = etree.SubElement(header, "revisionDesc")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    change = etree.SubElement(rev, "change", when=today, who=who)
    parent = os.path.basename(os.path.dirname(source_paths[0])) if source_paths else ""
    if parent:
        change.text = (
            f"Converted from {len(source_paths)} PageXML file(s) in {parent}"
        )
    else:
        change.text = f"Converted from {len(source_paths)} PageXML file(s)"


@dataclass
class _PageCounters:
    fnr: int = 0
    enr: int = 0
    lnr: int = 0


def _pagexml_sort_key(path: str) -> tuple:
    """Natural sort key for page filenames (page-2 before page-10)."""
    base = os.path.basename(path).lower()
    parts = _NATURAL_SORT_RE.split(base)
    key: list[tuple[int, int | str]] = []
    for part in parts:
        if part.isdigit():
            key.append((0, int(part)))
        else:
            key.append((1, part))
    return tuple(key)


def _is_pagexml_file(path: str) -> bool:
    return os.path.isfile(path) and path_to_input_format(path) == "pagexml"


def collect_pagexml_files(directory: str, *, recursive: bool = False) -> list[str]:
    """Collect PageXML files from a directory, sorted in natural page order."""
    files: list[str] = []
    if recursive:
        for root, _dirs, fnames in os.walk(directory):
            for fname in fnames:
                path = os.path.join(root, fname)
                if _is_pagexml_file(path):
                    files.append(path)
    else:
        for fname in os.listdir(directory):
            path = os.path.join(directory, fname)
            if _is_pagexml_file(path):
                files.append(path)
    return sorted(files, key=_pagexml_sort_key)


def _append_page_to_tei(
    page: etree._Element,
    *,
    source_basename: str,
    facs_el: etree._Element,
    text_el: etree._Element,
    counters: _PageCounters,
    strippath: bool = False,
    nopunct: bool = False,
) -> None:
    """Append one PAGE <Page> element to an in-progress TEITOK TEI tree."""
    counters.fnr += 1
    fnr = counters.fnr
    facs_id = f"facs-{fnr}"
    counters.enr += 1
    page_id = f"e-{counters.enr}"

    image_url = page.get("imageFilename") or ""
    if image_url and not strippath:
        image_url = f"{source_basename}/{image_url}"

    surface = etree.SubElement(facs_el, "surface", id=facs_id)
    if image_url:
        surface.set("facs", image_url)

    pb = etree.SubElement(text_el, "pb", id=page_id, corresp=f"#{facs_id}")
    if image_url:
        pb.set("facs", image_url)

    for area_idx, area in enumerate(_text_regions_in_reading_order(page), start=1):
        coords_elems = area.xpath("./*[local-name()='Coords']")
        points = coords_elems[0].get("points") if coords_elems else ""
        bbox = _make_bbox_from_points(points)
        region_type = _text_region_type(area)

        facs_id2 = f"facs-{fnr}.a{area_idx}"
        counters.enr += 1
        div_id = f"e-{counters.enr}"

        zone_region = etree.SubElement(
            surface,
            "zone",
            id=facs_id2,
            rendition="TextRegion",
        )
        if points:
            zone_region.set("points", points)
        if region_type:
            zone_region.set("subtype", region_type)

        div = etree.SubElement(text_el, "div", id=div_id, corresp=f"#{facs_id2}")
        if bbox:
            div.set("bbox", bbox)
        if region_type:
            div.set("type", region_type)

        for line in area.xpath("./*[local-name()='TextLine']"):
            coords_line = line.xpath("./*[local-name()='Coords']")
            points_line = coords_line[0].get("points") if coords_line else ""
            bbox_line = _make_bbox_from_points(points_line)

            counters.lnr += 1
            lnr = counters.lnr
            facs_id3 = f"facs-{fnr}.l{lnr}"
            lb_id = f"lb-{fnr}.{lnr}"

            zone_line = etree.SubElement(
                surface,
                "zone",
                id=facs_id3,
                rendition="Line",
            )
            if points_line:
                zone_line.set("points", points_line)

            if len(div) == 0:
                div.text = "\n"
            else:
                prev = div[-1]
                prev.tail = (prev.tail or "") + "\n"
            lb = etree.SubElement(div, "lb", id=lb_id, corresp=f"#{facs_id3}")
            if bbox_line:
                lb.set("bbox", bbox_line)

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

                    zone_word = etree.SubElement(
                        surface,
                        "zone",
                        id=facs_id4,
                        rendition="Word",
                    )
                    if points_word:
                        zone_word.set("points", points_word)

                    tok_text = ""
                    unicode_elems = word.xpath(
                        "./*[local-name()='TextEquiv']/*[local-name()='Unicode']"
                    )
                    if unicode_elems:
                        tok_text = _text_content(unicode_elems[0])
                    tok_text = tok_text.strip()
                    if not tok_text:
                        continue

                    if nopunct:
                        tok = etree.SubElement(
                            div, "tok", id=tok_id, corresp=f"#{facs_id4}"
                        )
                        if bbox_word:
                            tok.set("bbox", bbox_word)
                        tok.text = tok_text
                        if w_idx < len(words) - 1:
                            tok.tail = " "
                    else:
                        segments = _split_punct(tok_text)
                        last_tok_for_word: Optional[etree._Element] = None
                        for seg, is_punct in segments:
                            if not seg:
                                continue
                            tok = etree.SubElement(div, "tok")
                            if not is_punct:
                                tok.set("id", tok_id)
                                tok.set("corresp", f"#{facs_id4}")
                                if bbox_word:
                                    tok.set("bbox", bbox_word)
                            tok.text = seg
                            last_tok_for_word = tok
                        if last_tok_for_word is not None and w_idx < len(words) - 1:
                            last_tok_for_word.tail = " "
            else:
                unicode_elems = line.xpath(
                    "./*[local-name()='TextEquiv']/*[local-name()='Unicode']"
                )
                linetext = _text_content(unicode_elems[0]) if unicode_elems else ""
                linetext = linetext.strip()
                if linetext:
                    lb.tail = (lb.tail or "") + linetext


def _pages_from_pagexml_path(path: str) -> list[etree._Element]:
    tree = etree.parse(path)
    root = tree.getroot()
    if root is None or root.tag is None or root.tag.split("}")[-1] != "PcGts":
        raise ValueError(f"Not a PAGE XML (PcGts) document: {path}")
    return root.xpath(".//*[local-name()='Page']")


def pagexml_merge_to_tei_tree(
    paths: list[str],
    *,
    strippath: bool = False,
    nopunct: bool = False,
    noretoken: bool = False,  # currently unused; kept for API
) -> etree._Element:
    """
    Convert multiple PageXML files into one TEITOK-style TEI element tree.

    Files are processed in natural sort order (page-2 before page-10). Each file's
    <Page> element(s) become sequential <pb> breaks with continuous facsimile ids.
    """
    if not paths:
        raise ValueError("No PageXML files to merge")

    tei = etree.Element("TEI")
    _ensure_simple_header_for_merge(tei, paths)

    facs_el = etree.SubElement(tei, "facsimile")
    text_el = etree.SubElement(tei, "text")
    counters = _PageCounters()

    for path in paths:
        source_basename = os.path.splitext(os.path.basename(path))[0]
        for page in _pages_from_pagexml_path(path):
            _append_page_to_tei(
                page,
                source_basename=source_basename,
                facs_el=facs_el,
                text_el=text_el,
                counters=counters,
                strippath=strippath,
                nopunct=nopunct,
            )

    if counters.fnr == 0:
        raise ValueError("No <Page> elements found in the given PageXML files")
    return tei


def merge_pagexml_dir_to_teitok(
    directory: str,
    output_path: str,
    *,
    recursive: bool = False,
    strippath: bool = False,
    nopunct: bool = False,
    prettyprint: bool = False,
    force: bool = False,
) -> str:
    """
    Merge PageXML files from a directory into one TEITOK XML file.

    Returns the output path written.
    """
    from .teitok_xml import save_teitok

    paths = collect_pagexml_files(directory, recursive=recursive)
    if not paths:
        raise ValueError(f"No PageXML files found in {directory}")

    if os.path.isfile(output_path) and not force:
        raise FileExistsError(f"Refusing to overwrite existing file: {output_path}")

    tei_root = pagexml_merge_to_tei_tree(
        paths,
        strippath=strippath,
        nopunct=nopunct,
    )
    doc = Document(id=directory)
    doc.meta["source_filename"] = os.path.basename(directory)
    doc.meta["_teitok_tei_root"] = tei_root
    save_teitok(
        doc,
        output_path,
        source_path=directory,
        prettyprint=prettyprint,
    )
    return output_path


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
    counters = _PageCounters()

    for page in root.xpath(".//*[local-name()='Page']"):
        _append_page_to_tei(
            page,
            source_basename=basename,
            facs_el=facs_el,
            text_el=text_el,
            counters=counters,
            strippath=strippath,
            nopunct=nopunct,
        )

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

