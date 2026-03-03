from __future__ import annotations

"""
LaTeX (.tex) → TEITOK-style TEI loader (initial, simplified).

Current behaviour (intentionally conservative):
- Strips the preamble and processes only the document body between
  \\begin{document} ... \\end{document}.
- Recognises sectioning commands at the start of a line:
  \\section{...}, \\subsection{...}, \\subsubsection{...}
  and maps them to <head type="section|subsection|subsubsection">.
- Recognises itemize/enumerate environments and \\item, mapping them to
  <list><item>...</item></list>.
- Other non-empty lines are grouped into paragraphs <p>.

Inline markup (e.g. \\textbf, \\emph) and math are currently ignored; text is
treated as plain content. The resulting TEI tree is stored in
document.meta["_teitok_tei_root"] so save_teitok / save_html / save_docx can
reuse it verbatim. This is intended as a starting point; support for popular
linguistics packages and richer inline markup can be added later.
"""

import os
import re
from typing import Optional, List, Tuple

from lxml import etree

from ..core.model import Document
from .teitok_xml import _ensure_tei_header


SECTION_CMDS = {
    "section": "section",
    "subsection": "subsection",
    "subsubsection": "subsubsection",
}


def _extract_document_body(text: str) -> str:
    """Return the LaTeX content between \\begin{document} and \\end{document} if present."""
    begin = re.search(r"\\begin\{document\}", text)
    if begin:
        text = text[begin.end() :]
    end = re.search(r"\\end\{document\}", text)
    if end:
        text = text[: end.start()]
    return text


def _append_inline_from_latex(parent: etree._Element, latex_text: str) -> None:
    """
    Append inline content parsed from a LaTeX fragment into a TEI element.

    Uses pylatexenc's LatexWalker when available to handle braces and a few
    common style macros (\\textbf, \\emph, \\textit, \\underline, \\texttt).
    Falls back to plain text when pylatexenc is not installed.
    """
    latex_text = (latex_text or "").strip()
    if not latex_text:
        return

    try:
        from pylatexenc.latexwalker import LatexWalker, LatexCharsNode, LatexGroupNode, LatexMacroNode  # type: ignore
    except ImportError:
        # Best-effort fallback: plain text.
        parent.text = (parent.text or "") + latex_text
        return

    walker = LatexWalker(latex_text)
    nodes, _, _ = walker.get_latex_nodes()

    style_macros = {
        "textbf": "bold",
        "bfseries": "bold",
        "textit": "italic",
        "emph": "italic",
        "itshape": "italic",
        "underline": "underline",
        "texttt": "code",
        "ttfamily": "code",
    }

    def _add_text(target: etree._Element, text: str) -> None:
        if not text:
            return
        if target.text is None and len(target) == 0:
            target.text = text
        else:
            last = target[-1] if len(target) > 0 else None
            if last is None:
                target.text = (target.text or "") + text
            else:
                last.tail = (last.tail or "") + text

    def _append_hi(target: etree._Element, text: str, rend: str) -> None:
        if not text:
            return
        # Reuse last <hi rend=...> when possible.
        last = target[-1] if len(target) > 0 else None
        if last is not None and (last.tag or "").split("}")[-1] == "hi" and last.get("rend") == rend:
            last.text = (last.text or "") + text
            return
        hi = etree.SubElement(target, "hi", rend=rend)
        hi.text = text

    def _collect_text(nodelist) -> str:
        parts: List[str] = []
        for n in nodelist:
            if isinstance(n, LatexCharsNode):
                parts.append(n.chars)
            elif isinstance(n, LatexGroupNode):
                parts.append(_collect_text(n.nodelist or []))
        return "".join(parts)

    def _walk(nodelist, target: etree._Element, current_rend: Optional[str] = None) -> None:
        for n in nodelist:
            if isinstance(n, LatexCharsNode):
                txt = n.chars
                if current_rend:
                    _append_hi(target, txt, current_rend)
                else:
                    _add_text(target, txt)
            elif isinstance(n, LatexGroupNode):
                _walk(n.nodelist or [], target, current_rend)
            elif isinstance(n, LatexMacroNode):
                name = n.macroname or ""
                args = []
                if n.nodeargd and getattr(n.nodeargd, "argnlist", None):
                    args = [a for a in n.nodeargd.argnlist if a is not None]

                first_arg_nodes = None
                if args:
                    first = args[0]
                    if hasattr(first, "nodelist"):
                        first_arg_nodes = first.nodelist or []

                # Styling macros like \textbf{...}, \emph{...}
                if name in style_macros and first_arg_nodes is not None:
                    rend = style_macros[name]
                    _walk(first_arg_nodes, target, rend)
                # \multicolumn{cols}{align}{content} – we only care about the content.
                elif name == "multicolumn" and len(args) >= 3:
                    third = args[2]
                    if hasattr(third, "nodelist"):
                        content_nodes = third.nodelist or []
                        _walk(content_nodes, target, current_rend)
                else:
                    # Unknown macro: render its *first* argument contents as plain text.
                    if first_arg_nodes is not None:
                        txt = _collect_text(first_arg_nodes)
                        if current_rend:
                            _append_hi(target, txt, current_rend)
                        else:
                            _add_text(target, txt)
            else:
                # Fallback: keep raw LaTeX for unhandled node types, if available.
                s = getattr(n, "latex_verbatim", "")
                if callable(s):  # pylatexenc nodes expose latex_verbatim() as a method
                    s = s()
                s = str(s)
                if current_rend:
                    _append_hi(target, s, current_rend)
                else:
                    _add_text(target, s)

    _walk(nodes, parent, None)


