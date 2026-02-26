from __future__ import annotations

"""
DoReCo-specific EAF → TEITOK converter for single-speaker DoReCo files.

Goals:
- Reproduce the TEI structure in tests/doreco_bain1259_DJI041109AC-ttool.xml
  from examples/elan/doreco_bain1259_DJI041109AC.eaf:
  - Minimal TEI header with fileDesc, recordingStmt/media, and a
    revisionDesc/change who="flexiconv".
  - <text> containing a sequence of:
      <u who="HS" tier="ref" start="…" end="…" eid="…" text="…" gloss="…">…</u>
      <pause wd="&lt;p:&gt;"/>
    where <u> have nested <tok> and <m> elements with wd/form/morph/gloss.

This loader focuses on building that TEI tree and storing it in the
Document's metadata for save_teitok to write verbatim. It does not yet
replicate every metadata.csv-based enrichment, or all edge-case repairs.
"""

import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from lxml import etree

from ..core.model import Document
from .hocr import _split_punct


class _MorphSeg:
    def __init__(self, form: str, gloss: str = "") -> None:
        self.form = form
        self.gloss = gloss


class _Token:
    def __init__(self, ann_id: str, wd: str) -> None:
        self.ann_id = ann_id
        self.wd = wd
        self.morph_segs: List[_MorphSeg] = []


class _Utterance:
    def __init__(self, ann_id: str, start_sec: float, end_sec: float, who: str) -> None:
        self.ann_id = ann_id
        self.start = start_sec
        self.end = end_sec
        self.who = who
        self.eid: str = ""
        self.text: str = ""
        self.gloss: str = ""
        self.tokens: List[_Token] = []


def _load_eaf_root(path: str) -> etree._Element:
    parser = etree.XMLParser(remove_blank_text=True)
    tree = etree.parse(path, parser)
    return tree.getroot()


