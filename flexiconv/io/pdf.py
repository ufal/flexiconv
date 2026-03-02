"""PDF to TEITOK-style TEI loader.

This is a best-effort text extractor built on pdfminer.six. It:
- extracts text per page and groups it into paragraph-like blocks
- preserves page boundaries
- optionally extracts images into a directory and references them from TEI
"""
from __future__ import annotations

import os
import tempfile
from datetime import date
from typing import Optional, Any
import re

from lxml import etree

from ..core.model import Document, Anchor, AnchorType, Node

# Lines starting with a bullet-like marker (•, -, –, *, ·) and a space
BULLET_RE = re.compile(r"^\s*([•\-–\*\u00B7])\s+")

# Tolerance in points for grouping lines into the same row (same y)
Y_ROW_TOLERANCE = 3.0


def _collect_line_records(blocks: list, text_classes: tuple, LTTextLine) -> list[tuple]:
    """Collect (y0, x0, runs, full_text) for each line across blocks, sorted top-to-bottom then left-to-right."""
    records: list[tuple] = []
    for block in blocks:
        for line in block:
            if not isinstance(line, LTTextLine):
                continue
            bbox = getattr(line, "bbox", None)
            if not bbox or len(bbox) != 4:
                continue
            x0, y0, x1, y1 = bbox
            runs = _collect_runs_from_line(line, text_classes)
            if not runs:
                continue
            full_text = "".join(txt for _, txt in runs).strip()
            if not full_text:
                continue
            records.append((float(y0), float(x0), runs, full_text))
    records.sort(key=lambda r: (-r[0], r[1]))
    return records


def _group_rows_by_y(
    records: list[tuple], tolerance: float = Y_ROW_TOLERANCE
) -> list[list[tuple]]:
    """Group line records by similar y into rows. Each row is list of (x0, runs, full_text) sorted by x0."""
    if not records:
        return []
    rows: list[list[tuple]] = []
    current_y: Optional[float] = None
    current_row: list[tuple] = []

    for y0, x0, runs, full_text in records:
        if current_y is not None and abs(y0 - current_y) <= tolerance:
            current_row.append((x0, runs, full_text))
        else:
            if current_row:
                current_row.sort(key=lambda t: t[0])
                rows.append(current_row)
            current_y = y0
            current_row = [(x0, runs, full_text)]
    if current_row:
        current_row.sort(key=lambda t: t[0])
        rows.append(current_row)
    return rows


def _find_table_regions(rows: list[list[tuple]]) -> list[tuple[int, int]]:
    """Find maximal contiguous table regions: consecutive rows each with 2+ cells. Returns [(start, end), ...]."""
    regions: list[tuple[int, int]] = []
    i = 0
    while i < len(rows):
        if len(rows[i]) >= 2:
            start = i
            while i < len(rows) and len(rows[i]) >= 2:
                i += 1
            regions.append((start, i))
        else:
            i += 1
    return regions


def _emit_runs_into(parent: etree._Element, runs: list[tuple[str, str]]) -> None:
    """Append content from (style, text) runs into parent: text or <hi style="...">, set parent.tail = newline."""
    last_el: Optional[etree._Element] = None
    for style, txt in runs:
        if not style:
            if parent.text is None and last_el is None:
                parent.text = txt
                last_el = parent
            else:
                target = last_el if last_el is not None else parent
                if target is parent:
                    parent.text = (parent.text or "") + txt
                else:
                    target.tail = (target.tail or "") + txt
        else:
            hi = etree.SubElement(parent, "hi")
            hi.set("style", style)
            hi.text = txt
            last_el = hi
    parent.tail = "\n"


def _unwrap_element(el: etree._Element) -> None:
    """Move el's text, children, and tail into its parent, then remove el."""
    parent = el.getparent()
    if parent is None:
        return
    idx = parent.index(el)
    text_before = el.text or ""
    tail_after = el.tail or ""
    children = list(el)
    for child in children:
        el.remove(child)
    parent.remove(el)
    if idx == 0:
        parent.text = (parent.text or "") + text_before
    else:
        parent[idx - 1].tail = (parent[idx - 1].tail or "") + text_before
    for i, child in enumerate(children):
        parent.insert(idx + i, child)
    if children:
        children[-1].tail = (children[-1].tail or "") + tail_after
    else:
        if idx == 0:
            parent.text = (parent.text or "") + tail_after
        else:
            parent[idx - 1].tail = (parent[idx - 1].tail or "") + tail_after


