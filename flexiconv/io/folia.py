"""
FoLiA (Format for Linguistic Annotation) → TEITOK-style TEI conversion.

FoLiA is an XML format for linguistic annotation with <text>, <s>, <w> (words),
<t> (token text), <lemma>, <pos>, dependencies, etc. This module builds a TEITOK
TEI tree with <text>, <s>, <tok> (id, lemma, pos, head, deprel from FoLiA),
and stores it in document.meta["_teitok_tei_root"] for save_teitok.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from lxml import etree

from ..core.model import Anchor, AnchorType, Document, Node
from .teitok_xml import _ensure_tei_header, _xpath_local


def _local_name(el: etree._Element) -> str:
    return (el.tag or "").split("}")[-1]


def _xpath_folia(root: etree._Element, path: str) -> List[etree._Element]:
    """XPath with local-name() so FoLiA namespaces are ignored."""
    parts = [p for p in path.strip("/").split("/") if p]
    if not parts:
        return root.xpath(".//*")
    steps = [f"*[local-name()='{p}']" for p in parts]
    return root.xpath(".//" + "/".join(steps))


def _get_id(el: etree._Element) -> str:
    return (el.get("{http://www.w3.org/XML/1998/namespace}id") or el.get("id") or "").strip()


def _build_tei_from_folia(path: str) -> etree._Element:
    """Build a TEITOK-style TEI tree from a FoLiA XML file."""
    parser = etree.XMLParser(remove_blank_text=True)
    tree = etree.parse(path, parser)
    root = tree.getroot()

    base = os.path.basename(path)
    if base.lower().endswith(".folia.xml"):
        stem = base[: base.lower().rfind(".folia.xml")].rstrip(".")
    else:
        stem, _ = os.path.splitext(base)
    when_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    tei = etree.Element("TEI")
    _ensure_tei_header(tei, source_filename=base, when=when_iso)
    header = tei.find("teiHeader")

    # Optional: copy FoLiA metadata into header
    for meta in _xpath_folia(root, "//metadata/meta"):
        meta_id = (meta.get("id") or meta.get("{http://www.w3.org/XML/1998/namespace}id") or "").strip()
        val = "".join(meta.itertext()).strip()
        if not val:
            continue
        if meta_id == "title" and header is not None:
            title = header.find(".//title")
            if title is not None:
                title.text = val
        # language, genre, etc. could be mapped to profileDesc/langUsage, etc.

    text_el = etree.SubElement(tei, "text", id=stem)

    # FoLiA: text elements contain structure (div/s, or direct s)
    text_nodes = _xpath_folia(root, "//text")
    if not text_nodes:
        return tei

    first_text = text_nodes[0]
    lang_els = first_text.xpath(".//*[local-name()='lang']")
    lang_el = lang_els[0] if lang_els else None
    if lang_el is not None:
        lang_class = lang_el.get("class") or ""
        if lang_class:
            text_el.set("lang", lang_class)

    # Sentences: all s under the first text
    sentences = first_text.xpath(".//*[local-name()='s']")
    tok_id_to_tok: Dict[str, etree._Element] = {}

    for s_idx, s_el in enumerate(sentences, start=1):
        sent_id = s_el.get("pdtid") or _get_id(s_el) or f"s-{s_idx}"
        s_tei = etree.SubElement(text_el, "s", id=sent_id)

        for w in s_el.xpath("*[local-name()='w']"):
            wid = _get_id(w)
            if not wid:
                wid = f"w-{len(tok_id_to_tok) + 1}"
            tok = etree.SubElement(s_tei, "tok", id=wid)
            tok_id_to_tok[wid] = tok

            # Token text from <t> child (class "text" or first t)
            tok_text = ""
            for t_el in w.xpath("*[local-name()='t']"):
                tok_text = "".join(t_el.itertext()).strip()
                break
            if not tok_text:
                tok_text = "".join(w.itertext()).strip()
            tok.text = tok_text or ""

            # Other children → attributes (lemma, pos, etc.): use @class or text content
            for child in w:
                ln = _local_name(child)
                if ln == "t":
                    continue
                val = child.get("class") or "".join(child.itertext()).strip()
                val = " ".join(val.split())
                if val:
                    tok.set(ln, val)

            space = (w.get("space") or "yes").strip().lower()
            tok.tail = " " if space != "no" else ""

    # Last token in document: no trailing space
    all_toks = text_el.xpath(".//*[local-name()='tok']")
    if all_toks:
        all_toks[-1].tail = ""

    # Dependencies: dep/wref points to dependent token, hd/wref to head; class = deprel
    for dep_el in _xpath_folia(root, "//dependency"):
        deprel = (dep_el.get("class") or "").strip()
        dep_list = dep_el.xpath(".//*[local-name()='dep']")
        hd_list = dep_el.xpath(".//*[local-name()='hd']")
        dep_cont = dep_list[0] if dep_list else None
        hd_cont = hd_list[0] if hd_list else None
        dep_ref = dep_cont.xpath("*[local-name()='wref']")[0] if dep_cont is not None and dep_cont.xpath("*[local-name()='wref']") else None
        hd_ref = hd_cont.xpath("*[local-name()='wref']")[0] if hd_cont is not None and hd_cont.xpath("*[local-name()='wref']") else None
        dep_id = None
        head_id = None
        if dep_ref is not None:
            dep_id = (dep_ref.get("id") or dep_ref.get("{http://www.w3.org/XML/1998/namespace}id") or dep_ref.get("ref") or "").strip()
        elif dep_cont is not None:
            dep_id = (dep_cont.get("id") or dep_cont.get("{http://www.w3.org/XML/1998/namespace}id") or dep_cont.get("ref") or "").strip()
        if hd_ref is not None:
            head_id = (hd_ref.get("id") or hd_ref.get("{http://www.w3.org/XML/1998/namespace}id") or hd_ref.get("ref") or "").strip()
        elif hd_cont is not None:
            head_id = (hd_cont.get("id") or hd_cont.get("{http://www.w3.org/XML/1998/namespace}id") or hd_cont.get("ref") or "").strip()
        if dep_id and dep_id in tok_id_to_tok:
            tok = tok_id_to_tok[dep_id]
            if head_id:
                tok.set("head", head_id)
            if deprel:
                tok.set("deprel", deprel)

    return tei


def load_folia(path: str, **kwargs: Any) -> Document:
    """Load a FoLiA XML file into a pivot Document with TEITOK-style TEI in meta."""
    tei = _build_tei_from_folia(path)
    base = os.path.basename(path)
    if base.lower().endswith(".folia.xml"):
        stem = base[: base.lower().rfind(".folia.xml")].rstrip(".")
    else:
        stem, _ = os.path.splitext(base)
    doc = Document(id=stem)
    doc.meta["_teitok_tei_root"] = tei

    tokens_layer = doc.get_or_create_layer("tokens")
    sentences_layer = doc.get_or_create_layer("sentences")

    token_elems = _xpath_local(tei, "tok")
    token_index_by_xmlid: Dict[str, int] = {}
    for idx, t in enumerate(token_elems, start=1):
        xmlid = t.get("id") or t.get("{http://www.w3.org/XML/1998/namespace}id") or f"w-{idx}"
        token_index_by_xmlid[xmlid] = idx
        form = (t.text or "").strip()
        features: Dict[str, Any] = {"form": form, "space_after": bool(t.tail and " " in (t.tail or ""))}
        for attr in ("lemma", "pos", "head", "deprel"):
            v = t.get(attr)
            if v is not None:
                features[attr] = v
        anchor = Anchor(type=AnchorType.TOKEN, token_start=idx, token_end=idx)
        node = Node(id=xmlid, type="token", anchors=[anchor], features=features)
        tokens_layer.nodes[node.id] = node

    sent_elems = _xpath_local(tei, "s")
    for s_idx, s_el in enumerate(sent_elems, start=1):
        sid = s_el.get("id") or s_el.get("{http://www.w3.org/XML/1998/namespace}id") or f"s-{s_idx}"
        toks_in_s = s_el.xpath(".//*[local-name()='tok']")
        if not toks_in_s:
            continue
        first_id = toks_in_s[0].get("id") or toks_in_s[0].get("{http://www.w3.org/XML/1998/namespace}id")
        last_id = toks_in_s[-1].get("id") or toks_in_s[-1].get("{http://www.w3.org/XML/1998/namespace}id")
        if first_id and last_id:
            t1 = token_index_by_xmlid.get(first_id, 0)
            t2 = token_index_by_xmlid.get(last_id, 0)
            if t1 and t2:
                anchor = Anchor(type=AnchorType.TOKEN, token_start=t1, token_end=t2)
                node = Node(id=sid, type="sentence", anchors=[anchor], features={})
                sentences_layer.nodes[node.id] = node

    return doc