def _build_doreco_tei(path: str) -> etree._Element:
    root = _load_eaf_root(path)
    base = os.path.basename(path)

    # Timeline: TIME_SLOT_ID -> TIME_VALUE (ms)
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

    # Utterances (by ref tier) and pauses
    utters: Dict[str, _Utterance] = {}
    events: List[Tuple[float, str, Optional[str]]] = []

    for tier in root.xpath(".//*[local-name()='TIER']"):
        tier_id_raw = tier.get("TIER_ID") or ""
        if not tier_id_raw:
            continue
        # Split TIER_ID like "ref@HS" into base tier "ref" and speaker "HS"
        if "@" in tier_id_raw:
            base_tier, spk = tier_id_raw.split("@", 1)
            tier_id = base_tier
            who = spk or (tier.get("PARTICIPANT") or "")
        else:
            tier_id = tier_id_raw
            who = tier.get("PARTICIPANT") or ""

        if tier_id != "ref":
            continue

        for ann in tier.xpath("./*[local-name()='ANNOTATION']/*[local-name()='ALIGNABLE_ANNOTATION']"):
            ann_id = ann.get("ANNOTATION_ID") or ""
            if not ann_id:
                continue
            start_ref = ann.get("TIME_SLOT_REF1") or ""
            end_ref = ann.get("TIME_SLOT_REF2") or ""
            start_ms = time_slots.get(start_ref, 0.0)
            end_ms = time_slots.get(end_ref, start_ms)
            start_sec = start_ms / 1000.0
            end_sec = end_ms / 1000.0
            txt_nodes = ann.xpath("./*[local-name()='ANNOTATION_VALUE']")
            txt = "".join((txt_nodes[0].text or "") if txt_nodes else "").strip()

            # ref tier can contain pause markers "<p:>" between sentences.
            if txt == "<p:>":
                events.append((start_ms, "pause", None))
                continue

            utt = _Utterance(ann_id=ann_id, start_sec=start_sec, end_sec=end_sec, who=who or tier_id)
            utt.eid = txt  # sentence ID from ref tier
            utters[ann_id] = utt
            events.append((start_ms, "utt", ann_id))

    # Sentence text (tx tier) and free translation (ft tier)
    def _fill_utt_attr_from_ref_tier(base_tier: str, attr: str) -> None:
        for tier in root.xpath(".//*[local-name()='TIER']"):
            tier_id_raw = tier.get("TIER_ID") or ""
            if not tier_id_raw:
                continue
            if "@" in tier_id_raw:
                t_base, _ = tier_id_raw.split("@", 1)
            else:
                t_base = tier_id_raw
            if t_base != base_tier:
                continue
            for ref_ann in tier.xpath("./*[local-name()='ANNOTATION']/*[local-name()='REF_ANNOTATION']"):
                ann_ref = ref_ann.get("ANNOTATION_REF") or ""
                utt = utters.get(ann_ref)
                if utt is None:
                    continue
                txt_nodes = ref_ann.xpath("./*[local-name()='ANNOTATION_VALUE']")
                txt = "".join((txt_nodes[0].text or "") if txt_nodes else "").strip()
                if not txt:
                    continue
                if attr == "text":
                    utt.text = txt
                elif attr == "gloss":
                    utt.gloss = txt

    _fill_utt_attr_from_ref_tier("tx", "text")
    _fill_utt_attr_from_ref_tier("ft", "gloss")

    # Words (wd tier) → token records per utterance
    tokens_by_wd_id: Dict[str, _Token] = {}

    for tier in root.xpath(".//*[local-name()='TIER']"):
        tier_id_raw = tier.get("TIER_ID") or ""
        if not tier_id_raw:
            continue
        if "@" in tier_id_raw:
            t_base, _ = tier_id_raw.split("@", 1)
        else:
            t_base = tier_id_raw
        if t_base != "wd":
            continue
        for ref_ann in tier.xpath("./*[local-name()='ANNOTATION']/*[local-name()='REF_ANNOTATION']"):
            wd_id = ref_ann.get("ANNOTATION_ID") or ""
            ann_ref = ref_ann.get("ANNOTATION_REF") or ""
            utt = utters.get(ann_ref)
            if utt is None or not wd_id:
                continue
            txt_nodes = ref_ann.xpath("./*[local-name()='ANNOTATION_VALUE']")
            wd_text = "".join((txt_nodes[0].text or "") if txt_nodes else "").strip()
            if not wd_text:
                continue
            tok = _Token(ann_id=wd_id, wd=wd_text)
            utt.tokens.append(tok)
            tokens_by_wd_id[wd_id] = tok

    # Morpheme segments (mb tier) and glosses (gl tier)
    seg_by_mb_id: Dict[str, _MorphSeg] = {}

    for tier in root.xpath(".//*[local-name()='TIER']"):
        tier_id_raw = tier.get("TIER_ID") or ""
        if not tier_id_raw:
            continue
        if "@" in tier_id_raw:
            t_base, _ = tier_id_raw.split("@", 1)
        else:
            t_base = tier_id_raw

        # mb: morpheme forms, attached to wd
        if t_base == "mb":
            for ref_ann in tier.xpath("./*[local-name()='ANNOTATION']/*[local-name()='REF_ANNOTATION']"):
                mb_id = ref_ann.get("ANNOTATION_ID") or ""
                wd_ref = ref_ann.get("ANNOTATION_REF") or ""
                tok = tokens_by_wd_id.get(wd_ref)
                if tok is None or not mb_id:
                    continue
                txt_nodes = ref_ann.xpath("./*[local-name()='ANNOTATION_VALUE']")
                seg_text = "".join((txt_nodes[0].text or "") if txt_nodes else "").strip()
                if not seg_text:
                    continue
                seg = _MorphSeg(form=seg_text)
                tok.morph_segs.append(seg)
                seg_by_mb_id[mb_id] = seg

        # gl: morpheme glosses, attached to mb
        if t_base == "gl":
            for ref_ann in tier.xpath("./*[local-name()='ANNOTATION']/*[local-name()='REF_ANNOTATION']"):
                mb_ref = ref_ann.get("ANNOTATION_REF") or ""
                seg = seg_by_mb_id.get(mb_ref)
                if seg is None:
                    continue
                txt_nodes = ref_ann.xpath("./*[local-name()='ANNOTATION_VALUE']")
                gloss_text = "".join((txt_nodes[0].text or "") if txt_nodes else "").strip()
                if not gloss_text:
                    continue
                seg.gloss = gloss_text

    # Build TEI tree
    tei = etree.Element("TEI")
    header = etree.SubElement(tei, "teiHeader")
    # Minimal header as in doreco_bain1259_DJI041109AC-ttool.xml
    etree.SubElement(header, "fileDesc")

    recording_stmt = etree.SubElement(header, "recordingStmt")
    # Media from MEDIA_DESCRIPTOR
    for media_node in root.xpath(".//*[local-name()='MEDIA_DESCRIPTOR']"):
        media_url = media_node.get("MEDIA_URL") or ""
        media_url = media_url.lstrip("./")
        if media_url.startswith("file:"):
            media_url = os.path.basename(media_url)
        recording = etree.SubElement(recording_stmt, "recording")
        media_el = etree.SubElement(recording, "media")
        if media_url:
            media_el.set("url", media_url)
        mime = media_node.get("MIME_TYPE")
        if mime:
            media_el.set("mimeType", mime)

    rev = etree.SubElement(header, "revisionDesc")
    today = datetime.now().strftime("%Y-%m-%d")
    change = etree.SubElement(rev, "change", who="flexiconv", when=today)
    change.text = f"Converted from ELAN file {base}"

    text_el = etree.SubElement(tei, "text")

    # Sort events by start time (ms) and emit <u> and <pause> in order.
    for _, etype, ref_id in sorted(events, key=lambda t: t[0]):
        if etype == "pause":
            # Flush before pause element.
            if len(text_el) == 0:
                text_el.text = "\n"
            else:
                prev = text_el[-1]
                prev.tail = (prev.tail or "") + "\n"
            pause = etree.SubElement(text_el, "pause")
            # Use the literal marker "<p:>" so the serializer will escape it
            # as &lt;p:&gt;, matching the ttools output.
            pause.set("wd", "<p:>")
            continue

        utt = utters.get(ref_id or "")
        if utt is None:
            continue

        # Flush before each <u>
        if len(text_el) == 0:
            text_el.text = "\n"
        else:
            prev = text_el[-1]
            prev.tail = (prev.tail or "") + "\n"

        u = etree.SubElement(
            text_el,
            "u",
            who=utt.who,
            tier="ref",
            start=str(round(utt.start, 3)).rstrip("0").rstrip(".") if utt.start else "0",
            end=str(round(utt.end, 3)).rstrip("0").rstrip(".") if utt.end else "0",
        )
        if utt.eid:
            u.set("eid", utt.eid)
        if utt.text:
            u.set("text", utt.text)
        if utt.gloss:
            u.set("gloss", utt.gloss)

        # Tokens and morphemes, with hOCR-like punctuation splitting: split leading/
        # trailing punctuation into separate <tok> without morph/gloss, and keep
        # morph/gloss only on the lexical part. Exception: if the whole word is
        # punctuation but has morph/gloss in the EAF (e.g. "?" with mb="****"),
        # emit it as a full lexical token with wd and <m> to match ttools.
        for tok in utt.tokens:
            segments = _split_punct(tok.wd)
            # Single segment that is punct but has morph data → treat as lexical
            only_punct = len(segments) == 1 and segments[0][1] and tok.morph_segs
            lexical_seen = False
            for seg, is_punct in segments:
                if not seg:
                    continue
                tok_el = etree.SubElement(u, "tok")
                if is_punct and not only_punct:
                    # For pure punctuation, ttools outputs <tok>'</tok> without a wd
                    # attribute, so we only set the textual content here.
                    tok_el.text = seg
                    continue

                if not lexical_seen or only_punct:
                    if not lexical_seen:
                        lexical_seen = True
                    tok_el.set("wd", tok.wd)
                    if tok.morph_segs:
                        morph = ".".join(s.form for s in tok.morph_segs if s.form)
                        gloss = ".".join(s.gloss for s in tok.morph_segs if s.gloss)
                        if morph:
                            tok_el.set("morph", morph)
                        if gloss:
                            tok_el.set("gloss", gloss)
                    tok_el.text = seg
                    for seg_m in tok.morph_segs:
                        m_el = etree.SubElement(tok_el, "m", form=seg_m.form)
                        if seg_m.gloss:
                            m_el.set("gloss", seg_m.gloss)
                    if only_punct:
                        continue
                else:
                    tok_el.set("wd", seg)
                    tok_el.text = seg

    return tei


