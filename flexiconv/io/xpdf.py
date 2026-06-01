"""
XPDF bbox-layout HTML (Poppler pdftotext -bbox-layout) to TEITOK-style TEI.

The format is XHTML with a custom vocabulary under <body><doc>:
  <page width="..." height="...">
    <flow><block xMin="..." yMin="..." xMax="..." yMax="...">
      <line ...><word ...>text</word></line>
    </block></flow>
  </page>

Produces TEI with pb/p/lb/tok and bbox attributes, similar to hOCR import.
Page images are linked via @facs on <pb>; coordinates are scaled from PDF
points to image pixel space (TEITOK convention).
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import struct
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from lxml import etree

from ..core.model import Document
from .teitok_xml import _ensure_tei_header

_BBOX_ATTRS = ("xMin", "yMin", "xMax", "yMax")
_PDF_POINTS_PER_INCH = 72.0
_PAGE_IMAGE_RE = re.compile(r"^(.+)-(\d+)(?:_\d+)?\.(png|jpe?g|tif?f)$", re.IGNORECASE)
_PDFTOPPM_PAGE_RE = re.compile(r"-(\d+)\.(png|jpe?g)$", re.IGNORECASE)


@dataclass
class PageContext:
    """Per-page image and PDF-point → pixel scaling."""

    facs: str
    image_path: str
    pdf_width: float
    pdf_height: float
    img_width: int
    img_height: int

    @property
    def sx(self) -> float:
        return self.img_width / self.pdf_width if self.pdf_width else 1.0

    @property
    def sy(self) -> float:
        return self.img_height / self.pdf_height if self.pdf_height else 1.0


def _require_pdftotext() -> str:
    """Return path to pdftotext or raise with install hint."""
    from shutil import which

    path = which("pdftotext")
    if path:
        return path
    raise RuntimeError(
        "XPDF bbox extraction requires Poppler's pdftotext on PATH. "
        "Install poppler-utils (Linux), poppler (macOS/Homebrew), or Poppler for Windows."
    )


def _require_pdftoppm() -> str:
    from shutil import which

    path = which("pdftoppm")
    if path:
        return path
    raise RuntimeError(
        "XPDF page rendering requires Poppler's pdftoppm on PATH. "
        "Install poppler-utils (Linux), poppler (macOS/Homebrew), or Poppler for Windows."
    )


def parse_bbox_options(options: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Parse pdf/xpdf bbox-related options from a flexiconv options dict."""
    dpi = 200
    image_dir: Optional[str] = None
    render = True
    if not options:
        return {"dpi": dpi, "image_dir": image_dir, "render": render}
    opt_raw = (options.get("option") or options.get("pdf") or "").strip()
    if not opt_raw:
        return {"dpi": dpi, "image_dir": image_dir, "render": render}
    for part in opt_raw.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, val = part.split("=", 1)
        key = key.strip().lower()
        val = val.strip()
        if key == "dpi" and val.isdigit():
            dpi = max(1, int(val))
        elif key in {"images", "imagedir", "image_dir"} and val:
            image_dir = os.path.expanduser(val)
        elif key == "render" and val.lower() in {"0", "false", "no", "off"}:
            render = False
    return {"dpi": dpi, "image_dir": image_dir, "render": render}


def pdftotext_bbox_layout(pdf_path: str) -> bytes:
    """Run pdftotext -bbox-layout and return the XPDF HTML bytes."""
    pdftotext = _require_pdftotext()
    try:
        result = subprocess.run(
            [pdftotext, "-bbox-layout", pdf_path, "-"],
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise RuntimeError(f"Failed to run pdftotext: {exc}") from exc
    if result.returncode != 0:
        err = (result.stderr or b"").decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"pdftotext -bbox-layout failed (exit {result.returncode})"
            + (f": {err}" if err else "")
        )
    if not result.stdout.strip():
        raise RuntimeError("pdftotext -bbox-layout produced no output")
    return result.stdout


def is_xpdf_html_content(text: str) -> bool:
    """True when HTML looks like pdftotext -bbox-layout output."""
    lowered = text.lower()
    return (
        "<doc" in lowered
        and "<page" in lowered
        and re.search(r'<word\s+[^>]*xmin\s*=', lowered) is not None
    )


