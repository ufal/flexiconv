from __future__ import annotations

import hashlib
import os
import re
import shutil
from io import BytesIO
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from lxml import etree

# Empty TEI elements we serialize as self-closing (TEI convention).
_EMPTY_TEI_TAGS = ("pb", "lb")

# Token feature for spacing: space_after (bool). When True, TEITOK writer outputs a space after
# this token. Not written as an attribute on <tok>; used only to set tail. Enables scripts with
# no spaces (e.g. Chinese, historic) when loaders set space_after=False or omit it.
SPACE_AFTER_FEATURE = "space_after"

# Structure (and similar) feature: break_after (bool). When False, no newline after this element
# (e.g. historic paragraphs without line break). Default True for readable XML. Never add newline
# after <lb/> (truncated words across lines).
BREAK_AFTER_FEATURE = "break_after"

from ..core.model import Anchor, AnchorType, Document, Node, Span


NS_TEI = {"tei": "http://www.tei-c.org/ns/1.0"}

# TEITOK uses namespace-off by default so lxml/libxml don't need explicit namespace registration.
# XPath by local-name() accepts both namespaced and non-namespaced documents.
def _xpath_local(root: etree._Element, local_name: str) -> list:
    """Find all elements with the given local name (any namespace or none)."""
    return root.xpath(f".//*[local-name()='{local_name}']")


def _is_tei(root: etree._Element) -> bool:
    return root.tag.endswith("TEI")


# Space normalization for text fingerprint: collapse any run of whitespace to a single space, strip.
_WHITESPACE_NORM_RE = re.compile(r"\s+")


def teitok_text_fingerprint(
    path: str | os.PathLike,
    *,
    root: Optional[etree._Element] = None,
) -> str:
    """Return the space-normalized inner text of the <text> node in a TEITOK/XML document.

    Used for duplication detection: when two files have the same fingerprint, they are
    considered copies (same content). This is more reliable than comparing Originals
    references, since it compares the actual text body.

    Text is normalized so that spaces inside vs outside inline elements (e.g. <hi>)
    do not affect the fingerprint: we join all text chunks with a space, then
    collapse runs of whitespace to a single space. Thus "hello <hi>world</hi> again"
    and "hello<hi> world</hi>again" yield the same fingerprint.

    Arguments:
        path: Path to the TEITOK XML file (used when root is not provided).
        root: Optional already-parsed TEI root element. If given, path is not read.

    Returns:
        Normalized string: all whitespace collapsed to single spaces, trimmed.

    Raises:
        ValueError: If the document is not TEI or has no <text> element.
    """
    if root is None:
        tree = etree.parse(os.fspath(path))
        root = tree.getroot()
    if not _is_tei(root):
        raise ValueError("Not a TEI document")
    text_el = root.xpath(".//*[local-name()='text']")
    if not text_el:
        raise ValueError("TEI document has no <text> element")
    # Join text chunks with a space so that space inside vs outside elements (e.g. <hi>)
    # does not change the fingerprint; then collapse runs of whitespace.
    inner_text = " ".join(text_el[0].itertext())
    return _WHITESPACE_NORM_RE.sub(" ", inner_text).strip()


def find_duplicate_teitok_files(
    paths: Iterable[str | os.PathLike],
) -> list[list[str]]:
    """Group TEITOK XML paths by (space-normalized) <text> content; return duplicate groups.

    Two files are considered duplicates when the inner text of their <text> element
    is the same after normalizing whitespace (collapse runs to single space, strip).
    This is intended to replace Originals-based duplication detection.

    Arguments:
        paths: Iterable of paths to TEITOK XML files.

    Returns:
        List of groups; each group is a list of paths that share the same text content.
        Only groups with at least two files are returned. Order within each group
        is arbitrary; groups are in no particular order.
    """
    fingerprint_to_paths: dict[str, list[str]] = {}
    for p in paths:
        path_str = os.fspath(p)
        try:
            fp = teitok_text_fingerprint(path_str)
        except (ValueError, OSError, etree.XMLSyntaxError):
            continue
        fingerprint_to_paths.setdefault(fp, []).append(path_str)
    return [g for g in fingerprint_to_paths.values() if len(g) > 1]


def teitok_text_fingerprint_hash(path: str | os.PathLike) -> Optional[str]:
    """Return SHA-256 hex digest of the space-normalized <text> content, or None if unreadable.

    Used by easycorp and other tools to build a duplicate index without relying on Originals.
    """
    try:
        fp = teitok_text_fingerprint(path)
        return hashlib.sha256(fp.encode("utf-8")).hexdigest()
    except (ValueError, OSError, etree.XMLSyntaxError):
        return None


