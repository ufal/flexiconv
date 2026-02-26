from __future__ import annotations

from typing import Optional

from lxml import etree
from lxml import html as lxml_html

from ..core.model import Anchor, AnchorType, Document, Node


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
    into a 'structure' layer; no tokenization.
    """
    doc = Document(id=doc_id)
    doc.meta["source_filename"] = source_filename
    structure = doc.get_or_create_layer("structure")

    body = root.find(".//body")
    if body is None:
        body = root

    block_xpath = ".//p | .//h1 | .//h2 | .//h3 | .//h4 | .//h5 | .//h6 | .//li | .//blockquote | .//div"
    blocks = body.xpath(block_xpath)
    # When body is the root (e.g. MD wrapped in <div>), do not treat the root as a block.
    blocks = [b for b in blocks if b is not body]

    offset = 0
    para_idx = 0

    for elem in blocks:
        text = elem.text_content()
        if text is None:
            continue
        stripped = text.strip()
        if not stripped:
            continue

        para_idx += 1
        start = offset
        end = start + len(stripped)

        anchor = Anchor(
            type=AnchorType.CHAR,
            char_start=start,
            char_end=end,
        )
        tag = elem.tag if isinstance(elem.tag, str) else (elem.tag or "")
        local_tag = tag.split("}")[-1] if "}" in tag else tag
        node = Node(
            id=f"p{para_idx}",
            type=local_tag.lower(),
            anchors=[anchor],
            features={"text": stripped},
        )
        structure.nodes[node.id] = node
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

