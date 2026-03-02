from __future__ import annotations

"""
RTF to TEITOK-style TEI loader.

This is a standalone, minimal RTF reader that:
- parses basic inline styling: bold, italic, underline, font size
- detects paragraphs, simple bullet lists, and simple tables
- builds a TEITOK-style TEI tree similar to the DOCX loader

Limitations:
- Only a tiny subset of RTF is understood (enough for typical word-processor output)
- Hyperlinks and footnotes are not interpreted yet; they appear as plain text
"""

import os
import re
from datetime import date
from typing import Optional, Any

from lxml import etree

from ..core.model import Document


def _is_legal_xml_char(ch: str) -> bool:
    """Return True if character is allowed in XML 1.0."""
    codepoint = ord(ch)
    return (
        codepoint == 0x9
        or codepoint == 0xA
        or codepoint == 0xD
        or 0x20 <= codepoint <= 0xD7FF
        or 0xE000 <= codepoint <= 0xFFFD
        or 0x10000 <= codepoint <= 0x10FFFF
    )


def _sanitize_xml_text(s: str) -> str:
    """Strip characters that are not allowed in XML 1.0."""
    return "".join(ch for ch in s if _is_legal_xml_char(ch))


class _RTFParser:
    """Very small RTF parser geared towards word-processor output.

    It walks the RTF content once and builds a TEI <body> consisting of:
    - <head> for the main title (large bold first paragraph)
    - <p> for regular paragraphs
    - <list><item> for bulleted items (based on bullet characters)
    - <table><row><cell><p>...</p></cell></row> for simple tables using \trowd / \cell / \row
    Inline styling is encoded via <hi style="..."> elements.
    """

    def __init__(self, content: str, body: etree._Element):
        self.content = content
        self.body = body

        # Inline style flags (reflect current RTF state)
        self.bold = False
        self.italic = False
        self.underline = False
        self.font_size_pt: Optional[float] = None  # points, not half-points

        # Current text run (pending text with the *current* style)
        self._run_text: list[str] = []

        # Block / structure state
        self._current_block: Optional[etree._Element] = None
        self._current_list: Optional[etree._Element] = None
        self._current_table: Optional[etree._Element] = None
        self._current_row: Optional[etree._Element] = None
        self._current_cell: Optional[etree._Element] = None

        self._have_any_block = False  # any head/p/list/table content emitted yet
        self._block_is_list_item = False
        self._block_emitted_char = False  # saw any real character in current block

    # ----------------- helpers -----------------

    def _current_style_css(self) -> str:
        parts: list[str] = []
        if self.bold:
            parts.append("font-weight: bold;")
        if self.italic:
            parts.append("font-style: italic;")
        if self.underline:
            parts.append("text-decoration: underline;")
        if self.font_size_pt:
            parts.append(f"font-size: {self.font_size_pt:.1f}pt;")
        return " ".join(parts)

    def _flush_run(self) -> None:
        if self._current_block is None or not self._run_text:
            self._run_text = []
            return
        text = _sanitize_xml_text("".join(self._run_text))
        self._run_text = []
        if not text:
            return
        style = self._current_style_css()
        if style:
            hi = etree.SubElement(self._current_block, "hi")
            hi.set("style", style)
            hi.text = text
        else:
            # Append as mixed content on the block
            if self._current_block.text is None and len(self._current_block) == 0:
                self._current_block.text = text
            else:
                last = self._current_block[-1] if len(self._current_block) > 0 else None
                if last is None:
                    self._current_block.text = (self._current_block.text or "") + text
                else:
                    last.tail = (last.tail or "") + text

    def _end_block(self) -> None:
        """Finish the current logical block (paragraph or list item)."""
        self._flush_run()
        self._current_block = None
        self._block_is_list_item = False
        self._block_emitted_char = False

    def _ensure_block(self) -> None:
        """Ensure there is a current block element to receive text."""
        if self._current_block is not None:
            return

        # Decide element type
        in_table = self._current_row is not None

        if in_table:
            # Table cell: ensure <cell><p>...</p>
            if self._current_table is None:
                self._current_table = etree.SubElement(self.body, "table")
            if self._current_row is None:
                self._current_row = etree.SubElement(self._current_table, "row")
            if self._current_cell is None:
                self._current_cell = etree.SubElement(self._current_row, "cell")
            p = etree.SubElement(self._current_cell, "p")
            self._current_block = p
            return

        # Outside table
        if self._block_is_list_item:
            if self._current_list is None:
                self._current_list = etree.SubElement(self.body, "list")
            item = etree.SubElement(self._current_list, "item")
            self._current_block = item
        else:
            # Non-list paragraph or head
            # Heuristic: first block with clearly larger font becomes <head>
            is_head = (
                not self._have_any_block
                and self.font_size_pt is not None
                and self.font_size_pt >= 16.0
            )
            tag = "head" if is_head else "p"
            self._current_block = etree.SubElement(self.body, tag)
            self._have_any_block = True

    def _start_new_row(self) -> None:
        self._end_block()
        if self._current_table is None:
            self._current_table = etree.SubElement(self.body, "table")
        self._current_row = etree.SubElement(self._current_table, "row")
        self._current_cell = None

    def _end_cell(self) -> None:
        self._end_block()
        self._current_cell = None

    def _end_row(self) -> None:
        self._end_block()
        self._current_row = None
        self._current_cell = None

    # ----------------- parsing -----------------

    def parse(self) -> None:
        s = self.content
        i = 0
        n = len(s)

        while i < n:
            c = s[i]

            if c == "{":
                # Start group: push style by value (ignored; RTF groups rarely
                # affect high-level layout for our purposes).
                i += 1

            elif c == "}":
                # End group: nothing special here beyond whatever control words did.
                i += 1

            elif c == "\\":
                i = self._handle_control(s, i + 1)

            elif c in ("\n", "\r", "\t"):
                # Ignore raw whitespace control characters; logical breaks use \par.
                i += 1

            else:
                # Regular text character
                ch = c
                ch = _sanitize_xml_text(ch)
                if not ch:
                    i += 1
                    continue

                # Detect bullet at start of block: treat as list marker and skip output.
                if not self._block_emitted_char and ch == "•":
                    self._block_is_list_item = True
                    i += 1
                    continue

                self._ensure_block()
                self._block_emitted_char = True
                self._run_text.append(ch)
                i += 1

        # End of file
        self._end_block()

    def _handle_control(self, s: str, i: int) -> int:
        """Handle RTF control word or symbol starting at s[i]. Returns new index."""
        n = len(s)
        if i >= n:
            return i

        ch = s[i]

        # Escaped brace or backslash
        if ch in "{}\\":
            self._ensure_block()
            self._block_emitted_char = True
            self._run_text.append(ch)
            return i + 1

        # Hex char \'hh
        if ch == "'":
            if i + 2 < n:
                hexcode = s[i + 1 : i + 3]
                try:
                    code = int(hexcode, 16)
                    ch2 = chr(code)
                    ch2 = _sanitize_xml_text(ch2)
                    # Bullet detection at block start
                    if not self._block_emitted_char and ch2 == "•":
                        self._block_is_list_item = True
                        return i + 3
                    self._ensure_block()
                    self._block_emitted_char = True
                    self._run_text.append(ch2)
                except ValueError:
                    pass
                return i + 3
            return i + 1

        # Control word: alphabetic name + optional signed integer parameter
        j = i
        while j < n and s[j].isalpha():
            j += 1
        if j == i:
            # Unknown or symbolic control; skip one char
            return i + 1
        word = s[i:j]

        k = j
        sign = ""
        if k < n and s[k] in "+-":
            sign = s[k]
            k += 1
        while k < n and s[k].isdigit():
            k += 1
        param_str = sign + s[j:k] if k > j else ""

        # Optional space delimiter after control word
        if k < n and s[k] == " ":
            k += 1

        self._apply_control(word, param_str or None)
        return k

    def _apply_control(self, word: str, param: Optional[str]) -> None:
        """Update parser state based on a control word."""
        word = word.lower()

        if word == "b":  # bold
            self._flush_run()
            self.bold = param != "0"
        elif word == "i":  # italic
            self._flush_run()
            self.italic = param != "0"
        elif word == "ul":  # underline on
            self._flush_run()
            self.underline = param != "0"
        elif word in {"ulnone", "ul0"}:  # underline off
            self._flush_run()
            self.underline = False
        elif word == "fs":  # font size in half-points
            try:
                if param is not None:
                    self.font_size_pt = int(param) / 2.0
            except ValueError:
                pass
        elif word == "par":
            # Paragraph break outside tables; inside tables we mostly rely on \cell.
            if self._current_row is None:
                self._end_block()
        elif word == "tab":
            # Represent \tab as a regular space.
            self._ensure_block()
            self._block_emitted_char = True
            self._run_text.append(" ")
        elif word == "u" and param is not None:
            # Unicode character \uN
            try:
                n = int(param)
                if n < 0:
                    n += 0x110000
                if 0 <= n < 0x110000:
                    ch = chr(n)
                    ch = _sanitize_xml_text(ch)
                    if not self._block_emitted_char and ch == "•":
                        self._block_is_list_item = True
                        return
                    self._ensure_block()
                    self._block_emitted_char = True
                    self._run_text.append(ch)
            except ValueError:
                pass
        elif word == "trowd":
            # Start of a new table row
            self._start_new_row()
        elif word == "cell":
            # End of a cell inside a table
            self._end_cell()
        elif word == "row":
            # End of table row
            self._end_row()
        elif word == "pard":
            # Reset paragraph defaults; for now we treat it as block boundary.
            self._end_block()
        elif word in {"super", "nosupersub"}:
            # Ignore superscript/subscript for now (footnote markers remain inline as text).
            pass
        else:
            # Many control words (fonts, colors, metadata) are ignored.
            pass


