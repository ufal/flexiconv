"""
EPUB to TEITOK-style TEI loader.

EPUB is a ZIP package containing:
- META-INF/container.xml (points to the OPF package document)
- OPF file: manifest (id -> href, media-type) and spine (reading order)
- XHTML/HTML content files and optional CSS/images

This module parses the container and OPF, then converts each spine XHTML document
into TEI body content (head, p, list, table, hi), wrapped in <div type="chapter">.
Images from the manifest can be extracted to an output directory and referenced.
"""
from __future__ import annotations

import os
import tempfile
import zipfile
from datetime import date
from typing import Optional

from lxml import etree
from lxml import html as lxml_html

from ..core.model import Anchor, AnchorType, Document, Node

# Common OPF namespaces (EPUB 2 and 3)
XML_NS = "http://www.w3.org/XML/1998/namespace"


def _find_opf_path(epub_zip: zipfile.ZipFile) -> Optional[str]:
    """Return the path of the root OPF file from META-INF/container.xml."""
    try:
        data = epub_zip.read("META-INF/container.xml")
    except KeyError:
        return None
    root = etree.fromstring(data)
    for elem in root.iter():
        if elem.tag.endswith("rootfile") or elem.tag == "rootfile":
            path = elem.get("full-path")
            if path:
                return path
    return None


def _parse_opf_manifest_and_spine(opf_content: bytes, opf_dir: str) -> tuple[dict, list]:
    """Parse OPF XML; return (manifest: id -> {href, media_type, full_path}, spine: list of manifest ids)."""
    root = etree.fromstring(opf_content)
    manifest: dict[str, dict] = {}
    spine: list[str] = []

    def local_tag(elem) -> str:
        tag = elem.tag or ""
        if "}" in tag:
            return tag.split("}")[-1]
        return tag

    for elem in root.iter():
        if local_tag(elem) == "item":
            id_attr = elem.get("id")
            href = elem.get("href")
            media_type = (elem.get("media-type") or "").strip().lower()
            if id_attr and href:
                full = os.path.normpath(os.path.join(opf_dir, href))
                manifest[id_attr] = {"href": href, "media_type": media_type, "full_path": full}
        elif local_tag(elem) == "itemref":
            idref = elem.get("idref")
            if idref:
                spine.append(idref)

    return manifest, spine


def _copy_inline_content(
    html_elem: etree._Element,
    tei_parent: etree._Element,
    image_dir: Optional[str],
    image_reldir: str,
    base_path: str,
) -> None:
    """Copy text and inline elements (span, a, strong, em, img) from html_elem into tei_parent as text and <hi>."""
    last = tei_parent

    def flush_text(text: str) -> None:
        nonlocal last
        if not text:
            return
        if last is tei_parent:
            tei_parent.text = (tei_parent.text or "") + text
        else:
            last.tail = (last.tail or "") + text

    def process_node(node: etree._Element, parent: etree._Element) -> None:
        nonlocal last
        tag = (node.tag or "").split("}")[-1].lower()
        # Flush this node's text into parent (except for strong/em, which put it in hi below; and linked <a>)
        if node.text and tag not in ("strong", "b", "em", "i") and not (tag == "a" and node.get("href")):
            if parent is not tei_parent and last is parent:
                parent.text = (parent.text or "") + node.text
            elif last is tei_parent:
                tei_parent.text = (tei_parent.text or "") + node.text
            else:
                last.tail = (last.tail or "") + node.text
        if tag in ("strong", "b"):
            hi = etree.SubElement(parent, "hi")
            hi.set("style", "font-weight: bold;")
            if node.text:
                hi.text = node.text
            last = hi
            for child in node:
                process_node(child, hi)
            if node.tail:
                last.tail = (last.tail or "") + node.tail
        elif tag in ("em", "i"):
            hi = etree.SubElement(parent, "hi")
            hi.set("style", "font-style: italic;")
            if node.text:
                hi.text = node.text
            last = hi
            for child in node:
                process_node(child, hi)
            if node.tail:
                last.tail = (last.tail or "") + node.tail
        elif tag == "img" and image_dir and node.get("src"):
            src = node.get("src", "")
            fig = etree.SubElement(parent, "figure")
            fig.set("n", os.path.basename(src))
            etree.SubElement(fig, "graphic", url=os.path.join(image_reldir, os.path.basename(src)))
            last = fig
            if node.tail:
                last.tail = node.tail
        elif tag == "a":
            href = node.get("href") or ""
            if href:
                ref = etree.SubElement(parent, "ref", target=href)
                ref.text = "".join(node.itertext())
                last = ref
            else:
                for child in node:
                    process_node(child, parent)
            if node.tail:
                last.tail = (last.tail or "") + node.tail
        else:
            for child in node:
                process_node(child, parent)
            if node.tail:
                if last is tei_parent:
                    tei_parent.text = (tei_parent.text or "") + node.tail
                else:
                    last.tail = (last.tail or "") + node.tail

    if html_elem.text:
        flush_text(html_elem.text)
    for child in html_elem:
        process_node(child, tei_parent)


