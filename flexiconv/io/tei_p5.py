from __future__ import annotations

from typing import Optional

import os
from lxml import etree

from ..core.model import Anchor, AnchorType, Document, Node


NS_TEI = {"tei": "http://www.tei-c.org/ns/1.0"}


def load_tei_p5(path: str, *, doc_id: Optional[str] = None) -> Document:
    """Load a generic TEI P5 document into a pivot Document.

    This implementation is intentionally conservative:
    - `<w>` are treated as tokens where present.
    - Otherwise, `<tok>` (TEITOK-style) are also accepted.
    - `<s>` elements become sentence nodes.
    """
    tree = etree.parse(path)
    root = tree.getroot()
    if not root.tag.endswith("TEI"):
        raise ValueError("Not a TEI document")

    if doc_id is None:
        doc_id = root.get("xml:id") or path
    doc = Document(id=doc_id)
    doc.meta["source_filename"] = os.path.basename(path)
    # Keep the original TEI tree so TEITOK/HTML writers can reuse it verbatim when appropriate.
    doc.meta["_teitok_tei_root"] = root

    tokens_layer = doc.get_or_create_layer("tokens")
    sentences_layer = doc.get_or_create_layer("sentences")

    token_xpath = ".//tei:text//tei:w | .//tei:text//tei:tok"
    token_elems = root.findall(token_xpath, namespaces=NS_TEI)
    token_index_by_xmlid: dict[str, int] = {}
    for idx, t in enumerate(token_elems, start=1):
        xmlid = t.get("id") or t.get("{http://www.w3.org/XML/1998/namespace}id") or f"t{idx}"
        token_index_by_xmlid[xmlid] = idx
        form = (t.text or "").strip()
        features = {"form": form}
        for attr in ("lemma", "pos", "msd", "ana"):
            val = t.get(attr)
            if val is not None:
                features[attr] = val
        anchor = Anchor(type=AnchorType.TOKEN, token_start=idx, token_end=idx)
        node = Node(id=xmlid, type="token", anchors=[anchor], features=features)
        tokens_layer.nodes[node.id] = node

    # Sentences
    sent_elems = root.findall(".//tei:text//tei:s", namespaces=NS_TEI)
    for s_idx, s in enumerate(sent_elems, start=1):
        sid = s.get("id") or s.get("{http://www.w3.org/XML/1998/namespace}id") or f"s{s_idx}"
        toks_in_s = s.findall(".//tei:w | .//tei:tok", namespaces=NS_TEI)
        if not toks_in_s:
            continue
        indices = []
        for t in toks_in_s:
            tid = t.get("id") or t.get("{http://www.w3.org/XML/1998/namespace}id")
            if not tid:
                continue
            idx = token_index_by_xmlid.get(tid)
            if idx is not None:
                indices.append(idx)
        if not indices:
            continue
        start = min(indices)
        end = max(indices)
        anchor = Anchor(type=AnchorType.TOKEN, token_start=start, token_end=end)
        sent_text = "".join(t.text or "" for t in toks_in_s).strip()
        features = {"sent_id": sid, "text": sent_text}
        node = Node(id=sid, type="sentence", anchors=[anchor], features=features)
        sentences_layer.nodes[node.id] = node

    return doc


def save_tei_p5(document: Document, path: str) -> None:
    """Very simple TEI P5 exporter (tokens and sentences only)."""
    NSMAP = {None: "http://www.tei-c.org/ns/1.0"}
    tei = etree.Element("TEI", nsmap=NSMAP)
    text_el = etree.SubElement(tei, "text")
    body_el = etree.SubElement(text_el, "body")

    tokens_layer = document.layers.get("tokens")
    sentences_layer = document.layers.get("sentences")
    structure_layer = document.layers.get("structure")

    # When there are no tokens, fall back to a very simple structure-only TEI:
    # one <p> per structure node, with plain text content.
    if not tokens_layer:
        if not structure_layer or not structure_layer.nodes:
            raise ValueError("Document has neither 'tokens' nor 'structure' layer")

        struct_nodes = sorted(
            structure_layer.nodes.values(),
            key=lambda n: (
                n.anchors[0].char_start if n.anchors and n.anchors[0].char_start is not None else 0,
                n.id,
            ),
        )
        for node in struct_nodes:
            p_el = etree.SubElement(body_el, "p")
            text = (node.features.get("text") or "").strip()
            if text:
                p_el.text = text

        tree = etree.ElementTree(tei)
        tree.write(path, encoding="utf-8", xml_declaration=True, pretty_print=True)
        return

    tokens = sorted(
        tokens_layer.nodes.values(),
        key=lambda n: (n.anchors[0].token_start or 0),
    )
    p_el = etree.SubElement(body_el, "p")

    if sentences_layer:
        s_nodes = sorted(
            sentences_layer.nodes.values(),
            key=lambda n: (n.anchors[0].token_start or 0),
        )
        for s in s_nodes:
            s_el = etree.SubElement(p_el, "s", id=s.id)
            start = s.anchors[0].token_start or 0
            end = s.anchors[0].token_end or 0
            for tok in tokens:
                ti = tok.anchors[0].token_start or 0
                if start <= ti <= end:
                    attrs = {"id": tok.id}
                    for k, v in tok.features.items():
                        if k == "form":
                            continue
                        attrs[k] = str(v)
                    w_el = etree.SubElement(s_el, "w", **attrs)
                    w_el.text = str(tok.features.get("form", ""))
    else:
        s_el = etree.SubElement(p_el, "s", id="s1")
        for tok in tokens:
            attrs = {"id": tok.id}
            for k, v in tok.features.items():
                if k == "form":
                    continue
                attrs[k] = str(v)
            w_el = etree.SubElement(s_el, "w", **attrs)
            w_el.text = str(tok.features.get("form", ""))

    tree = etree.ElementTree(tei)
    tree.write(path, encoding="utf-8", xml_declaration=True, pretty_print=True)