def _write_teitok_xml(path: str, tree: etree._ElementTree, *, prettyprint: bool = False) -> None:
    """Write TEITOK TEI to path.

    - teiHeader is always pretty-printed (for readability).
    - <text> is serialized compactly; spacing is controlled via element tails (tok.tail, etc.)
      that must already be set by loaders/constructors.
    - When prettyprint=True, we expand *existing* token tails (single spaces) into
      ' \\n  ' (space + newline + indent) so each token appears on its own line where
      there was already a word boundary, without changing the logical text.
    """
    root = tree.getroot()

    # Pretty-print header only: temporarily detach <text> (no deepcopy — that is
    # prohibitively expensive for large tokenized TEI trees).
    text_els = [c for c in list(root) if (c.tag or "").endswith("text")]
    for text_el in text_els:
        root.remove(text_el)
    try:
        header_buf = BytesIO()
        etree.ElementTree(root).write(
            header_buf, encoding="utf-8", xml_declaration=True, pretty_print=True
        )
        out = header_buf.getvalue().decode("utf-8")
    finally:
        for text_el in text_els:
            root.append(text_el)

    text_el = text_els[0] if text_els else None
    if text_el is not None:
        if prettyprint:
            # Expand existing space tails between tokens into ' \n  ' for readability.
            for el in text_el.iter():
                local = (el.tag or "").split("}")[-1]
                if local == "tok" and el.tail == " ":
                    el.tail = " \n  "

            # Flush closing tags for some block-level elements (div, s, l) where it has
            # no textual implications: put a newline before </blk> by adding it to the
            # last child's tail. We intentionally *exclude* <p> here so that closing
            # </p> tags stay on the same line as their content.
            block_tags = {"div", "s", "l"}
            for blk in text_el.iter():
                local = (blk.tag or "").split("}")[-1]
                if local in block_tags and len(blk):
                    last_child = blk[-1]
                    tail = last_child.tail or ""
                    if "\n" not in tail:
                        last_child.tail = tail + "\n  "

            # Put each top-level block under <body> on its own line by adding a
            # newline to the *previous* sibling's tail. This yields:
            #   </p>\n  <list>...
            # rather than breaking inside the paragraph content.
            body_el = next(
                (c for c in text_el if (c.tag or "").split("}")[-1] == "body"), None
            )
            if body_el is not None and len(body_el) > 1:
                for prev, cur in zip(body_el, list(body_el)[1:]):
                    # Only add a newline once; avoid duplicating if already present.
                    tail = prev.tail or ""
                    if "\n" not in tail:
                        prev.tail = tail + "\n  "

            # Also pretty-print list items and table structure: rows and cells never
            # share words across them, so it is safe to break lines there.
            def _newline_between_children(parent_tag: str, child_tag: str) -> None:
                for parent in text_el.iter():
                    local_p = (parent.tag or "").split("}")[-1]
                    if local_p != parent_tag or len(parent) <= 1:
                        continue
                    children = list(parent)
                    for prev, cur in zip(children, children[1:]):
                        if (cur.tag or "").split("}")[-1] != child_tag:
                            continue
                        tail = prev.tail or ""
                        if "\n" not in tail:
                            prev.tail = tail + "\n  "

            _newline_between_children("list", "item")
            _newline_between_children("table", "row")
            _newline_between_children("row", "cell")

            # Ensure </text> itself is on its own line by adding a newline to the tail
            # of the last child of <text>, if not already present.
            if len(text_el):
                last = text_el[-1]
                tail = last.tail or ""
                if "\n" not in tail:
                    last.tail = tail + "\n"

        # tostring on the element itself does not include parent context.
        text_str = etree.tostring(text_el, encoding="unicode", pretty_print=False)
        last_close = out.rfind("</TEI>")
        out = out[:last_close] + "\n  " + text_str + "\n</TEI>"
    with open(path, "w", encoding="utf-8") as f:
        f.write(out)


def _ensure_tei_header(tei: etree._Element, source_filename: Optional[str], when: str) -> None:
    """Homogenized TEITOK header: titleStmt, notesStmt (source_file, orgfile), encodingDesc, revisionDesc.
    Used by loaders (TextGrid, SRT, EAF, CHAT, TMX, EXB, hOCR) that build a TEI tree from external formats.
    """
    header = tei.find("teiHeader")
    if header is None:
        header = etree.SubElement(tei, "teiHeader")
    filedesc = header.find("fileDesc")
    if filedesc is None:
        filedesc = etree.SubElement(header, "fileDesc")
    titlestmt = filedesc.find("titleStmt")
    if titlestmt is None:
        titlestmt = etree.SubElement(filedesc, "titleStmt")
    title_el = titlestmt.find("title")
    if title_el is None:
        title_el = etree.SubElement(titlestmt, "title")
    title_el.text = (f"Converted from {source_filename}" if source_filename else "Converted document").strip()
    notes = filedesc.find("notesStmt")
    if notes is None:
        notes = etree.SubElement(filedesc, "notesStmt")
    for n in notes:
        notes.remove(n)
    if source_filename:
        etree.SubElement(notes, "note", n="source_file").text = source_filename
        etree.SubElement(notes, "note", n="orgfile").text = f"Originals/{source_filename}"
    enc = header.find("encodingDesc")
    if enc is None:
        enc = etree.SubElement(header, "encodingDesc")
    app = enc.find("appInfo")
    if app is None:
        app = etree.SubElement(enc, "appInfo")
    app_el = app.find("application[@ident='flexiconv']")
    if app_el is None:
        app_el = etree.SubElement(app, "application", ident="flexiconv", version="1.0", when=when)
    app_el.text = f"Converted from {source_filename}" if source_filename else "Conversion"
    rev = header.find("revisionDesc")
    if rev is None:
        rev = etree.SubElement(header, "revisionDesc")
    change = rev.find("change[@who='flexiconv']")
    if change is None:
        change = etree.SubElement(rev, "change", who="flexiconv", when=when)
    change.set("when", when)
    change.text = f"Converted from {source_filename} by flexiconv" if source_filename else "Converted by flexiconv"


_XML_NAME_CACHE: dict[str, bool] = {}


def _xml_attr_name_ok(name: str) -> bool:
    """Whether `name` can be an (unprefixed) XML attribute name; lxml decides."""
    ok = _XML_NAME_CACHE.get(name)
    if ok is None:
        try:
            etree.Element("t").set(name, "")
            ok = ":" not in name
        except ValueError:
            ok = False
        _XML_NAME_CACHE[name] = ok
    return ok


def _xml_attr_name_safe(name: str) -> str:
    """`name` with every character an XML name cannot have replaced by `_`."""
    out = "".join(c if _xml_attr_name_ok("a" + c) else "_" for c in name)
    if not _xml_attr_name_ok(out):
        out = "_" + out
    return out


_SPACE_STOP = frozenset({"s", "p", "doc", "body", "text", "div", "u", "lb", "head", "item", "TEI"})


