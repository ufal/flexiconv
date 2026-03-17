from __future__ import annotations

from typing import List, Optional, Tuple

from lxml import etree
from lxml import html as lxml_html

from ..core.model import Anchor, AnchorType, Document, Node


def _local_tag(elem: etree._Element) -> str:
    tag = elem.tag if isinstance(elem.tag, str) else (elem.tag or "")
    return tag.split("}")[-1] if "}" in tag else tag


def _rend_from_tag(tag: str) -> Optional[str]:
    t = tag.lower()
    if t in ("strong", "b"):
        return "bold"
    if t in ("em", "i"):
        return "italic"
    return None


def _inline_segments(
    elem: etree._Element,
    stop_at_list: bool = False,
) -> List[Tuple[str, Optional[str]]]:
    """Extract (text, rend) segments from an element's inline content. rend is 'bold'|'italic'|None."""
    segments: List[Tuple[str, Optional[str]]] = []
    if elem.text:
        segments.append((elem.text, None))
    for child in elem:
        tag = _local_tag(child).lower()
        if stop_at_list and tag in ("ul", "ol"):
            break
        rend = _rend_from_tag(tag)
        sub = _inline_segments(child, stop_at_list=stop_at_list)
        for t, r in sub:
            segments.append((t, r if r is not None else rend))
        if child.tail:
            segments.append((child.tail, None))
    return segments


def _merge_segments(segments: List[Tuple[str, Optional[str]]]) -> List[Tuple[str, Optional[str]]]:
    """Merge adjacent segments with the same rend."""
    if not segments:
        return []
    out: List[Tuple[str, Optional[str]]] = []
    cur_text, cur_rend = segments[0]
    for t, r in segments[1:]:
        if r == cur_rend:
            cur_text += t
        else:
            if cur_text:
                out.append((cur_text, cur_rend))
            cur_text, cur_rend = t, r
    if cur_text:
        out.append((cur_text, cur_rend))
    return out


def _li_direct_text(li_elem: etree._Element) -> str:
    """Text content of an li up to (but not including) the first nested ul/ol."""
    parts: List[str] = []
    if li_elem.text:
        parts.append(li_elem.text)
    for child in li_elem:
        if _local_tag(child).lower() in ("ul", "ol"):
            break
        if child.text:
            parts.append(child.text)
        parts.append(child.tail or "")
    return "".join(parts).strip()