def _html_elem_to_tei(
    elem: etree._Element,
    parent: etree._Element,
    image_dir: Optional[str],
    image_reldir: str,
    base_path: str,
) -> None:
    """Append TEI equivalent of an HTML element to parent."""
    tag = (elem.tag or "").split("}")[-1].lower()

    if tag in ("p", "div"):
        p = etree.SubElement(parent, "p")
        p.tail = "\n"
        _copy_inline_content(elem, p, image_dir, image_reldir, base_path)
        return
    if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
        head = etree.SubElement(parent, "head")
        head.tail = "\n"
        _copy_inline_content(elem, head, image_dir, image_reldir, base_path)
        return
    if tag in ("ul", "ol"):
        list_el = etree.SubElement(parent, "list")
        list_el.tail = "\n"
        for child in elem:
            ctag = (child.tag or "").split("}")[-1].lower()
            if ctag == "li":
                item = etree.SubElement(list_el, "item")
                item.tail = "\n"
                _copy_inline_content(child, item, image_dir, image_reldir, base_path)
        return
    if tag == "table":
        table_el = etree.SubElement(parent, "table")
        table_el.tail = "\n"
        for tr in elem:
            tr_tag = (tr.tag or "").split("}")[-1].lower()
            if tr_tag != "tr":
                continue
            row_el = etree.SubElement(table_el, "row")
            row_el.tail = "\n"
            for cell in tr:
                cell_tag = (cell.tag or "").split("}")[-1].lower()
                if cell_tag not in ("td", "th"):
                    continue
                cell_el = etree.SubElement(row_el, "cell")
                p = etree.SubElement(cell_el, "p")
                _copy_inline_content(cell, p, image_dir, image_reldir, base_path)
                cell_el.tail = "\n"
        return
    if tag in ("section", "article", "header", "footer", "main", "nav"):
        for child in elem:
            _html_elem_to_tei(child, parent, image_dir, image_reldir, base_path)
        return
    for child in elem:
        _html_elem_to_tei(child, parent, image_dir, image_reldir, base_path)


def _extract_body_from_xhtml(html_bytes: bytes) -> Optional[etree._Element]:
    """Parse XHTML/HTML and return the body element (or root if no body)."""
    try:
        root = lxml_html.fromstring(html_bytes)
    except Exception:
        return None
    body = root.find(".//body")
    if body is not None:
        return body
    return root


def _extract_images_from_epub(
    epub_zip: zipfile.ZipFile,
    manifest: dict,
    image_dir: str,
) -> list[str]:
    """Copy image items from manifest into image_dir; return list of filenames."""
    os.makedirs(image_dir, exist_ok=True)
    image_types = {"image/jpeg", "image/png", "image/gif", "image/svg+xml", "image/webp"}
    extracted: list[str] = []
    for item in manifest.values():
        if item["media_type"] not in image_types:
            continue
        path = item["full_path"]
        try:
            data = epub_zip.read(path)
        except KeyError:
            continue
        name = os.path.basename(path)
        out_path = os.path.join(image_dir, name)
        try:
            with open(out_path, "wb") as f:
                f.write(data)
            extracted.append(name)
        except OSError:
            pass
    return extracted