def _space_after(t: etree._Element) -> bool:
    """Whether a space follows token `t`: its tail, or, when `t` ends an inline element (e.g. a
    <mention>), that element's tail. Any space character in that text means a space."""
    el = t
    while True:
        if el.tail:
            return " " in el.tail
        if el.getnext() is not None:
            return False
        parent = el.getparent()
        if parent is None or not isinstance(parent.tag, str) or etree.QName(parent).localname in _SPACE_STOP:
            return False
        el = parent


# <tok> / <dtok> / <notok> attributes read as word features (MISC: misc_* and @misc)
_TEITOK_WORD_ATTRS = (
    "lemma", "upos", "xpos", "feats", "head", "deprel", "deps", "ord", "ohead", "reg", "expan", "corr",
    "trslit", "lex", "nform", "ort", "gram", "opos", "olemma",
)


def load_teitok(path: str, *, doc_id: Optional[str] = None) -> Document:
    """Load a TEITOK-style TEI XML file into a pivot Document.

    Works with namespace-off TEITOK (no TEI namespace) and with namespaced TEI;
    uses local-name() so lxml/libxml do not require explicit namespace registration.
    """
    tree = etree.parse(path)
    root = tree.getroot()
    if not _is_tei(root):
        raise ValueError("Not a TEI document")

    if doc_id is None:
        doc_id = root.get("xml:id") or root.get("{http://www.w3.org/XML/1998/namespace}id") or path
    doc = Document(id=doc_id)
    doc.meta["source_filename"] = os.path.basename(path)
    # Keep the original TEI/TEITOK tree so writers (TEITOK, HTML, DOCX, etc.) can reuse it verbatim when appropriate.
    doc.meta["_teitok_tei_root"] = root

    # Extract some header metadata into doc.meta (very lightly for now).
    headers = _xpath_local(root, "teiHeader")
    if headers:
        titles = headers[0].xpath(".//*[local-name()='titleStmt']/*[local-name()='title']")
        if titles and (titles[0].text or "").strip():
            doc.meta["title"] = (titles[0].text or "").strip()
        conllu_notes = {
            n.get("n")[len("conllu:"):]: (n.text or "")
            for n in headers[0].xpath(".//*[local-name()='note'][starts-with(@n, 'conllu:')]")
        }
        if conllu_notes:
            doc.meta["_conllu_file_attrs"] = conllu_notes

    tokens_layer = doc.get_or_create_layer("tokens")
    sentences_layer = doc.get_or_create_layer("sentences")

    # Words in document order: <tok>, or the <dtok>s of a <tok> (a multi-word token: mwt layer);
    # <notok> (an empty node: empty layer, anchored to the word it follows).
    def _xid(el: etree._Element) -> Optional[str]:
        return el.get("id") or el.get("{http://www.w3.org/XML/1998/namespace}id")

    def _word_features(el: etree._Element, form: str) -> dict[str, Any]:
        features: dict[str, Any] = {"form": form}
        for attr in _TEITOK_WORD_ATTRS:
            val = el.get(attr)
            if val is not None:
                features[attr] = val
        # MISC: one attribute per item (misc_KEY), plus @misc with items kept verbatim
        # (keys that are no XML name, e.g. `LMSeg:a-b`).
        for attr, val in el.attrib.items():
            if isinstance(attr, str) and attr.startswith("misc_"):
                features[attr] = val if val != "" else True  # misc_KEY="" is a bare item
        for part in (el.get("misc") or "").split("|"):
            if part and part != "_":
                k, eq, v = part.partition("=")
                features.setdefault(f"misc_{k}", v if eq else True)
        return features

    def _ancestor(el: etree._Element, name: str) -> Optional[etree._Element]:
        found = el.xpath(f"ancestor::*[local-name()='{name}'][1]")
        return found[0] if found else None

    token_index_by_xmlid: dict[str, int] = {}
    tok_range: dict[str, tuple[int, int]] = {}  # <tok> id -> its first and last word
    surface: dict[str, tuple[str, bool]] = {}  # <tok> id -> (text, space after)
    idx = 0
    last_word_s: Optional[etree._Element] = None
    pending_before: list[Node] = []
    n_empty = 0
    for t in root.xpath(".//*[local-name()='tok' or local-name()='notok']"):
        local = etree.QName(t).localname
        s_anc = _ancestor(t, "s")
        if local == "notok":
            # a UD empty node (decimal @ord or @deps); other <notok>s (e.g. PROIEL's) are no words of UD
            ord_ = t.get("ord") or ""
            if not (t.get("deps") or (ord_.count(".") == 1 and ord_.replace(".", "").isdigit())):
                continue
            n_empty += 1
            efeat = _word_features(t, t.get("form") or (t.text or "").strip())
            if not efeat["form"]:
                del efeat["form"]
            eid = _xid(t) or f"e-{n_empty}"
            enode = Node(id=eid, type="empty", anchors=[Anchor(type=AnchorType.TOKEN, token_start=idx, token_end=idx)],
                         features=efeat)
            doc.get_or_create_layer("empty").nodes[eid] = enode
            if idx == 0 or last_word_s is not s_anc:
                efeat["_before"] = True
                pending_before.append(enode)
            continue
        tid = _xid(t) or f"w-{idx + 1}"
        form = (t.text or "").strip()
        has_space_after = _space_after(t)
        dtoks = [d for d in t if isinstance(d.tag, str) and etree.QName(d).localname == "dtok"]
        first = idx + 1
        if dtoks:
            for k, d in enumerate(dtoks, start=1):
                idx += 1
                did = _xid(d) or f"{tid}-{k}"
                dfeat = _word_features(d, d.get("form") or "")
                dfeat[SPACE_AFTER_FEATURE] = True
                anchor = Anchor(type=AnchorType.TOKEN, token_start=idx, token_end=idx)
                tokens_layer.nodes[did] = Node(id=did, type="token", anchors=[anchor], features=dfeat)
                token_index_by_xmlid[did] = idx
            mfeat = _word_features(t, form)
            mfeat[SPACE_AFTER_FEATURE] = has_space_after
            doc.get_or_create_layer("mwt").nodes[tid] = Node(
                id=tid, type="mwt", anchors=[Anchor(type=AnchorType.TOKEN, token_start=first, token_end=idx)],
                features=mfeat,
            )
        else:
            idx += 1
            features = _word_features(t, form)
            features[SPACE_AFTER_FEATURE] = has_space_after
            anchor = Anchor(type=AnchorType.TOKEN, token_start=idx, token_end=idx)
            tokens_layer.nodes[tid] = Node(id=tid, type="token", anchors=[anchor], features=features)
        token_index_by_xmlid[tid] = first
        tok_range[tid] = (first, idx)
        surface[tid] = (form, has_space_after)
        for e in pending_before:
            e.anchors[0].token_start = e.anchors[0].token_end = first
        pending_before = []
        last_word_s = s_anc

    # Sentences: map <s> elements to token ranges (child <tok> or sameAs="#w-1 #w-2 ...");
    # <s> attributes become sentence features; a new <doc> / <p> sets _newdoc / _newpar.
    sent_elems = _xpath_local(root, "s")
    extra_s_attrs = False
    prev_doc: Optional[etree._Element] = None
    prev_p: Optional[etree._Element] = None
    has_doc = bool(_xpath_local(root, "doc"))
    for s_idx, s in enumerate(sent_elems, start=1):
        sid = _xid(s) or f"s-{s_idx}"
        toks_in_s = s.xpath(".//*[local-name()='tok']")
        if toks_in_s:
            id_sequence = [tid for tid in (_xid(t) for t in toks_in_s) if tid and tid in tok_range]
        else:
            # TEITOK often uses sameAs on <s> to reference token IDs (s and tok are siblings)
            same_as = s.get("sameAs") or ""
            id_sequence = [r.lstrip("#").strip() for r in same_as.split() if r.strip().lstrip("#") in tok_range]
        if not id_sequence:
            continue
        start = min(tok_range[tid][0] for tid in id_sequence)
        end = max(tok_range[tid][1] for tid in id_sequence)
        # Reconstruct sentence text from the <tok> texts and their spacing.
        sent_text_parts: list[str] = []
        for tid in id_sequence:
            form, space = surface[tid]
            if form:
                sent_text_parts.append(form)
                if space:
                    sent_text_parts.append(" ")
        features: dict[str, Any] = {}
        for attr, val in s.attrib.items():
            if not isinstance(attr, str) or attr in ("id", "sameAs") or attr.startswith("{"):
                continue
            features[attr] = val
            extra_s_attrs = True
        features.setdefault("sent_id", sid)
        features.setdefault("text", "".join(sent_text_parts).rstrip())
        doc_el = _ancestor(s, "doc")
        p_el = _ancestor(s, "p")
        if has_doc and doc_el is not None and doc_el is not prev_doc:
            features["_newdoc"] = doc_el.get("id") or ""
        if p_el is not None and p_el is not prev_p:
            par_id = p_el.get("org_id") or p_el.get("id") or ""
            # a file's one plain <p> is no paragraph mark; in a <doc>, every <p> is
            if par_id or prev_p is not None or has_doc:
                features["_newpar"] = par_id
        prev_doc, prev_p = doc_el, p_el
        anchor = Anchor(type=AnchorType.TOKEN, token_start=start, token_end=end)
        sentences_layer.nodes[sid] = Node(id=sid, type="sentence", anchors=[anchor], features=features)
    if extra_s_attrs:
        doc.meta["_sentence_features_as_attrs"] = True

    # Preserve full TEI tree so TEITOK-aware savers (teitok, hocr, doreco, etc.)
    # can reuse the original structure when needed.
    doc.meta["_teitok_tei_root"] = root
    doc.meta["source_filename"] = os.path.basename(path)

    return doc


