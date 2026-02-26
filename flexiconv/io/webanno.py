"""
WebAnno TSV → TEITOK-style TEI conversion.

WebAnno TSV (e.g. from INCEpTION/WebAnno export) is a tab-separated format with:
- Line 1: format identifier
- Line 2: #T_XX=LayerName|field1|field2|... (annotation column names)
- Then blocks: #Text=... or #MText=... (segment source text) followed by token lines
  "sent-tok\\tbegin-end\\tform\\tval1\\tval2\\t..." (e.g. 1-1\\t0-4\\tThe\\tthe\\tDET)

Values can be "_" (empty), a literal value (→ token attribute), or "value[annid]" for
multi-token span annotations (→ standOff <spanGrp>/<span> with corresp to token IDs).

This module builds a TEITOK-style TEI tree with <s>, <tok> (and token attributes from
the TSV columns) and optional <standOff>/<spanGrp> for span annotations.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from lxml import etree

from ..core.model import Document
from .teitok_xml import _ensure_tei_header


def _parse_webanno_header(line: str) -> Tuple[str, List[str]]:
    """Parse #T_XX=Layer|field1|field2|... into (layer_name, [field1, field2, ...])."""
    m = re.match(r"#T_.{2}=([^|\t]+)\|(.*)", line.strip())
    if not m:
        return "", []
    layer = m.group(1).strip()
    if layer.startswith("webanno.custom."):
        layer = layer[len("webanno.custom.") :]
    rest = m.group(2).strip()
    fields = [f.strip() for f in rest.split("|") if f.strip()]
    return layer, fields


def _escape_xml_text(s: str) -> str:
    s = s.replace("&", "&amp;")
    s = s.replace("<", "&lt;")
    s = s.replace(">", "&gt;")
    return s


def _build_tei_from_webanno(
    path: str,
    *,
    seg_element: str = "s",
    with_seg_text: bool = False,
) -> etree._Element:
    """Build a TEITOK-style TEI tree from a WebAnno TSV file."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    base = os.path.basename(path)
    stem, _ = os.path.splitext(base)
    if stem.lower().endswith(".webanno"):
        stem = stem[: -len(".webanno")]
    when_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    tei = etree.Element("TEI")
    _ensure_tei_header(tei, source_filename=base, when=when_iso)
    text_el = etree.SubElement(tei, "text", id=stem)

    if len(lines) < 2:
        return tei

    # Line 0: format; Line 1: #T_XX=Layer|field1|field2|...
    _, field_names = _parse_webanno_header(lines[1])
    if not field_names:
        return tei

    # Multi-token span annotations: annid -> {token_ids, fields}
    span_anns: Dict[str, Dict[str, Any]] = {}
    tok_id_to_form: Dict[str, str] = {}

    seg_id = 0
    segment_text = ""
    last_end = 0
    sent_el: Optional[etree._Element] = None
    num_tokens_in_seg = 0
    i = 2
    while i < len(lines):
        line = lines[i]
        i += 1
        stripped = line.strip()
        if not stripped:
            continue

        # New segment: #Text=... or #MText=...
        if re.match(r"#M?Text=", stripped, re.I):
            seg_id += 1
            segment_text = re.sub(r"^#M?Text=", "", stripped, flags=re.I)
            segment_text = segment_text.strip()
            last_end = 0
            sent_el = etree.SubElement(text_el, seg_element, id=f"{seg_element}-{seg_id}")
            if with_seg_text:
                sent_el.set("text", _escape_xml_text(segment_text))
            num_tokens_in_seg = 0
            continue

        # Token line: sent-tok\tbegin-end\tform\tval1\tval2...
        if not re.match(r"^\d+-\d+", stripped):
            continue

        parts = stripped.split("\t")
        if len(parts) < 3:
            continue
        sent_tok = parts[0].strip()
        span_str = parts[1].strip()
        form = parts[2]
        ann_vals = parts[3:] if len(parts) > 3 else []

        if sent_el is None:
            seg_id += 1
            segment_text = ""
            last_end = 0
            sent_el = etree.SubElement(text_el, seg_element, id=f"{seg_element}-{seg_id}")
            num_tokens_in_seg = 0

        tok_id = f"w-{sent_tok}"
        try:
            begin, end = int(span_str.split("-")[0]), int(span_str.split("-")[1])
        except (ValueError, IndexError):
            begin, end = last_end, last_end + len(form)

        # Gap (spacing) from segment text between previous token and this one (0-based offsets)
        gap = ""
        if num_tokens_in_seg > 0 and segment_text and begin > last_end and begin <= len(segment_text):
            gap = segment_text[last_end:begin]
        last_end = end

        # Assign gap to the *previous* token's tail (so the space appears after it)
        if num_tokens_in_seg > 0 and len(sent_el) > 0:
            sent_el[-1].tail = gap

        tok_el = etree.SubElement(sent_el, "tok", id=tok_id)
        form_escaped = _escape_xml_text(form)
        tok_el.text = form_escaped
        tok_el.tail = ""
        tok_id_to_form[tok_id] = form
        num_tokens_in_seg += 1

        # Token-level attributes and span references from annotation columns
        for col_idx, val in enumerate(ann_vals):
            if col_idx >= len(field_names):
                break
            val = val.strip()
            if val == "_" or not val:
                continue
            fld = field_names[col_idx].lower()
            for v in val.split("|"):
                v = v.strip()
                if not v:
                    continue
                mm = re.match(r"^(.+)\[(\d+)\]$", v)
                if mm:
                    ann_val, annid = mm.group(1), mm.group(2)
                    if annid not in span_anns:
                        span_anns[annid] = {"token_ids": [], "fields": {}}
                    span_anns[annid]["fields"][col_idx] = (fld, ann_val)
                    if tok_id not in span_anns[annid]["token_ids"]:
                        span_anns[annid]["token_ids"].append(tok_id)
                else:
                    tok_el.set(fld, v)

    # Ensure last token in document has no trailing tail
    for s in text_el:
        if len(s) > 0:
            last_tok = s[-1]
            if last_tok.tag == "tok":
                last_tok.tail = ""

    # StandOff: spanGrp for multi-token annotations
    if span_anns:
        stand_off = etree.SubElement(tei, "standOff")
        span_grp = etree.SubElement(stand_off, "spanGrp")
        for annid, data in sorted(span_anns.items(), key=lambda x: int(x[0])):
            token_ids = data.get("token_ids", [])
            fields = data.get("fields", {})
            if not token_ids:
                continue
            corresp = " ".join(f"#{tid}" for tid in token_ids)
            span_text = " ".join(tok_id_to_form.get(tid, "") for tid in token_ids)
            attrs: Dict[str, str] = {"id": f"ann-{annid}", "corresp": corresp}
            for _col_idx, (fld, val) in sorted(fields.items()):
                attrs[fld] = val
            span_el = etree.SubElement(span_grp, "span", **attrs)
            span_el.text = span_text.strip()

    return tei


def load_webanno(
    path: str,
    *,
    seg_element: str = "s",
    with_seg_text: bool = False,
) -> Document:
    """Load a WebAnno TSV file into a pivot Document with TEITOK-style TEI in meta."""
    tei_root = _build_tei_from_webanno(
        path,
        seg_element=seg_element,
        with_seg_text=with_seg_text,
    )
    doc = Document(id=path)
    doc.meta["source_filename"] = os.path.basename(path)
    doc.meta["_teitok_tei_root"] = tei_root
    return doc
