"""
Toolbox (TBT) interlinear text → TEITOK-style TEI conversion.

TBT format: line-based. Lines are \\fieldname content. A blank line separates records (phrases).
The field 'tx' is the main transcription (words separated by spaces). Other fields (e.g. mrph, mb, ge)
can be morpheme-aligned: they have the same character-span alignment as tx (word boundaries follow
spaces in tx; within each word, spaces in the first morpheme tier separate morphemes). Each record
becomes <s original="..." lang="..."> with <tok>word<m .../></tok> children.

The TEI tree is stored in document.meta["_teitok_tei_root"] so save_teitok can write it verbatim.
Tokens and sentences layers are populated from the TEI for consistency with other formats.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from lxml import etree

from ..core.model import Anchor, AnchorType, Document, Node
from .teitok_xml import _ensure_tei_header, _xpath_local


# Line that starts with backslash + field name + optional space + rest
_TBT_LINE_RE = re.compile(r"^\\([^\s]+)\s*(.*)$", re.DOTALL)


def _parse_tbt(path: str) -> List[Dict[str, str]]:
    """Read a TBT file and return a list of records. Each record is a dict of field -> content."""
    records: List[Dict[str, str]] = []
    current: Dict[str, str] = {}

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n\r")
            if not line.strip():
                if current:
                    records.append(current)
                    current = {}
                continue
            m = _TBT_LINE_RE.match(line)
            if m:
                code = m.group(1).strip()
                content = (m.group(2) or "").replace("&", "&amp;")
                current[code] = content
            # Non-matching lines are ignored (or could be appended to previous field)
        if current:
            records.append(current)

    return records


def _word_boundaries(tx: str) -> List[Tuple[int, int]]:
    """Return [(start, end), ...] for each word in tx (split on spaces)."""
    if not tx or not tx.strip():
        return []
    spans: List[Tuple[int, int]] = []
    start = 0
    for i, c in enumerate(tx):
        if c == " ":
            if start < i:
                spans.append((start, i))
            start = i + 1
    if start < len(tx):
        spans.append((start, len(tx)))
    return spans


def _morph_boundaries_within_span(text: str, start: int, end: int) -> List[Tuple[int, int]]:
    """Within text[start:end], split on spaces; return [(start+o1, start+o2), ...] in string indices."""
    segment = text[start:end].rstrip()
    if not segment:
        return [(start, end)] if start < end else []
    spans: List[Tuple[int, int]] = []
    pos = 0
    for i, c in enumerate(segment):
        if c == " ":
            if pos < i:
                spans.append((start + pos, start + i))
            pos = i + 1
    if pos <= len(segment):
        spans.append((start + pos, start + len(segment)))
    return spans


def _build_tei_from_tbt(path: str) -> etree._Element:
    """Build a TEITOK-style TEI tree from a TBT file."""
    base = os.path.basename(path)
    stem, _ = os.path.splitext(base)
    when_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    tei = etree.Element("TEI")
    _ensure_tei_header(tei, source_filename=base, when=when_iso)

    text_el = etree.SubElement(tei, "text", id=stem)

    tok_num = 0
    for rec_idx, record in enumerate(_parse_tbt(path), start=1):
        tx = record.get("tx") or ""
        tx = tx.strip()
        if not tx:
            continue

        word_spans = _word_boundaries(tx)
        if not word_spans:
            continue

        # Morpheme tiers: all keys except 'tx' that have content aligned to this phrase.
        # For simplicity we treat every other field as a potential tier; we use the first
        # non-tx tier that has the same length as tx (or we use all tiers and take character
        # spans from tx word boundaries, then within each word use the first tier's spaces).
        tier_names = [k for k in record if k != "tx" and (record[k] or "").strip()]
        # First tier with length >= len(tx) is used for morpheme boundaries (space-separated
        # within each word span). If none match, use first tier anyway and hope alignment holds.
        morph_tier = None
        for k in tier_names:
            if len(record[k] or "") >= len(tx):
                morph_tier = k
                break
        if morph_tier is None and tier_names:
            morph_tier = tier_names[0]

        lang = (record.get("lang") or "").strip()
        s_attrib: Dict[str, str] = {"original": tx, "id": f"s-{rec_idx}"}
        if lang:
            s_attrib["lang"] = lang
        s_el = etree.SubElement(text_el, "s", **s_attrib)

        for wi, (w_start, w_end) in enumerate(word_spans):
            word = tx[w_start:w_end].rstrip()
            if not word:
                continue

            tok_num += 1
            tok = etree.SubElement(s_el, "tok", n=str(tok_num), id=f"w-{tok_num}")
            tok.text = word

            if morph_tier and morph_tier in record:
                tier_text = record[morph_tier] or ""
                morph_spans = _morph_boundaries_within_span(tier_text, w_start, w_end)
                if len(morph_spans) > 1 or (morph_spans and tier_names):
                    for m_start, m_end in morph_spans:
                        attrs: Dict[str, str] = {}
                        for tname in tier_names:
                            if tname not in record:
                                continue
                            val = (record[tname] or "")[m_start:m_end].rstrip()
                            if val:
                                attrs[tname] = val
                        if attrs:
                            m_el = etree.SubElement(tok, "m", **attrs)
                            m_el.tail = ""

            tok.tail = " "

        if len(s_el):
            s_el[-1].tail = ""

    return tei


def load_tbt(path: str, **kwargs: Any) -> Document:
    """Load a Toolbox (TBT) file into a pivot Document with TEITOK-style TEI in meta."""
    tei = _build_tei_from_tbt(path)
    base = os.path.basename(path)
    stem, _ = os.path.splitext(base)
    doc = Document(id=stem)
    doc.meta["_teitok_tei_root"] = tei

    # Populate tokens and sentences from the TEI so downstream and save_teitok see them.
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
