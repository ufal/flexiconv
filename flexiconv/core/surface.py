"""The surface tokens of a document: what the text shows.

The ``tokens`` layer holds syntactic words. A multi-word token (``mwt`` layer: CoNLL-U range lines,
TEITOK ``<tok>`` with ``<dtok>``s) is one surface token for several words: ``del`` for ``de`` + ``el``.
Writers that render text use these, writers that render annotation use the words.
"""

from __future__ import annotations

from typing import List

from .model import Document, Node


def surface_tokens(document: Document) -> List[Node]:
    """Tokens in order, each run of words under a multi-word token replaced by that token."""
    tokens_layer = document.layers.get("tokens")
    if not tokens_layer:
        return []
    words = sorted(tokens_layer.nodes.values(), key=lambda n: (n.anchors[0].token_start or 0) if n.anchors else 0)
    mwt_layer = document.layers.get("mwt")
    if not mwt_layer or not mwt_layer.nodes:
        return words
    by_start = {m.anchors[0].token_start or 0: m for m in mwt_layer.nodes.values() if m.anchors}
    out: List[Node] = []
    skip_to = 0
    for w in words:
        ts = (w.anchors[0].token_start or 0) if w.anchors else 0
        if ts <= skip_to:
            continue
        m = by_start.get(ts)
        if m is not None:
            out.append(m)
            skip_to = m.anchors[0].token_end or ts
        else:
            out.append(w)
    return out
