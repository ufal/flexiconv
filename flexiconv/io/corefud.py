"""CorefUD coreference (MISC `Entity=`, CorefUD 1.x) read into the pivot document, as flexencoder reads it.

Mentions are brackets over tokens: `Entity=(e6353-person-2(e6352-person-1)` opens two mentions (the second also
closes), `Entity=e6353)` closes one. An opening names the entity and the mention's head as an offset within the
mention; the field order comes from `# global.Entity = eid-etype-head-other` (GUM names the id `GRP` and has no
head: the mention's first token then). A discontinuous mention's parts are `e5[1/2]`, `e5[2/2]`: one entity.
Entity ids hold within their document, so they are written with the document's id (`doc:e5`).

Out: each mention's head token gets the entity id in the feature `coref` ('|'-joined when it heads several), the
multivalue attribute that pando's equivalence layer `coref` is declared over (flexencoder's CorefUD rule writes the
same). The raw `misc_Entity` stays on the tokens.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class Mention:
    eid: str
    etype: str
    start: int   # token index (1-based, the tokens' anchor order)
    end: int
    head_offset: int   # 1-based within the mention; 0 = none given


def _fields(spec: Optional[str]) -> Tuple[int, int, int]:
    """Positions of eid, etype and head in an opening (`global.Entity`); -1 when absent."""
    names = (spec or "eid-etype-head-other").split("-")
    eid = next((i for i, n in enumerate(names) if n in ("eid", "GRP")), 0)
    return eid, names.index("etype") if "etype" in names else -1, names.index("head") if "head" in names else -1


def _entity(key: str) -> str:
    return re.sub(r"\[\d+/\d+\]$", "", key)   # e5[1/2] → e5


def parse_mentions(values: List[Tuple[int, str]], global_entity: Optional[str] = None) -> List[Mention]:
    """The mentions of one document from its tokens' `Entity` values: (token index, value) in token order."""
    f_eid, f_etype, f_head = _fields(global_entity)
    open_: List[Tuple[str, Mention]] = []   # (key as written, mention), innermost last
    out: List[Mention] = []
    last = 0
    for pos, value in values:
        last = pos
        i = 0
        while i < len(value):
            if value[i] == "(":
                j = i + 1
                while j < len(value) and value[j] not in "()":
                    j += 1
                parts = value[i + 1:j].split("-")
                key = parts[f_eid] if f_eid < len(parts) else parts[0]
                etype = parts[f_etype] if 0 <= f_etype < len(parts) else ""
                head = parts[f_head] if 0 <= f_head < len(parts) else ""
                m = Mention(_entity(key), etype, pos, pos, int(head) if head.isdigit() else 0)
                if j < len(value) and value[j] == ")":
                    out.append(m)
                    i = j + 1
                else:
                    open_.append((key, m))
                    i = j
            else:
                j = value.find(")", i)
                j = len(value) if j < 0 else j
                key = value[i:j]
                for k in range(len(open_) - 1, -1, -1):
                    if open_[k][0] == key:
                        m = open_.pop(k)[1]
                        m.end = pos
                        out.append(m)
                        break
                i = j + 1
    for _, m in open_:   # never closed: up to the document's end
        m.end = last
        out.append(m)
    return sorted(out, key=lambda m: (m.start, -m.end))


def head_of(m: Mention) -> int:
    if m.head_offset <= 0:
        return m.start
    return min(m.start + m.head_offset - 1, m.end)


def apply_corefud(doc, *, doc_id: str, global_entity: Optional[str] = None) -> int:
    """`coref` on the mention heads of a document loaded from CoNLL-U; returns the number of mentions."""
    tokens = doc.layers.get("tokens") if hasattr(doc, "layers") else None
    if tokens is None:
        return 0
    by_index: Dict[int, object] = {}
    values: List[Tuple[int, str]] = []
    for node in tokens.nodes.values():
        idx = node.anchors[0].token_start if node.anchors else None
        if idx is None:
            continue
        by_index[idx] = node
        v = node.features.get("misc_Entity")
        if v:
            values.append((idx, v))
    if not values:
        return 0
    values.sort()
    mentions = parse_mentions(values, global_entity)
    heads: Dict[int, List[str]] = {}
    for m in mentions:
        ids = heads.setdefault(head_of(m), [])
        eid = f"{doc_id}:{m.eid}"
        if eid not in ids:
            ids.append(eid)
    for idx, ids in heads.items():
        node = by_index.get(idx)
        if node is not None:
            node.features["coref"] = "|".join(ids)
    return len(mentions)