def _require_pdfminer():
    try:
        from pdfminer.high_level import extract_pages  # type: ignore
        from pdfminer.layout import (  # type: ignore
            LTTextContainer,
            LTTextBox,
            LTChar,
            LTAnno,
            LTImage,
            LTFigure,
            LTTextLine,
        )
    except ImportError as exc:
        raise RuntimeError(
            "PDF support requires the 'pdfminer.six' package. "
            "Install with: pip install 'flexiconv[pdf]'"
        ) from exc
    return extract_pages, (LTTextContainer, LTTextBox, LTChar, LTAnno, LTImage, LTFigure, LTTextLine)


def _iter_text_containers(layout, text_classes) -> list[Any]:
    """Return a flat list of LTTextContainer/LTTextBox on a page."""
    LTTextContainer, LTTextBox, *_ = text_classes
    out = []

    def walk(obj):
        if isinstance(obj, (LTTextContainer, LTTextBox)):
            out.append(obj)
        elif hasattr(obj, "__iter__"):
            for child in obj:
                walk(child)

    walk(layout)
    # Sort roughly top-to-bottom, then left-to-right
    out.sort(key=lambda t: (-getattr(t, "y1", 0.0), getattr(t, "x0", 0.0)))
    return out


def _extract_images_from_page(layout, image_dir: str, page_num: int, text_classes) -> list[str]:
    """Extract images (if any) from a page; return list of filenames."""
    *_, LTImage, LTFigure, _ = text_classes
    os.makedirs(image_dir, exist_ok=True)
    images: list[str] = []

    def walk(obj):
        if isinstance(obj, LTImage):
            stream = getattr(obj, "stream", None)
            if stream is None:
                return
            try:
                data = stream.get_data()
            except Exception:
                return
            # Guess extension from name or subtype; fall back to .bin
            name = getattr(obj, "name", "") or "img"
            ext = ".bin"
            for guess in (".jpg", ".jpeg", ".png", ".tiff", ".bmp"):
                if name.lower().endswith(guess):
                    ext = guess
                    break
            filename = f"page-{page_num}-img-{len(images)+1}{ext}"
            out_path = os.path.join(image_dir, filename)
            try:
                with open(out_path, "wb") as f:
                    f.write(data)
                images.append(filename)
            except OSError:
                return
        elif isinstance(obj, LTFigure) or hasattr(obj, "__iter__"):
            for child in obj:
                walk(child)

    walk(layout)
    return images


def _classify_char_style(ch: Any) -> str:
    """Return a CSS-like style string for a pdfminer LTChar."""
    parts: list[str] = []
    size = getattr(ch, "size", None)
    if isinstance(size, (int, float)):
        parts.append(f"font-size: {size:.1f}pt;")
    fontname = (getattr(ch, "fontname", "") or "").lower()
    if "bold" in fontname:
        parts.append("font-weight: bold;")
    if "italic" in fontname or "oblique" in fontname:
        parts.append("font-style: italic;")
    return " ".join(parts)


def _collect_runs(block: Any, text_classes) -> list[tuple[str, str]]:
    """Collect (style, text) runs from a text block using LTChar styling."""
    *_, _, LTTextLine = text_classes
    runs: list[tuple[str, str]] = []
    current_style = ""
    buffer: list[str] = []

    def flush():
        nonlocal buffer, current_style
        if buffer:
            text = "".join(buffer)
            # Normalise whitespace inside the run and ensure a trailing space so
            # neighbouring runs do not collapse words together.
            norm = " ".join(text.split())
            if norm and not norm.endswith(" "):
                norm += " "
            if norm:
                runs.append((current_style, norm))
        buffer = []

    for line in block:
        if not isinstance(line, LTTextLine):
            continue
        for obj in line:
            from pdfminer.layout import LTChar as _LTChar, LTAnno as _LTAnno  # type: ignore
            if isinstance(obj, _LTChar):
                ch = obj.get_text()
                if not ch:
                    continue
                style = _classify_char_style(obj)
                # Treat all whitespace uniformly; they will be normalised later.
                if ch.isspace():
                    ch = " "
                if style != current_style:
                    flush()
                    current_style = style
                buffer.append(ch)
            elif isinstance(obj, _LTAnno):
                # LTAnno usually represents spaces or newlines; normalise to space.
                text = obj.get_text()
                if text and text.isspace():
                    if buffer and buffer[-1] != " ":
                        buffer.append(" ")
        # Treat line break as a space between lines in the same block.
        if buffer and buffer[-1] != " ":
            buffer.append(" ")
    flush()
    return runs


