from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from lxml import etree

from ..core.model import Anchor, AnchorType, Document, Node, Span
from .teitok_xml import _ensure_tei_header, _set_paragraph_content


def _rtf_to_text_and_runs(rtf: str) -> Tuple[str, List[Tuple[int, int, str]]]:
    """Parse RTF and return (plain_text, runs) where runs are (start, end, rend) e.g. 'bold', 'italic'."""
    text: List[str] = []
    runs: List[Tuple[int, int, str]] = []
    bold = False
    italic = False
    run_start = 0
    i = 0
    depth = 0
    in_skip_group = False
    skip_depth = 0

    def flush_run() -> None:
        nonlocal run_start
        pos = len("".join(text))
        if run_start < pos and (bold or italic):
            rend_str = " ".join(sorted(r for r in ("bold", "italic") if (r == "bold" and bold) or (r == "italic" and italic)))
            if rend_str:
                runs.append((run_start, pos, rend_str))
        run_start = pos

    while i < len(rtf):
        c = rtf[i]
        if c == "\\":
            i += 1
            if i >= len(rtf):
                break
            if rtf[i] in "'\\{}":
                if rtf[i] == "'" and i + 2 < len(rtf):
                    try:
                        code = int(rtf[i + 1 : i + 3], 16)
                        text.append(chr(code))
                        i += 3
                        continue
                    except ValueError:
                        pass
                elif rtf[i] == "\\":
                    text.append("\\")
                    i += 1
                    continue
                i += 1
                continue
            match = re.match(r"([a-zA-Z]+)(-?\d*)\s*", rtf[i:])
            if match:
                word = match.group(1).lower()
                param = match.group(2)
                i += len(match.group(0))
                if word == "b":
                    flush_run()
                    bold = param != "0"
                    run_start = len("".join(text))
                elif word == "i":
                    flush_run()
                    italic = param != "0"
                    run_start = len("".join(text))
                elif word == "u" and param:
                    try:
                        n = int(param)
                        if n < 0:
                            n += 0x110000
                        if n < 0x110000:
                            text.append(chr(n))
                        if i < len(rtf) and rtf[i] not in (" ", "\n", "\r", "\\", "{", "}"):
                            i += 1
                        continue
                    except ValueError:
                        pass
                elif word in ("par", "line", "tab"):
                    text.append("\n")
            continue
        if c == "{":
            depth += 1
            # Skip {\fonttbl ...}, {\colortbl ...}, {\* ...} (destinations)
            if not in_skip_group and i + 2 < len(rtf) and rtf[i + 1] == "\\":
                j = i + 2
                if rtf[j] == "*":
                    in_skip_group = True
                    skip_depth = depth
                else:
                    match = re.match(r"([a-zA-Z]+)\s*", rtf[j:])
                    if match:
                        cw = match.group(1).lower()
                        if cw in ("fonttbl", "colortbl", "stylesheet", "info"):
                            in_skip_group = True
                            skip_depth = depth
            elif in_skip_group:
                skip_depth += 1
            i += 1
            continue
        if c == "}":
            if in_skip_group and depth - 1 < skip_depth:
                in_skip_group = False
            depth -= 1
            i += 1
            continue
        # Emit text when inside document body (depth >= 1, inside {\rtf1 ...}) and not in skipped group
        if depth >= 1 and not in_skip_group and c not in ("\n", "\r", "\t"):
            if c.isprintable() or c == " ":
                text.append(c)
        i += 1

    flush_run()
    plain = "".join(text)
    plain = re.sub(r"\r\n?", "\n", plain)
    return plain, runs


def _require_striprtf():
    try:
        from striprtf.striprtf import rtf_to_text  # type: ignore
    except ImportError as exc:  # pragma: no cover - simple dependency error path
        raise RuntimeError(
            "RTF support requires the 'striprtf' package. "
            "Install with: pip install 'flexiconv[rtf]'"
        ) from exc
    return rtf_to_text


