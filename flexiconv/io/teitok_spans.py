"""Span layers as inline elements in TEITOK XML: each span wraps its tokens (`<mention eid=… etype=…>…</mention>`).

Spans are placed outer first, so a span inside another (a nested mention) lands inside its element. A span whose
tokens cannot be wrapped without taking in other tokens (it crosses an element: two sentences, or a span it
overlaps without nesting) is left out of the XML and counted; its tokens keep what they carry (CorefUD: `coref` on
the head).
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from lxml import etree


def _local(el) -> str:
    tag = el.tag if isinstance(el.tag, str) else ""
    return tag.rsplit("}", 1)[-1]


def _child_under(el: etree._Element, parent: etree._Element) -> Optional[etree._Element]:
    """el's ancestor-or-self that is a child of parent."""
    while el is not None and el.getparent() is not parent:
        el = el.getparent()
    return el


def wrap_spans(root: etree._Element, document, layer_name: str, element: str) -> Tuple[int, int]:
    """Wrap the spans of `layer_name` (nodes anchored on token indices) as `element`; returns (wrapped, left out)."""
    layer = document.layers.get(layer_name)
    tokens = document.layers.get("tokens")
    if layer is None or tokens is None or not layer.nodes:
        return 0, 0
    id_of: Dict[int, str] = {n.anchors[0].token_start: n.id for n in tokens.nodes.values() if n.anchors}
    tok_el: Dict[str, etree._Element] = {t.get("id"): t for t in root.iter() if _local(t) == "tok"}
    index_of: Dict[str, int] = {v: k for k, v in id_of.items()}
    spans = sorted((n for n in layer.nodes.values() if n.anchors),
                   key=lambda n: (n.anchors[0].token_start, -(n.anchors[0].token_end or n.anchors[0].token_start)))
    wrapped = skipped = 0
    for node in spans:
        a = node.anchors[0]
        first = tok_el.get(id_of.get(a.token_start, ""))
        last = tok_el.get(id_of.get(a.token_end or a.token_start, ""))
        if first is None or last is None:
            skipped += 1
            continue
        parent = first.getparent()
        while parent is not None and _child_under(last, parent) is None:
            parent = parent.getparent()
        if parent is None:
            skipped += 1
            continue
        lo, hi = _child_under(first, parent), _child_under(last, parent)
        children: List[etree._Element] = list(parent)
        i, j = children.index(lo), children.index(hi)
        run = children[i:j + 1]
        covered = [index_of.get(t.get("id")) for el in run for t in el.iter() if _local(t) == "tok"]
        if sorted(c for c in covered if c is not None) != list(range(a.token_start, (a.token_end or a.token_start) + 1)):
            skipped += 1   # would take in other tokens: crosses an element or another span
            continue
        wrap = etree.Element(element, {k: str(v) for k, v in node.features.items()}, id=node.id)
        parent.insert(i, wrap)
        for el in run:
            wrap.append(el)   # moves it, with its tail
        wrap.tail, run[-1].tail = run[-1].tail, None
        wrapped += 1
    return wrapped, skipped