def document_from_html_root(
    root: etree._Element,
    *,
    doc_id: str,
    source_filename: str,
) -> Document:
    """
    Build a pivot Document from an already-parsed HTML root (e.g. from a file or from
    a string). Used by load_html and by load_md (Markdown → HTML → this).

    Extracts visible text from block-level elements (p, h1–h6, li, blockquote, div)
    into a 'structure' layer; preserves nested list structure (list inside list item)
    via node.parent / node.children. No tokenization.
    """
    doc = Document(id=doc_id)
    doc.meta["source_filename"] = source_filename
    structure = doc.get_or_create_layer("structure")

    body = root.find(".//body")
    if body is None:
        body = root

    def _walk_blocks_with_parent(
        elem: etree._Element,
        parent_li_el: Optional[etree._Element],
        out: List[Tuple[etree._Element, Optional[etree._Element]]],
    ) -> None:
        tag = _local_tag(elem).lower()
        if tag in ("ul", "ol", "div"):
            for child in elem:
                _walk_blocks_with_parent(child, parent_li_el, out)
            return
        if tag == "li":
            out.append((elem, parent_li_el))
            for child in elem:
                _walk_blocks_with_parent(child, elem, out)
            return
        if tag in ("p", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"):
            # Only emit as top-level block when not inside a list item (avoids duplicating item text)
            if parent_li_el is None:
                out.append((elem, None))
            return
        for child in elem:
            _walk_blocks_with_parent(child, parent_li_el, out)

    order_with_parent_el: List[Tuple[etree._Element, Optional[etree._Element]]] = []
    for child in body:
        _walk_blocks_with_parent(child, None, order_with_parent_el)

    offset = 0
    para_idx = 0
    li_element_to_node_id: dict[int, str] = {}  # id(li element) -> node id for resolving parent

    for elem, parent_li_el in order_with_parent_el:
        tag = _local_tag(elem).lower()
        if tag == "li":
            text = _li_direct_text(elem)
            raw_segments = _merge_segments(_inline_segments(elem, stop_at_list=True))
        else:
            text = elem.text_content() if elem.text_content() else ""
            raw_segments = _merge_segments(_inline_segments(elem))
        if text is None:
            continue
        stripped = text.strip()
        if not stripped and tag != "li":
            continue
        # Allow empty li (e.g. placeholder item) to keep structure
        if not stripped and tag == "li":
            stripped = ""

        para_idx += 1
        start = offset
        end = start + len(stripped)

        parent_id: Optional[str] = None
        if parent_li_el is not None and id(parent_li_el) in li_element_to_node_id:
            parent_id = li_element_to_node_id[id(parent_li_el)]

        features: dict = {"text": stripped}
        if raw_segments and any(r for _, r in raw_segments):
            features["content_segments"] = [[t, r] for t, r in raw_segments]

        node = Node(
            id=f"p{para_idx}",
            type=tag,
            anchors=[Anchor(type=AnchorType.CHAR, char_start=start, char_end=end)],
            features=features,
            parent=parent_id,
        )
        structure.nodes[node.id] = node
        if parent_id and parent_id in structure.nodes:
            structure.nodes[parent_id].children.append(node.id)
        if tag == "li":
            li_element_to_node_id[id(elem)] = node.id
        offset = end + 1

    return doc


def load_html(path: str, *, doc_id: Optional[str] = None) -> Document:
    """
    Load an HTML document into a pivot Document.

    Current behaviour:
    - Extracts visible text from block-level elements (p, h1–h6, li, blockquote, div).
    - Creates a 'structure' layer with one node per block in document order.
    - Each node has a CHAR anchor spanning the block's text in the concatenated document,
      and a 'text' feature holding the block's plain text.

    No tokenization or detailed rendition marks are produced yet; TEITOK / TEI exporters
    will use the structure/text only.
    """
    tree = lxml_html.parse(path)
    root = tree.getroot()
    if doc_id is None:
        doc_id = path
    return document_from_html_root(
        root,
        doc_id=doc_id,
        source_filename=path.split("/")[-1].split("\\")[-1],
    )


def save_html(document: Document, path: str) -> None:
    """
    Export a pivot Document to a very simple HTML document.

    Behaviour:
    - If Document.meta['_teitok_tei_root'] is present (e.g. from DOCX), we treat it
      as TEITOK-style TEI and convert its <text>/<body> content to HTML, mapping
      <p> → <p> and <hi> → <span style='...'>.
    - Otherwise, if a 'structure' layer is present, we write one <p> per structure
      node with its 'text' feature.
    - As a last resort, if only a 'tokens' layer exists, we join token forms into
      a single <p>.
    """
    html_root = etree.Element("html")
    head = etree.SubElement(html_root, "head")
    etree.SubElement(head, "meta", charset="utf-8")
    body = etree.SubElement(html_root, "body")

    tei_root = document.meta.get("_teitok_tei_root")
    if tei_root is not None:
        # Copy over the TEI body content, mapping tags to simple HTML equivalents.
        text_el = tei_root.find(".//text")
        if text_el is None:
            text_el = tei_root.find("text")
        if text_el is not None:
            tei_body = text_el.find("body")
        else:
            tei_body = None

        if tei_body is not None:
            for child in tei_body:
                if child.tag == "p":
                    p = etree.SubElement(body, "p")
                    # Carry over paragraph-level style (e.g. text-align).
                    p_style = child.get("style")
                    if p_style:
                        p.set("style", p_style)
                    # Copy the paragraph content, remapping <hi> to <span> but otherwise
                    # keeping text and inline structure as-is (no extra whitespace magic).
                    last = p
                    if child.text:
                        p.text = child.text
                    for elem in child:
                        if elem.tag == "hi":
                            span = etree.SubElement(p, "span")
                            style = elem.get("style") or elem.get("rend") or ""
                            if style:
                                span.set("style", style)
                            span.text = elem.text
                            last = span
                            # Map TEI <lb/> (line breaks inside styled runs) to HTML <br>,
                            # and copy any other inline children as-is under the span.
                            for sub in elem:
                                if sub.tag == "lb":
                                    br = etree.SubElement(span, "br")
                                    if sub.tail:
                                        br.tail = (br.tail or "") + sub.tail
                                    last = br
                                else:
                                    sub_clone = etree.SubElement(span, sub.tag)
                                    for k, v in sub.attrib.items():
                                        sub_clone.set(k, v)
                                    sub_clone.text = sub.text
                                    if sub.tail:
                                        sub_clone.tail = (sub_clone.tail or "") + sub.tail
                                    last = sub_clone
                        else:
                            # Fallback: copy tag name and text as-is.
                            clone = etree.SubElement(p, elem.tag)
                            for k, v in elem.attrib.items():
                                clone.set(k, v)
                            clone.text = elem.text
                            last = clone
                        if elem.tail:
                            last.tail = (last.tail or "") + elem.tail
                else:
                    # Non-<p> child: create a div wrapper.
                    div = etree.SubElement(body, "div")
                    div.text = (child.text or "").strip()

        tree = etree.ElementTree(html_root)
        tree.write(path, encoding="utf-8", method="html", pretty_print=True)
        return

    # Fallback: build HTML from structure/tokens.
    structure = document.layers.get("structure")
    if structure and structure.nodes:
        struct_nodes = sorted(
            structure.nodes.values(),
            key=lambda n: (
                n.anchors[0].char_start if n.anchors and n.anchors[0].char_start is not None else 0,
                n.id,
            ),
        )
        ul_el = None
        for node in struct_nodes:
            node_type = (node.type or "p").lower()
            text = (node.features.get("text") or "").strip()
            if node_type == "li":
                if ul_el is None:
                    ul_el = etree.SubElement(body, "ul")
                li = etree.SubElement(ul_el, "li")
                if text:
                    li.text = text
            else:
                ul_el = None
                if node_type in ("h1", "h2", "h3", "h4", "h5", "h6"):
                    el = etree.SubElement(body, node_type)
                elif node_type == "blockquote":
                    el = etree.SubElement(body, "blockquote")
                else:
                    el = etree.SubElement(body, "p")
                if text:
                    el.text = text
    else:
        tokens_layer = document.layers.get("tokens")
        if tokens_layer and tokens_layer.nodes:
            tokens = sorted(
                tokens_layer.nodes.values(),
                key=lambda n: (n.anchors[0].token_start or 0),
            )
            p = etree.SubElement(body, "p")
            p.text = " ".join(str(t.features.get("form", "")) for t in tokens)

    tree = etree.ElementTree(html_root)
    tree.write(path, encoding="utf-8", method="html", pretty_print=True)