def _bbox_from_attrs(el: etree._Element) -> str:
    """Convert xMin/yMin/xMax/yMax attributes to TEITOK bbox 'xmin ymin xmax ymax'."""
    parts: list[str] = []
    for name in _BBOX_ATTRS:
        val = el.get(name)
        if val is None:
            return ""
        parts.append(val.strip())
    if len(parts) != 4:
        return ""
    return " ".join(parts)


def _set_bbox_attrs(el: etree._Element, bbox: str) -> None:
    """Set xMin/yMin/xMax/yMax from TEITOK bbox string."""
    parts = (bbox or "").split()
    if len(parts) != 4:
        return
    for name, val in zip(_BBOX_ATTRS, parts):
        el.set(name, val)


def _parse_bbox(bbox: str) -> Optional[tuple[float, float, float, float]]:
    parts = (bbox or "").split()
    if len(parts) != 4:
        return None
    try:
        return tuple(float(p) for p in parts)  # type: ignore[return-value]
    except ValueError:
        return None


def _format_bbox(x0: float, y0: float, x1: float, y1: float) -> str:
    """Format bbox as integer pixel coordinates (TEITOK / PressMint convention)."""
    return f"{round(x0)} {round(y0)} {round(x1)} {round(y1)}"


def _scale_bbox(bbox: str, sx: float, sy: float) -> str:
    parsed = _parse_bbox(bbox)
    if parsed is None:
        return bbox
    x0, y0, x1, y1 = parsed
    return _format_bbox(x0 * sx, y0 * sy, x1 * sx, y1 * sy)


def _scale_bboxes_in(el: etree._Element, ctx: PageContext) -> None:
    bbox = el.get("bbox")
    if bbox:
        el.set("bbox", _scale_bbox(bbox, ctx.sx, ctx.sy))
    for child in el:
        _scale_bboxes_in(child, ctx)


def _apply_page_contexts(text_el: etree._Element, pages: list[PageContext]) -> None:
    """Set pb @facs/@bbox and scale all bboxes on each page to image coordinates."""
    if not pages:
        return
    page_idx = 0
    ctx: Optional[PageContext] = None
    for child in list(text_el):
        tag = (child.tag or "").split("}")[-1]
        if tag == "pb":
            if page_idx < len(pages):
                ctx = pages[page_idx]
                if ctx.facs:
                    child.set("facs", ctx.facs)
                child.set(
                    "bbox",
                    _format_bbox(0, 0, ctx.img_width, ctx.img_height),
                )
                child.set("pdfpage", f"{ctx.pdf_width:g} {ctx.pdf_height:g}")
            page_idx += 1
            continue
        if ctx is not None:
            _scale_bboxes_in(child, ctx)


def _png_size(path: str) -> tuple[int, int]:
    with open(path, "rb") as f:
        header = f.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"Not a PNG file: {path}")
    width, height = struct.unpack(">II", header[16:24])
    return int(width), int(height)


def _jpeg_size(path: str) -> tuple[int, int]:
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        raise ValueError(f"Not a JPEG file: {path}")
    i = 2
    while i < len(data) - 9:
        if data[i] != 0xFF:
            i += 1
            continue
        while i < len(data) and data[i] == 0xFF:
            i += 1
        if i >= len(data):
            break
        marker = data[i]
        i += 1
        if marker in (
            0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
            0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
        ):
            height = int.from_bytes(data[i + 3 : i + 5], "big")
            width = int.from_bytes(data[i + 5 : i + 7], "big")
            return width, height
        if i + 1 >= len(data):
            break
        seg_len = int.from_bytes(data[i : i + 2], "big")
        i += seg_len
    raise ValueError(f"Could not read JPEG dimensions: {path}")


def _image_size(path: str) -> tuple[int, int]:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".png":
        return _png_size(path)
    if ext in (".jpg", ".jpeg"):
        return _jpeg_size(path)
    raise ValueError(f"Unsupported page image type: {path}")


def _page_size_from_pb(pb: etree._Element) -> tuple[str, str]:
    bbox = (pb.get("bbox") or "").split()
    if len(bbox) == 4:
        try:
            width = float(bbox[2]) - float(bbox[0])
            height = float(bbox[3]) - float(bbox[1])
            return f"{width:.6f}", f"{height:.6f}"
        except ValueError:
            pass
    return "", ""


def _parse_xpdf_root(raw: bytes) -> etree._Element:
    try:
        raw_str = raw.decode("utf-8", errors="replace")
    except Exception:
        raw_str = raw.decode("latin-1", errors="replace")
    parser = etree.XMLParser(recover=True, remove_blank_text=True)
    try:
        return etree.fromstring(raw_str.encode("utf-8"), parser=parser)
    except Exception:
        return etree.fromstring(
            b"<html><body>" + raw_str.encode("utf-8") + b"</body></html>",
            etree.HTMLParser(encoding="utf-8"),
        )


