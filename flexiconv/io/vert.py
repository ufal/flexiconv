"""
VERT / VRT (vertical text) → TEITOK-style TEI conversion.

This module reads a verticalised corpus (one token per line, optional XML tags)
and builds a TEITOK-style TEI tree. It is inspired by the behaviour of
manatee2teitok.pl but does *not* depend on Manatee itself; instead it:

- Optionally reads a Manatee/CWB registry file to obtain column names.
- Treats <doc> / <text> tags as document boundaries (new <div> per doc/text).
- Treats <s> / </s> tags as sentence boundaries (otherwise uses blank lines).
- Ignores other inline XML for now (no attempt yet to preserve or split
  overlapping inline spans).
- Reconstructs spacing heuristically so that punctuation usually appears
  without preceding spaces (spacing_mode="guess").

The resulting TEI tree is stored in Document.meta["_teitok_tei_root"] for
save_teitok; no pivot token/sentence layers are currently populated.
"""

from __future__ import annotations

import copy
import os
import re
from datetime import datetime, timezone
from typing import List, Optional

from lxml import etree

from ..core.model import Document
from .teitok_xml import _ensure_tei_header, _write_teitok_xml


def _parse_registry_attributes(path: str) -> List[str]:
    """Parse a Manatee/CWB registry file to obtain positional attribute names.

    We collect lines starting with 'ATTRIBUTE name' and skip the special 'lc'
    attribute. The order of attributes defines the column order for VRT lines.
    """
    attrs: List[str] = []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                m = re.match(r"\s*ATTRIBUTE\s+(\S+)", line)
                if not m:
                    continue
                name = m.group(1)
                if name == "lc":
                    continue
                attrs.append(name)
    except OSError:
        return []
    return attrs


def _guess_column_names(ncols: int) -> List[str]:
    """Heuristic default column names when no registry is available."""
    if ncols == 1:
        return ["form"]
    if ncols == 2:
        return ["form", "lemma"]
    if ncols >= 3:
        return ["form", "lemma", "pos"] + [f"col{i}" for i in range(4, ncols + 1)]
    return [f"col{i}" for i in range(1, ncols + 1)]


_PUNCT_CLOSERS = {".", ",", ";", ":", "!", "?", ")", "]", "»", "”", "’"}
_PUNCT_OPENERS = {"(", "[", "«", "“", "‘"}


def _compute_space_after(tokens: List[str], mode: str) -> List[bool]:
    """Return per-token space_after flags based on simple punctuation heuristics."""
    n = len(tokens)
    if n == 0:
        return []
    # Default: space after every token.
    space_after = [True] * n
    if mode != "guess":
        # In 'none' mode we keep simple word spacing (space after every token
        # except the last in a sentence; callers can decide to trim tails).
        return space_after

    # No space before closing punctuation.
    for i in range(n - 1):
        if tokens[i + 1] in _PUNCT_CLOSERS:
            space_after[i] = False

    # No space after opening punctuation.
    for i in range(n):
        if tokens[i] in _PUNCT_OPENERS:
            space_after[i] = False

    return space_after


