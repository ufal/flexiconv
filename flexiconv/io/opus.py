"""
OPUS XML documents → TEITOK-style TEI.

OPUS (opus.nlpl.eu) keeps each corpus as one XML document per language and source document, with sentence
alignments (XCES) pointing at the sentence ids. This reader keeps those ids unchanged, so the alignments apply to the
converted documents as they are (flexalign merge).

    <document id="ep-00-01-17">                  (Europarl: <CHAPTER ID>, <SPEAKER ID NAME>, <P>)
      <p id="p1">
        <s id="1">Resumption of the session</s>                      raw: the sentence text
        <s id="2"><w id="w2.1">I</w> <w id="w2.2" lem="declare">declare</w> …</s>    tokenised

- `<s>` → `<s id>` (OPUS's id kept); `<w>` → `<tok>` (its attributes kept, `lem` as `lemma`), spacing guessed
  from punctuation when the source has none; a sentence without `<w>` keeps its text (flexipipe tokenises it).
- `<p>` / `<P>` → `<p>`; other elements holding sentences (CHAPTER, SPEAKER, …) → `<div type="chapter">` with their
  attributes (lower-cased).
- Nothing is dropped: every other element is kept where it stands, inside sentences too (OpenSubtitles
  `<time id="T1S" value="00:00:01,000"/>`, the subtitle boundaries, as milestones between the tokens; elements
  grouping words keep their words inside), and outside them (headings, notes without sentences).
- Ids: `<s>` and `<w>` keep theirs (the alignments point at them); every other element's `id` becomes `n`, so it
  cannot clash with them.
- `lang`: the document's language (OPUS has it in the path, `en/…`), set on `<text>`.
"""

from __future__ import annotations

import gzip
import os
from datetime import datetime, timezone
from typing import List, Optional

from lxml import etree

from ..core.model import Document
from .teitok_xml import _ensure_tei_header
from .vert import _compute_space_after


def _local(tag: object) -> str:
    return tag.split("}", 1)[-1] if isinstance(tag, str) else ""


def _parse(path: str) -> etree._Element:
    parser = etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False, huge_tree=True)
    with open(path, "rb") as f:
        gz = f.read(2) == b"\x1f\x8b"
    if gz:
        with gzip.open(path, "rb") as f:
            return etree.fromstring(f.read(), parser)
    return etree.parse(path, parser).getroot()


def _holds_sentences(elem: etree._Element) -> bool:
    return any(_local(e.tag).lower() == "s" for e in elem.iter() if e is not elem)


def _copy_attrs(src: etree._Element, dst: etree._Element) -> None:
    for k, v in src.attrib.items():
        key = _local(k).lower()
        dst.set("n" if key == "id" else key, v)


def _copy(src: etree._Element) -> etree._Element:
    """An element kept as it is (content, attributes; `id` as `n`), without its tail."""
    el = etree.Element(_local(src.tag))
    _copy_attrs(src, el)
    el.text = src.text
    for child in src:
        if _local(child.tag):
            sub = _copy(child)
            sub.tail = child.tail
            el.append(sub)
    return el


def _has_words(elem: etree._Element) -> bool:
    return any(_local(e.tag).lower() == "w" for e in elem.iter())


def _fill(src: etree._Element, dst: etree._Element, toks: List[etree._Element]) -> None:
    """A tokenised sentence's content in order: `<w>` as `<tok>`, elements holding words kept with their words
    inside, every other element (OpenSubtitles `<time>`) kept where it stands."""
    for child in src:
        name = _local(child.tag).lower()
        if not name:
            continue
        if name == "w":
            tok = etree.SubElement(dst, "tok")
            for k, v in child.attrib.items():
                key = _local(k)
                tok.set("lemma" if key == "lem" else key, v)
            tok.text = "".join(child.itertext())
            toks.append(tok)
        elif _has_words(child):
            el = etree.SubElement(dst, _local(child.tag))
            _copy_attrs(child, el)
            _fill(child, el, toks)
            el.tail = ""
        else:
            el = _copy(child)
            el.tail = ""
            dst.append(el)


def _sentence(src: etree._Element, parent: etree._Element, spacing_mode: str) -> None:
    s_el = etree.SubElement(parent, "s")
    s_el.tail = "\n"   # sentences apart in the document's text
    for k, v in src.attrib.items():
        s_el.set(_local(k), v)   # OPUS's id unchanged: the XCES alignments point at it
    if not _has_words(src):
        # untokenised: its text with any elements in it where they stand
        s_el.text = (src.text or "").lstrip()
        for child in src:
            if _local(child.tag):
                el = _copy(child)
                el.tail = child.tail
                s_el.append(el)
        if len(s_el):
            s_el[-1].tail = (s_el[-1].tail or "").rstrip()
        else:
            s_el.text = s_el.text.rstrip()
        return
    toks: List[etree._Element] = []
    _fill(src, s_el, toks)
    for tok, space in zip(toks, _compute_space_after([t.text or "" for t in toks], spacing_mode)):
        tok.tail = " " if space else ""
    toks[-1].tail = ""


def _walk(src: etree._Element, parent: etree._Element, spacing_mode: str) -> None:
    """Sentences, elements holding sentences (as `p` / `div type`), and every other element kept as it is."""
    for child in src:
        name = _local(child.tag).lower()
        if not name:
            continue
        if name == "s":
            _sentence(child, parent, spacing_mode)
        elif _holds_sentences(child):
            el = etree.SubElement(parent, "p" if name == "p" else "div")
            el.text, el.tail = "\n", "\n"
            if name != "p":
                el.set("type", name)
            _copy_attrs(child, el)
            _walk(child, el, spacing_mode)
        else:
            el = _copy(child)
            el.tail = "\n"
            parent.append(el)


def _build_tei_from_opus(path: str, *, lang: Optional[str] = None, spacing_mode: str = "guess") -> etree._Element:
    root = _parse(path)
    base = os.path.basename(path)
    stem = base[:-3] if base.endswith(".gz") else base
    stem, _ = os.path.splitext(stem)
    when_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    tei = etree.Element("TEI")
    _ensure_tei_header(tei, source_filename=base, when=when_iso)
    text_el = etree.SubElement(tei, "text", id=root.get("id") or stem)
    if lang:
        text_el.set("lang", lang)
    body = etree.SubElement(text_el, "body")
    if _local(root.tag).lower() == "s":
        _sentence(root, body, spacing_mode)
    else:
        _walk(root, body, spacing_mode)
    return tei


def load_opus(path: str, *, doc_id: Optional[str] = None, lang: Optional[str] = None,
              spacing_mode: str = "guess") -> Document:
    """Load an OPUS XML document (gzipped or not) into a pivot Document with TEITOK-style TEI in meta."""
    tei_root = _build_tei_from_opus(path, lang=lang, spacing_mode=spacing_mode)
    doc = Document(id=doc_id or path)
    doc.meta["source_filename"] = os.path.basename(path)
    doc.meta["_teitok_tei_root"] = tei_root
    return doc
