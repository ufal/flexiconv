from __future__ import annotations

"""
EAF (ELAN) to TEITOK-style TEI conversion.

Core behaviour:
- Create a TEI document with:
  - Standardized teiHeader (via _ensure_tei_header).
  - recordingStmt/media entries for each MEDIA_DESCRIPTOR.
  - <text> with one <u> per ALIGNABLE_ANNOTATION, with @who, @tier, @start, @end.
  - Additional REF_ANNOTATIONs attached as attributes on the corresponding <u>.

Pivot model:
- Store full TEI tree in document.meta['_teitok_tei_root'] so save_teitok can
  write it verbatim.
- Populate:
  - media[...] from MEDIA_DESCRIPTORs.
  - a single Timeline (unit=seconds) corresponding to TIME_ORDER (TIME_VALUE/1000).
  - an 'utterances' layer: one node per <u>, anchored by TIME.

This makes it possible in principle to convert EAF → ELAN via FPM later.
"""

import os
from datetime import datetime, timezone
from typing import Dict, Optional

from lxml import etree

from ..core.model import Anchor, AnchorType, Document, MediaResource, Node, Timeline
from .teitok_xml import _ensure_tei_header


def _load_eaf_tree(path: str) -> etree._Element:
    parser = etree.XMLParser(remove_blank_text=True)
    tree = etree.parse(path, parser)
    return tree.getroot()


def _eaf_to_tei_tree(path: str, *, style: str = "generic") -> etree._Element:
    root = _load_eaf_tree(path)
    base = os.path.basename(path)

    tei = etree.Element("TEI")
    header = etree.SubElement(tei, "teiHeader")

    # Standard TEI header bits (fileDesc, notesStmt, encodingDesc, revisionDesc with flexiconv).
    when_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _ensure_tei_header(tei, source_filename=base, when=when_iso)

    # recordingStmt/media entries for each MEDIA_DESCRIPTOR.
    recording_stmt = etree.SubElement(header, "recordingStmt")
    for media_node in root.xpath(".//*[local-name()='MEDIA_DESCRIPTOR']"):
        media_url = media_node.get("MEDIA_URL") or ""
        media_url = media_url.lstrip("./")
        if media_url.startswith("file:"):
            # Keep only basename for file:// URLs
            media_url = os.path.basename(media_url)

        recording = etree.SubElement(recording_stmt, "recording", type="audio")
        media_el = etree.SubElement(recording, "media")
        if media_url:
            media_el.set("url", media_url)
        mime = media_node.get("MIME_TYPE")
        if mime:
            media_el.set("mimeType", mime)

    # Timeline: TIME_SLOT_ID -> TIME_VALUE (ms), and reverse mapping.
    time_slots: Dict[str, float] = {}
    for ts in root.xpath(".//*[local-name()='TIME_ORDER']/*[local-name()='TIME_SLOT']"):
        slot_id = ts.get("TIME_SLOT_ID") or ""
        val = ts.get("TIME_VALUE")
        if not slot_id or val is None:
            continue
        try:
            ms = float(val)
        except ValueError:
            continue
        time_slots[slot_id] = ms

    text_el = etree.SubElement(tei, "text")

    # Collect annotations: ALIGNABLE_ANNOTATIONs and REF_ANNOTATIONs.
    # We first gather all ALIGNABLE_ANNOTATIONs keyed by their ANNOTATION_ID,
    # then add REF_ANNOTATIONs as additional attributes to them.
    anns: Dict[str, Dict[str, object]] = {}

    # DORECO-specific tier handling: certain tiers are either skipped or have
    # participant encoded in the TIER_ID (e.g. "tx@SPK").
    doreco_skip_tiers = {
        "doreco-mb-algn",
        "comment",
        "notes",
        "comments",
    }

    for tier in root.xpath(".//*[local-name()='TIER']"):
        tier_id_raw = tier.get("TIER_ID") or ""
        who_attr = tier.get("PARTICIPANT") or ""
        tier_id = tier_id_raw
        who = who_attr

        if style == "doreco":
            # Split TIER_ID on '@' to recover (tier_id, who) for dependent tiers
            if "@" in tier_id_raw:
                base_tier, spk = tier_id_raw.split("@", 1)
                tier_id = base_tier
                # Participant from TIER_ID overrides PARTICIPANT attribute.
                who = spk or who_attr or tier_id
            # Skip known DORECO helper tiers.
            if tier_id in doreco_skip_tiers:
                continue
        if not who:
            who = tier_id

        # Sanitize dependent tier attribute name: strip non-alnum.
        ann_name = "".join(ch for ch in tier_id if ch.isalnum())

        # ALIGNABLE_ANNOTATIONs → utterances
        for ann in tier.xpath("./*[local-name()='ANNOTATION']/*[local-name()='ALIGNABLE_ANNOTATION']"):
            ann_id = ann.get("ANNOTATION_ID") or ""
            if not ann_id:
                continue
            start_ref = ann.get("TIME_SLOT_REF1") or ""
            end_ref = ann.get("TIME_SLOT_REF2") or ""
            txt_nodes = ann.xpath("./*[local-name()='ANNOTATION_VALUE']")
            txt = "".join((txt_nodes[0].text or "") if txt_nodes else "").strip()
            anns[ann_id] = {
                "tier": tier_id,
                "who": who,
                "ann_name": ann_name,
                "start_ref": start_ref,
                "end_ref": end_ref,
                "text": txt,
                "refs": {},  # filled by REF_ANNOTATIONs
            }

        # REF_ANNOTATIONs → extra attributes on their referenced ALIGNABLE_ANNOTATION
        for ref_ann in tier.xpath("./*[local-name()='ANNOTATION']/*[local-name()='REF_ANNOTATION']"):
            ref_id = ref_ann.get("ANNOTATION_ID") or ""
            ann_ref = ref_ann.get("ANNOTATION_REF") or ""
            if not ann_ref:
                continue
            txt_nodes = ref_ann.xpath("./*[local-name()='ANNOTATION_VALUE']")
            txt = "".join((txt_nodes[0].text or "") if txt_nodes else "").strip()
            if not txt:
                continue
            target = anns.get(ann_ref)
            if target is None:
                # If ALIGNABLE_ANNOTATION hasn't been seen yet, create a stub and fill later.
                target = {
                    "tier": tier_id,
                    "who": who,
                    "ann_name": ann_name,
                    "start_ref": "",
                    "end_ref": "",
                    "text": "",
                    "refs": {},
                }
                anns[ann_ref] = target
            refs = target["refs"]  # type: ignore[assignment]
            if isinstance(refs, dict):
                refs[ann_name] = txt

    # Emit <u> in TEI text, one per ALIGNABLE_ANNOTATION that has a start_ref.
    # Sort by start time for stable order.
    def _start_ms(entry: Dict[str, object]) -> float:
        sr = str(entry.get("start_ref") or "")
        return time_slots.get(sr, 0.0)

    for ann_id, data in sorted(anns.items(), key=lambda kv: _start_ms(kv[1])):
        start_ref = str(data.get("start_ref") or "")
        end_ref = str(data.get("end_ref") or "")
        if not start_ref or not end_ref:
            # Skip pure REF_ANNOTATION stubs without own time anchors.
            continue
        start_ms = time_slots.get(start_ref, 0.0)
        end_ms = time_slots.get(end_ref, start_ms)
        start_sec = start_ms / 1000.0
        end_sec = end_ms / 1000.0

        who = str(data.get("who") or "")
        tier_id = str(data.get("tier") or "")
        txt = str(data.get("text") or "")

        # Flush each <u> onto its own line for readability.
        if len(text_el) == 0:
            text_el.text = "\n  "
        else:
            prev = text_el[-1]
            prev.tail = (prev.tail or "") + "\n  "

        u = etree.SubElement(
            text_el,
            "u",
            id=ann_id,
            start=str(start_sec),
            end=str(end_sec),
        )
        if who:
            u.set("who", who)
        if tier_id:
            u.set("tier", tier_id)
        if txt:
            u.text = txt

        # Attach REF_ANNOTATION-based attributes.
        refs = data.get("refs") or {}
        if isinstance(refs, dict):
            for key, val in sorted(refs.items()):
                if not key:
                    continue
                u.set(key, str(val))

    return tei


