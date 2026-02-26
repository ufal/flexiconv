from __future__ import annotations

"""
SRT (SubRip) to TEITOK-style TEI conversion.

This produces TEITOK-style TEI with time-aligned <u> and recordingStmt:
  - Creates a TEI header with a recordingStmt/media pointing at the audio file.
  - Under <text>, emits one <u> per subtitle, with @n, @id, @start, @end and the text.

In addition, we also fill the pivot Document so that future SRT → ELAN conversion is
possible via FPM:
  - A MediaResource for the audio.
  - A Timeline (unit=seconds) linked to that media.
  - An 'utterances' layer with one node per subtitle, anchored by TIME (start/end).
"""

import os
import re
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from lxml import etree

from ..core.model import Anchor, AnchorType, Document, MediaResource, Node, Timeline
from .teitok_xml import _ensure_tei_header


_TIME_RE = re.compile(
    r"^\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*$"
)


def _time_to_seconds(
    h: str, m: str, s: str, ms: str,
) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def _seconds_to_srt_time(sec: float) -> str:
    """Format seconds as SRT timestamp HH:MM:SS,mmm."""
    if sec < 0:
        sec = 0.0
    total_ms = int(round(sec * 1000))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _parse_srt_blocks(text: str) -> List[Tuple[str, float, float, str]]:
    """
    Parse an SRT file into (number, start_seconds, end_seconds, text) tuples.

    This is more robust than the original Perl script (which assumed a strict
    4-line pattern), but preserves its basic behaviour.
    """
    blocks: List[List[str]] = []
    current: List[str] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r\n")
        if line.strip():
            current.append(line)
        else:
            if current:
                blocks.append(current)
                current = []
    if current:
        blocks.append(current)

    result: List[Tuple[str, float, float, str]] = []
    for block in blocks:
        if len(block) < 2:
            continue
        n_line = block[0].strip()
        time_line = block[1]
        m = _TIME_RE.match(time_line)
        if not m:
            continue
        sh, sm, ss, sms, eh, em, es, ems = m.groups()
        start = _time_to_seconds(sh, sm, ss, sms)
        end = _time_to_seconds(eh, em, es, ems)
        # Remaining lines are the subtitle text; join with spaces.
        text_lines = [ln.strip() for ln in block[2:] if ln.strip()]
        txt = " ".join(text_lines)
        if not txt:
            continue
        result.append((n_line, start, end, txt))
    return result


def _srt_to_tei_tree(
    path: str,
    *,
    audio_path: Optional[str] = None,
    audio_ext: Optional[str] = None,
) -> etree._Element:
    """
    Build a TEI tree for an SRT file:

    <TEI>
      <teiHeader>
        <recordingStmt>
          <recording type="audio">
            <media mimeType="audio/{ext}" url="Audio/{audiofile}">
              <desc/>
            </media>
          </recording>
        </recordingStmt>
        <revisionDesc>
          <change who="flexiconv" when="YYYY-MM-DD">Converted from SRT file ...</change>
        </revisionDesc>
      </teiHeader>
      <text>
        <u n="1" id="u-1" start="..." end="...">...</u>
        ...
      </text>
    </TEI>
    """
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    segments = _parse_srt_blocks(content)

    # Derive audio filename and extension from path or default.
    base = os.path.basename(path)
    stem, _ = os.path.splitext(base)
    if audio_ext:
        ext = audio_ext
    elif audio_path:
        _, ext = os.path.splitext(audio_path)
        ext = (ext.lstrip(".") or "wav")
    else:
        ext = "wav"
    if audio_path:
        audio_file = os.path.basename(audio_path)
    else:
        audio_file = f"{stem}.{ext}"

    tei = etree.Element("TEI")
    header = etree.SubElement(tei, "teiHeader")

    # Standardize header (fileDesc, notesStmt, encodingDesc, revisionDesc with flexiconv)
    when_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _ensure_tei_header(tei, source_filename=base, when=when_iso)

    # Recording statement with audio media.
    recording_stmt = etree.SubElement(header, "recordingStmt")
    recording = etree.SubElement(recording_stmt, "recording", type="audio")
    media_el = etree.SubElement(
        recording,
        "media",
        mimeType=f"audio/{ext}",
        url=f"Audio/{audio_file}",
    )
    etree.SubElement(media_el, "desc")

    # Add an additional revisionDesc/change entry documenting the original SRT conversion.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rev = header.find("revisionDesc")
    if rev is None:
        rev = etree.SubElement(header, "revisionDesc")
    change = etree.SubElement(rev, "change", who="flexiconv", when=today)
    change.text = f"Converted from SRT file {base}"

    text_el = etree.SubElement(tei, "text")
    for n_str, start, end, txt in segments:
        # Flush each <u> onto its own line for readability, similar to how we
        # treat paragraph-like blocks elsewhere: newline before each utterance.
        if len(text_el) == 0:
            text_el.text = "\n  "
        else:
            prev = text_el[-1]
            prev.tail = (prev.tail or "") + "\n  "
        u = etree.SubElement(
            text_el,
            "u",
            n=str(n_str),
            id=f"u-{n_str}",
            start=str(start),
            end=str(end),
        )
        u.text = txt

    return tei