def _find_doc_el(root: etree._Element) -> Optional[etree._Element]:
    docs = root.xpath("//*[local-name()='doc']")
    return docs[0] if docs else None


def _xpdf_page_dimensions(doc_el: etree._Element) -> list[tuple[float, float]]:
    dims: list[tuple[float, float]] = []
    for page_el in doc_el.xpath("./*[local-name()='page']"):
        try:
            w = float(page_el.get("width") or "0")
            h = float(page_el.get("height") or "0")
        except ValueError:
            w = h = 0.0
        dims.append((w, h))
    return dims


def _search_dirs_for_images(pdf_path: Optional[str], image_dir: Optional[str]) -> list[str]:
    dirs: list[str] = []
    if image_dir:
        dirs.append(os.path.abspath(image_dir))
    if pdf_path:
        pdf_dir = os.path.dirname(os.path.abspath(pdf_path))
        dirs.append(pdf_dir)
        parent = os.path.dirname(pdf_dir)
        for name in ("scans", "images", "Images", "pages"):
            candidate = os.path.join(parent, name)
            if os.path.isdir(candidate):
                dirs.append(candidate)
    seen: set[str] = set()
    out: list[str] = []
    for d in dirs:
        norm = os.path.normpath(d)
        if norm not in seen and os.path.isdir(norm):
            seen.add(norm)
            out.append(norm)
    return out


def _discover_page_images(
    stem: str,
    search_dirs: list[str],
    page_count: int,
) -> list[Optional[str]]:
    """Return image paths indexed by page (0-based), or None when not found."""
    found: dict[int, str] = {}
    stem_lower = stem.lower()
    for directory in search_dirs:
        for fn in os.listdir(directory):
            path = os.path.join(directory, fn)
            if not os.path.isfile(path):
                continue
            m = _PAGE_IMAGE_RE.match(fn)
            if m and m.group(1).lower() == stem_lower:
                page_num = int(m.group(2))
                if 1 <= page_num <= page_count:
                    found.setdefault(page_num - 1, path)
    return [found.get(i) for i in range(page_count)]


def _render_pdf_pages(
    pdf_path: str,
    out_dir: str,
    *,
    dpi: int,
    page_count: int,
    stem: str,
) -> list[str]:
    """Render PDF pages to PNG via pdftoppm; return paths in page order."""
    os.makedirs(out_dir, exist_ok=True)
    prefix = os.path.join(out_dir, f"{stem}-page")
    pdftoppm = _require_pdftoppm()
    try:
        result = subprocess.run(
            [pdftoppm, "-png", "-r", str(dpi), pdf_path, prefix],
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise RuntimeError(f"Failed to run pdftoppm: {exc}") from exc
    if result.returncode != 0:
        err = (result.stderr or b"").decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"pdftoppm failed (exit {result.returncode})"
            + (f": {err}" if err else "")
        )
    rendered = sorted(glob.glob(f"{prefix}-*.png"), key=_pdftoppm_sort_key)
    if len(rendered) < page_count:
        rendered = sorted(glob.glob(f"{prefix}-*.png"))
    if len(rendered) != page_count:
        raise RuntimeError(
            f"pdftoppm produced {len(rendered)} page image(s), expected {page_count}"
        )
    # Rename to stable pressmint-like names: {stem}-{n}_1.png
    paths: list[str] = []
    for idx, src in enumerate(rendered, 1):
        dst = os.path.join(out_dir, f"{stem}-{idx}_1.png")
        if os.path.abspath(src) != os.path.abspath(dst):
            if os.path.exists(dst):
                os.remove(dst)
            os.replace(src, dst)
        paths.append(dst)
    return paths


def _pdftoppm_sort_key(path: str) -> int:
    m = _PDFTOPPM_PAGE_RE.search(os.path.basename(path))
    return int(m.group(1)) if m else 0


