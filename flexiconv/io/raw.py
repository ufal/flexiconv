"""Raw pivot Document dumper.

Writes a human-readable text dump of:
- document id, meta, attrs
- layers, nodes (anchors + features), spans, and edges
"""
from __future__ import annotations

from typing import TextIO

from ..core.model import Document, Anchor, Node, Span, Edge, Layer  # type: ignore


def _write_anchor(f: TextIO, a: Anchor, indent: str = "") -> None:
    parts = [f"type={a.type}"]
    if a.char_start is not None or a.char_end is not None:
        parts.append(f"char=[{a.char_start},{a.char_end})")
    if a.token_start is not None or a.token_end is not None:
        parts.append(f"tok=[{a.token_start},{a.token_end}]")
    if a.time_start is not None or a.time_end is not None:
        parts.append(f"time=[{a.time_start},{a.time_end}]")
    f.write(indent + "Anchor(" + ", ".join(parts) + ")\n")


def _write_node(f: TextIO, n: Node, indent: str = "") -> None:
    f.write(f"{indent}Node {n.id} (type={n.type})\n")
    for a in n.anchors:
        _write_anchor(f, a, indent + "  ")
    if n.features:
        f.write(indent + "  features:\n")
        for k, v in sorted(n.features.items()):
            f.write(indent + f"    {k}: {v!r}\n")
    if n.parent or n.children:
        f.write(indent + f"  parent: {n.parent!r}, children: {n.children!r}\n")


def _write_span(f: TextIO, s: Span, indent: str = "") -> None:
    f.write(f"{indent}Span {s.id} (label={s.label})\n")
    _write_anchor(f, s.anchor, indent + "  ")
    if s.attrs:
        f.write(indent + "  attrs:\n")
        for k, v in sorted(s.attrs.items()):
            f.write(indent + f"    {k}: {v!r}\n")


def _write_edge(f: TextIO, e: Edge, indent: str = "") -> None:
    f.write(
        f"{indent}Edge {e.id} (label={e.label}, source={e.source}, target={e.target})\n"
    )
    if e.attrs:
        f.write(indent + "  attrs:\n")
        for k, v in sorted(e.attrs.items()):
            f.write(indent + f"    {k}: {v!r}\n")


def save_raw(document: Document, path: str) -> None:
    """Save Document as a plain-text dump of its pivot structure."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"Document id: {document.id}\n")
        if document.meta:
            f.write("Meta:\n")
            for k, v in sorted(document.meta.items()):
                f.write(f"  {k}: {v!r}\n")
        if document.attrs:
            f.write("Attrs:\n")
            for k, v in sorted(document.attrs.items()):
                f.write(f"  {k}: {v!r}\n")

        if document.media:
            f.write("Media:\n")
            for mid, m in sorted(document.media.items()):
                f.write(f"  {mid}: uri={m.uri!r}, mime={m.mime_type!r}, duration={m.duration!r}\n")
                if m.attrs:
                    for k, v in sorted(m.attrs.items()):
                        f.write(f"    {k}: {v!r}\n")

        if document.timelines:
            f.write("Timelines:\n")
            for tid, t in sorted(document.timelines.items()):
                f.write(f"  {tid}: unit={t.unit!r}, media={t.media_id!r}\n")
                if t.attrs:
                    for k, v in sorted(t.attrs.items()):
                        f.write(f"    {k}: {v!r}\n")

        if document.layers:
            f.write("Layers:\n")
            for lname, layer in sorted(document.layers.items()):
                f.write(f"- Layer '{lname}':\n")
                if layer.nodes:
                    f.write("  Nodes:\n")
                    for nid, node in sorted(layer.nodes.items()):
                        _write_node(f, node, indent="    ")
                if layer.spans:
                    f.write("  Spans:\n")
                    for sid, span in sorted(layer.spans.items()):
                        _write_span(f, span, indent="    ")
                if layer.edges:
                    f.write("  Edges:\n")
                    for eid, edge in sorted(layer.edges.items()):
                        _write_edge(f, edge, indent="    ")