def load_srt(
    path: str,
    *,
    doc_id: Optional[str] = None,
    audio_path: Optional[str] = None,
    audio_ext: Optional[str] = None,
) -> Document:
    """
    Load an SRT file into a pivot Document and attach a TEITOK-style TEI tree.

    - The TEI tree (with <recordingStmt>/<media> and <u start/end>) is stored in
      document.meta['_teitok_tei_root'] so that save_teitok writes it verbatim.
    - The pivot Document also contains:
      - media['audio-1']: MediaResource pointing at the audio file.
      - timelines['t1']: Timeline (unit=seconds) linked to that media.
      - layer 'utterances': one Node per subtitle, anchored by TIME.

    This makes it possible in principle to convert SRT → ELAN via FPM in a later step.
    """
    tei_root = _srt_to_tei_tree(path, audio_path=audio_path, audio_ext=audio_ext)

    if doc_id is None:
        doc_id = path
    doc = Document(id=doc_id)
    doc.meta["source_filename"] = os.path.basename(path)
    doc.meta["_teitok_tei_root"] = tei_root

    # Derive audio URL and extension from the TEI header we just built.
    media_el = tei_root.find(".//media")
    audio_uri = ""
    mime_type = ""
    if media_el is not None:
        audio_uri = media_el.get("url") or ""
        mime_type = media_el.get("mimeType") or ""

    # Populate media and timeline so time-aligned formats (e.g. ELAN) can be targeted later.
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
        text_el = tei_root.find(".//text")
        if text_el is not None:
            for u in text_el.findall("u") or []:
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
                uid = u.get("id") or u.get("{http://www.w3.org/XML/1998/namespace}id") or ""
                if not uid:
                    uid = f"u-{len(utter_layer.nodes) + 1}"
                features = {
                    "n": u.get("n") or "",
                    "text": "".join(u.itertext()).strip(),
                }
                node = Node(
                    id=uid,
                    type="utterance",
                    anchors=[anchor],
                    features=features,
                )
                utter_layer.nodes[node.id] = node

    return doc


def save_srt(document: Document, path: str) -> None:
    """
    Write an SRT file from a pivot Document.

    Prefers the TEITOK TEI tree (with <u start/end>) when available in
    document.meta['_teitok_tei_root'], falling back to the 'utterances'
    layer with TIME anchors when no TEI tree is present.
    """
    segments: List[Tuple[float, float, str]] = []

    tei_root = document.meta.get("_teitok_tei_root")
    if isinstance(tei_root, etree._Element):
        text_el = tei_root.find(".//text")
        if text_el is not None:
            for u in text_el.findall("u") or []:
                start_str = u.get("start") or "0"
                end_str = u.get("end") or "0"
                try:
                    start = float(start_str)
                except ValueError:
                    start = 0.0
                try:
                    end = float(end_str)
                except ValueError:
                    end = start
                txt = "".join(u.itertext()).strip()
                if not txt:
                    continue
                segments.append((start, end, txt))

    # Fallback: use 'utterances' layer with TIME anchors.
    if not segments:
        utter = document.layers.get("utterances")
        if utter:
            for node in utter.nodes.values():
                if not node.anchors:
                    continue
                a = node.anchors[0]
                if a.type != AnchorType.TIME:
                    continue
                start = a.time_start or 0.0
                end = a.time_end or start
                txt = str(node.features.get("text", "")).strip()
                if not txt:
                    continue
                segments.append((start, end, txt))

    # Sort by start time for stable output.
    segments.sort(key=lambda t: t[0])

    lines: List[str] = []
    for idx, (start, end, txt) in enumerate(segments, start=1):
        lines.append(str(idx))
        lines.append(f"{_seconds_to_srt_time(start)} --> {_seconds_to_srt_time(end)}")
        lines.append(txt)
        lines.append("")  # blank line after each cue

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