def _paragraph_segments_with_hi(
    para_start: int,
    para_end: int,
    para_text: str,
    rendition_spans: list[Span],
) -> list[tuple[str, Optional[str]]]:
    """Split paragraph into segments (text, rend|None). rend is for <hi rend='...'>."""
    if not rendition_spans:
        return [(para_text, None)] if para_text else []
    # Spans overlapping this paragraph
    overlapping = [
        (s.anchor.char_start or 0, s.anchor.char_end or 0, s.attrs.get("rend", "bold"))
        for s in rendition_spans
        if s.anchor.char_start is not None and s.anchor.char_end is not None
        and (s.anchor.char_start < para_end and (s.anchor.char_end or 0) > para_start)
    ]
    if not overlapping:
        return [(para_text, None)] if para_text else []
    # Sort by start, then build (start, end, rend) covering para range
    overlapping.sort(key=lambda x: (x[0], x[1]))
    intervals: list[tuple[int, int, Optional[str]]] = []
    for s, e, rend in overlapping:
        s = max(s, para_start)
        e = min(e, para_end)
        if s >= e:
            continue
        if intervals and intervals[-1][1] == s and intervals[-1][2] == rend:
            intervals[-1] = (intervals[-1][0], e, rend)
        else:
            intervals.append((s, e, rend))
    # Fill gaps with None rend
    out: list[tuple[int, int, Optional[str]]] = []
    pos = para_start
    for s, e, rend in intervals:
        if pos < s:
            out.append((pos, s, None))
        out.append((s, e, rend))
        pos = e
    if pos < para_end:
        out.append((pos, para_end, None))
    # Convert to (text_slice, rend)
    return [
        (para_text[max(0, s - para_start) : e - para_start], rend)
        for s, e, rend in out
        if e > s
    ]