def _build_tei_from_vert(
    path: str,
    *,
    registry: Optional[str] = None,
    columns: Optional[List[str]] = None,
    spacing_mode: str = "guess",
    split_on_doc: bool = True,
) -> etree._Element:
    """Build a TEITOK-style TEI tree from a VRT/vertical file."""
    base = os.path.basename(path)
    stem, _ = os.path.splitext(base)
    when_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    tei = etree.Element("TEI")
    _ensure_tei_header(tei, source_filename=base, when=when_iso)

    text_el = etree.SubElement(tei, "text", id=stem)
    body_el = etree.SubElement(text_el, "body")

    # Column names from registry (if provided), explicit columns option, or
    # guessed from the first data line.
    registry_cols: List[str] = []
    if registry:
        registry_cols = _parse_registry_attributes(registry)
    if not registry_cols and columns:
        registry_cols = list(columns)

    # Current document/div and sentence
    div_el: Optional[etree._Element] = None
    s_el: Optional[etree._Element] = None
    sent_tokens: List[str] = []
    sent_toks: List[etree._Element] = []

    def _flush_sentence():
        nonlocal s_el, sent_tokens, sent_toks
        if s_el is None or not sent_tokens:
            sent_tokens = []
            sent_toks = []
            return
        # Compute space_after and set tails.
        space_flags = _compute_space_after(sent_tokens, spacing_mode)
        for tok_el, has_space in zip(sent_toks, space_flags):
            tok_el.tail = " " if has_space else ""
        # No trailing space after last token in sentence.
        if sent_toks:
            sent_toks[-1].tail = ""
        sent_tokens = []
        sent_toks = []

    def _ensure_div():
        nonlocal div_el
        if div_el is None:
            div_el = etree.SubElement(body_el, "div")
        return div_el

    def _start_new_sentence():
        nonlocal s_el, div_el
        if div_el is None:
            _ensure_div()
        s_el_local = etree.SubElement(div_el, "s")
        s_count = len(div_el.xpath(".//*[local-name()='s']"))
        s_el_local.set("id", f"s-{s_count}")
        return s_el_local

    # Simple XML tag regex.
    tag_re = re.compile(r"<(/?)([A-Za-z0-9:_-]+)([^>]*)>")

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n")
            stripped = line.strip()
            if not stripped:
                # Sentence boundary on blank line.
                _flush_sentence()
                s_el = None
                continue

            if stripped.startswith("<") and ">" in stripped:
                m = tag_re.match(stripped)
                if not m:
                    continue
                closing, name, _attrs = m.groups()
                name_lower = name.lower()

                if not closing:
                    # Start tag
                    if split_on_doc and name_lower in {"doc", "text"}:
                        # New document: flush any open sentence and start a new div.
                        _flush_sentence()
                        s_el = None
                        div_el = etree.SubElement(body_el, "div")
                    elif name_lower == "s":
                        _flush_sentence()
                        s_el = _start_new_sentence()
                    # Other inline/structural tags are currently ignored.
                else:
                    # End tag
                    if split_on_doc and name_lower in {"doc", "text"}:
                        _flush_sentence()
                        s_el = None
                        div_el = None
                    elif name_lower == "s":
                        _flush_sentence()
                        s_el = None
                continue

            # Token line.
            # First time we see a token line and have no registry-based columns
            # or explicit columns, guess them from the number of fields.
            parts = re.split(r"\s+", stripped)
            if not parts:
                continue
            if not registry_cols:
                registry_cols = _guess_column_names(len(parts))
            # Align columns.
            cols = parts + [""] * (len(registry_cols) - len(parts))
            cols = cols[: len(registry_cols)]

            form = cols[0]
            if form == "":
                continue

            if s_el is None:
                s_el = _start_new_sentence()

            tok_el = etree.SubElement(s_el, "tok")
            tok_el.text = form
            # Map remaining columns to TEITOK-friendly attributes.
            for cname, cval in zip(registry_cols[1:], cols[1:]):
                if not cval:
                    continue
                key = cname
                # Normalize some common names, but respect explicit 'pos'.
                cname_l = cname.lower()
                if cname_l == "lemma":
                    key = "lemma"
                elif cname_l == "upos":
                    key = "upos"
                elif cname_l == "xpos":
                    key = "xpos"
                elif cname_l == "pos":
                    key = "pos"
                elif cname_l == "feats":
                    key = "feats"
                tok_el.set(key, cval)

            sent_tokens.append(form)
            sent_toks.append(tok_el)

    # Flush at EOF.
    _flush_sentence()

    return tei


def load_vert(
    path: str,
    *,
    registry: Optional[str] = None,
    columns: Optional[List[str]] = None,
    spacing_mode: str = "guess",
    split_on_doc: bool = True,
) -> Document:
    """Load a VRT/vertical corpus into a pivot Document with TEITOK-style TEI in meta."""
    tei_root = _build_tei_from_vert(
        path,
        registry=registry,
        columns=columns,
        spacing_mode=spacing_mode,
        split_on_doc=split_on_doc,
    )
    doc = Document(id=path)
    doc.meta["source_filename"] = os.path.basename(path)
    doc.meta["_teitok_tei_root"] = tei_root
    return doc


def split_vert_to_teitok_files(
    path: str,
    out_dir: str,
    *,
    registry: Optional[str] = None,
    columns: Optional[List[str]] = None,
    spacing_mode: str = "guess",
) -> List[str]:
    """Split a VRT/vertical corpus into one TEITOK TEI file per <doc>/<text> block.

    This mirrors manatee2teitok.pl behaviour: INPUT is a vertical corpus with
    document boundaries marked by <doc> or <text>. OUTPUT is a directory;
    each block becomes its own TEI file with a single <div> under <body>.
    """
    base = os.path.basename(path)
    stem, _ = os.path.splitext(base)
    when_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # First build a TEI tree with separate <div> elements per <doc>/<text>.
    tei_root = _build_tei_from_vert(
        path,
        registry=registry,
        columns=columns,
        spacing_mode=spacing_mode,
        split_on_doc=True,
    )

    text_el = next((c for c in tei_root if (c.tag or "").endswith("text")), None)
    if text_el is None:
        return []
    body_el = text_el.find("body")
    if body_el is None:
        return []

    divs = [child for child in list(body_el) if (child.tag or "").endswith("div")]
    if not divs:
        # Fallback: treat the entire body as a single document.
        divs = [body_el]

    written: List[str] = []
    for idx, div in enumerate(divs, start=1):
        tei = etree.Element("TEI")
        _ensure_tei_header(tei, source_filename=base, when=when_iso)
        text_out = etree.SubElement(tei, "text", id=f"{stem}_{idx}")
        body_out = etree.SubElement(text_out, "body")
        body_out.append(copy.deepcopy(div))

        tree = etree.ElementTree(tei)
        out_path = os.path.join(out_dir, f"{stem}_{idx}.xml")
        _write_teitok_xml(out_path, tree, prettyprint=False)
        written.append(out_path)

    return written