def _resolve_page_contexts(
    *,
    pdf_path: Optional[str],
    page_dims: list[tuple[float, float]],
    options: Optional[dict[str, Any]] = None,
    image_work_dir: Optional[str] = None,
) -> tuple[list[PageContext], str]:
    """Resolve page images and scaling contexts. Returns (contexts, image_dir)."""
    if not page_dims:
        return [], image_work_dir or ""

    opts = parse_bbox_options(options)
    dpi = opts["dpi"]
    page_count = len(page_dims)
    stem = os.path.splitext(os.path.basename(pdf_path or "document"))[0]

    work_dir = image_work_dir
    if work_dir is None:
        work_dir = tempfile.mkdtemp(prefix="flexiconv_pdf_pages_")

    discovered = _discover_page_images(
        stem,
        _search_dirs_for_images(pdf_path, opts["image_dir"]),
        page_count,
    )

    image_paths: list[str] = []
    if all(discovered):
        image_paths = [p for p in discovered if p]  # type: ignore[misc]
    elif opts["render"] and pdf_path:
        image_paths = _render_pdf_pages(
            pdf_path,
            work_dir,
            dpi=dpi,
            page_count=page_count,
            stem=stem,
        )
    elif any(discovered):
        raise RuntimeError(
            "Only some page images were found; provide a full set via "
            f"--option images=/path/to/dir or enable rendering (dpi={dpi})."
        )
    else:
        raise RuntimeError(
            f"No page images found for '{stem}' (searched: "
            f"{', '.join(_search_dirs_for_images(pdf_path, opts['image_dir'])) or 'n/a'}). "
            f"Place images as {stem}-1_1.png, … or use --option images=/path/to/dir "
            f"(pdftoppm renders at dpi={dpi} by default)."
        )

    contexts: list[PageContext] = []
    for idx, (pdf_w, pdf_h) in enumerate(page_dims):
        if pdf_w <= 0 or pdf_h <= 0:
            raise RuntimeError(f"XPDF page {idx + 1} has invalid dimensions")
        img_path = image_paths[idx]
        img_w, img_h = _image_size(img_path)
        contexts.append(
            PageContext(
                facs=os.path.basename(img_path),
                image_path=img_path,
                pdf_width=pdf_w,
                pdf_height=pdf_h,
                img_width=img_w,
                img_height=img_h,
            )
        )
    return contexts, work_dir


def _emit_word(parent: etree._Element, word_el: etree._Element) -> None:
    text = (word_el.text or "").strip()
    if not text and not word_el.text:
        text = "".join(word_el.itertext()).strip()
    if not text:
        return
    tok = etree.SubElement(parent, "tok")
    bbox = _bbox_from_attrs(word_el)
    if bbox:
        tok.set("bbox", bbox)
    tok.text = text
    tok.tail = " "


def _emit_line(parent: etree._Element, line_el: etree._Element) -> None:
    bbox = _bbox_from_attrs(line_el)
    if bbox:
        lb = etree.SubElement(parent, "lb")
        lb.set("bbox", bbox)
    for word_el in line_el.xpath("./*[local-name()='word']"):
        _emit_word(parent, word_el)


def _emit_block(parent: etree._Element, block_el: etree._Element) -> None:
    bbox = _bbox_from_attrs(block_el)
    p = etree.SubElement(parent, "p")
    if bbox:
        p.set("bbox", bbox)
    lines = block_el.xpath("./*[local-name()='line']")
    if not lines:
        for word_el in block_el.xpath("./*[local-name()='word']"):
            _emit_word(p, word_el)
        return
    for line_el in lines:
        _emit_line(p, line_el)
    if len(p) and p[-1].tail is None:
        p[-1].tail = "\n"


def xpdf_to_tei_tree(
    path_or_bytes: str | bytes,
    *,
    source_filename: Optional[str] = None,
    page_contexts: Optional[list[PageContext]] = None,
) -> etree._Element:
    """Convert XPDF bbox-layout HTML to a TEITOK-style TEI element tree."""
    if isinstance(path_or_bytes, bytes):
        raw = path_or_bytes
        source_filename = source_filename or "document.pdf"
    else:
        with open(path_or_bytes, "rb") as f:
            raw = f.read()
        source_filename = source_filename or os.path.basename(path_or_bytes)

    root = _parse_xpdf_root(raw)
    doc_el = _find_doc_el(root)
    if doc_el is None:
        raise ValueError("Not an XPDF bbox-layout document: missing <doc> element")

    tei = etree.Element("TEI")
    when = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _ensure_tei_header(tei, source_filename, when)
    text_el = etree.SubElement(tei, "text")

    page_dims = _xpdf_page_dimensions(doc_el)
    for page_el in doc_el.xpath("./*[local-name()='page']"):
        width = page_el.get("width") or ""
        height = page_el.get("height") or ""
        pb = etree.SubElement(text_el, "pb")
        if width and height:
            try:
                pb.set("bbox", f"0 0 {float(width):g} {float(height):g}")
            except ValueError:
                pb.set("bbox", f"0 0 {width} {height}")
        for block_el in page_el.xpath(".//*[local-name()='block']"):
            _emit_block(text_el, block_el)

    if page_contexts is None and page_dims:
        page_contexts, _ = _resolve_page_contexts(
            pdf_path=source_filename if source_filename.lower().endswith(".pdf") else None,
            page_dims=page_dims,
            options=None,
        )
    if page_contexts:
        _apply_page_contexts(text_el, page_contexts)

    return tei


