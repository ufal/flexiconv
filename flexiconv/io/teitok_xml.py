from __future__ import annotations

import copy
import os
import re
import shutil
from io import BytesIO
from datetime import datetime, timezone
from typing import Any, Optional

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

    # Pretty-print header only: serialize TEI without <text>, then append <text> without pretty_print.
    root_copy = copy.deepcopy(root)
    for child in list(root_copy):
        if (child.tag or "").endswith("text"):
            root_copy.remove(child)
    header_buf = BytesIO()
    etree.ElementTree(root_copy).write(
        header_buf, encoding="utf-8", xml_declaration=True, pretty_print=True
    )
    out = header_buf.getvalue().decode("utf-8")
    text_el = next((c for c in root if (c.tag or "").endswith("text")), None)
    if text_el is not None:
        if prettyprint:
            # Expand existing space tails between tokens into ' \n  ' for readability.
            for el in text_el.iter():
                local = (el.tag or "").split("}")[-1]
                if local == "tok" and el.tail == " ":
                    el.tail = " \n  "

            # Flush closing tags for block-level elements (div, p, s, l) where it has no
            # textual implications: put a newline before </blk> by adding it to the last
            # child's tail. This prevents very long lines but does not insert spaces
            # between tokens.
            block_tags = {"div", "p", "s", "l"}
            for blk in text_el.iter():
                local = (blk.tag or "").split("}")[-1]
                if local in block_tags and len(blk):
                    last_child = blk[-1]
                    tail = last_child.tail or ""
                    if "\n" not in tail:
                        last_child.tail = tail + "\n  "

            # Ensure </text> itself is on its own line by adding a newline to the tail
            # of the last child of <text>, if not already present.
            if len(text_el):
                last = text_el[-1]
                tail = last.tail or ""
                if "\n" not in tail:
                    last.tail = tail + "\n"

        # Serialize a copy so no parent context (e.g. "</TEI>") is included.
        text_copy = copy.deepcopy(text_el)
        text_str = etree.tostring(text_copy, encoding="unicode", pretty_print=False)
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

    # Extract some header metadata into doc.meta (very lightly for now).
    headers = _xpath_local(root, "teiHeader")
    if headers:
        titles = headers[0].xpath(".//*[local-name()='titleStmt']/*[local-name()='title']")
        if titles and (titles[0].text or "").strip():
            doc.meta["title"] = (titles[0].text or "").strip()

    tokens_layer = doc.get_or_create_layer("tokens")
    sentences_layer = doc.get_or_create_layer("sentences")

    # Collect tokens in document order (under text, or anywhere)
    token_elems = _xpath_local(root, "tok")
    token_index_by_xmlid: dict[str, int] = {}
    for idx, t in enumerate(token_elems, start=1):
        xmlid = t.get("id") or t.get("{http://www.w3.org/XML/1998/namespace}id") or f"w-{idx}"
        token_index_by_xmlid[xmlid] = idx

        form = (t.text or "").strip()
        features = {
            "form": form,
        }
        for attr in ("lemma", "upos", "xpos", "feats", "head", "deprel", "deps", "reg", "expan", "corr", "trslit", "lex", "nform", "ort", "gram", "opos", "olemma"):
            val = t.get(attr)
            if val is not None:
                features[attr] = val
        # Derive space_after from tok.tail: any space character in the tail means a
        # space follows this token; otherwise there is no space. We record this as a
        # boolean so downstream formats (e.g. CoNLL-U MISC SpaceAfter=No) can use it.
        has_space_after = bool(t.tail and " " in t.tail)
        features[SPACE_AFTER_FEATURE] = has_space_after

        anchor = Anchor(type=AnchorType.TOKEN, token_start=idx, token_end=idx)
        node = Node(id=xmlid, type="token", anchors=[anchor], features=features)
        tokens_layer.nodes[node.id] = node

    # Sentences: map <s> elements to token ranges (child <tok> or sameAs="#w-1 #w-2 ...")
    sent_elems = _xpath_local(root, "s")
    for s_idx, s in enumerate(sent_elems, start=1):
        sid = s.get("id") or s.get("{http://www.w3.org/XML/1998/namespace}id") or f"s-{s_idx}"
        toks_in_s = s.xpath(".//*[local-name()='tok']")
        id_sequence: list[str] = []
        if not toks_in_s:
            # TEITOK often uses sameAs on <s> to reference token IDs (s and tok are siblings)
            same_as = s.get("sameAs") or ""
            ids_from_same_as = [ref.lstrip("#").strip() for ref in same_as.split() if ref.strip()]
            indices = [token_index_by_xmlid[tid] for tid in ids_from_same_as if tid in token_index_by_xmlid]
            if not indices:
                continue
            start = min(indices)
            end = max(indices)
            # Preserve actual spacing from token features instead of forcing spaces between all forms.
            id_sequence = [tid for tid in ids_from_same_as if tid in tokens_layer.nodes]
        else:
            indices = []
            for t in toks_in_s:
                tid = t.get("id") or t.get("{http://www.w3.org/XML/1998/namespace}id")
                if not tid:
                    continue
                idx = token_index_by_xmlid.get(tid)
                if idx is not None:
                    indices.append(idx)
                    id_sequence.append(tid)
            if not indices:
                continue
            start = min(indices)
            end = max(indices)
        # Reconstruct sentence text from token layer using space_after feature,
        # so we respect TEITOK's no-space-before-punctuation behaviour.
        sent_text_parts: list[str] = []
        for tid in id_sequence:
            tok_node = tokens_layer.nodes.get(tid)
            if not tok_node:
                continue
            form = str(tok_node.features.get("form", ""))
            if not form:
                continue
            sent_text_parts.append(form)
            if tok_node.features.get(SPACE_AFTER_FEATURE):
                sent_text_parts.append(" ")
        sent_text = "".join(sent_text_parts).rstrip()
        anchor = Anchor(type=AnchorType.TOKEN, token_start=start, token_end=end)
        features = {
            "sent_id": sid,
            "text": sent_text,
        }
        node = Node(id=sid, type="sentence", anchors=[anchor], features=features)
        sentences_layer.nodes[node.id] = node

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