def epub_to_tei_tree(
    path: str,
    *,
    orgfile: Optional[str] = None,
    image_dir: Optional[str] = None,
    image_reldir: Optional[str] = None,
) -> tuple[etree._Element, Optional[str]]:
    """Convert an EPUB file to a TEITOK-style TEI tree. Returns (tei_root, image_dir_used)."""
    basename = os.path.splitext(os.path.basename(path))[0]
    if image_dir is None:
        image_dir = tempfile.mkdtemp(prefix="flexiconv_epub_")
    if image_reldir is None:
        image_reldir = os.path.basename(image_dir)

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
    change.text = "Converted from EPUB file " + path
    etree.SubElement(filedesc, "titleStmt")
    etree.SubElement(tei_header, "profileDesc")

    used_image_dir: Optional[str] = None
    with zipfile.ZipFile(path, "r") as z:
        opf_path = _find_opf_path(z)
        if not opf_path:
            body_note = etree.SubElement(body, "note")
            body_note.text = "Could not find OPF package in EPUB."
            return tei, None
        opf_dir = os.path.dirname(opf_path)
        try:
            opf_content = z.read(opf_path)
        except KeyError:
            body_note = etree.SubElement(body, "note")
            body_note.text = "Could not read OPF file."
            return tei, None
        manifest, spine_ids = _parse_opf_manifest_and_spine(opf_content, opf_dir)
        content_ids = [
            id_ for id_ in spine_ids
            if id_ in manifest
            and manifest[id_]["media_type"] in ("application/xhtml+xml", "text/html", "application/x-dtbncx+xml")
        ]
        content_ids = [id_ for id_ in content_ids if manifest[id_]["media_type"] != "application/x-dtbncx+xml"]
        extracted = _extract_images_from_epub(z, manifest, image_dir)
        if extracted:
            used_image_dir = image_dir
        raw_chapters: list[tuple[str, bytes]] = []  # (href, raw_xhtml)
        for idx, id_ in enumerate(content_ids):
            item = manifest[id_]
            full_path = item["full_path"]
            try:
                raw = z.read(full_path)
            except KeyError:
                continue
            raw_chapters.append((item["href"], raw))
            html_body = _extract_body_from_xhtml(raw)
            if html_body is None:
                continue
            base_path = os.path.dirname(full_path)
            div = etree.SubElement(body, "div")
            div.set("type", "chapter")
            div.set("n", str(idx + 1))
            div.set("source", item["href"])
            div.tail = "\n"
            for child in html_body:
                ctag = (child.tag or "").split("}")[-1].lower()
                if ctag in ("p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "table", "section", "article"):
                    _html_elem_to_tei(child, div, image_dir, image_reldir, base_path)
                elif ctag in ("blockquote", "pre"):
                    p = etree.SubElement(div, "p")
                    _copy_inline_content(child, p, image_dir, image_reldir, base_path)
                    p.tail = "\n"
                else:
                    for grandchild in child:
                        gtag = (grandchild.tag or "").split("}")[-1].lower()
                        if gtag in ("p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "table", "section", "article"):
                            _html_elem_to_tei(grandchild, div, image_dir, image_reldir, base_path)

        # Embed original XHTML of each chapter in <back><sourceDoc> so the TEI is self-contained.
        if raw_chapters:
            back = etree.SubElement(text_el, "back")
            back.tail = "\n"
            for href, raw in raw_chapters:
                source_doc = etree.SubElement(back, "sourceDoc")
                source_doc.set("n", href)
                source_doc.set("type", "application/xhtml+xml")
                try:
                    raw_str = raw.decode("utf-8", errors="replace")
                except Exception:
                    raw_str = raw.decode("latin-1", errors="replace")
                source_doc.text = etree.CDATA(raw_str)
                source_doc.tail = "\n"

    return tei, used_image_dir


def load_epub(
    path: str,
    *,
    doc_id: Optional[str] = None,
    orgfile: Optional[str] = None,
    image_dir: Optional[str] = None,
    image_reldir: Optional[str] = None,
) -> Document:
    """Load an EPUB file into a pivot Document with a TEITOK-style TEI tree."""
    tei_root, used_image_dir = epub_to_tei_tree(
        path,
        orgfile=orgfile or path,
        image_dir=image_dir,
        image_reldir=image_reldir,
    )
    if doc_id is None:
        doc_id = path
    doc = Document(id=doc_id)
    doc.meta["source_filename"] = os.path.basename(path)
    doc.meta["_teitok_tei_root"] = tei_root
    if used_image_dir:
        doc.meta["_teitok_image_dir"] = used_image_dir
    body = tei_root.find(".//body")
    if body is not None:
        structure = doc.get_or_create_layer("structure")
        plain_parts: list[str] = []
        offset = 0
        para_idx = 0
        for p in body.iterfind(".//p"):
            text_content = (p.text or "").strip()
            text_content += "".join((e.tail or "") for e in p.iter() if e.tail)
            text_content = " ".join(text_content.split())
            if not text_content:
                continue
            para_idx += 1
            start = offset
            end = start + len(text_content)
            plain_parts.append(text_content)
            anchor = Anchor(type=AnchorType.CHAR, char_start=start, char_end=end)
            node = Node(
                id=f"p{para_idx}",
                type="paragraph",
                anchors=[anchor],
                features={"text": text_content},
            )
            structure.nodes[node.id] = node
            offset = end + 1
        if plain_parts:
            doc.meta["plain_text"] = "\n".join(plain_parts)
    return doc