def pdf_bbox_to_tei_tree(
    pdf_path: str,
    *,
    orgfile: Optional[str] = None,
    options: Optional[dict[str, Any]] = None,
    image_work_dir: Optional[str] = None,
) -> tuple[etree._Element, Optional[str]]:
    """Extract word-level bbox layout from a PDF via pdftotext -bbox-layout."""
    raw = pdftotext_bbox_layout(pdf_path)
    root = _parse_xpdf_root(raw)
    doc_el = _find_doc_el(root)
    if doc_el is None:
        raise ValueError("pdftotext -bbox-layout output has no <doc> element")
    page_dims = _xpdf_page_dimensions(doc_el)
    page_contexts, image_dir = _resolve_page_contexts(
        pdf_path=pdf_path,
        page_dims=page_dims,
        options=options,
        image_work_dir=image_work_dir,
    )
    tei = xpdf_to_tei_tree(
        raw,
        source_filename=os.path.basename(pdf_path),
        page_contexts=page_contexts,
    )
    return tei, image_dir if any(c.image_path for c in page_contexts) else None


def load_xpdf(
    path: str,
    *,
    doc_id: Optional[str] = None,
    options: Optional[dict[str, Any]] = None,
) -> Document:
    """Load an XPDF bbox-layout HTML file into a pivot Document."""
    with open(path, "rb") as f:
        raw = f.read()
    root = _parse_xpdf_root(raw)
    doc_el = _find_doc_el(root)
    if doc_el is None:
        raise ValueError("Not an XPDF bbox-layout document: missing <doc> element")
    page_dims = _xpdf_page_dimensions(doc_el)
    pdf_guess = os.path.splitext(path)[0] + ".pdf"
    pdf_path = pdf_guess if os.path.isfile(pdf_guess) else None
    page_contexts, image_dir = _resolve_page_contexts(
        pdf_path=pdf_path,
        page_dims=page_dims,
        options=options,
    )
    tei_root = xpdf_to_tei_tree(
        raw,
        source_filename=os.path.basename(path),
        page_contexts=page_contexts,
    )
    if doc_id is None:
        doc_id = path
    doc = Document(id=doc_id)
    doc.meta["source_filename"] = os.path.basename(path)
    doc.meta["_teitok_tei_root"] = tei_root
    if image_dir and any(c.image_path for c in page_contexts):
        doc.meta["_teitok_image_dir"] = image_dir
    return doc


def load_pdf_bbox(
    path: str,
    *,
    doc_id: Optional[str] = None,
    orgfile: Optional[str] = None,
    options: Optional[dict[str, Any]] = None,
) -> Document:
    """Load a PDF via pdftotext -bbox-layout into a pivot Document with tok bbox."""
    tei_root, image_dir = pdf_bbox_to_tei_tree(
        path,
        orgfile=orgfile or path,
        options=options,
    )
    if doc_id is None:
        doc_id = path
    doc = Document(id=doc_id)
    doc.meta["source_filename"] = os.path.basename(path)
    doc.meta["_teitok_tei_root"] = tei_root
    doc.meta["pdf_bbox_mode"] = True
    if image_dir:
        doc.meta["_teitok_image_dir"] = image_dir
    return doc


def _tei_text_children(tei_el: etree._Element) -> list[etree._Element]:
    text_el = tei_el.xpath("//*[local-name()='text']")
    if not text_el:
        return []
    return list(text_el[0])


def _unscale_bbox(bbox: str, sx: float, sy: float) -> str:
    parsed = _parse_bbox(bbox)
    if parsed is None or not sx or not sy:
        return bbox
    x0, y0, x1, y1 = parsed
    return f"{x0 / sx:.6f} {y0 / sy:.6f} {x1 / sx:.6f} {y1 / sy:.6f}"


