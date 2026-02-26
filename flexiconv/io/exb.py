from __future__ import annotations

"""
EXMARaLDA basic transcription (.exb) → TEITOK-style TEI conversion.

Core behaviour:
- Read an EXMARaLDA basic transcription and produce TEI with:
  - Homogenized teiHeader (via _ensure_tei_header).
  - Additional metadata from <meta-information> and <speaker>-table, where present.
  - <text> containing a chronologically ordered sequence of <u> utterances:
      <u start="…" end="…" who="SPK">…inline markup…</u>
    where start/end come from TIME_LINE (<tli time="…"/>) and who is the speaker
    abbreviation (or the original EXMARaLDA @speaker code).

- Inline markup for common conventions:
  - Corrections, repetitions → <del reason="reformulation|repetition">…</del>
  - Unintelligible segments → <gap reason="unintelligible"/> / <gap extend="2+" …/>
  - Non-lexical/vocal noises → <vocal><desc>…</desc></vocal>
  - Truncation (&word) → <del reason="truncated">word</del>
  - Continuation marker " > " → <cont/>
  - Pauses "/" and "//" → <pause type="short|long"/>
  - Turn shifts "+" → <shift/>

The resulting TEI tree is stored as doc.meta["_teitok_tei_root"] so save_teitok
can write it verbatim.
"""

import os
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from lxml import etree

from ..core.model import Document
from .teitok_xml import _ensure_tei_header


def _load_exb_root(path: str) -> etree._Element:
    parser = etree.XMLParser(remove_blank_text=True)
    tree = etree.parse(path, parser)
    return tree.getroot()


def _convert_event_text(text: str) -> str:
    """
    Apply inline markup conventions to an event's text,
    returning an XML-ready string (without the surrounding <u> element).
    """
    # Unwrap any CDATA-like markers if present.
    text = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", text, flags=re.DOTALL)

    # Protect < and > so that regexes don't see real tags.
    text = text.replace("<", "«").replace(">", "»")

    # Speaker corrections: [///] and [//] patterns.
    text = re.sub(
        r"([^<>]*) \[///\]", r'<del reason="reformulation">\1</del>', text
    )
    text = re.sub(
        r"«([^<>»]+)» \[//\]", r'<del reason="reformulation">\1</del>', text
    )
    text = re.sub(
        r"([^ <>»]+) \[//\]", r'<del reason="reformulation">\1</del>', text
    )

    # Repetition: [/]
    text = re.sub(
        r"«([^<>»]+)» \[/\]", r'<del reason="repetition">\1</del>', text
    )
    text = re.sub(
        r"([^<> »]+) \[/\]", r'<del reason="repetition">\1</del>', text
    )

    # Unintelligible segments.
    text = text.replace("xxx", '<gap reason="unintelligible"/>')
    text = text.replace("yyyy", '<gap extend="2+" reason="unintelligible"/>')

    # Non-lexical/vocal noises.
    text = text.replace("hhh", "<vocal><desc>hhh</desc></vocal>")
    text = re.sub(
        r"&(ah|uh|hum|eh)",
        lambda m: f"<vocal><desc>{m.group(1)}</desc></vocal>",
        text,
    )

    # Truncation: &word → <del reason="truncated">word</del>
    text = re.sub(
        r"&([^ <>;/]+)([^;])", r'<del reason="truncated">\1</del>\2', text
    )

    # Continuation marker.
    text = re.sub(r" > ", " <cont/> ", text)
    text = re.sub(r" >$", " <cont/>", text)

    # Pauses.
    text = re.sub(r" / ", " <pause type=\"short\"/> ", text)
    text = re.sub(r" // ", " <pause type=\"long\"/> ", text)
    text = re.sub(r" //$", " <pause type=\"long\"/>", text)

    # Turn shifts.
    text = re.sub(r" \+ ", " <shift/> ", text)
    text = re.sub(r" \+$", " <shift/>", text)

    # Unprotect and escape.
    text = text.replace("&", "&amp;")
    text = text.replace("«", "&lt;").replace("»", "&gt;")

    return text.strip()