def _set_paragraph_content(
    p_el: etree._Element,
    para_text: str,
    para_start: int,
    para_end: int,
    rendition_layer: Any,
) -> None:
    """Set paragraph element content: text and <hi rend='...'> from rendition spans."""
    spans = list(rendition_layer.spans.values()) if rendition_layer and rendition_layer.spans else []
    segments = _paragraph_segments_with_hi(para_start, para_end, para_text, spans)
    if not segments:
        return
    last = None
    for seg_text, rend in segments:
        if not seg_text:
            continue
        if rend:
            hi = etree.SubElement(p_el, "hi", rend=rend)
            hi.text = seg_text
            last = hi
        else:
            if last is not None:
                last.tail = (last.tail or "") + seg_text
            else:
                p_el.text = (p_el.text or "") + seg_text


def _tidy_inline_spaces(root: etree._Element) -> None:
    """Move trailing spaces from inline <hi> text nodes into their tails.

    This normalises inline spacing so that pretty-printing can place spaces
    *between* elements instead of inside them, without changing the logical
    text. Applied just before writing TEITOK XML, so it affects all formats
    that provide a TEI tree (DOCX, PDF, RTF, etc.).
    """
    # Find the <text> element, then operate under it only.
    text_el = next((c for c in root if (c.tag or "").endswith("text")), None)
    if text_el is None:
        return
    for hi in text_el.findall(".//hi"):
        if hi.text and hi.text.endswith(" "):
            hi.text = hi.text.rstrip(" ")
            if hi.tail:
                hi.tail = " " + hi.tail
            else:
                hi.tail = " "


def _strip_style_attributes(root: etree._Element) -> None:
    """
    Remove presentational style attributes (style=\"...\") from the TEI tree,
    while keeping the structural/semantic elements (e.g. <hi>).
    """
    for el in root.iter():
        if "style" in el.attrib:
            del el.attrib["style"]


def _find_teitok_project_root(path: str) -> Optional[str]:
    """If path or a parent directory contains Resources/settings.xml, return that directory."""
    dirpath = os.path.dirname(os.path.abspath(path))
    while dirpath and dirpath != os.path.dirname(dirpath):
        if os.path.isfile(os.path.join(dirpath, "Resources", "settings.xml")):
            return dirpath
        dirpath = os.path.dirname(dirpath)
    return None


def _relocate_external_assets(document: Document, tei_root: etree._Element, effective_path: str) -> None:
    """
    Copy external assets (currently images) next to the TEI file in a Chrome-style
    sidecar folder, and rewrite <graphic url="..."> to point there.

    For example, saving to /path/doc.xml produces /path/doc_files/, and
    <graphic url="..."> becomes url="doc_files/filename.png".
    """
    src_dir = document.meta.get("_teitok_image_dir")
    if not src_dir or not os.path.isdir(src_dir):
        return

    base = os.path.splitext(os.path.basename(effective_path))[0] or "document"
    assets_dir_name = f"{base}_files"
    assets_dir = os.path.join(os.path.dirname(effective_path) or ".", assets_dir_name)
    os.makedirs(assets_dir, exist_ok=True)

    # Rewrite all <graphic url="..."> to point into assets_dir_name, and copy files.
    for g in tei_root.xpath(".//*[local-name()='graphic']"):
        url = g.get("url")
        if not url:
            continue
        filename = os.path.basename(url)
        if not filename:
            continue
        src_path = os.path.join(src_dir, filename)
        if not os.path.isfile(src_path):
            continue
        dst_path = os.path.join(assets_dir, filename)
        if not os.path.exists(dst_path):
            try:
                shutil.copy2(src_path, dst_path)
            except OSError:
                continue
        g.set("url", os.path.join(assets_dir_name, filename))

    # Best-effort cleanup for temporary image dirs we created ourselves.
    try:
        base_src = os.path.basename(os.path.normpath(src_dir))
        if base_src.startswith(
            ("flexiconv_docx_", "flexiconv_pdf_", "flexiconv_epub_", "flexiconv_pdf_pages_")
        ):
            shutil.rmtree(src_dir)
    except OSError:
        pass