def _tei_to_xpdf_doc(tei_root: etree._Element) -> etree._Element:
    """Build <doc> from TEI pb/p/lb/tok structure."""
    doc = etree.Element("doc")
    current_page: Optional[etree._Element] = None
    sx = sy = 1.0

    for node in _tei_text_children(tei_root):
        tag = (node.tag or "").split("}")[-1]
        if tag == "pb":
            pdfpage = (node.get("pdfpage") or "").split()
            pb_bbox = _parse_bbox(node.get("bbox") or "")
            if len(pdfpage) == 2:
                try:
                    pdf_w = float(pdfpage[0])
                    pdf_h = float(pdfpage[1])
                    if pb_bbox and pdf_w and pdf_h:
                        sx = (pb_bbox[2] - pb_bbox[0]) / pdf_w
                        sy = (pb_bbox[3] - pb_bbox[1]) / pdf_h
                    width, height = pdfpage[0], pdfpage[1]
                except ValueError:
                    width, height = _page_size_from_pb(node)
            else:
                width, height = _page_size_from_pb(node)
            current_page = etree.SubElement(doc, "page")
            if width:
                current_page.set("width", width)
            if height:
                current_page.set("height", height)
        elif tag == "p" and current_page is not None:
            flow = etree.SubElement(current_page, "flow")
            block = etree.SubElement(flow, "block")
            bbox = node.get("bbox", "")
            if bbox:
                _set_bbox_attrs(block, _unscale_bbox(bbox, sx, sy))
            current_line: Optional[etree._Element] = None
            for ch in node:
                local = (ch.tag or "").split("}")[-1]
                if local == "lb":
                    current_line = etree.SubElement(block, "line")
                    bbox_l = ch.get("bbox", "")
                    if bbox_l:
                        _set_bbox_attrs(current_line, _unscale_bbox(bbox_l, sx, sy))
                elif local in ("tok", "gtok"):
                    if current_line is None:
                        current_line = etree.SubElement(block, "line")
                        bbox_w = ch.get("bbox", "")
                        if bbox_w:
                            _set_bbox_attrs(current_line, _unscale_bbox(bbox_w, sx, sy))
                    word = etree.SubElement(current_line, "word")
                    bbox_w = ch.get("bbox", "")
                    if bbox_w:
                        _set_bbox_attrs(word, _unscale_bbox(bbox_w, sx, sy))
                    word.text = (ch.text or "").strip()
    return doc


def save_xpdf(document: Document, path: str) -> None:
    """Write XPDF bbox-layout HTML from a Document with TEI bbox structure."""
    tei_root = document.meta.get("_teitok_tei_root")
    if tei_root is None:
        raise ValueError(
            "save_xpdf requires a document with bbox structure (e.g. from load_xpdf, "
            "load_pdf with pdf=bbox, or TEITOK TEI with pb/p/lb/tok bbox)."
        )
    doc_el = _tei_to_xpdf_doc(tei_root)
    root = etree.Element(
        "html",
        nsmap={None: "http://www.w3.org/1999/xhtml"},
    )
    head = etree.SubElement(root, "head")
    etree.SubElement(head, "title")
    body = etree.SubElement(root, "body")
    body.append(doc_el)
    tree = etree.ElementTree(root)
    doctype = (
        '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" '
        '"http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">'
    )
    with open(path, "wb") as out:
        out.write(doctype.encode("utf-8"))
        out.write(b"\n")
        tree.write(
            out,
            encoding="utf-8",
            xml_declaration=False,
            pretty_print=True,
            method="xml",
        )


def copy_facs_images(document: Document, tei_root: etree._Element, effective_path: str) -> None:
    """Copy page images referenced by pb @facs next to the TEI output file."""
    src_dir = document.meta.get("_teitok_image_dir")
    if not src_dir or not os.path.isdir(src_dir):
        return
    out_dir = os.path.dirname(os.path.abspath(effective_path)) or "."
    for pb in tei_root.xpath(".//*[local-name()='pb'][@facs]"):
        facs = pb.get("facs") or ""
        if not facs or os.path.dirname(facs):
            continue
        src_path = os.path.join(src_dir, os.path.basename(facs))
        if not os.path.isfile(src_path):
            continue
        dst_path = os.path.join(out_dir, os.path.basename(facs))
        if not os.path.exists(dst_path):
            try:
                shutil.copy2(src_path, dst_path)
            except OSError:
                continue