def _ensure_header_for_exb(tei: etree._Element, source_filename: str | None, meta_root: Optional[etree._Element]) -> None:
    """Create a standard flexiconv header, then enrich it with EXMARaLDA metadata."""
    when_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _ensure_tei_header(tei, source_filename=source_filename, when=when_iso)

    if meta_root is None:
        return

    header = tei.find("teiHeader")
    if header is None:
        header = etree.SubElement(tei, "teiHeader")
    fileDesc = header.find("fileDesc")
    if fileDesc is None:
        fileDesc = etree.SubElement(header, "fileDesc")
    titleStmt = fileDesc.find("titleStmt")
    if titleStmt is None:
        titleStmt = etree.SubElement(fileDesc, "titleStmt")
    notesStmt = fileDesc.find("notesStmt")
    if notesStmt is None:
        notesStmt = etree.SubElement(fileDesc, "notesStmt")
    profileDesc = header.find("profileDesc")
    if profileDesc is None:
        profileDesc = etree.SubElement(header, "profileDesc")
    textDesc = profileDesc.find("textDesc")
    if textDesc is None:
        textDesc = etree.SubElement(profileDesc, "textDesc")
    particDesc = profileDesc.find("particDesc")
    if particDesc is None:
        particDesc = etree.SubElement(profileDesc, "particDesc")
    listPerson = particDesc.find("listPerson")
    if listPerson is None:
        listPerson = etree.SubElement(particDesc, "listPerson")
    recordingStmt = header.find("recordingStmt")
    if recordingStmt is None:
        recordingStmt = etree.SubElement(header, "recordingStmt")

    # Basic meta-information fields.
    trans_name_el = meta_root.find(".//transcription-name")
    if trans_name_el is not None and (trans_name_el.text or "").strip():
        title_el = titleStmt.find("title")
        if title_el is None:
            title_el = etree.SubElement(titleStmt, "title")
        title_el.text = (trans_name_el.text or "").strip()

    comment_el = meta_root.find(".//comment")
    if comment_el is not None and (comment_el.text or "").strip():
        note = etree.SubElement(notesStmt, "note", n="comment")
        note.text = (comment_el.text or "").strip()

    # Project, topic, etc. go into notesStmt or textDesc as simple notes.
    for elem_name, n_val in [
        ("project-name", "project"),
        ("ud-information[@attribute-name='Topic']", "topic"),
        ("ud-information[@attribute-name='Code in CRPC']", "CRPC id"),
    ]:
        el = meta_root.find(f".//{elem_name}")
        if el is not None and (el.text or "").strip():
            note = etree.SubElement(notesStmt, "note", n=n_val)
            note.text = (el.text or "").strip()

    # Channel (communication channel) → textDesc/channel element.
    channel_el = meta_root.find(".//ud-information[@attribute-name='Communication channel']")
    if channel_el is not None and (channel_el.text or "").strip():
        ch = textDesc.find("channel") or etree.SubElement(textDesc, "channel")
        ch.set("mode", "s")
        ch.text = (channel_el.text or "").strip()

    # Country / settlement / date → recordingStmt.
    country_el = meta_root.find(".//ud-information[@attribute-name='Country']")
    if country_el is not None and (country_el.text or "").strip():
        c = recordingStmt.find("country") or etree.SubElement(recordingStmt, "country")
        c.text = (country_el.text or "").strip()

    place_el = meta_root.find(".//ud-information[@attribute-name='Place of the recording']")
    if place_el is not None and (place_el.text or "").strip():
        s = recordingStmt.find("settlement") or etree.SubElement(recordingStmt, "settlement")
        s.text = (place_el.text or "").strip()

    # lxml's limited XPath in .find() does not support starts-with(), so we scan manually.
    date_el = None
    for cand in meta_root.findall(".//ud-information"):
        attr = cand.get("attribute-name") or ""
        if attr.startswith("Date") and (cand.text or "").strip():
            date_el = cand
            break
    if date_el is not None and (date_el.text or "").strip():
        d = recordingStmt.find("date") or etree.SubElement(recordingStmt, "date")
        d.text = (date_el.text or "").strip()

    # Minimal generic recording/media placeholder.
    rec = recordingStmt.find("recording")
    if rec is None:
        rec = etree.SubElement(recordingStmt, "recording", type="audio")
    media = rec.find("media") or etree.SubElement(rec, "media")
    # We keep a simple relative URL based on the EXB basename, user can adjust in TEITOK.
    if source_filename:
        stem, _ = os.path.splitext(source_filename)
        media.set("mimeType", "audio/wav")
        media.set("url", f"Audio/{stem}.wav")

    # Speakers → listPerson entries (id, name, gender, age, role, etc.).
    parent_root = meta_root.getroottree().getroot()
    for idx, sp in enumerate(parent_root.findall(".//speaker"), start=1):
        sp_id = sp.get("id") or f"S{idx}"
        abbr_el = sp.find("abbreviation")
        abbr = (abbr_el.text or "").strip() if abbr_el is not None else sp_id
        prs = etree.SubElement(
            listPerson,
            "person",
            id=abbr,
            n=str(idx),
        )
        # Sex
        sex_el = sp.find("sex")
        if sex_el is not None and (sex_el.get("value") or "").strip():
            prs.set("sex", sex_el.get("value") or "")
        # Age, role, etc. from ud-information children.
        def _ud(attr_name: str) -> str:
            el = sp.find(f".//ud-information[@attribute-name='{attr_name}']")
            return (el.text or "").strip() if el is not None and (el.text or "").strip() else ""

        age = _ud("Age")
        if age:
            prs.set("age", age)
        role = _ud("Role")
        if role:
            prs.set("role", role)

        name = _ud("Name")
        if name:
            name_el = etree.SubElement(prs, "name")
            name_el.text = name
        nation = _ud("Geographical origin")
        if nation:
            nat_el = etree.SubElement(prs, "nationality")
            nat_el.text = nation
        edu = _ud("Education")
        if edu:
            edu_el = etree.SubElement(prs, "education")
            edu_el.text = edu
        prof = _ud("Profession")
        if prof:
            socec = etree.SubElement(prs, "socecStatus")
            socec.text = prof
        res = _ud("Residence")
        if res:
            res_el = etree.SubElement(prs, "residence")
            res_el.text = res


