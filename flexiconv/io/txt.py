"""
Plain-text (TXT) import/export with configurable line-break semantics.

Supports --linebreaks: sentence (each newline = sentence), paragraph (each newline =
paragraph), or double (only blank lines separate paragraphs).
"""
from __future__ import annotations

import re
from typing import Literal, Optional

from lxml import etree

from ..core.model import Anchor, AnchorType, Document, Node

LinebreaksMode = Literal["sentence", "paragraph", "double"]


def load_txt(
    path: str,
    *,
    doc_id: Optional[str] = None,
    linebreaks: LinebreaksMode = "paragraph",
) -> Document:
    """
    Load a plain-text file into a pivot Document.

    linebreaks:
      - "sentence": each non-empty line becomes one sentence and one structure node.
      - "paragraph": each non-empty line becomes one structure node (paragraph).
      - "double": only blank lines separate paragraphs; blocks separated by \\n\\n+
        become one structure node each (internal newlines preserved in text).
    """
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()

    if doc_id is None:
        doc_id = path
    doc = Document(id=doc_id)
    doc.meta["source_filename"] = path.split("/")[-1].split("\\")[-1]

    structure = doc.get_or_create_layer("structure")

    if linebreaks == "double":
        # Paragraphs = blocks separated by one or more blank lines
        blocks = re.split(r"\n\s*\n", text)
        para_idx = 0
        pos = 0
        for raw_block in blocks:
            block = raw_block.strip()
            if not block:
                pos += len(raw_block) + 2
                continue
            start = pos
            end = start + len(block)
            para_idx += 1
            anchor = Anchor(type=AnchorType.CHAR, char_start=start, char_end=end)
            node = Node(
                id=f"p{para_idx}",
                type="paragraph",
                anchors=[anchor],
                features={"text": block},
            )
            structure.nodes[node.id] = node
            pos = start + len(raw_block) + 2
        return doc

    # sentence / paragraph: each line is a unit
    raw_lines = text.splitlines(keepends=True)
    offset = 0
    para_idx = 0
    for raw_line in raw_lines:
        line = raw_line.rstrip("\n\r")
        if not line.strip():
            offset += len(raw_line)
            continue
        para_idx += 1
        start = offset
        end = offset + len(line)
        anchor = Anchor(type=AnchorType.CHAR, char_start=start, char_end=end)
        node = Node(
            id=f"p{para_idx}",
            type="paragraph",
            anchors=[anchor],
            features={"text": line},
        )
        structure.nodes[node.id] = node
        offset += len(raw_line)

    if linebreaks == "sentence":
        sentences_layer = doc.get_or_create_layer("sentences")
        for nid, node in list(structure.nodes.items()):
            s_anchor = Anchor(
                type=AnchorType.CHAR,
                char_start=node.anchors[0].char_start,
                char_end=node.anchors[0].char_end,
            )
            s_node = Node(
                id=nid.replace("p", "s", 1),
                type="sentence",
                anchors=[s_anchor],
                features={"text": node.features.get("text", "")},
            )
            sentences_layer.nodes[s_node.id] = s_node

    return doc


def _text_of_el(el: etree._Element) -> str:
    """Full inline text of an element, with TEI <lb/> rendered as newlines."""
    parts: list[str] = [el.text or ""]
    for child in el:
        tag = child.tag if isinstance(child.tag, str) else (child.tag or "")
        local = tag.split("}")[-1] if "}" in tag else tag
        if local == "lb":
            parts.append("\n")
        else:
            parts.append(_text_of_el(child))
        parts.append(child.tail or "")
    return "".join(parts)


def document_to_plain_text(
    document: Document,
    *,
    linebreaks: LinebreaksMode = "paragraph",
) -> str:
    """
    Extract plain text from a pivot Document (same logic as save_txt, but returns a string).

    Used for content-based fingerprinting so that RTF, DOCX, TEITOK XML, etc. can be
    compared by their converted text.
    """
    structure = document.layers.get("structure")
    sentences_layer = document.layers.get("sentences")
    lines: list[str] = []

    tei_root = document.meta.get("_teitok_tei_root")
    if tei_root is not None:
        body = tei_root.find(".//body")
        if body is None:
            body = tei_root.find("body")
        if body is not None:
            for p in body.findall("p") or body.xpath(".//p"):
                lines.append(_text_of_el(p).strip())
            lines = [s for s in lines if s]

    if not lines:
        if linebreaks == "sentence" and sentences_layer and sentences_layer.nodes:
            s_nodes = sorted(
                sentences_layer.nodes.values(),
                key=lambda n: (n.anchors[0].char_start if n.anchors and n.anchors[0].char_start is not None else 0, n.id),
            )
            lines = [str(n.features.get("text", "")) for n in s_nodes]
        elif structure and structure.nodes:
            s_nodes = sorted(
                structure.nodes.values(),
                key=lambda n: (n.anchors[0].char_start if n.anchors and n.anchors[0].char_start is not None else 0, n.id),
            )
            lines = [str(n.features.get("text", "")) for n in s_nodes]
        else:
            # Fallback: tokens or sentences as single block (e.g. TEI P5 loader has no structure / _teitok_tei_root)
            tokens_layer = document.layers.get("tokens")
            if tokens_layer and tokens_layer.nodes:
                toks = sorted(
                    tokens_layer.nodes.values(),
                    key=lambda n: (n.anchors[0].token_start if n.anchors and n.anchors[0].token_start is not None else 0, n.id),
                )
                one_line = " ".join(str(n.features.get("form", "")) for n in toks)
                if one_line.strip():
                    lines = [one_line]
            elif sentences_layer and sentences_layer.nodes:
                s_nodes = sorted(
                    sentences_layer.nodes.values(),
                    key=lambda n: (n.anchors[0].token_start if n.anchors and n.anchors[0].token_start is not None else 0, n.id),
                )
                one_line = " ".join(str(n.features.get("text", "")) for n in s_nodes)
                if one_line.strip():
                    lines = [one_line]

    if linebreaks == "double":
        return "\n\n".join(lines)
    return "\n".join(lines)


def normalize_text_for_fingerprint(text: str) -> str:
    """Collapse any run of whitespace to a single space and strip. For content hashing."""
    return re.sub(r"\s+", " ", text).strip()


def save_txt(
    document: Document,
    path: str,
    *,
    linebreaks: LinebreaksMode = "paragraph",
) -> None:
    """
    Export a pivot Document to plain text.

    linebreaks:
      - "sentence": one line per sentence (from sentences layer, or from structure).
      - "paragraph": one line per structure node.
      - "double": structure nodes joined by blank lines (each node's text can contain \\n).
    """
    content = document_to_plain_text(document, linebreaks=linebreaks)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