def _build_tei_from_latex(path: str) -> etree._Element:
    """Parse a LaTeX file into a very simple TEI tree with <head>, <p>, and <list>/<item>."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()

    body_text = _extract_document_body(raw)
    lines = body_text.splitlines()

    tei = etree.Element("TEI")
    when_iso = "1970-01-01T00:00:00Z"  # dummy; _ensure_tei_header updates the revision/change text
    _ensure_tei_header(tei, source_filename=os.path.basename(path), when=when_iso)

    text_el = etree.SubElement(tei, "text")
    body_el = etree.SubElement(text_el, "body")

    in_list = False
    list_el: Optional[etree._Element] = None
    in_table = False
    table_el: Optional[etree._Element] = None
    para_lines: list[str] = []

    def flush_paragraph() -> None:
        nonlocal para_lines
        if not para_lines:
            return
        text = "\n".join(s for s in para_lines if s.strip())
        para_lines = []
        if not text:
            return
        p = etree.SubElement(body_el, "p")
        _append_inline_from_latex(p, text)

    env_stack: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("%"):
            # Blank line or comment: end current paragraph.
            flush_paragraph()
            continue

        # Layout-only commands we currently ignore.
        if stripped.startswith(("\\centering", "\\setlength", "\\renewcommand", "\\vspace", "\\hspace")):
            continue

        # Special-case tabular begin where column spec follows immediately.
        if stripped.startswith(r"\begin{tabular}"):
            env_stack.append("tabular")
            flush_paragraph()
            in_table = True
            table_el = etree.SubElement(body_el, "table")
            continue

        # Simple environment handling for itemize/enumerate and others.
        m_begin = re.match(r"\\begin\{([a-zA-Z*]+)\}", stripped)
        if m_begin:
            env = m_begin.group(1)
            env_stack.append(env)
            if env in {"itemize", "enumerate"}:
                flush_paragraph()
                in_list = True
                list_el = etree.SubElement(body_el, "list")
            continue

        m_end = re.match(r"\\end\{([a-zA-Z*]+)\}", stripped)
        if m_end:
            env = m_end.group(1)
            if env_stack and env_stack[-1] == env:
                env_stack.pop()
            if env in {"itemize", "enumerate"}:
                in_list = False
                list_el = None
            if env == "tabular":
                in_table = False
                table_el = None
            continue

        # Inside a tabular environment: build a simple TEI <table>.
        if in_table and table_el is not None:
            # Skip purely formatting lines (column specs, rules, colors).
            if stripped.startswith(">") or stripped.startswith(r"\hline") or stripped.startswith(r"\rowcolor"):
                continue
            row_line = stripped
            # Remove trailing row separator.
            if row_line.endswith(r"\\"):
                row_line = row_line[:-2].rstrip()
            # Simplify common multicolumn header syntax: \multicolumn{1}{c}{Content} -> Content
            row_line = re.sub(
                r"\\multicolumn\{[^}]*\}\{[^}]*\}\{([^}]*)\}",
                r"\1",
                row_line,
            )
            if not row_line:
                continue
            cells = [c.strip() for c in row_line.split("&")]
            row_el = etree.SubElement(table_el, "row")
            for c in cells:
                cell_el = etree.SubElement(row_el, "cell")
                _append_inline_from_latex(cell_el, c)
            continue

        # Sectioning commands at start of line.
        m_sec = re.match(r"\\(subsubsection|subsection|section)\{(.+)\}", stripped)
        if m_sec:
            cmd = m_sec.group(1)
            title = m_sec.group(2).strip()
            flush_paragraph()
            head = etree.SubElement(body_el, "head", type=SECTION_CMDS.get(cmd, cmd))
            _append_inline_from_latex(head, title)
            continue

        # Items inside itemize/enumerate.
        if stripped.startswith(r"\item"):
            content = stripped[5:].strip()
            if not in_list or list_el is None:
                # Implicit list if we see \item outside a known list.
                flush_paragraph()
                in_list = True
                list_el = etree.SubElement(body_el, "list")
            item_el = etree.SubElement(list_el, "item")
            _append_inline_from_latex(item_el, content)
            continue

        # Fallback: accumulate into a paragraph buffer.
        para_lines.append(stripped)

    flush_paragraph()
    return tei


def load_latex(path: str, *, doc_id: Optional[str] = None) -> Document:
    """Load a LaTeX (.tex) file into a pivot Document with a basic TEI tree."""
    tei_root = _build_tei_from_latex(path)
    if doc_id is None:
        doc_id = path
    doc = Document(id=doc_id)
    doc.meta["source_filename"] = os.path.basename(path)
    doc.meta["_teitok_tei_root"] = tei_root
    return doc