def load_exb(path: str, *, doc_id: Optional[str] = None) -> Document:
    """
    Load an EXMARaLDA basic transcription (.exb) into a pivot Document,
    attaching a TEITOK-style TEI tree in doc.meta['_teitok_tei_root'].
    """
    root = _load_exb_root(path)
    base = os.path.basename(path)

    # Speaker abbreviations: EXMARaLDA @speaker → TEITOK who code.
    speaker_abbr: Dict[str, str] = {}
    for sp in root.findall(".//speaker"):
        sid = sp.get("id") or ""
        if not sid:
            continue
        abbr_el = sp.find("abbreviation")
        if abbr_el is not None and (abbr_el.text or "").strip():
            speaker_abbr[sid] = (abbr_el.text or "").strip()
        else:
            speaker_abbr[sid] = sid

    # Timeline: tli id → time string.
    tli_time: Dict[str, str] = {}
    for tli in root.findall(".//tli"):
        tid = tli.get("id") or ""
        tval = tli.get("time")
        if not tid or tval is None:
            continue
        tli_time[tid] = tval

    # TEI skeleton with header, enriched from meta-information.
    tei = etree.Element("TEI")
    meta_root = root.find(".//meta-information")
    _ensure_header_for_exb(tei, source_filename=base, meta_root=meta_root)

    text_el = etree.SubElement(tei, "text", id=os.path.splitext(base)[0])

    # Collect all events as (start_time_float, seq, <u>) to sort globally.
    events: List[Tuple[float, int, etree._Element]] = []
    seq = 0
    multi_speaker = len(speaker_abbr) > 1

    for tier in root.findall(".//tier"):
        speaker_ref = tier.get("speaker") or ""
        who_code = speaker_abbr.get(speaker_ref, speaker_ref)

        for ev in tier.findall("event"):
            start_ref = ev.get("start") or ""
            end_ref = ev.get("end") or ""
            if not start_ref or not end_ref:
                continue
            start_time_str = tli_time.get(start_ref)
            end_time_str = tli_time.get(end_ref)
            if start_time_str is None or end_time_str is None:
                continue

            raw_text = "".join(ev.itertext() or []).strip()
            if not raw_text:
                continue

            body = _convert_event_text(raw_text)
            attrs = f' start="{start_time_str}" end="{end_time_str}"'
            if multi_speaker and who_code:
                attrs += f' who="{who_code}"'
            u_xml = f"<u{attrs}>{body}</u>"
            try:
                u_el = etree.fromstring(u_xml)
            except etree.XMLSyntaxError:
                # Fallback: plain text in case of unexpected markup issues.
                u_el = etree.Element("u")
                u_el.set("start", start_time_str)
                u_el.set("end", end_time_str)
                if multi_speaker and who_code:
                    u_el.set("who", who_code)
                u_el.text = raw_text

            try:
                start_float = float(start_time_str)
            except ValueError:
                start_float = float(len(events))
            events.append((start_float, seq, u_el))
            seq += 1

    # Sort by numeric start time, then by original order.
    events.sort(key=lambda t: (t[0], t[1]))
    for _, _, u_el in events:
        if len(text_el) == 0:
            text_el.text = "\n"
        else:
            prev = text_el[-1]
            prev.tail = (prev.tail or "") + "\n"
        text_el.append(u_el)

    # Wrap into Document and store TEI root for TEITOK saver.
    if doc_id is None:
        doc_id = path
    doc = Document(id=doc_id)
    doc.meta["source_filename"] = base
    doc.meta["_teitok_tei_root"] = tei
    return doc


