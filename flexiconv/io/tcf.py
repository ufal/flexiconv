"""
TCF (Text Corpus Format, D-Spin/WebLicht) → TEITOK-style TEI conversion.

TCF is an XML interchange format for linguistic annotation (tokens, sentences,
lemmas, POS, dependencies, named entities, etc.). This module builds a TEITOK
TEI tree with <text>, <s>, <tok> (and optional <name> wrappers for named entities),
token attributes (lemma, pos, reg, head, deprel), and stores it in
document.meta["_teitok_tei_root"] for save_teitok.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from lxml import etree

from ..core.model import Anchor, AnchorType, Document, Node
from .teitok_xml import _ensure_tei_header, _xpath_local


def _xpath_tcf(root: etree._Element, path: str) -> List[etree._Element]:
    """XPath that uses local-name() so TCF namespaces are ignored."""
    parts = path.strip("/").split("/")
    if not parts or (len(parts) == 1 and not parts[0]):
        return root.xpath(".//*")
    steps = []
    for p in parts:
        steps.append(f"*[local-name()='{p}']")
    xpath = ".//" + "/".join(steps)
    return root.xpath(xpath)


def _build_tei_from_tcf(path: str) -> etree._Element:
    """Build a TEITOK-style TEI tree from a TCF XML file."""
    parser = etree.XMLParser(remove_blank_text=True)
    tree = etree.parse(path, parser)
    root = tree.getroot()

    base = os.path.basename(path)
    stem, _ = os.path.splitext(base)
    when_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    tei = etree.Element("TEI")
    _ensure_tei_header(tei, source_filename=base, when=when_iso)

    text_el = etree.SubElement(tei, "text", id=stem)

    # Collect tokens in document order: id -> form (text content)
    tokens_ordered: List[str] = []
    forms: Dict[str, str] = {}
    for tok_el in _xpath_tcf(root, "//token"):
        tid = (tok_el.get("ID") or tok_el.get("id") or "").strip()
        if not tid:
            continue
        text = "".join(tok_el.itertext()).strip()
        forms[tid] = text
        tokens_ordered.append(tid)

    if not tokens_ordered:
        return tei

    # Per-token attributes: lemma, pos, reg, head, deprel
    attrs: Dict[str, Dict[str, str]] = {}
    for tid in tokens_ordered:
        attrs[tid] = {}

    for node in _xpath_tcf(root, "//lemmas/lemma"):
        tid = (node.get("tokenIDs") or "").strip()
        if tid and tid in attrs:
            attrs[tid]["lemma"] = "".join(node.itertext()).strip()

    for node in _xpath_tcf(root, "//POStags/tag"):
        tid = (node.get("tokenIDs") or "").strip()
        if tid and tid in attrs:
            attrs[tid]["pos"] = "".join(node.itertext()).strip()

    for node in _xpath_tcf(root, "//orthography/correction"):
        tid = (node.get("tokenIDs") or "").strip()
        if tid and tid in attrs:
            attrs[tid]["reg"] = "".join(node.itertext()).strip()

    for node in _xpath_tcf(root, "//depparsing/dependency") or _xpath_tcf(root, "//depparsing//dependency"):
        dep_ids = (node.get("depIDs") or "").strip()
        gov_ids = (node.get("govIDs") or "").strip()
        func = (node.get("func") or "").strip()
        if dep_ids and dep_ids in attrs:
            if gov_ids:
                attrs[dep_ids]["head"] = gov_ids
            if func:
                attrs[dep_ids]["deprel"] = func

    # Sentence boundaries
    sentences = _xpath_tcf(root, "//sentences/sentence") or _xpath_tcf(root, "//sentence")
    tok_elements: Dict[str, etree._Element] = {}

    def make_tok(tid: str, parent: etree._Element) -> etree._Element:
        tok = etree.SubElement(parent, "tok", id=tid)
        tok.text = forms.get(tid, "")
        for k, v in (attrs.get(tid) or {}).items():
            if v:
                tok.set(k, v)
        tok.tail = " "
        tok_elements[tid] = tok
        return tok

    if sentences:
        for s_el in sentences:
            sent_id = (s_el.get("ID") or s_el.get("id") or "").strip()
            token_ids_str = (s_el.get("tokenIDs") or "").strip()
            if not token_ids_str:
                continue
            tids = token_ids_str.split()
            s_tei = etree.SubElement(text_el, "s", id=sent_id or f"s-{len(text_el)}")
            for tid in tids:
                if tid in forms:
                    make_tok(tid, s_tei)
            if len(s_tei) > 0:
                s_tei[-1].tail = " "
        if len(text_el) > 0:
            text_el[-1].tail = ""
    else:
        for tid in tokens_ordered:
            make_tok(tid, text_el)
        if tokens_ordered:
            text_el[-1].tail = ""

    # Named entities: wrap token runs in <name type="..." id="...">
    entities = _xpath_tcf(root, "//namedEntities/entity") or _xpath_tcf(root, "//namedEntities//entity")
    for ent_el in entities:
        token_ids_str = (ent_el.get("tokenIDs") or "").strip()
        if not token_ids_str:
            continue
        tids = [t for t in token_ids_str.split() if t in tok_elements]
        if not tids:
            continue
        first_tok = tok_elements[tids[0]]
        parent = first_tok.getparent()
        if parent is None:
            continue
        name_el = etree.Element("name")
        ent_type = (ent_el.get("class") or ent_el.get("type") or "").strip()
        if ent_type:
            name_el.set("type", ent_type)
        ent_id = (ent_el.get("ID") or ent_el.get("id") or "").strip()
        if ent_id:
            name_el.set("id", ent_id)
        idx = list(parent).index(first_tok)
        parent.insert(idx, name_el)
        for tid in tids:
            tok = tok_elements[tid]
            name_el.append(tok)

    return tei


def load_tcf(path: str, **kwargs: Any) -> Document:
    """Load a TCF XML file into a pivot Document with TEITOK-style TEI in meta."""
    tei = _build_tei_from_tcf(path)
    base = os.path.basename(path)
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
        features: Dict[str, Any] = {"form": form, "space_after": True}
        for attr in ("lemma", "pos", "reg", "head", "deprel"):
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