def load_doreco(path: str, *, doc_id: Optional[str] = None) -> Document:
    """
    Load a DoReCo-style EAF file into a pivot Document.

    - Builds a TEI tree matching doreco_bain1259_DJI041109AC-ttool.xml as closely
      as possible for ref/tx/ft/wd/mb/gl tiers and pause markers.
    - Stores that TEI tree in document.meta['_teitok_tei_root'] so save_teitok
      can write it verbatim.

    This loader does NOT currently populate token/morpheme layers in the pivot
    model; the authoritative representation for DoReCo is the TEITOK TEI itself.
    """
    tei_root = _build_doreco_tei(path)
    if doc_id is None:
        doc_id = path
    doc = Document(id=doc_id)
    doc.meta["source_filename"] = os.path.basename(path)
    doc.meta["_teitok_tei_root"] = tei_root
    return doc


def _tei_to_doreco_eaf(tei_root: etree._Element) -> etree._Element:
    """
    Convert a DoReCo-style TEITOK TEI tree back into a minimal DoReCo EAF file.

    This inverts _build_doreco_tei for the core tiers:
    - TIME_ORDER from <u @start/@end> (seconds → milliseconds).
    - ref@SPK: ALIGNABLE_ANNOTATIONs (eid as ANNOTATION_VALUE, or empty).
    - tx@SPK, ft@SPK: REF_ANNOTATIONs with utterance text/gloss.
    - wd@SPK: REF_ANNOTATIONs for lexical <tok wd="..."> (punctuation-only <tok> without wd are skipped).
    - mb@SPK, gl@SPK: REF_ANNOTATIONs for <m form/gloss> attached to their wd.

    It ignores auxiliary DoReCo tiers such as HAS_morph-gls-fr; those could be
    reintroduced later if needed.
    """
    # Namespace for xsi:noNamespaceSchemaLocation
    nsmap = {"xsi": "http://www.w3.org/2001/XMLSchema-instance"}
    eaf = etree.Element(
        "ANNOTATION_DOCUMENT",
        nsmap=nsmap,
    )

    # Basic document attributes
    now_iso = datetime.now().isoformat()
    eaf.set("AUTHOR", "flexiconv")
    eaf.set("DATE", now_iso)
    eaf.set("FORMAT", "3.0")
    eaf.set("VERSION", "3.0")
    eaf.set(
        "{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation",
        "http://www.mpi.nl/tools/elan/EAFv3.0.xsd",
    )

    # HEADER with MEDIA_DESCRIPTOR from TEI recordingStmt/media when present.
    header = etree.SubElement(eaf, "HEADER", MEDIA_FILE="", TIME_UNITS="milliseconds")
    media_nodes = tei_root.xpath(".//*[local-name()='teiHeader']//*[local-name()='media']")
    for m in media_nodes:
        url = (m.get("url") or "").lstrip("./")
        mime = m.get("mimeType") or ""
        md = etree.SubElement(header, "MEDIA_DESCRIPTOR")
        if url:
            # Keep relative URL similar to original DoReCo EAFs.
            md.set("MEDIA_URL", url)
            md.set("RELATIVE_MEDIA_URL", "./" + url)
        if mime:
            md.set("MIME_TYPE", mime)

    # TIME_ORDER: create distinct time slots for each utterance start/end (ms).
    time_order = etree.SubElement(eaf, "TIME_ORDER")
    ts_counter = 1

    def _new_ts(time_ms: int) -> str:
        nonlocal ts_counter
        ts_id = f"ts{ts_counter}"
        ts_counter += 1
        etree.SubElement(
            time_order,
            "TIME_SLOT",
            TIME_SLOT_ID=ts_id,
            TIME_VALUE=str(int(time_ms)),
        )
        return ts_id

    # Collect utterances (<u>) and pauses (<pause>) in document order under <text>.
    text_el = tei_root.find(".//text")
    if text_el is None:
        raise ValueError("DoReCo TEI has no <text> element; cannot export to EAF")

    # For now we assume single-speaker DoReCo as in the loader.
    # Use first encountered @who (or 'SPK' as fallback).
    who_vals: List[str] = []
    for u in text_el.findall("u"):
        who = u.get("who") or ""
        if who and who not in who_vals:
            who_vals.append(who)
    if not who_vals:
        who_vals.append("SPK")

    # We only support single-speaker export for now; use the first speaker.
    who = who_vals[0]
    ref_id = f"ref@{who}"

    # Core tiers for that speaker.
    tier_ref = etree.SubElement(
        eaf,
        "TIER",
        DEFAULT_LOCALE="en",
        LINGUISTIC_TYPE_REF="ref",
        PARTICIPANT=who,
        TIER_ID=ref_id,
    )
    tier_ft = etree.SubElement(
        eaf,
        "TIER",
        DEFAULT_LOCALE="en",
        LINGUISTIC_TYPE_REF="ft",
        PARENT_REF=ref_id,
        PARTICIPANT=who,
        TIER_ID=f"ft@{who}",
    )
    tier_tx = etree.SubElement(
        eaf,
        "TIER",
        LINGUISTIC_TYPE_REF="tx",
        PARENT_REF=ref_id,
        PARTICIPANT=who,
        TIER_ID=f"tx@{who}",
    )
    tier_wd = etree.SubElement(
        eaf,
        "TIER",
        DEFAULT_LOCALE="en",
        LINGUISTIC_TYPE_REF="wd",
        PARENT_REF=ref_id,
        PARTICIPANT=who,
        TIER_ID=f"wd@{who}",
    )
    tier_mb = etree.SubElement(
        eaf,
        "TIER",
        DEFAULT_LOCALE="en",
        LINGUISTIC_TYPE_REF="mb",
        PARENT_REF=f"wd@{who}",
        PARTICIPANT=who,
        TIER_ID=f"mb@{who}",
    )
    tier_gl = etree.SubElement(
        eaf,
        "TIER",
        DEFAULT_LOCALE="en",
        LINGUISTIC_TYPE_REF="gl",
        PARENT_REF=f"mb@{who}",
        PARTICIPANT=who,
        TIER_ID=f"gl@{who}",
    )

    # Helpers to add annotations.
    ann_counter = 0

    def _new_ann_id() -> str:
        nonlocal ann_counter
        ann_id = f"a{ann_counter}"
        ann_counter += 1
        return ann_id

    def _add_alignable(tier: etree._Element, ts1: str, ts2: str, value: str) -> str:
        ann_id = _new_ann_id()
        ann_wrap = etree.SubElement(tier, "ANNOTATION")
        align = etree.SubElement(
            ann_wrap,
            "ALIGNABLE_ANNOTATION",
            ANNOTATION_ID=ann_id,
            TIME_SLOT_REF1=ts1,
            TIME_SLOT_REF2=ts2,
        )
        val_el = etree.SubElement(align, "ANNOTATION_VALUE")
        val_el.text = value
        return ann_id

    def _add_ref(tier: etree._Element, ref_ann: str, value: str) -> str:
        ann_id = _new_ann_id()
        ann_wrap = etree.SubElement(tier, "ANNOTATION")
        ref = etree.SubElement(
            ann_wrap,
            "REF_ANNOTATION",
            ANNOTATION_ID=ann_id,
            ANNOTATION_REF=ref_ann,
        )
        val_el = etree.SubElement(ref, "ANNOTATION_VALUE")
        val_el.text = value
        return ann_id

    # Iterate children of <text> to preserve pauses between utterances.
    prev_end_ms = 0
    for child in list(text_el):
        local = (child.tag or "").split("}")[-1]
        if local == "pause":
            # Represent pauses as ALIGNABLE_ANNOTATIONs on ref tier with "<p:>".
            # Anchor them at the previous utterance's end time when available.
            wd = child.get("wd") or "<p:>"
            ts = _new_ts(prev_end_ms)
            _add_alignable(tier_ref, ts, ts, wd)
            continue

        if local != "u":
            continue

        u = child
        start_str = u.get("start") or "0"
        end_str = u.get("end") or start_str
        try:
            start_sec = float(start_str)
        except ValueError:
            start_sec = 0.0
        try:
            end_sec = float(end_str)
        except ValueError:
            end_sec = start_sec

        start_ms = int(round(start_sec * 1000.0))
        end_ms = int(round(end_sec * 1000.0))
        prev_end_ms = end_ms

        ts1 = _new_ts(start_ms)
        ts2 = _new_ts(end_ms)

        eid = u.get("eid") or ""
        text_val = u.get("text") or ""
        gloss_val = u.get("gloss") or ""

        # ALIGNABLE_ANNOTATION on ref tier.
        ref_ann_id = _add_alignable(tier_ref, ts1, ts2, eid)

        # tx/ft tiers as REF_ANNOTATIONs pointing to ref.
        if text_val:
            _add_ref(tier_tx, ref_ann_id, text_val)
        if gloss_val:
            _add_ref(tier_ft, ref_ann_id, gloss_val)

        # wd/mb/gl tiers from <tok> and nested <m>.
        for tok_el in u.findall("tok"):
            wd = tok_el.get("wd")
            if not wd:
                # Skip pure punctuation tokens; DoReCo wd tier only holds lexical words.
                continue
            wd_ann_id = _add_ref(tier_wd, ref_ann_id, wd)
            # Morpheme segments for this word.
            for m_el in tok_el.findall("m"):
                form = m_el.get("form") or ""
                if not form:
                    continue
                mb_ann_id = _add_ref(tier_mb, wd_ann_id, form)
                gloss = m_el.get("gloss") or ""
                if gloss:
                    _add_ref(tier_gl, mb_ann_id, gloss)

    # Linguistic types for the core tiers, approximating the original DoReCo EAF.
    etree.SubElement(
        eaf,
        "LINGUISTIC_TYPE",
        GRAPHIC_REFERENCES="false",
        LINGUISTIC_TYPE_ID="ref",
        TIME_ALIGNABLE="true",
    )
    etree.SubElement(
        eaf,
        "LINGUISTIC_TYPE",
        CONSTRAINTS="Symbolic_Association",
        GRAPHIC_REFERENCES="false",
        LINGUISTIC_TYPE_ID="ft",
        TIME_ALIGNABLE="false",
    )
    etree.SubElement(
        eaf,
        "LINGUISTIC_TYPE",
        CONSTRAINTS="Symbolic_Association",
        GRAPHIC_REFERENCES="false",
        LINGUISTIC_TYPE_ID="tx",
        TIME_ALIGNABLE="false",
    )
    etree.SubElement(
        eaf,
        "LINGUISTIC_TYPE",
        CONSTRAINTS="Symbolic_Subdivision",
        GRAPHIC_REFERENCES="false",
        LINGUISTIC_TYPE_ID="wd",
        TIME_ALIGNABLE="false",
    )
    etree.SubElement(
        eaf,
        "LINGUISTIC_TYPE",
        CONSTRAINTS="Symbolic_Subdivision",
        GRAPHIC_REFERENCES="false",
        LINGUISTIC_TYPE_ID="mb",
        TIME_ALIGNABLE="false",
    )
    etree.SubElement(
        eaf,
        "LINGUISTIC_TYPE",
        CONSTRAINTS="Symbolic_Association",
        GRAPHIC_REFERENCES="false",
        LINGUISTIC_TYPE_ID="gl",
        TIME_ALIGNABLE="false",
    )

    # Default locale as in typical DoReCo EAFs.
    etree.SubElement(eaf, "LOCALE", COUNTRY_CODE="US", LANGUAGE_CODE="en")

    return eaf


def save_doreco(doc: Document, path: str) -> None:
    """
    Save a pivot Document as a DoReCo-style EAF file.

    For now this requires that the Document carries a DoReCo TEITOK TEI tree in
    doc.meta['_teitok_tei_root'], i.e. that it ultimately originated from a
    DoReCo EAF via load_doreco or a compatible pipeline.
    """
    tei_root = doc.meta.get("_teitok_tei_root")
    if tei_root is None or not isinstance(tei_root, etree._Element):
        raise ValueError("Document has no DoReCo TEI tree in doc.meta['_teitok_tei_root']; cannot save as doreco EAF")
    eaf_root = _tei_to_doreco_eaf(tei_root)
    tree = etree.ElementTree(eaf_root)
    tree.write(path, encoding="utf-8", xml_declaration=True, pretty_print=True)

