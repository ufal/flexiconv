"""
Praat TextGrid to TEITOK-style TEI conversion.

Parses the TextGrid **text format** (Praat's line-based key=value format, not XML) via
line-by-line regex; the TEI tree is built only with lxml (no regex on XML).
Interval tiers become <u> or, when a words tier exists, <tok> with nested <syll>/<ph>.
Stores the TEI in document.meta['_teitok_tei_root'] and populates media, timeline,
and 'utterances' layer.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from lxml import etree

from ..core.model import Anchor, AnchorType, Document, MediaResource, Node, Timeline
from .teitok_xml import _ensure_tei_header


def _unquote(s: str) -> str:
    """Strip surrounding double quotes and unescape "" -> "."""
    s = s.strip()
    if s.startswith('"') and s.endswith('"'):
        s = s[1:-1].replace('""', '"')
    return s


def _parse_textgrid(path: str) -> Tuple[float, float, List[Dict[str, Any]]]:
    """
    Parse a TextGrid text file. Returns (xmin, xmax, tiers) where each tier is
    {"name": str, "intervals": [{"xmin": float, "xmax": float, "text": str}, ...]}.
    Only interval tiers are read; point tiers are skipped.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    xmin_grid = 0.0
    xmax_grid = 0.0
    tiers: List[Dict[str, Any]] = []
    current_tier: Optional[Dict[str, Any]] = None
    current_interval: Optional[Dict[str, str]] = None
    in_intervals = False
    tier_num = 0

    for raw_line in lines:
        line = raw_line.rstrip("\r\n").replace("\0", "")
        if not line.strip():
            continue

        # item [N]:
        m = re.match(r"^\s*item\s*\[\s*(\d+)\s*\]\s*:", line, re.IGNORECASE)
        if m:
            tier_num = int(m.group(1))
            current_tier = {"name": str(tier_num), "intervals": []}
            tiers.append(current_tier)
            current_interval = None
            in_intervals = False
            continue

        # intervals [N]: (start of an interval block)
        m = re.match(r"^\s*intervals\s*\[\s*(\d+)\s*\]\s*:", line, re.IGNORECASE)
        if m and current_tier is not None:
            current_interval = {}
            in_intervals = True
            continue

        # intervals: size = N (alternate form, skip)
        if re.match(r"intervals\s*:\s*size", line, re.IGNORECASE):
            continue

        # key = value
        key_val = re.match(r"^\s*(.+?)\s*=\s*(.*)$", line)
        if key_val:
            key_raw = key_val.group(1).strip()
            val_raw = key_val.group(2).strip()
            key = re.sub(r"[^a-z]", "", key_raw.lower())
            val = _unquote(val_raw)

            if current_tier is None and not tiers:
                if key == "xmin":
                    try:
                        xmin_grid = float(val)
                    except ValueError:
                        pass
                elif key == "xmax":
                    try:
                        xmax_grid = float(val)
                    except ValueError:
                        pass
                continue

            if current_interval is not None and in_intervals:
                current_interval[key] = val
                if key in ("xmin", "xmax") and val:
                    try:
                        current_interval[key] = float(val)
                    except ValueError:
                        pass
                if key == "text" and current_tier is not None:
                    try:
                        xmin = float(current_interval.get("xmin", 0))
                        xmax = float(current_interval.get("xmax", 0))
                    except (TypeError, ValueError):
                        xmin = xmax = 0.0
                    current_tier["intervals"].append({
                        "xmin": xmin,
                        "xmax": xmax,
                        "text": val,
                    })
                    current_interval = None
            elif current_tier is not None and not in_intervals:
                if key == "name":
                    current_tier["name"] = val
                elif key == "class" and val.lower() != "intervaltier":
                    current_tier["_skip"] = True
            continue

    out_tiers = []
    for t in tiers:
        if t.get("_skip"):
            continue
        intervals = [i for i in t.get("intervals", []) if isinstance(i, dict)]
        out_tiers.append({"name": t.get("name", ""), "intervals": intervals})
    return xmin_grid, xmax_grid, out_tiers


def _textgrid_to_tei_tree(
    path: str,
    *,
    audio_path: Optional[str] = None,
    audio_ext: Optional[str] = None,
    export_tiers: Optional[List[int]] = None,
    exclude_pattern: Optional[str] = None,
    tier_names: Optional[Dict[int, str]] = None,
) -> etree._Element:
    """
    Build a TEI tree for a TextGrid file.

    recordingStmt/media added when audio_path or stem suggests an audio file (like SRT).
    <text> contains <u start="" end="" who="tiername"> for each interval (empty text included
    when exclude_pattern is not used).
    """
    xmin_grid, xmax_grid, tiers = _parse_textgrid(path)
    base = os.path.basename(path)
    stem, _ = os.path.splitext(base)

    if tier_names is None:
        tier_names = {}
    if export_tiers is not None:
        tier_indices = set(export_tiers)
    else:
        tier_indices = set(range(1, len(tiers) + 1))

    exclude_re = re.compile(exclude_pattern) if exclude_pattern else None

    # Build one list of all intervals with global index (for id/n consistency).
    all_intervals: List[Tuple[float, float, str, str, int]] = []
    for idx, tier in enumerate(tiers, start=1):
        if idx not in tier_indices:
            continue
        who = tier_names.get(idx, tier.get("name", str(idx)))
        for iv in tier.get("intervals", []):
            text = (iv.get("text") or "").strip()
            if not text:
                continue
            if exclude_re and exclude_re.search(text):
                continue
            try:
                start = float(iv.get("xmin", 0))
                end = float(iv.get("xmax", 0))
            except (TypeError, ValueError):
                continue
            all_intervals.append((start, end, who, text, 0))  # index set below

    all_intervals.sort(key=lambda x: (x[0], x[1]))
    for i, t in enumerate(all_intervals):
        all_intervals[i] = (t[0], t[1], t[2], t[3], i + 1)

    # Detect tier roles for hierarchical output (word -> syll -> phones).
    who_lower = {t[2].lower() for t in all_intervals}
    words_like = who_lower & {"words", "word"}
    syll_like = who_lower & {"syll", "syllable", "syllables"}
    phones_like = who_lower & {"phones", "phone", "phoneme", "phonemes"}
    has_words = bool(words_like)
    use_hierarchical = has_words

    tei = etree.Element("TEI")
    header = etree.SubElement(tei, "teiHeader")
    when_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _ensure_tei_header(tei, source_filename=base, when=when_iso)

    ext = (audio_ext or "wav").lstrip(".")
    if audio_path:
        _, ext = os.path.splitext(audio_path)
        ext = ext.lstrip(".") or "wav"
    audio_file = os.path.basename(audio_path) if audio_path else f"{stem}.{ext}"
    recording_stmt = etree.SubElement(header, "recordingStmt")
    recording = etree.SubElement(recording_stmt, "recording", type="audio")
    media_el = etree.SubElement(
        recording,
        "media",
        mimeType=f"audio/{ext}",
        url=f"Audio/{audio_file}",
    )
    etree.SubElement(media_el, "desc")

    text_el = etree.SubElement(tei, "text", id=stem)

    if use_hierarchical:
        # Emit one <tok> per word interval, with nested <syll> and <ph> by time overlap.
        # Do not add any tail/newlines inside <tok>; whitespace there would become part of
        # the token content and not correspond to the input.
        word_who = next(w for w in (t[2] for t in all_intervals) if w.lower() in words_like)
        syll_who = next((w for w in (t[2] for t in all_intervals) if w.lower() in syll_like), None)
        phones_who = next((w for w in (t[2] for t in all_intervals) if w.lower() in phones_like), None)

        word_intervals = [(s, e, txt, idx) for (s, e, who, txt, idx) in all_intervals if who == word_who]
        # Optionally skip silence tokens (e.g. "_"); for now include them so alignment is preserved.
        tok_num = 0
        for w_start, w_end, w_text, w_idx in word_intervals:
            tok_num += 1
            tok = etree.SubElement(
                text_el,
                "tok",
                n=str(tok_num),
                id=f"u-{w_idx}",
                start=str(w_start),
                end=str(w_end),
            )
            tok.text = w_text or ""
            # Intervals that overlap this word's span and belong to syll or phones tier.
            nested = [
                (s, e, who, txt, idx)
                for (s, e, who, txt, idx) in all_intervals
                if s < w_end and e > w_start and ((syll_who and who == syll_who) or (phones_who and who == phones_who))
            ]
            # Syllables first (in time order), then phones (in time order).
            nested.sort(key=lambda x: (0 if x[2] == syll_who else 1, x[0], x[1]))
            for s, e, who, txt, idx in nested:
                if who == syll_who:
                    etree.SubElement(tok, "syll", n=str(idx), id=f"u-{idx}", start=str(s), end=str(e), form=txt or "")
                else:
                    etree.SubElement(tok, "ph", n=str(idx), id=f"u-{idx}", start=str(s), end=str(e), form=txt or "")
            # Praat has no word spacing; assume space between (phonological) tokens for display.
            # tail=" " gives spaces between toks; teitok_xml can expand to " \n  " for linebreaks when prettyprint=True.
            tok.tail = " "
        if word_intervals:
            text_el[-1].tail = ""  # no trailing space after last token

    else:
        # Flat: one <u> per interval (original behaviour). No tails so no extra whitespace in output.
        for start, end, who, text, idx in all_intervals:
            u = etree.SubElement(
                text_el,
                "u",
                n=str(idx),
                id=f"u-{idx}",
                start=str(start),
                end=str(end),
                who=who,
            )
            u.text = text

    return tei


def load_textgrid(
    path: str,
    *,
    doc_id: Optional[str] = None,
    audio_path: Optional[str] = None,
    audio_ext: Optional[str] = None,
    export_tiers: Optional[List[int]] = None,
    exclude_pattern: Optional[str] = None,
    tier_names: Optional[Dict[int, str]] = None,
) -> Document:
    """
    Load a Praat TextGrid file into a pivot Document.

    Same pattern as SRT/EAF: TEI tree in document.meta['_teitok_tei_root'], plus
    media, timeline, and 'utterances' layer with TIME anchors for downstream export.
    """
    tei_root = _textgrid_to_tei_tree(
        path,
        audio_path=audio_path,
        audio_ext=audio_ext,
        export_tiers=export_tiers,
        exclude_pattern=exclude_pattern,
        tier_names=tier_names,
    )

    if doc_id is None:
        doc_id = path
    doc = Document(id=doc_id)
    doc.meta["source_filename"] = os.path.basename(path)
    doc.meta["_teitok_tei_root"] = tei_root

    media_el = tei_root.find(".//media")
    audio_uri = ""
    mime_type = ""
    if media_el is not None:
        audio_uri = media_el.get("url") or ""
        mime_type = media_el.get("mimeType") or ""

    if audio_uri:
        media_id = "audio-1"
        doc.media[media_id] = MediaResource(
            id=media_id,
            uri=audio_uri,
            mime_type=mime_type,
        )
        timeline_id = "t1"
        doc.timelines[timeline_id] = Timeline(
            id=timeline_id,
            unit="seconds",
            media_id=media_id,
        )
        utter_layer = doc.get_or_create_layer("utterances")
        for u in tei_root.findall(".//u") or []:
            start_str = u.get("start") or "0"
            end_str = u.get("end") or "0"
            try:
                t_start = float(start_str)
            except ValueError:
                t_start = 0.0
            try:
                t_end = float(end_str)
            except ValueError:
                t_end = t_start
            anchor = Anchor(
                type=AnchorType.TIME,
                timeline_id=timeline_id,
                time_start=t_start,
                time_end=t_end,
            )
            uid = u.get("id") or f"u-{len(utter_layer.nodes) + 1}"
            features = {
                "n": u.get("n") or "",
                "who": u.get("who") or "",
                "text": (u.text or "").strip(),
            }
            node = Node(
                id=uid,
                type="utterance",
                anchors=[anchor],
                features=features,
            )
            utter_layer.nodes[node.id] = node
        for tok in tei_root.findall(".//tok") or []:
            start_str = tok.get("start") or "0"
            end_str = tok.get("end") or "0"
            try:
                t_start = float(start_str)
            except ValueError:
                t_start = 0.0
            try:
                t_end = float(end_str)
            except ValueError:
                t_end = t_start
            anchor = Anchor(
                type=AnchorType.TIME,
                timeline_id=timeline_id,
                time_start=t_start,
                time_end=t_end,
            )
            uid = tok.get("id") or f"tok-{len(utter_layer.nodes) + 1}"
            features = {
                "n": tok.get("n") or "",
                "text": (tok.text or "").strip(),
            }
            node = Node(
                id=uid,
                type="utterance",
                anchors=[anchor],
                features=features,
            )
            utter_layer.nodes[node.id] = node

    return doc
