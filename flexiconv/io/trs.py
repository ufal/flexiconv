"""
Transcriber TRS → TEITOK-style TEI conversion.

TRS is an XML format for audio transcription (Transcriber). Structure:
Trans > Episode > Section (startTime, endTime) > Turn (startTime, endTime, speaker, mode).
Turn content is mixed: <Sync time="..."/> elements and text nodes. Each Sync starts a new
<tok start="...">; the previous tok gets end="..."; text between Syncs goes into the current tok.

Output: <text><ab><ug start end><u start end who mode><tok start end>...</tok></u></ug></ab></text>
with recordingStmt/media from Trans @audio_filename. Stored in document.meta["_teitok_tei_root"];
utterances layer is filled from <u> for downstream export.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple

from lxml import etree

from ..core.model import Anchor, AnchorType, Document, MediaResource, Node, Timeline
from .teitok_xml import _ensure_tei_header, _xpath_local


def _local_name(el: etree._Element) -> str:
    return (el.tag or "").split("}")[-1]


def _build_tei_from_trs(path: str) -> etree._Element:
    """Build a TEITOK-style TEI tree from a TRS XML file."""
    parser = etree.XMLParser(remove_blank_text=True)
    tree = etree.parse(path, parser)
    root = tree.getroot()

    base = os.path.basename(path)
    stem, _ = os.path.splitext(base)
    when_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    tei = etree.Element("TEI")
    header = etree.SubElement(tei, "teiHeader")
    _ensure_tei_header(tei, source_filename=base, when=when_iso)
    header = tei.find("teiHeader")

    audio_filename = root.get("audio_filename") or root.get("audioFilename") or ""
    if audio_filename:
        recording_stmt = header.find("recordingStmt")
        if recording_stmt is None:
            recording_stmt = etree.SubElement(header, "recordingStmt")
        recording = etree.SubElement(recording_stmt, "recording", type="audio")
        ext = os.path.splitext(audio_filename)[1].lstrip(".") or "wav"
        media_el = etree.SubElement(
            recording,
            "media",
            mimeType=f"audio/{ext}",
            url=audio_filename,
        )
        etree.SubElement(media_el, "desc")

    text_el = etree.SubElement(tei, "text", id=stem)

    episodes = root.xpath(".//*[local-name()='Episode']")
    for episode in episodes:
        ab = etree.SubElement(text_el, "ab")
        sections = episode.xpath("*[local-name()='Section']")
        for section in sections:
            start_t = section.get("startTime") or section.get("start") or "0"
            end_t = section.get("endTime") or section.get("end") or "0"
            ug = etree.SubElement(ab, "ug", start=start_t, end=end_t)
            turns = section.xpath("*[local-name()='Turn']")
            for turn in turns:
                start_t = turn.get("startTime") or turn.get("start") or "0"
                end_t = turn.get("endTime") or turn.get("end") or "0"
                u_attrib = {"start": start_t, "end": end_t}
                speaker = turn.get("speaker") or turn.get("who")
                if speaker:
                    u_attrib["who"] = speaker
                mode = turn.get("mode")
                if mode:
                    u_attrib["mode"] = mode
                u = etree.SubElement(ug, "u", **u_attrib)

                # Turn has mixed content: Sync elements and text (turn.text, child.tail).
                # Build list of ( "sync", time ) or ( "text", str )
                parts: List[Tuple[str, str]] = []
                if turn.text and turn.text.strip():
                    parts.append(("text", turn.text.strip()))
                for child in turn:
                    if _local_name(child) in ("Sync", "sync"):
                        time_val = child.get("time") or child.get("start") or "0"
                        parts.append(("sync", time_val))
                    if child.tail and child.tail.strip():
                        parts.append(("text", child.tail.strip()))

                current_tok: Optional[etree._Element] = None
                for kind, value in parts:
                    if kind == "sync":
                        if current_tok is not None:
                            current_tok.set("end", value)
                        current_tok = etree.SubElement(u, "tok", start=value)
                        current_tok.text = ""
                    else:
                        if current_tok is not None:
                            prev = (current_tok.text or "").strip()
                            current_tok.text = (prev + " " + value).strip() if prev else value
                        else:
                            current_tok = etree.SubElement(u, "tok", start=start_t)
                            current_tok.text = value

                if current_tok is not None and not current_tok.get("end"):
                    current_tok.set("end", end_t)

    return tei


def load_trs(path: str, **kwargs: Any) -> Document:
    """Load a Transcriber TRS file into a pivot Document with TEITOK-style TEI in meta."""
    tei = _build_tei_from_trs(path)
    base = os.path.basename(path)
    stem, _ = os.path.splitext(base)
    doc = Document(id=stem)
    doc.meta["_teitok_tei_root"] = tei
    doc.meta["source_filename"] = base

    audio_uri = ""
    mime_type = "audio/wav"
    media_el = tei.find(".//media")
    if media_el is not None:
        audio_uri = (media_el.get("url") or "").strip()
        mime_type = (media_el.get("mimeType") or "").strip() or "audio/wav"

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
        for u in tei.findall(".//u"):
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
                "mode": u.get("mode") or "",
                "text": " ".join((t.text or "").strip() for t in u.findall("tok")).strip(),
            }
            node = Node(
                id=uid,
                type="utterance",
                anchors=[anchor],
                features=features,
            )
            utter_layer.nodes[node.id] = node

    return doc
