from __future__ import annotations

"""
TMX (Translation Memory eXchange) → TEI/TEITOK converter.

Core behaviour (mode='join' by default):
- Parse a TMX file and turn each <tu> (translation unit) into an alignment id.
- For each language (from @xml:lang or @lang on <tuv>), create:
  - mode='join':
      <text>
        <div lang="en">
          <ab tuid="basename:tu-1">Hello</ab>
          <ab tuid="basename:tu-2">Bye</ab>
          ...
        </div>
        <div lang="fr">
          <ab tuid="basename:tu-1">Bonjour</ab>
          <ab tuid="basename:tu-2">Au revoir</ab>
          ...
        </div>
      </text>
  - mode='annotate':
      one <div lang="X"> per language; inside, each <ab> for language X carries
      @trans_OTHERLANG attributes with the other language strings in the same TU.

The TEI tree is stored in doc.meta["_teitok_tei_root"] so save_teitok can
write it verbatim.
"""

import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

from lxml import etree

from ..core.model import Document
from .teitok_xml import _ensure_tei_header


def _load_tmx_root(path: str) -> etree._Element:
    parser = etree.XMLParser(remove_blank_text=True)
    tree = etree.parse(path, parser)
    return tree.getroot()


def _build_tei_from_tmx(path: str, *, mode: str = "join", tu_element: str = "ab", tuid_attr: str = "tuid") -> etree._Element:
    root = _load_tmx_root(path)
    base = os.path.basename(path)
    stem, _ = os.path.splitext(base)

    # Collect segments per language as element lists.
    lang_parts: Dict[str, List[etree._Element]] = {}

    tunr = 1
    # Find all tu elements (any namespace).
    for tu in root.xpath(".//*[local-name()='tu']"):
        app_id = f"{stem}:tu-{tunr}"
        tunr += 1

        if mode == "annotate":
            # First gather all segments in this TU by language.
            seg_by_lang: Dict[str, str] = {}
            for tuv in tu.xpath(".//*[local-name()='tuv']"):
                lang = tuv.get("{http://www.w3.org/XML/1998/namespace}lang") or tuv.get("lang") or ""
                if not lang:
                    continue
                seg_el = None
                for cand in tuv:
                    if (cand.tag or "").split('}')[-1] == "seg":
                        seg_el = cand
                        break
                if seg_el is None:
                    continue
                seg_txt = "".join(seg_el.itertext()).strip()
                if not seg_txt:
                    continue
                seg_by_lang[lang] = seg_txt
            if not seg_by_lang:
                continue

            # For each language, create an <ab> with trans_OTHERLANG attributes.
            langs = sorted(seg_by_lang.keys())
            for lang in langs:
                text_here = seg_by_lang[lang]
                ab = etree.Element(tu_element)
                ab.set(tuid_attr, app_id)
                for other in langs:
                    if other == lang:
                        continue
                    ab.set(f"trans_{other}", seg_by_lang[other])
                ab.text = text_here
                lang_parts.setdefault(lang, []).append(ab)
        else:
            # Default mode ('join'): one <ab> per language per TU without trans_* attributes.
            for tuv in tu.xpath(".//*[local-name()='tuv']"):
                lang = tuv.get("{http://www.w3.org/XML/1998/namespace}lang") or tuv.get("lang") or ""
                if not lang:
                    continue
                seg_el = None
                for cand in tuv:
                    if (cand.tag or "").split('}')[-1] == "seg":
                        seg_el = cand
                        break
                if seg_el is None:
                    continue
                seg_txt = "".join(seg_el.itertext()).strip()
                if not seg_txt:
                    continue
                ab = etree.Element(tu_element)
                ab.set(tuid_attr, app_id)
                ab.text = seg_txt
                lang_parts.setdefault(lang, []).append(ab)

    tei = etree.Element("TEI")
    # Standard flexiconv header, plus a TMX-origin change entry.
    when_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _ensure_tei_header(tei, source_filename=base, when=when_iso)

    header = tei.find("teiHeader")
    if header is None:
        header = etree.SubElement(tei, "teiHeader")

    # Add a revisionDesc/change entry documenting TMX origin.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rev = header.find("revisionDesc")
    if rev is None:
        rev = etree.SubElement(header, "revisionDesc")
    change = etree.SubElement(rev, "change", who="flexiconv", when=today)
    change.text = f"Converted from TMX file {base}"

    text_el = etree.SubElement(tei, "text")

    # Emit one <div lang="..."> per language, preserving TU order as collected,
    # and flush each <div> and its children onto separate lines for readability.
    for lang in sorted(lang_parts.keys()):
        if len(text_el) == 0:
            text_el.text = "\n  "
        else:
            prev_div = text_el[-1]
            prev_div.tail = (prev_div.tail or "") + "\n  "
        div = etree.SubElement(text_el, "div")
        div.set("lang", lang)
        for ab in lang_parts[lang]:
            # Add a newline before each alignment block for readability.
            if len(div) == 0:
                div.text = "\n  "
            else:
                prev = div[-1]
                prev.tail = (prev.tail or "") + "\n  "
            div.append(ab)
        # Newline before </div>
        if len(div):
            last_ab = div[-1]
            last_ab.tail = (last_ab.tail or "") + "\n  "

    # Newline before </text>
    if len(text_el):
        last_div = text_el[-1]
        last_div.tail = (last_div.tail or "") + "\n"

    return tei