def load_eaf(path: str, *, doc_id: Optional[str] = None, style: str = "generic") -> Document:
    """
    Load an EAF file into a pivot Document and attach a TEITOK-style TEI tree.

    - Stores the TEI root under document.meta['_teitok_tei_root'] so save_teitok
      can write it verbatim.
    - Populates media/timelines/utterances so future ELAN export is possible.
    """
    tei_root = _eaf_to_tei_tree(path, style=style)

    if doc_id is None:
        doc_id = path
    doc = Document(id=doc_id)
    doc.meta["source_filename"] = os.path.basename(path)
    doc.meta["_teitok_tei_root"] = tei_root

    # Media: from recordingStmt/media in the TEI header we just built.
    media_nodes = tei_root.xpath(".//*[local-name()='teiHeader']//*[local-name()='media']")
    media_ids = []
    for idx, m_el in enumerate(media_nodes, start=1):
        uri = m_el.get("url") or ""
        mime = m_el.get("mimeType") or ""
        if not uri:
            continue
        media_id = f"audio-{idx}"
        doc.media[media_id] = MediaResource(
            id=media_id,
            uri=uri,
            mime_type=mime,
        )
        media_ids.append(media_id)

    # Single timeline for now: ELAN's TIME_ORDER is global. We use seconds as in TEI.
    timeline_id = "t1"
    media_id_for_timeline = media_ids[0] if media_ids else None
    doc.timelines[timeline_id] = Timeline(
        id=timeline_id,
        unit="seconds",
        media_id=media_id_for_timeline,
    )

    # Utterances layer from <u start/end>.
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
            uid = (
                u.get("id")
                or u.get("{http://www.w3.org/XML/1998/namespace}id")
                or f"u-{len(utter_layer.nodes) + 1}"
            )
            features = {
                "who": u.get("who") or "",
                "tier": u.get("tier") or "",
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