def load_rtf(path: str, *, doc_id: Optional[str] = None) -> Document:
    """Load an RTF document into the pivot Document.

    Behaviour:
    - Preserve the raw RTF source in ``Document.meta['rtf_source']``.
    - Parse the RTF to a plain-text string plus simple inline formatting runs
      (bold / italic) via ``_rtf_to_text_and_runs``; fall back to ``striprtf``
      when that fails.
    - Create a ``structure`` layer with paragraph-like nodes anchored by
    - character offsets in the plain text.
    - Create a ``rendition`` layer with character-span highlights for bold /
      italic so downstream formats can reconstruct ``<hi>`` markup.
    - Build a TEITOK-style TEI tree with ``<p>`` and inline ``<hi>`` elements
      from the structure + rendition layers and store it in
      ``Document.meta['_teitok_tei_root']`` so ``save_teitok`` can write it
      verbatim (similar to the DOCX converter).

    No tokens or sentences are created; text/token segmentation is intentionally
    left to flexipipe or other NLP components.
    """
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        rtf_content = f.read()

    text, format_runs = _rtf_to_text_and_runs(rtf_content)
    if not text.strip():
        rtf_to_text = _require_striprtf()
        text = rtf_to_text(rtf_content)

    if doc_id is None:
        doc_id = path
    doc = Document(id=doc_id)
    doc.meta["rtf_source"] = rtf_content
    doc.meta["plain_text"] = text
    doc.meta["source_filename"] = os.path.basename(path)

    structure = doc.get_or_create_layer("structure")
    offset = 0
    para_idx = 0
    for raw_line in text.splitlines(keepends=True):
        line = raw_line.rstrip("\n\r")
        line_len = len(raw_line)
        if line.strip():
            para_idx += 1
            start = offset
            end = offset + len(line)
            anchor = Anchor(
                type=AnchorType.CHAR,
                char_start=start,
                char_end=end,
            )
            node = Node(
                id=f"p{para_idx}",
                type="paragraph",
                anchors=[anchor],
                features={"text": line},
            )
            structure.nodes[node.id] = node
        offset += line_len

    if format_runs:
        rendition = doc.get_or_create_layer("rendition")
        for idx, (start, end, rend) in enumerate(format_runs):
            if start >= end:
                continue
            span = Span(
                id=f"hi-{idx}",
                label="hi",
                anchor=Anchor(type=AnchorType.CHAR, char_start=start, char_end=end),
                attrs={"rend": rend},
            )
            rendition.spans[span.id] = span
    else:
        rendition = doc.layers.get("rendition")

    # Build a TEITOK-style TEI tree from structure + rendition so save_teitok
    # (and TEITOK itself) can reuse it directly, mirroring the DOCX workflow.
    tei = etree.Element("TEI")
    when_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    source_filename = os.path.basename(path)
    _ensure_tei_header(tei, source_filename=source_filename, when=when_iso)

    basename, _ = os.path.splitext(source_filename)
    text_el = etree.SubElement(tei, "text", id=basename)
    body_el = etree.SubElement(text_el, "body")

    structure_layer = doc.layers.get("structure")
    if structure_layer and structure_layer.nodes:
        struct_nodes = sorted(
            structure_layer.nodes.values(),
            key=lambda n: (
                n.anchors[0].char_start
                if n.anchors and n.anchors[0].char_start is not None
                else 0,
                n.id,
            ),
        )
        for node in struct_nodes:
            if (
                not node.anchors
                or node.anchors[0].char_start is None
                or node.anchors[0].char_end is None
            ):
                continue
            para_start = node.anchors[0].char_start
            para_end = node.anchors[0].char_end
            para_text = text[para_start:para_end]
            p_el = etree.SubElement(body_el, "p")
            _set_paragraph_content(
                p_el,
                para_text,
                para_start,
                para_end,
                rendition,
            )

    doc.meta["_teitok_tei_root"] = tei
    doc.meta["source_filename"] = source_filename

    return doc


def save_rtf(document: Document, path: str) -> None:
    """Export a Document back to RTF.

    Current behaviour:
    - If Document.meta['rtf_source'] is available, write it back verbatim.
    - Otherwise, fall back to a plain-text-only RTF if tokens are present.
    """
    source = document.meta.get("rtf_source")
    if isinstance(source, str):
        with open(path, "w", encoding="utf-8") as f:
            f.write(source)
        return

    sentences_layer = document.layers.get("sentences")
    tokens_layer = document.layers.get("tokens")
    if not tokens_layer:
        raise ValueError(
            "Document has no 'rtf_source' and no 'tokens' layer; cannot build RTF."
        )

    tokens = sorted(
        tokens_layer.nodes.values(),
        key=lambda n: (n.anchors[0].token_start or 0),
    )

    lines: list[str] = []
    if sentences_layer:
        s_nodes = sorted(
            sentences_layer.nodes.values(),
            key=lambda n: (n.anchors[0].token_start or 0),
        )
        for s in s_nodes:
            start = s.anchors[0].token_start or 0
            end = s.anchors[0].token_end or 0
            words = []
            for tok in tokens:
                ti = tok.anchors[0].token_start or 0
                if start <= ti <= end:
                    words.append(str(tok.features.get("form", "")))
            lines.append(" ".join(words))
    else:
        words = [str(tok.features.get("form", "")) for tok in tokens]
        lines.append(" ".join(words))

    body = "\\par\n".join(
        line.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
        for line in lines
    )
    rtf = "{\\rtf1\\ansi\n" + body + "\n}"

    with open(path, "w", encoding="utf-8") as f:
        f.write(rtf)

