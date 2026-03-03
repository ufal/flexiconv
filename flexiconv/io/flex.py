"""
FLEx (FieldWorks Language Explorer) FLExText XML → TEITOK-style TEI conversion.

FLExText (e.g. .flextext) is the interlinear export format from FieldWorks. Structure:
- interlinear-text (root)
- paragraph (optional container)
- phrase (sentence-level; contains words and optional phrase-level item e.g. free translation)
- word (contains item elements: type="txt" form, type="gls" gloss, type="pos" POS; optional morph children)
- morph (under word; contains item type txt, cf, gls, msa, etc.)

We map: one phrase → one <s>, one word → one <tok>, word/morph items → token text and <m> (morpheme) elements.
The TEI tree is stored in document.meta["_teitok_tei_root"]; tokens and sentences layers are populated.
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


def _item_text(item: etree._Element) -> str:
    return "".join((item.text or "") + "".join(etree.tostring(c, encoding="unicode", method="text") for c in item) + (item.tail or "")).strip()


def _get_items_by_type(parent: etree._Element) -> Dict[str, str]:
    """Collect direct child <item> elements by type attribute. Returns dict type -> text."""
    out: Dict[str, str] = {}
    for child in parent:
        if _local_name(child) != "item":
            continue
        t = (child.get("type") or "").strip()
        if not t:
            continue
        text = _item_text(child).strip()
        if text:
            out[t] = text
    return out


def _phrase_words(phrase: etree._Element) -> List[etree._Element]:
    """Return word elements for this phrase. Variant A: direct child <word>; B: child <words> contains <word>."""
    for child in phrase:
        if _local_name(child) == "words":
            return [c for c in child if _local_name(c) == "word"]
    return [c for c in phrase if _local_name(c) == "word"]


def _word_form(word: etree._Element) -> str:
    """Baseline word form: item type='txt' or 'punct' (for punctuation-only words)."""
    items = _get_items_by_type(word)
    return (items.get("txt") or items.get("punct") or "").strip()


def _word_morphs(word: etree._Element) -> List[Dict[str, str]]:
    """List of morph annotations. Variant A: direct <morph> children; B: child <morphemes> contains <morph>."""
    morphs: List[Dict[str, str]] = []
    for child in word:
        ln = _local_name(child)
        if ln == "morph":
            items = _get_items_by_type(child)
            if items:
                morphs.append(items)
        elif ln == "morphemes":
            for m in child:
                if _local_name(m) == "morph":
                    items = _get_items_by_type(m)
                    if items:
                        morphs.append(items)
            return morphs
    return morphs


def _phrase_free_translation(phrase: etree._Element) -> str:
    """Phrase-level free translation: item type='gls' or 'ft' at phrase level."""
    items = _get_items_by_type(phrase)
    return (items.get("ft") or items.get("gls") or "").strip()


def _phrase_lang(phrase: etree._Element) -> str:
    """Lang from phrase or first word item with lang."""
    lang = (phrase.get("lang") or phrase.get("{http://www.w3.org/XML/1998/namespace}lang") or "").strip()
    if lang:
        return lang
    words = _phrase_words(phrase)
    first_word = words[0] if words else None
    if first_word is not None:
        for item in first_word:
            if _local_name(item) == "item":
                l = (item.get("lang") or item.get("{http://www.w3.org/XML/1998/namespace}lang") or "").strip()
                if l:
                    return l
    return ""


def _collect_phrases(root: etree._Element) -> List[etree._Element]:
    """Return all phrase elements in document order. FLExText: paragraph>phrase or phrase; FlexInterlinear: paragraphs>paragraph>phrases>word."""
    phrases: List[etree._Element] = []
    for child in root:
        ln = _local_name(child)
        if ln == "paragraph":
            phrases.extend([c for c in child if _local_name(c) == "phrase"])
        elif ln == "phrase":
            phrases.append(child)
        elif ln == "paragraphs":
            for par in child:
                if _local_name(par) != "paragraph":
                    continue
                for ph_cont in par:
                    if _local_name(ph_cont) == "phrases":
                        phrases.extend([c for c in ph_cont if _local_name(c) == "word"])
                        break
    return phrases


def _resolve_interlinear_root(root: etree._Element) -> etree._Element:
    """Return the interlinear-text element. Accept root <document> (FlexInterlinear) or <interlinear-text>."""
    ln = _local_name(root)
    if ln == "interlinear-text":
        return root
    if ln == "document":
        for child in root:
            if _local_name(child) == "interlinear-text":
                return child
        raise ValueError("Expected <document> to contain <interlinear-text>")
    raise ValueError(f"Expected root <interlinear-text> or <document>, got <{root.tag}>")


def _build_tei_from_flex(path: str) -> etree._Element:
    """Build a TEITOK-style TEI tree from a FLExText or FlexInterlinear XML file."""
    parser = etree.XMLParser(recover=True, remove_blank_text=False)
    tree = etree.parse(path, parser)
    root = _resolve_interlinear_root(tree.getroot())

    base = os.path.basename(path)
    stem, _ = os.path.splitext(base)
    if stem.lower().endswith(".flextext"):
        stem = stem[: -len(".flextext")]
    when_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    tei = etree.Element("TEI")
    _ensure_tei_header(tei, source_filename=base, when=when_iso)

    text_el = etree.SubElement(tei, "text", id=stem)

    phrases = _collect_phrases(root)
    tok_num = 0
    for s_idx, phrase in enumerate(phrases, start=1):
        words = _phrase_words(phrase)
        if not words:
            continue

        forms = [_word_form(w) for w in words]
        original = " ".join(forms).strip()
        if not original:
            continue

        free_tr = _phrase_free_translation(phrase)
        lang = _phrase_lang(phrase)

        s_attrib: Dict[str, str] = {"original": original, "id": f"s-{s_idx}"}
        if lang:
            s_attrib["lang"] = lang
        if free_tr:
            s_attrib["gloss"] = free_tr
        s_el = etree.SubElement(text_el, "s", **s_attrib)

        for w_el in words:
            form = _word_form(w_el)
            tok_num += 1
            tok = etree.SubElement(s_el, "tok", n=str(tok_num), id=f"w-{tok_num}")
            tok.text = form or ""

            morphs = _word_morphs(w_el)
            items = _get_items_by_type(w_el)

            if morphs:
                for m in morphs:
                    m_el = etree.SubElement(tok, "m", **{k: (v or "") for k, v in m.items()})
                    m_el.tail = ""
            else:
                # Word-level gloss/POS etc. but no morph children: single <m> from items
                attrs = {k: v for k, v in items.items() if k != "txt" and v}
                if attrs:
                    m_el = etree.SubElement(tok, "m", **attrs)
                    m_el.tail = ""

            tok.tail = " "

        if len(s_el):
            s_el[-1].tail = ""
        # Space between sentences (after </s>)
        s_el.tail = " "

    if len(text_el):
        text_el[-1].tail = ""

    return tei

def load_flex(path: str, **kwargs: Any) -> Document:
    """Load a FLEx FLExText (.flextext or FLEx-exported XML) file into a pivot Document."""
    tei = _build_tei_from_flex(path)
    base = os.path.basename(path)
    stem, ext = os.path.splitext(base)
    if stem.lower().endswith(".flextext"):
        stem = stem[: -len(".flextext")]
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
        anchor = Anchor(type=AnchorType.TOKEN, token_start=idx, token_end=idx)
        node = Node(id=xmlid, type="token", anchors=[anchor], features=features)
        tokens_layer.nodes[node.id] = node

    sent_elems = _xpath_local(tei, "s")
    for s_idx, s_el in enumerate(sent_elems, start=1):
        sid = s_el.get("id") or s_el.get("{http://www.w3.org/XML/1998/namespace}id") or f"s-{s_idx}"
        toks_in_s = s_el.xpath(".//*[local-name()='tok']")
        if not toks_in_s:
            continue
        first_tok = toks_in_s[0]
        last_tok = toks_in_s[-1]
        first_id = first_tok.get("id") or first_tok.get("{http://www.w3.org/XML/1998/namespace}id")
        last_id = last_tok.get("id") or last_tok.get("{http://www.w3.org/XML/1998/namespace}id")
        if first_id and last_id:
            t1 = token_index_by_xmlid.get(first_id, 0)
            t2 = token_index_by_xmlid.get(last_id, 0)
            if t1 and t2:
                anchor = Anchor(type=AnchorType.TOKEN, token_start=t1, token_end=t2)
                node = Node(id=sid, type="sentence", anchors=[anchor], features={})
                sentences_layer.nodes[node.id] = node

    return doc