def _find_teitok_project_root(path: str) -> Optional[str]:
    """If path or a parent directory contains Resources/settings.xml, return that directory."""
    dirpath = os.path.dirname(os.path.abspath(path))
    while dirpath and dirpath != os.path.dirname(dirpath):
        if os.path.isfile(os.path.join(dirpath, "Resources", "settings.xml")):
            return dirpath
        dirpath = os.path.dirname(dirpath)
    return None


def save_teitok(
    document: Document,
    path: str,
    *,
    source_path: Optional[str] = None,
    copy_original_to_originals: bool = False,
    teitok_project_root: Optional[str] = None,
    prettyprint: bool = False,
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

    # If this document came from DOCX (or other source that produced a full TEI tree),
    # write that TEI verbatim (so DOCX→TEI output stays identical to the original converter).
    stored_tei = document.meta.get("_teitok_tei_root")
    if stored_tei is not None:
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

    def _add_tokens_to_p(p_el: etree._Element, tok_list: list[Node], sent_layer: Optional[Any]) -> None:
        """Append <s><tok>...</tok></s> to p_el for the given token list."""
        if not tok_list:
            return
        if sent_layer:
            s_nodes = sorted(
                sent_layer.nodes.values(),
                key=lambda n: (n.anchors[0].token_start or 0),
            )
            for s in s_nodes:
                start = s.anchors[0].token_start or 0
                end = s.anchors[0].token_end or 0
                in_this = [t for t in tok_list if (t.anchors[0].token_start or 0) >= start and (t.anchors[0].token_start or 0) <= end]
                if not in_this:
                    continue
                if len(p_el) > 0:
                    p_el[-1].tail = "\n    "
                s_el = etree.SubElement(p_el, "s", id=s.id)
                for tok in in_this:
                    t_attrs = {"id": tok.id}
                    for k, v in tok.features.items():
                        if k not in ("form", SPACE_AFTER_FEATURE, "spaceAfter"):
                            t_attrs[k] = str(v)
                    t_el = etree.SubElement(s_el, "tok", **t_attrs)
                    t_el.text = str(tok.features.get("form", ""))
                    t_el.tail = " " if (tok.features.get(SPACE_AFTER_FEATURE) or tok.features.get("spaceAfter")) else ""
        else:
            s_el = etree.SubElement(p_el, "s", id="s-1")
            for tok in tok_list:
                t_attrs = {"id": tok.id}
                for k, v in tok.features.items():
                    if k not in ("form", SPACE_AFTER_FEATURE, "spaceAfter"):
                        t_attrs[k] = str(v)
                t_el = etree.SubElement(s_el, "tok", **t_attrs)
                t_el.text = str(tok.features.get("form", ""))
                t_el.tail = " " if (tok.features.get(SPACE_AFTER_FEATURE) or tok.features.get("spaceAfter")) else ""

    if has_structure:
        # Structure nodes in document order; use node.type for TEI element (head, list/item, quote, p).
        struct_nodes = sorted(
            structure_layer.nodes.values(),
            key=lambda n: (
                n.anchors[0].char_start if n.anchors and n.anchors[0].char_start is not None else 0,
                n.id,
            ),
        )
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
                text = (node.features.get("text") or "").strip()
                if text and block_el.tag == "p" and node.anchors and node.anchors[0].char_start is not None and node.anchors[0].char_end is not None:
                    _set_paragraph_content(
                        block_el, text,
                        node.anchors[0].char_start, node.anchors[0].char_end,
                        rendition_layer,
                    )
                elif text:
                    block_el.text = text

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
                item_el = etree.SubElement(list_el, "item")
                _set_block_content(item_el, node)
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
        # No structure: single <p> with all tokens
        p_el = etree.SubElement(body_el, "p")
        _add_tokens_to_p(p_el, tokens, sentences_layer)

    # When we had structure but tokens don't have char anchors, we only emitted <p> with text.
    # If we had tokens and no char mapping, we need one <p> with all tokens.
    if has_tokens and has_structure:
        tokens_placed = {
            el.get("id") for el in body_el.iter()
            if (el.tag or "").endswith("tok") or el.tag == "tok"
        }
        if tokens and tokens_placed != {t.id for t in tokens}:
            p_el = etree.SubElement(body_el, "p")
            _add_tokens_to_p(p_el, tokens, sentences_layer)

    tree = etree.ElementTree(tei)
    _write_teitok_xml(effective_path, tree, prettyprint=prettyprint)