def _rtf_to_tei_tree(path: str, *, orgfile: Optional[str] = None) -> etree._Element:
    """Convert an RTF file to a TEITOK-style TEI tree (no namespace)."""
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # Strip large header groups that do not carry document body text.
    for pattern in (
        r"\{\\fonttbl.*?\}",
        r"\{\\colortbl.*?\}",
        r"\{\\\*\\listtable.*?\}",
        r"\{\\\*\\listoverridetable.*?\}",
        r"\{\\stylesheet.*?\}",
    ):
        content = re.sub(pattern, "", content, flags=re.S)

    # Simplify Word-style hyperlink fields: keep only the displayed text (fldrslt),
    # drop the fldinst 'HYPERLINK \"...\"' instruction.
    content = re.sub(
        r"\{\\field\{\\\*\\fldinst\{[^}]*\}\{\\fldrslt",
        r"{\\fldrslt",
        content,
        flags=re.S,
    )

    basename = os.path.splitext(os.path.basename(path))[0]
    XML_NS = "http://www.w3.org/XML/1998/namespace"

    tei = etree.Element("TEI")
    tei_header = etree.SubElement(tei, "teiHeader")
    text_el = etree.SubElement(tei, "text")
    text_el.set(f"{{{XML_NS}}}space", "preserve")
    text_el.set("id", basename)
    body = etree.SubElement(text_el, "body")

    filedesc = etree.SubElement(tei_header, "fileDesc")
    notesstmt = etree.SubElement(filedesc, "notesStmt")
    note = etree.SubElement(notesstmt, "note")
    note.set("n", "orgfile")
    note.text = orgfile or path
    revisiondesc = etree.SubElement(tei_header, "revisionDesc")
    change = etree.SubElement(revisiondesc, "change")
    change.set("who", "flexiconv")
    change.set("when", str(date.today()))
    change.text = "Converted from RTF file " + path
    etree.SubElement(filedesc, "titleStmt")  # keep header shape close to DOCX/PDF
    etree.SubElement(tei_header, "profileDesc")

    parser = _RTFParser(content, body)
    parser.parse()

    # Drop an initial garbage paragraph that only contains punctuation (e.g. artifacts
    # from stripped header/list metadata).
    if len(body) and body[0].tag == "p":
        txt = "".join(body[0].itertext()).strip()
        if txt and all(ch in ";•" for ch in txt):
            body.remove(body[0])

    # Promote the first substantial paragraph with a large font size to <head>, then
    # unwrap any inline <hi> so the head text matches the DOCX loader.
    if len(body):
        first = body[0]
        if first.tag == "p":
            max_fs = 0.0
            for hi in first.findall(".//hi"):
                style = hi.get("style") or ""
                m = re.search(r"font-size:\s*([0-9.]+)pt", style)
                if m:
                    try:
                        fs = float(m.group(1))
                        if fs > max_fs:
                            max_fs = fs
                    except ValueError:
                        continue
            if max_fs >= 16.0:
                first.tag = "head"

        if first.tag == "head":
            head_text = "".join(first.itertext()).strip()
            if head_text:
                for child in list(first):
                    first.remove(child)
                first.attrib.clear()
                first.text = head_text

    # Remove literal field instructions like HYPERLINK "http://..." that may still
    # appear as plain text; keep only the displayed field result.
    hyperlink_re = re.compile(r'HYPERLINK\s+"[^"]+"')
    for el in tei.iter():
        if el.text:
            el.text = hyperlink_re.sub("", el.text)
        if el.tail:
            el.tail = hyperlink_re.sub("", el.tail)

    # Tidy spaces around <hi>: move trailing spaces from hi.text into hi.tail so that
    # pretty-printing can place spaces *between* inline elements instead of inside
    # them. Mirrors the behaviour used in the PDF loader.
    body_el = tei.find(".//body")
    if body_el is not None:
        for hi in body_el.findall(".//hi"):
            if hi.text and hi.text.endswith(" "):
                hi.text = hi.text.rstrip(" ")
                if hi.tail:
                    hi.tail = " " + hi.tail
                else:
                    hi.tail = " "

    return tei


def load_rtf(
    path: str,
    *,
    doc_id: Optional[str] = None,
    orgfile: Optional[str] = None,
) -> Document:
    """Load an RTF file into a pivot Document via a TEITOK-style TEI tree."""
    tei_root = _rtf_to_tei_tree(path, orgfile=orgfile or path)

    if doc_id is None:
        doc_id = path
    doc = Document(id=doc_id)
    doc.meta["source_filename"] = os.path.basename(path)
    doc.meta["_teitok_tei_root"] = tei_root
    # Also keep original RTF source around so it can be re-exported if needed.
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            doc.meta["rtf_source"] = f.read()
    except OSError:
        doc.meta["rtf_source"] = None
    return doc


def save_rtf(document: Document, path: str) -> None:
    """Export a Document back to RTF.

    Behaviour:
    - If Document.meta['rtf_source'] is available, write it back verbatim.
    - Otherwise, raise an error (round-tripping arbitrary TEI→RTF is out of scope).
    """
    source = document.meta.get("rtf_source")
    if isinstance(source, str):
        with open(path, "w", encoding="utf-8") as f:
            f.write(source)
        return

    raise ValueError(
        "Document has no 'rtf_source'; generic TEI→RTF conversion is not implemented."
    )