def load_tmx(path: str, *, doc_id: Optional[str] = None, mode: str = "join") -> Document:
    """
    Load a TMX file into a pivot Document, attaching a TEI tree in
    doc.meta['_teitok_tei_root'] (join/annotate modes).

    Parameters
    ----------
    mode:
        "join" (default): group segments per language in <div lang="..."><ab tuid=...>...</ab></div>.
        "annotate": same, but each <ab> also carries trans_OTHERLANG attributes.
    """
    tei_root = _build_tei_from_tmx(path, mode=mode)

    if doc_id is None:
        doc_id = path
    doc = Document(id=doc_id)
    doc.meta["source_filename"] = os.path.basename(path)
    doc.meta["_teitok_tei_root"] = tei_root
    return doc


def split_tmx_to_teitok_files(
    path: str,
    out_dir: str,
    *,
    tu_element: str = "ab",
    tuid_attr: str = "tuid",
) -> list[str]:
    """
    Convert a TMX file into one TEI file per language (split mode), roughly
    matching 'split' behaviour:

    basename-en.xml, basename-fr.xml, ...
    """
    root = _load_tmx_root(path)
    base = os.path.basename(path)
    stem, _ = os.path.splitext(base)

    lang_parts: Dict[str, List[etree._Element]] = {}
    tunr = 1

    for tu in root.xpath(".//*[local-name()='tu']"):
        app_id = f"{stem}:tu-{tunr}"
        tunr += 1
        for tuv in tu.xpath(".//*[local-name()='tuv']"):
            lang = (
                tuv.get("{http://www.w3.org/XML/1998/namespace}lang")
                or tuv.get("lang")
                or ""
            )
            if not lang:
                continue
            seg_el = None
            for cand in tuv:
                if (cand.tag or "").split("}")[-1] == "seg":
                    seg_el = cand
                    break
            if seg_el is None:
                continue
            seg_txt = "".join(seg_el.itertext()).strip()
            if not seg_txt:
                continue
            ab = etree.Element(tu_element)
            ab.set(tuid_attr, app_id)
            ab.text = seg_txt
            lang_parts.setdefault(lang, []).append(ab)

    written: list[str] = []
    when_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for lang, abs_ in lang_parts.items():
        tei = etree.Element("TEI")
        _ensure_tei_header(tei, source_filename=base, when=when_iso)
        header = tei.find("teiHeader")
        if header is None:
            header = etree.SubElement(tei, "teiHeader")
        rev = header.find("revisionDesc")
        if rev is None:
            rev = etree.SubElement(header, "revisionDesc")
        change = etree.SubElement(rev, "change", who="flexiconv", when=today)
        change.text = f"Converted from TMX file {base}"

        text_el = etree.SubElement(tei, "text")
        text_el.set("lang", lang)

        for ab in abs_:
            if len(text_el) == 0:
                text_el.text = "\n  "
            else:
                prev = text_el[-1]
                prev.tail = (prev.tail or "") + "\n  "
            text_el.append(ab)

        out_path = os.path.join(out_dir, f"{stem}-{lang}.xml")
        etree.ElementTree(tei).write(
            out_path,
            encoding="utf-8",
            xml_declaration=True,
            pretty_print=True,
        )
        written.append(out_path)

    return written