def save_teitok(
    document: Document,
    path: str,
    *,
    source_path: Optional[str] = None,
    copy_original_to_originals: bool = False,
    teitok_project_root: Optional[str] = None,
    prettyprint: bool = False,
    strip_styles: bool = False,
    **kwargs: Any,
) -> None:
    """Write a pivot Document to TEITOK-style TEI.

    Optionally records the source document (filename only) in the header and adds
    a revision statement. When used inside a TEITOK project (Resources/settings.xml
    present), can write to xmlfiles/ and copy the original to Originals/.

    Keyword arguments:
        source_path: Path to the file this document was converted from (used for
            header note and for copying into Originals if requested).
        copy_original_to_originals: If True and source_path and teitok_project_root
            are set, copy the source file to teitok_project_root/Originals/{basename}.
        teitok_project_root: If set, write XML to project_root/xmlfiles/{basename(path)}.xml
            and optionally copy source to project_root/Originals/.
        strip_styles: If True, drop presentational style=\"...\" attributes from the
            TEI output (e.g. inline CSS such as text-align).
    """
    # TEITOK is namespace-off by default so lxml/libxml don't need explicit namespace registration.
    tei = etree.Element("TEI")

    # Only redirect to xmlfiles/ when teitok_project_root was explicitly set (e.g. --teitok-project).
    # When the user passes an explicit output path, write to that path.
    effective_path = path
    if teitok_project_root:
        xmlfiles_dir = os.path.join(teitok_project_root, "xmlfiles")
        basename = os.path.basename(path)
        if not basename.endswith(".xml"):
            basename = (os.path.splitext(basename)[0] or "document") + ".xml"
        effective_path = os.path.join(xmlfiles_dir, basename)
        os.makedirs(xmlfiles_dir, exist_ok=True)
        if copy_original_to_originals and source_path and os.path.isfile(source_path):
            originals_dir = os.path.join(teitok_project_root, "Originals")
            os.makedirs(originals_dir, exist_ok=True)
            orig_basename = os.path.basename(source_path)
            shutil.copy2(source_path, os.path.join(originals_dir, orig_basename))

    # If this document came from DOCX/PDF/EPUB/etc. with a full TEI tree already
    # built, write that TEI (after normalisation and asset relocation).
    stored_tei = document.meta.get("_teitok_tei_root")
    if stored_tei is not None:
        # Normalise inline spaces (e.g. move trailing spaces out of <hi> text).
        _tidy_inline_spaces(stored_tei)
        if strip_styles:
            _strip_style_attributes(stored_tei)
        _relocate_external_assets(document, stored_tei, effective_path)
        if document.meta.get("_teitok_image_dir"):
            from .xpdf import copy_facs_images

            copy_facs_images(document, stored_tei, effective_path)
        tree = etree.ElementTree(stored_tei)
        _write_teitok_xml(effective_path, tree, prettyprint=prettyprint)
        return

    source_filename = None
    if source_path:
        source_filename = os.path.basename(source_path)
    if not source_filename and document.meta.get("source_filename"):
        source_filename = document.meta["source_filename"]

    # Header: source document, conversion statement, and (for RTF) note that typesetting was not preserved
    when = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    header = etree.SubElement(tei, "teiHeader")
    filedesc = etree.SubElement(header, "fileDesc")
    title_stmt = etree.SubElement(filedesc, "titleStmt")
    title_el = etree.SubElement(title_stmt, "title")
    title_el.text = (document.meta.get("title") or (f"Converted from {source_filename}" if source_filename else "Converted document")).strip()
    notes = etree.SubElement(filedesc, "notesStmt")
    if source_filename:
        etree.SubElement(notes, "note", n="source_file").text = source_filename
        etree.SubElement(notes, "note", n="orgfile").text = f"Originals/{source_filename}"
    if document.meta.get("rtf_source") is not None or (source_path and source_path.lower().endswith(".rtf")):
        etree.SubElement(notes, "note", n="conversion").text = (
            "Converted from RTF by flexiconv; typesetting (bold, italic, fonts, etc.) was not preserved."
        )
    # CoNLL-U file / document comments (global.*, meta::*, generator, ...): <note n="conllu:KEY">
    file_attrs = document.meta.get("_conllu_file_attrs")
    if isinstance(file_attrs, dict):
        for k, v in file_attrs.items():
            etree.SubElement(notes, "note", n=f"conllu:{k}").text = str(v)
    enc = etree.SubElement(header, "encodingDesc")
    app = etree.SubElement(enc, "appInfo")
    app_el = etree.SubElement(app, "application", ident="flexiconv", version="1.0", when=when)
    # Optionally record detected input MIME type if available in document.meta.
    mime = document.meta.get("source_mime")
    if mime:
        app_el.set("mime", str(mime))
    app_el.text = f"Converted from {source_filename}" if source_filename else "Conversion"
    rev = etree.SubElement(header, "revisionDesc")
    etree.SubElement(rev, "change", who="flexiconv", when=when).text = (
        f"Converted from {source_filename} by flexiconv" if source_filename else "Converted by flexiconv"
    )
    chunk_revision = document.meta.get("_conllu_chunk_revision")
    if chunk_revision:
        etree.SubElement(rev, "change", who="flexiconv", when=when, n="chunk").text = str(
            chunk_revision
        )

    text_el = etree.SubElement(tei, "text")
    body_el = etree.SubElement(text_el, "body")

    tokens_layer = document.layers.get("tokens")
    sentences_layer = document.layers.get("sentences")
    structure_layer = document.layers.get("structure")
    rendition_layer = document.layers.get("rendition")

    has_tokens = tokens_layer and len(tokens_layer.nodes) > 0
    has_structure = structure_layer and len(structure_layer.nodes) > 0

    if not has_tokens and not has_structure:
        raise ValueError(
            "Document has neither 'tokens' nor 'structure' layer. "
            "TEITOK output needs tokenized input and/or a structure layer (e.g. from RTF)."
        )

    tokens: list[Node] = []
    if tokens_layer:
        tokens = sorted(
            tokens_layer.nodes.values(),
            key=lambda n: (n.anchors[0].token_start or 0),
        )

    omit_ord = document.meta.get("_omit_conllu_ord")
    sent_attrs = bool(document.meta.get("_sentence_features_as_attrs"))
    # Multi-word tokens (mwt layer) by their first word; empty nodes (empty layer) by the word they follow
    mwt_by_start: dict[int, Node] = {}
    if document.layers.get("mwt"):
        for m in document.layers["mwt"].nodes.values():
            mwt_by_start[m.anchors[0].token_start or 0] = m
    empty_after: dict[int, list[Node]] = {}
    empty_before: dict[int, list[Node]] = {}
    if document.layers.get("empty"):
        for e in document.layers["empty"].nodes.values():
            where = empty_before if e.features.get("_before") else empty_after
            where.setdefault(e.anchors[0].token_start or 0, []).append(e)
    for lst in list(empty_after.values()) + list(empty_before.values()):
        lst.sort(key=lambda e: [int(x) for x in str(e.features.get("ord", "0.0")).split(".") if x.isdigit()])

    def _node_attrs(node: Node, *, with_form: bool = False) -> dict[str, str]:
        """A token-like node's features as XML attributes (MISC items that are no XML name in @misc)."""
        attrs = {"id": node.id}
        raw_misc: list[str] = []
        for k, v in node.features.items():
            if k.startswith("_") or k in (SPACE_AFTER_FEATURE, "spaceAfter"):
                continue
            if k == "form" and not with_form:
                continue
            if omit_ord and k in ("ord", "ohead"):
                continue
            if k.startswith("misc_"):
                # MISC: misc_KEY="value", a bare item misc_KEY=""; kept verbatim in @misc when KEY
                # is no XML name (e.g. `LMSeg:a-b`) or the value is empty (`Gloss=`)
                item = k[len("misc_"):]
                if v is True and _xml_attr_name_ok(k):
                    attrs[k] = ""
                elif v is not True and str(v) != "" and _xml_attr_name_ok(k):
                    attrs[k] = str(v)
                else:
                    raw_misc.append(item if v is True else f"{item}={v}")
            elif _xml_attr_name_ok(k):
                attrs[k] = str(v)
            else:
                attrs[_xml_attr_name_safe(k)] = str(v)
        if raw_misc:
            prev = attrs.get("misc")
            attrs["misc"] = "|".join(([prev] if prev else []) + raw_misc)
        return attrs

    def _tail(node: Node) -> str:
        return " " if (node.features.get(SPACE_AFTER_FEATURE) or node.features.get("spaceAfter")) else ""

    def _emit_empties(s_el: etree._Element, nodes: list[Node]) -> None:
        """Empty nodes: <notok/>, a zero-width element between the words (form as attribute)."""
        for e in nodes:
            etree.SubElement(s_el, "notok", **_node_attrs(e, with_form=True))

    def _emit_sentence_tokens(s_el: etree._Element, words: list[Node]) -> None:
        i = 0
        while i < len(words):
            w = words[i]
            ts = w.anchors[0].token_start or 0
            _emit_empties(s_el, empty_before.get(ts, []))
            m = mwt_by_start.get(ts)
            if m is not None:
                last = m.anchors[0].token_end or ts
                parts = []
                while i < len(words) and (words[i].anchors[0].token_start or 0) <= last:
                    parts.append(words[i])
                    i += 1
                t_el = etree.SubElement(s_el, "tok", **_node_attrs(m))
                t_el.text = str(m.features.get("form", ""))
                for d in parts:
                    etree.SubElement(t_el, "dtok", **_node_attrs(d, with_form=True))
                t_el.tail = _tail(m)
                for d in parts:
                    _emit_empties(s_el, empty_after.get(d.anchors[0].token_start or 0, []))
                continue
            t_el = etree.SubElement(s_el, "tok", **_node_attrs(w))
            t_el.text = str(w.features.get("form", ""))
            t_el.tail = _tail(w)
            _emit_empties(s_el, empty_after.get(ts, []))
            i += 1

    def _sentence_el(parent: etree._Element, s: Node) -> etree._Element:
        attrs = {"id": s.id}
        if sent_attrs:
            for k, v in s.features.items():
                if k.startswith("_") or isinstance(v, (dict, list, tuple)) or v is None:
                    continue
                name = k if _xml_attr_name_ok(k) else _xml_attr_name_safe(k)
                if name != "id":
                    attrs[name] = str(v)
        return etree.SubElement(parent, "s", **attrs)

    def _add_tokens_to_p(
        p_el: etree._Element,
        tok_list: list[Node],
        sent_layer: Optional[Any],
        container: Optional[Any] = None,
    ) -> None:
        """Append <s><tok>...</tok></s> to p_el for the given token list.

        ``container(s_node, current_parent)``, when given, returns the element the sentence goes in
        (for CoNLL-U newdoc / newpar: <doc> and <p>)."""
        if not tok_list:
            return

        if sent_layer:
            s_nodes = sorted(
                sent_layer.nodes.values(),
                key=lambda n: (n.anchors[0].token_start or 0),
            )
            # Index tokens by 1-based token position for O(n) sentence packing
            # (avoids scanning the full token list once per sentence).
            max_idx = 0
            for t in tok_list:
                ts = t.anchors[0].token_start or 0
                if ts > max_idx:
                    max_idx = ts
            by_idx: list[Optional[Node]] = [None] * (max_idx + 1)
            for t in tok_list:
                ts = t.anchors[0].token_start or 0
                if ts >= 0:
                    by_idx[ts] = t

            parent = p_el
            for s in s_nodes:
                start = s.anchors[0].token_start or 0
                end = s.anchors[0].token_end or 0
                if start < 0:
                    start = 0
                if end > max_idx:
                    end = max_idx
                in_this = [by_idx[i] for i in range(start, end + 1) if by_idx[i] is not None]
                if not in_this:
                    continue
                if container is not None:
                    parent = container(s, parent)
                if len(parent) > 0:
                    parent[-1].tail = "\n    "
                s_el = _sentence_el(parent, s)
                _emit_sentence_tokens(s_el, in_this)
        else:
            s_el = etree.SubElement(p_el, "s", id="s-1")
            _emit_sentence_tokens(s_el, tok_list)

    def _conllu_container(body: etree._Element) -> Any:
        """newdoc → <doc id> (sentences directly in it until a newpar), newpar → <p org_id>
        (as conllu2teitok.pl), else the current parent."""
        state: dict[str, Any] = {"doc": None}

        def pick(s: Node, current: etree._Element) -> etree._Element:
            f = s.features
            if "_newdoc" in f:
                doc_el = etree.SubElement(body, "doc")
                if f["_newdoc"]:
                    doc_el.set("id", str(f["_newdoc"]))
                state["doc"] = doc_el
                if "_newpar" not in f:
                    return doc_el
            if "_newpar" in f:
                p = etree.SubElement(state["doc"] if state["doc"] is not None else body, "p")
                if f.get("_newpar"):
                    p.set("org_id", str(f["_newpar"]))
                return p
            return current

        return pick

    if has_structure:
        # Structure nodes in document order; use node.type for TEI element (head, list/item, quote, p).
        all_struct = sorted(
            structure_layer.nodes.values(),
            key=lambda n: (
                n.anchors[0].char_start if n.anchors and n.anchors[0].char_start is not None else 0,
                n.id,
            ),
        )
        # Only top-level blocks: skip li nodes that have an li parent (they are emitted inside that parent).
        struct_nodes = [
            n for n in all_struct
            if not (n.type and n.type.lower() == "li" and n.parent and structure_layer.nodes.get(n.parent) and structure_layer.nodes[n.parent].type and structure_layer.nodes[n.parent].type.lower() == "li")
        ]
        list_el: Optional[etree._Element] = None  # open <list> when we see consecutive <li>

        def _set_block_content(block_el: etree._Element, node: Node) -> None:
            """Set text or token content on a block element (p, head, item, quote)."""
            if has_tokens and node.anchors and node.anchors[0].char_start is not None and node.anchors[0].char_end is not None:
                para_start = node.anchors[0].char_start
                para_end = node.anchors[0].char_end
                in_para = [
                    t for t in tokens
                    if t.anchors and t.anchors[0].char_start is not None and t.anchors[0].char_end is not None
                    and t.anchors[0].char_start >= para_start and t.anchors[0].char_end <= para_end
                ]
                _add_tokens_to_p(block_el, in_para, sentences_layer)
            if len(block_el) == 0:
                segments = node.features.get("content_segments")
                if segments:
                    # Inline formatting from HTML/MD (bold, italic) -> <hi rend="...">
                    last_el = block_el
                    pending = ""
                    for part in segments:
                        t = part[0] if isinstance(part, (list, tuple)) else ""
                        r = part[1] if isinstance(part, (list, tuple)) and len(part) > 1 else None
                        if r:
                            if last_el is block_el:
                                block_el.text = (block_el.text or "") + pending
                            else:
                                last_el.tail = (last_el.tail or "") + pending
                            pending = ""
                            hi_el = etree.SubElement(block_el, "hi")
                            hi_el.set("rend", r)
                            hi_el.text = t or ""
                            last_el = hi_el
                        else:
                            pending += t or ""
                    if last_el is block_el:
                        block_el.text = (block_el.text or "") + pending
                    else:
                        last_el.tail = (last_el.tail or "") + pending
                else:
                    text = (node.features.get("text") or "").strip()
                    if text and block_el.tag == "p" and node.anchors and node.anchors[0].char_start is not None and node.anchors[0].char_end is not None:
                        _set_paragraph_content(
                            block_el, text,
                            node.anchors[0].char_start, node.anchors[0].char_end,
                            rendition_layer,
                        )
                    elif text:
                        block_el.text = text

        def _emit_item_with_nested(list_parent: etree._Element, li_node: Node) -> None:
            """Append one <item> to list_parent for li_node, and recurse for nested list items."""
            item_el = etree.SubElement(list_parent, "item")
            _set_block_content(item_el, li_node)
            child_li = [
                structure_layer.nodes[cid]
                for cid in (li_node.children or [])
                if cid in structure_layer.nodes and (structure_layer.nodes[cid].type or "").lower() == "li"
            ]
            if child_li:
                child_li.sort(
                    key=lambda n: (
                        n.anchors[0].char_start if n.anchors and n.anchors[0].char_start is not None else 0,
                        n.id,
                    ),
                )
                nested_list = etree.SubElement(item_el, "list")
                for child_node in child_li:
                    _emit_item_with_nested(nested_list, child_node)

        for i, node in enumerate(struct_nodes):
            if i > 0:
                prev_break = struct_nodes[i - 1].features.get(BREAK_AFTER_FEATURE, True)
                if prev_break is None:
                    prev_break = True
                body_el[-1].tail = "\n  " if prev_break else " "

            node_type = (node.type or "p").lower()

            if node_type == "li":
                if list_el is None:
                    list_el = etree.SubElement(body_el, "list")
                _emit_item_with_nested(list_el, node)
                continue

            # Non-list item: close any open list
            list_el = None

            if node_type in ("h1", "h2", "h3", "h4", "h5", "h6"):
                head_el = etree.SubElement(body_el, "head")
                head_el.set("type", node_type)
                _set_block_content(head_el, node)
            elif node_type == "blockquote":
                quote_el = etree.SubElement(body_el, "quote")
                _set_block_content(quote_el, node)
            else:
                # p, div, or unknown
                p_el = etree.SubElement(body_el, "p")
                _set_block_content(p_el, node)
    else:
        # No structure: one <p> with all tokens; CoNLL-U newdoc/newpar give <doc> and <p>
        markers = sentences_layer is not None and any(
            "_newdoc" in n.features or "_newpar" in n.features for n in sentences_layer.nodes.values()
        )
        if markers:
            first = min(sentences_layer.nodes.values(), key=lambda n: n.anchors[0].token_start or 0)
            p_el = body_el if ("_newdoc" in first.features or "_newpar" in first.features) else etree.SubElement(body_el, "p")
            _add_tokens_to_p(p_el, tokens, sentences_layer, container=_conllu_container(body_el))
        else:
            p_el = etree.SubElement(body_el, "p")
            _add_tokens_to_p(p_el, tokens, sentences_layer)

    # When we had structure but tokens don't have char anchors, we only emitted <p> with text.
    # If we had tokens and no char mapping, we need one <p> with all tokens.
    if has_tokens and has_structure:
        tokens_placed = {
            el.get("id") for el in body_el.iter()
            if (el.tag or "").endswith("tok") or el.tag == "tok"
        }
        if tokens and not {t.id for t in tokens} <= tokens_placed:
            p_el = etree.SubElement(body_el, "p")
            _add_tokens_to_p(p_el, tokens, sentences_layer)

    # span layers as inline elements (CorefUD mentions: <mention>, teitok_spans.py)
    if document.layers.get("mentions"):
        from .teitok_spans import wrap_spans

        _, left_out = wrap_spans(tei, document, "mentions", "mention")
        if left_out:
            document.meta["_mentions_left_out"] = left_out

    # Normalise inline spaces and relocate any external assets (images) before writing.
    _tidy_inline_spaces(tei)
    if strip_styles:
        _strip_style_attributes(tei)
    _relocate_external_assets(document, tei, effective_path)
    tree = etree.ElementTree(tei)
    _write_teitok_xml(effective_path, tree, prettyprint=prettyprint)

