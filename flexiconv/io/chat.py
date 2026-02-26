from __future__ import annotations

"""
CHAT (.cha) → TEITOK-style TEI converter.

Goals:
- Read CHILDES/CHAT transcripts and produce a TEI tree with:
  - Homogenized teiHeader (via _ensure_tei_header) plus CHAT-specific metadata
    (participants, media, languages, etc.) where available.
  - <text> containing:
      * <u who="CODE">…</u> utterances for speaker lines (*CODE: ...)
      * optional begin/end attributes on <u> when timing codes start_end are present
      * <note n="channel">…</note> elements for %channel: tiers
- Store the TEI root in doc.meta["_teitok_tei_root"] so save_teitok can reuse it.

Inline markup follows the common "heritage" option for CHAT; other options fall back to plain-text <u>.
"""

import os
import re
from datetime import datetime, timezone
from typing import Optional

from lxml import etree

from ..core.model import Document
from .teitok_xml import _ensure_tei_header


_TIMING_RE = re.compile(r"\x15(\d+)_(\d+)\x15")


def _sanitize(s: str) -> str:
    """Rudimentary sanitisation of control characters for XML 1.0."""
    # Strip characters that are not allowed in XML 1.0.
    return re.sub(r"[^\x09\x0A\x0D\x20-\xFF]", "", s)


def _conv_utt(trans: str, option: str) -> etree._Element:
    """
    Port of convutt() for the 'heritage' option; other options fall back to plain <u>.
    """
    text = trans
    begin: Optional[float] = None
    end: Optional[float] = None

    # Timing codes: begin_end (milliseconds) → begin/end (seconds)
    m = _TIMING_RE.search(text)
    if m:
        try:
            begin = int(m.group(1)) / 1000.0
            end = int(m.group(2)) / 1000.0
        except ValueError:
            begin = end = None
        text = text[: m.start()] + text[m.end() :]

    # Protect for XML
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    if option == "heritage":
        # Apply regex-based inline markup (heritage option)
        text = re.sub(r"&lt;(.*?)&gt;", r'<del reason="reformulation">\1</del>', text)
        text = re.sub(r"&amp;([^ <>]+)", r'<del reason="truncation">\1</del>', text)
        text = re.sub(r"\((.*?)\)", r"<ex>\1</ex>", text)
        text = re.sub(r"([^ ]+)@([^ ]+)", r'<sic n="\2">\1</sic>', text)
        text = text.replace("xxx", '<gap reason="unintelligible">xxx</gap>')
        text = text.replace("www", '<gap reason="non-transcribed"/>')
        text = text.replace("[/]", '<pause type="short"/>')
        text = text.replace("[//]", '<pause type="long"/>')

    attrs = ""
    if begin is not None and end is not None:
        attrs = f' begin="{begin}" end="{end}"'
    xml = f"<u{attrs}>{text}</u>"
    return etree.fromstring(xml)


def _ensure_header_for_chat(tei: etree._Element, source_filename: str | None) -> None:
    """Create a standard flexiconv header, then reuse it for CHAT-specific metadata."""
    when_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _ensure_tei_header(tei, source_filename=source_filename, when=when_iso)