def _collect_runs_from_line(line: Any, text_classes) -> list[tuple[str, str]]:
    """Collect (style, text) runs from a single LTTextLine."""
    runs: list[tuple[str, str]] = []
    current_style = ""
    buffer: list[str] = []

    def flush():
        nonlocal buffer, current_style
        if buffer:
            text = "".join(buffer)
            norm = " ".join(text.split())
            if norm and not norm.endswith(" "):
                norm += " "
            if norm:
                runs.append((current_style, norm))
        buffer = []

    from pdfminer.layout import LTChar as _LTChar, LTAnno as _LTAnno  # type: ignore

    for obj in line:
        if isinstance(obj, _LTChar):
            ch = obj.get_text()
            if not ch:
                continue
            style = _classify_char_style(obj)
            if ch.isspace():
                ch = " "
            if style != current_style:
                flush()
                current_style = style
            buffer.append(ch)
        elif isinstance(obj, _LTAnno):
            text = obj.get_text()
            if text and text.isspace():
                if buffer and buffer[-1] != " ":
                    buffer.append(" ")
    flush()
    return runs


def pdf_to_tei_tree(
    path: str,
    *,
    orgfile: Optional[str] = None,
    image_dir: Optional[str] = None,
    image_reldir: Optional[str] = None,
    smart: bool = True,
    tidy_hi: bool = True,
) -> tuple[etree._Element, Optional[str]]:
    """Convert a PDF file to a TEITOK-style TEI tree.

    Returns (tei_root, image_dir_used).
    """
    extract_pages, text_classes = _require_pdfminer()
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
    change.text = "Converted from PDF file " + path
    titlestmt = etree.SubElement(filedesc, "titleStmt")
    profiledesc = etree.SubElement(tei_header, "profileDesc")

    # Basic metadata from PDF Info is not handled here; could be added later.

    # Decide image dir
    used_image_dir: Optional[str]
    if image_dir is None:
        used_image_dir = tempfile.mkdtemp(prefix="flexiconv_pdf_")
    else:
        used_image_dir = os.path.abspath(image_dir)
    if image_reldir is None:
        image_reldir = os.path.basename(used_image_dir)

    any_text = False
    any_images = False

    for page_num, layout in enumerate(extract_pages(path), 1):
        page_div = etree.SubElement(body, "div")
        page_div.set("type", "page")
        page_div.set("n", str(page_num))

        text_blocks = _iter_text_containers(layout, text_classes)
        *_, _, LTTextLine = text_classes
        current_list: Optional[etree._Element] = None
        current_table: Optional[etree._Element] = None
        if not smart:
            # Simple mode: one paragraph per text block, no list detection, no inline styles
            for block in text_blocks:
                raw_text = block.get_text() or ""
                normalized = " ".join(raw_text.split())
                if not normalized:
                    continue
                any_text = True
                p = etree.SubElement(page_div, "p")
                p.text = normalized
                p.tail = "\n"
                current_list = None
        else:
            # Smart mode: geometry-based table detection, then paragraphs/lists with inline styles.
            line_records = _collect_line_records(text_blocks, text_classes, LTTextLine)
            rows = _group_rows_by_y(line_records)
            table_regions = _find_table_regions(rows)
            table_row_indices = set()
            for start, end in table_regions:
                for idx in range(start, end):
                    table_row_indices.add(idx)

            current_table: Optional[etree._Element] = None
            for row_idx, row in enumerate(rows):
                in_table = row_idx in table_row_indices
                if in_table:
                    if current_table is None:
                        current_table = etree.SubElement(page_div, "table")
                    current_list = None
                    row_el = etree.SubElement(current_table, "row")
                    for _x0, runs, _full_text in row:
                        cell_el = etree.SubElement(row_el, "cell")
                        p = etree.SubElement(cell_el, "p")
                        _emit_runs_into(p, runs)
                    any_text = True
                else:
                    current_table = None
                    # Single logical row: one or more lines at same y; we emit one p or one list item per first line (single-item rows)
                    for cell_idx, (x0, runs, full_text) in enumerate(row):
                        m = BULLET_RE.match(full_text)
                        is_bullet = m is not None
                        if is_bullet:
                            bullet_text = m.group(0)
                            to_strip = len(bullet_text)
                            new_runs: list[tuple[str, str]] = []
                            remaining = to_strip
                            for style, txt in runs:
                                if remaining <= 0:
                                    new_runs.append((style, txt))
                                    continue
                                if len(txt) <= remaining:
                                    remaining -= len(txt)
                                    continue
                                new_runs.append((style, txt[remaining:]))
                                remaining = 0
                            runs = new_runs
                            full_text = "".join(txt for _, txt in runs).strip()
                            if not full_text:
                                continue
                        any_text = True
                        if is_bullet:
                            if current_list is None:
                                current_list = etree.SubElement(page_div, "list")
                            item = etree.SubElement(current_list, "item")
                            _emit_runs_into(item, runs)
                        else:
                            current_list = None
                            p = etree.SubElement(page_div, "p")
                            _emit_runs_into(p, runs)

        # Images
        image_files = _extract_images_from_page(layout, used_image_dir, page_num, text_classes)
        if image_files:
            any_images = True
            for fn in image_files:
                fig = etree.SubElement(page_div, "figure")
                fig.set("n", fn)
                etree.SubElement(fig, "graphic", url=os.path.join(image_reldir, fn))

    if not any_text and not any_images:
        # Nothing extracted at all
        note = etree.SubElement(body, "note")
        note.text = "No text or images could be extracted from this PDF."

    # Heuristic: upgrade the first prominent line on the first page to <head>
    # when its font size is significantly larger than the median body size,
    # and simplify styles in smart mode (drop default font-size).
    if smart:
        hi_elems = body.findall(".//hi")
        font_sizes: list[float] = []
        for hi in hi_elems:
            style = hi.get("style") or ""
            m = re.search(r"font-size:\s*([0-9.]+)pt", style)
            if m:
                try:
                    font_sizes.append(float(m.group(1)))
                except ValueError:
                    continue
        if font_sizes:
            font_sizes.sort()
            body_size = font_sizes[len(font_sizes) // 2]

            # Drop default body font-size from all <hi> styles to reduce verbosity.
            body_fs_str = f"{body_size:.1f}pt"
            for hi in hi_elems:
                style = hi.get("style") or ""
                if not style:
                    continue
                style = re.sub(
                    rf"font-size:\s*{re.escape(body_fs_str)};?\s*", "", style
                ).strip()
                if style:
                    hi.set("style", style)
                else:
                    hi.attrib.pop("style", None)

            # Promote first large line on first page to <head> and unwrap <hi> inside it.
            first_page = body.find("./div[@type='page']")
            if first_page is not None:
                first_p = None
                for child in first_page:
                    if child.tag != "p":
                        continue
                    text_content = "".join(child.itertext()).strip()
                    if text_content:
                        first_p = child
                        break
                if first_p is not None:
                    p_sizes: list[float] = []
                    for hi in first_p.findall(".//hi"):
                        style = hi.get("style") or ""
                        m = re.search(r"font-size:\s*([0-9.]+)pt", style)
                        if m:
                            try:
                                p_sizes.append(float(m.group(1)))
                            except ValueError:
                                continue
                    if p_sizes and max(p_sizes) >= body_size * 1.3:
                        first_p.tag = "head"
                        # Unwrap any <hi> in the head: keep combined text, drop inline tags/styles.
                        head_text = "".join(first_p.itertext()).strip()
                        for child in list(first_p):
                            first_p.remove(child)
                        first_p.attrib.pop("style", None)
                        first_p.text = head_text

        if tidy_hi:
            # Tidy spaces around <hi>: move trailing space from hi.text into hi.tail
            for hi in body.findall(".//hi"):
                if hi.text and hi.text.endswith(" "):
                    hi.text = hi.text.rstrip(" ")
                    if hi.tail:
                        hi.tail = " " + hi.tail
                    else:
                        hi.tail = " "

        # Unwrap <cell>'s single <p> (content goes directly into cell)
        for cell in body.findall(".//cell"):
            children = list(cell)
            if len(children) == 1 and children[0].tag == "p":
                _unwrap_element(children[0])

        # Unwrap <hi> without style (or empty style)
        for hi in list(body.iter("hi")):
            if not (hi.get("style") or "").strip():
                _unwrap_element(hi)

    return tei, used_image_dir if any_images else None


def load_pdf(
    path: str,
    *,
    doc_id: Optional[str] = None,
    orgfile: Optional[str] = None,
    image_dir: Optional[str] = None,
    image_reldir: Optional[str] = None,
    options: Optional[dict[str, Any]] = None,
) -> Document:
    """Load a PDF file into a pivot Document.

    Options are currently unused but reserved for future pdf-specific tuning.
    """
    # Parse pdf-specific options: pdf=smart|simple and TEI cleanup: tei=clean|noclean
    smart = True
    tidy_hi = True
    if options:
        opt_raw = (options.get("pdf") or options.get("option") or "").strip()
        if opt_raw:
            for part in opt_raw.split(";"):
                part = part.strip()
                if not part:
                    continue
                if "=" in part:
                    key, val = part.split("=", 1)
                    key = key.strip().lower()
                    val = val.strip().lower()
                    if key == "pdf":
                        if val in {"simple", "nosmart", "0"}:
                            smart = False
                        elif val in {"smart", "1"}:
                            smart = True
                    elif key in {"tidyhi", "tidy_hi", "tidy"}:
                        tidy_hi = val not in {"0", "false", "no"}
                else:
                    low = part.lower()
                    if low in {"pdf=simple", "pdf=nosmart", "pdf=0"}:
                        smart = False
                    elif low in {"pdf=smart", "pdf=1"}:
                        smart = True

        # Also allow explicit TEI cleanup control via tei=clean|noclean
        if "tei=" in opt_raw:
            for part in opt_raw.split(";"):
                part = part.strip()
                if not part or "=" not in part:
                    continue
                key, val = part.split("=", 1)
                key = key.strip().lower()
                val = val.strip().lower()
                if key == "tei":
                    if val in {"clean", "1", "yes", "true"}:
                        tidy_hi = True
                    elif val in {"noclean", "0", "no", "false", "raw"}:
                        tidy_hi = False

    tei_root, used_image_dir = pdf_to_tei_tree(
        path,
        orgfile=orgfile or path,
        image_dir=image_dir,
        image_reldir=image_reldir,
        smart=smart,
        tidy_hi=tidy_hi,
    )
    if doc_id is None:
        doc_id = path
    doc = Document(id=doc_id)
    doc.meta["source_filename"] = os.path.basename(path)
    doc.meta["_teitok_tei_root"] = tei_root
    if used_image_dir:
        doc.meta["_teitok_image_dir"] = used_image_dir

    # Populate a simple structure layer and plain_text so generic TEI/TEITOK
    # savers can operate, similar to the RTF loader.
    body = tei_root.find(".//body")
    if body is not None:
        structure = doc.get_or_create_layer("structure")
        plain_parts: list[str] = []
        spans: list[tuple[int, int, str]] = []
        offset = 0
        para_idx = 0
        for p in body.iterfind(".//p"):
            text_content = (p.text or "").strip()
            if not text_content:
                continue
            para_idx += 1
            start = offset
            end = start + len(text_content)
            plain_parts.append(text_content)
            spans.append((start, end, text_content))
            offset = end + 1  # account for newline separator

        if spans:
            plain_text = "\n".join(plain_parts)
            doc.meta["plain_text"] = plain_text
            for idx, (start, end, text_content) in enumerate(spans, 1):
                anchor = Anchor(
                    type=AnchorType.CHAR,
                    char_start=start,
                    char_end=end,
                )
                node = Node(
                    id=f"p{idx}",
                    type="paragraph",
                    anchors=[anchor],
                    features={"text": text_content},
                )
                structure.nodes[node.id] = node

    return doc