def _tei_to_exb(tei_root: etree._Element, source_filename: Optional[str] = None) -> etree._Element:
    """
    Convert a TEITOK-style TEI tree with <u start/end who> back into a minimal
    EXMARaLDA basic transcription (.exb).

    This is intended to be symmetric with load_exb for the common case:
    - <u start="…" end="…" who="CODE">…</u> → <event start="Ti" end="Tj">…</event>
    - one <tier> per distinct speaker code
    - a single common timeline with one <tli> per distinct time value
    """
    # Collect utterances.
    text_el = tei_root.find(".//text")
    if text_el is None:
        raise ValueError("TEI document has no <text> element; cannot export to EXB")
    us = list(text_el.findall("u") or [])
    if not us:
        raise ValueError("TEI document has no <u> utterances; cannot export to EXB")

    # Speaker codes from @who; default to "SPK" when absent.
    who_codes: List[str] = []
    for u in us:
        who = u.get("who") or "SPK"
        if who not in who_codes:
            who_codes.append(who)
    if not who_codes:
        who_codes = ["SPK"]

    # Map speaker codes to EXB speaker ids (SPK0, SPK1, ...).
    speaker_id_by_code: Dict[str, str] = {}
    for idx, code in enumerate(who_codes):
        speaker_id_by_code[code] = f"SPK{idx}"

    # Time-line: distinct start/end times (as strings), sorted numerically.
    time_values: Dict[str, float] = {}
    for u in us:
        for attr in ("start", "end"):
            val = u.get(attr)
            if not val:
                continue
            if val not in time_values:
                try:
                    time_values[val] = float(val)
                except ValueError:
                    # Fallback: order by insertion if not numeric.
                    time_values[val] = float(len(time_values))
    if not time_values:
        raise ValueError("TEI utterances lack @start/@end times; cannot export to EXB")

    # Sort by numeric value and assign T0, T1, ...
    sorted_times = sorted(time_values.items(), key=lambda kv: kv[1])
    tli_by_time: Dict[str, str] = {}
    for idx, (t_str, _) in enumerate(sorted_times):
        tli_by_time[t_str] = f"T{idx}"

    # Build EXMARaLDA basic-transcription skeleton.
    bt = etree.Element("basic-transcription")
    head = etree.SubElement(bt, "head")
    meta_info = etree.SubElement(head, "meta-information")
    # Transcription name: reuse source filename when available.
    trans_name = etree.SubElement(meta_info, "transcription-name")
    if source_filename:
        trans_name.text = source_filename

    # Referenced file from TEI recordingStmt/media when present.
    media_el = tei_root.find(".//media")
    if media_el is not None:
        url = media_el.get("url") or ""
        if url:
            ref = etree.SubElement(meta_info, "referenced-file")
            ref.set("url", os.path.basename(url))

    # Minimal speakertable: one speaker per @who code.
    speakertable = etree.SubElement(head, "speakertable")
    for code in who_codes:
        spk_id = speaker_id_by_code[code]
        spk_el = etree.SubElement(speakertable, "speaker", id=spk_id)
        abbr_el = etree.SubElement(spk_el, "abbreviation")
        abbr_el.text = code

    # Body with timeline and tiers.
    body = etree.SubElement(bt, "basic-body")
    timeline = etree.SubElement(body, "common-timeline")
    for t_str, tli_id in tli_by_time.items():
        etree.SubElement(timeline, "tli", id=tli_id, time=t_str)

    # Prepare tiers per speaker code.
    tier_by_code: Dict[str, etree._Element] = {}
    for code in who_codes:
        spk_id = speaker_id_by_code[code]
        tier = etree.SubElement(
            body,
            "tier",
            id=f"TIER_{spk_id}",
            speaker=spk_id,
        )
        tier_by_code[code] = tier

    # Emit events from <u>.
    for u in us:
        start = u.get("start") or ""
        end = u.get("end") or ""
        if not start or not end:
            continue
        start_id = tli_by_time.get(start)
        end_id = tli_by_time.get(end)
        if not start_id or not end_id:
            continue
        who = u.get("who") or "SPK"
        tier = tier_by_code.get(who)
        if tier is None:
            # Should not happen, but fallback to first tier.
            tier = next(iter(tier_by_code.values()))
        ev = etree.SubElement(tier, "event", start=start_id, end=end_id)
        # Preserve u's inner XML/text as the event content.
        # We serialize children to string; if there are none, just copy text.
        if len(u):
            parts: List[str] = []
            if u.text and u.text.strip():
                parts.append(etree.CDATA(u.text))
            for ch in u:
                parts.append(etree.tostring(ch, encoding="unicode"))
            ev.text = "".join(str(p) for p in parts)
        else:
            ev.text = u.text or ""

    return bt


def save_exb(doc: Document, path: str) -> None:
    """
    Save a pivot Document as an EXMARaLDA basic transcription (.exb).

    This currently requires that the Document carries a TEITOK TEI tree in
    doc.meta['_teitok_tei_root'], i.e. that it ultimately originated from
    an EXB/TEITOK/SRT-style time-aligned TEI file.
    """
    tei_root = doc.meta.get("_teitok_tei_root")
    if tei_root is None or not isinstance(tei_root, etree._Element):
        raise ValueError(
            "Document has no TEI tree in doc.meta['_teitok_tei_root']; cannot save as EXB"
        )
    source_filename = doc.meta.get("source_filename")
    exb_root = _tei_to_exb(tei_root, source_filename=source_filename)
    tree = etree.ElementTree(exb_root)
    tree.write(path, encoding="utf-8", xml_declaration=True, pretty_print=True)