def load_chat(path: str, *, doc_id: Optional[str] = None, options: Optional[str] = None) -> Document:
    """
    Load a CHAT (.cha) file into a pivot Document, attaching a TEI tree in
    doc.meta['_teitok_tei_root'] with the TEI output structure.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()

    # Merge indented continuation lines
    raw = re.sub(r"\n\s+(?!\(\d)", " ", raw)

    # Detect options from @Options or timing markers if not provided explicitly.
    if options is None:
        m_opt = re.search(r"^@Options:\s*(.+)$", raw, flags=re.MULTILINE)
        if m_opt:
            options = m_opt.group(1).strip()
        elif _TIMING_RE.search(raw):
            options = "CA"

    # Build TEI skeleton with standard header.
    tei = etree.Element("TEI")
    _ensure_header_for_chat(tei, source_filename=os.path.basename(path))
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
    pubStmt = fileDesc.find("publicationStmt")
    if pubStmt is None:
        pubStmt = etree.SubElement(fileDesc, "publicationStmt")
    profileDesc = header.find("profileDesc")
    if profileDesc is None:
        profileDesc = etree.SubElement(header, "profileDesc")
    langUsage = profileDesc.find("langUsage")
    if langUsage is None:
        langUsage = etree.SubElement(profileDesc, "langUsage")
    textClass = profileDesc.find("textClass")
    if textClass is None:
        textClass = etree.SubElement(profileDesc, "textClass")
    keywords = textClass.find("keywords")
    if keywords is None:
        keywords = etree.SubElement(textClass, "keywords")
    particDesc = profileDesc.find("particDesc")
    if particDesc is None:
        particDesc = etree.SubElement(profileDesc, "particDesc")
    listPerson = particDesc.find("listPerson")
    if listPerson is None:
        listPerson = etree.SubElement(particDesc, "listPerson")
    recordingStmt = header.find("recordingStmt")
    if recordingStmt is None:
        recordingStmt = etree.SubElement(header, "recordingStmt")

    text_el = tei.find("text")
    if text_el is None:
        text_el = etree.SubElement(tei, "text")

    # Helpers for header population
    persons: dict[str, etree._Element] = {}
    intext = False  # whether we've started emitting <u>/<note> content yet

    for raw_line in raw.split("\n"):
        line = raw_line.replace("\r", "").replace("\0", "")
        if not line.strip():
            continue

        m_meta = re.match(r"@([^:]+):\s*(.*)", line)
        if m_meta:
            fld = m_meta.group(1)
            orgval = m_meta.group(2)
            val = _sanitize(orgval.strip())

            if fld == "Options":
                # Already handled above; keep for completeness.
                if not options:
                    options = val
            elif fld == "Participants":
                for pfld in val.split(", "):
                    parts = pfld.split()
                    if len(parts) < 3:
                        continue
                    code, name, role = parts[0], " ".join(parts[1:-1]), parts[-1]
                    person = etree.SubElement(listPerson, "person", id=code, role=role)
                    person.text = name
                    persons[code] = person
            elif fld == "ID":
                # @ID: language|corpus|code|age|sex|group|ethnicity|role|education|custom|
                fields = val.split("|")
                if len(fields) < 3:
                    continue
                code = fields[2]
                person = persons.get(code)
                if person is None:
                    continue
                # 0: language
                lang = fields[0] or ""
                if lang:
                    langKnown = etree.SubElement(
                        person, "langKnowledge"
                    ).find("langKnown")
                    if langKnown is None:
                        langKnown = etree.SubElement(
                            person, "langKnown", level="first"
                        )
                    langKnown.text = lang
                # 3: age
                if len(fields) > 3 and fields[3]:
                    person.set("age", fields[3])
                # 4: sex
                if len(fields) > 4 and fields[4]:
                    person.set("sex", fields[4])
                # 5: group → note[n="group"]
                if len(fields) > 5 and fields[5]:
                    n = etree.SubElement(person, "note", n="group")
                    n.text = fields[5]
                # 6: ethnicity → note[n="ethnicity"]
                if len(fields) > 6 and fields[6]:
                    n = etree.SubElement(person, "note", n="ethnicity")
                    n.text = fields[6]
                # 8: education
                if len(fields) > 8 and fields[8]:
                    edu = etree.SubElement(person, "education")
                    edu.text = fields[8]
                # 9: custom
                if len(fields) > 9 and fields[9]:
                    n = etree.SubElement(person, "note", n="custom")
                    n.text = fields[9]
            elif fld == "Media":
                # @Media: recurl, type
                parts = [p.strip() for p in val.split(",")]
                if parts:
                    recurl = parts[0]
                    mtype = parts[1] if len(parts) > 1 else ""
                else:
                    recurl, mtype = "", ""
                media = recordingStmt.find("recording")
                if media is None:
                    media = etree.SubElement(recordingStmt, "recording")
                media_el = media.find("media") or etree.SubElement(media, "media")
                if recurl and "." not in recurl:
                    if mtype == "audio":
                        recurl = recurl + ".mp3"
                        media_el.set("mimeType", "audio/mp3")
                    elif mtype == "video":
                        recurl = recurl + ".mpg"
                        media_el.set("mimeType", "video/mpg")
                if recurl:
                    media_el.set("url", recurl)
            elif fld in {"Languages", "Language"}:
                if val:
                    lang_el = etree.SubElement(langUsage, "language")
                    lang_el.set("ident", val)
            elif fld == "Comment":
                note = etree.SubElement(notesStmt, "note")
                note.text = val
            elif fld == "Title":
                title_el = titleStmt.find("title") or etree.SubElement(titleStmt, "title")
                title_el.text = val
            elif fld == "Date":
                date_el = titleStmt.find("date") or etree.SubElement(titleStmt, "date")
                date_el.text = val
            elif fld in {"Types", "Subject"}:
                term = etree.SubElement(keywords, "term")
                term.set("type", "genre")
                term.text = val
            elif fld == "Transcriber":
                respStmt = titleStmt.find("respStmt") or etree.SubElement(titleStmt, "respStmt")
                resp = etree.SubElement(respStmt, "resp", n="Transcription")
                resp.text = val
            elif fld == "Creator":
                respStmt = titleStmt.find("respStmt") or etree.SubElement(titleStmt, "respStmt")
                resp = etree.SubElement(respStmt, "resp", n="Creator")
                resp.text = val
            elif fld == "Publisher":
                publ = pubStmt.find("publisher") or etree.SubElement(pubStmt, "publisher")
                publ.text = val
            elif fld == "PID":
                idno = etree.SubElement(pubStmt, "idno", type="handle")
                idno.text = val
            else:
                # Unknown header fields → notesStmt/note[@n=...]
                note = etree.SubElement(notesStmt, "note", n=fld)
                note.text = val
            continue

        # Transcription and dependent tiers
        m_utt = re.match(r"\*([^:]+):\s*(.*)", line)
        if m_utt:
            who = m_utt.group(1)
            trans = m_utt.group(2)
            intext = True

            if options:
                try:
                    u_el = _conv_utt(trans, options)
                except etree.XMLSyntaxError:
                    # Fallback to plain <u> on parse issues.
                    u_el = etree.Element("u")
                    u_el.text = trans
            else:
                u_el = etree.Element("u")
                u_el.text = trans

            u_el.set("who", who)
            text_el.append(u_el)
            continue

        m_dep = re.match(r"%([^:]+):\s*(.*)", line)
        if m_dep:
            channel = m_dep.group(1)
            val = m_dep.group(2)
            note = etree.SubElement(text_el, "note", n=channel)
            note.text = val
            intext = True
            continue

        # Other lines are ignored (debug-only in the Perl version).

    # Wrap into a pivot Document and preserve the TEI root.
    if doc_id is None:
        doc_id = path
    doc = Document(id=doc_id)
    doc.meta["source_filename"] = os.path.basename(path)
    doc.meta["_teitok_tei_root"] = tei
    return doc

