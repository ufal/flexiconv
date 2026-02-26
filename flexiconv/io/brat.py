"""
Brat stand-off (.ann + .txt) → TEITOK-style TEI conversion.

This module reads a BRAT-style annotation file (.ann) together with its
corresponding plain text (.txt), tokenises the text into <tok> elements,
and attaches standOff annotations (<standOff>/<spanGrp>/<linkGrp>) that
mirror the original BRAT annotations:

- Text-bound annotations (T*) become <span corresp="#w-1 #w-2" code="TYPE" ...>.
- Attribute annotations (A*) become <span corresp="#ID" code="ATTR" ...>.
- Relations (R*) become <link source="#ID1" target="#ID2" code="REL" ...>.

The resulting TEI tree is stored in document.meta["_teitok_tei_root"] for
save_teitok, and a simple token/sentence layer is populated in the pivot
Document. By default, the loader assumes:

- INPUT is either the .ann file or the .txt file.
- The matching counterpart lives in the same directory with the same stem
  (e.g. foo.ann ↔ foo.txt).

When run via the CLI with -f brat, you can override paths using:

    --option "plain=/path/to/text.txt;ann=/path/to/anno.ann"

Multiple .ann files can be provided as a comma-separated list for ann=.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from lxml import etree

from ..core.model import Anchor, AnchorType, Document, Node
from .teitok_xml import SPACE_AFTER_FEATURE, _ensure_tei_header, _xpath_local


# Universal Dependencies-style POS tags that, when used as T-types, likely
# indicate that T-annotations *are* the tokenisation (as in examples/brat/077b.ann).
_UD_POS_TAGS = {
    "ADJ",
    "ADP",
    "ADV",
    "AUX",
    "CCONJ",
    "DET",
    "INTJ",
    "NOUN",
    "NUM",
    "PART",
    "PRON",
    "PROPN",
    "PUNCT",
    "SCONJ",
    "SYM",
    "VERB",
    "X",
}


def _resolve_brat_paths(
    entry_path: str,
    plain_path: Optional[str] = None,
    ann_paths: Optional[List[str]] = None,
) -> Tuple[str, List[str]]:
    """Resolve plain text and annotation file paths for a BRAT input.

    - entry_path may be either the .ann file or the .txt file.
    - When plain_path/ann_paths are provided explicitly they take precedence.
    - Otherwise we assume matching names in the same directory.
    """
    entry_path = os.path.abspath(entry_path)
    base_dir = os.path.dirname(entry_path)
    base_name = os.path.basename(entry_path)
    stem, ext = os.path.splitext(base_name)
    ext = ext.lower()

    if plain_path:
        plain = os.path.abspath(plain_path)
    else:
        if ext == ".txt":
            plain = entry_path
        else:
            plain = os.path.join(base_dir, stem + ".txt")

    if ann_paths:
        anns = [os.path.abspath(p) for p in ann_paths]
    else:
        if ext == ".ann":
            anns = [entry_path]
        else:
            cand = os.path.join(base_dir, stem + ".ann")
            anns = [cand] if os.path.exists(cand) else []

    if not os.path.exists(plain):
        raise RuntimeError(f"Brat loader: plain text file not found: {plain}")
    if not anns:
        raise RuntimeError(f"Brat loader: no .ann annotation file found for {entry_path}")

    return plain, anns


def _tokenize_plain(text: str) -> List[Dict[str, Any]]:
    """Tokenise plain text into a list of tokens with character spans.

    We use a simple whitespace-based tokenisation (\\S+ runs) and record
    inclusive character offsets so we can map BRAT character spans back to
    token IDs later.
    """
    tokens: List[Dict[str, Any]] = []
    length = len(text)
    for idx, m in enumerate(re.finditer(r"\S+", text), start=1):
        start = m.start()
        # BRAT offsets are half-open [start, end); we store end as inclusive.
        end = m.end() - 1
        form = m.group(0)
        # Space-after feature: true when the next character is a space.
        space_after = end + 1 < length and text[end + 1] == " "
        tokens.append(
            {
                "id": f"w-{idx}",
                "form": form,
                "start": start,
                "end": end,
                "space_after": space_after,
            }
        )
    return tokens


def _tokens_for_span(
    tokens: List[Dict[str, Any]],
    span_start: int,
    span_end: int,
) -> List[str]:
    """Return token IDs that overlap the character span [span_start, span_end)."""
    if span_start >= span_end:
        return []
    ids: List[str] = []
    for tok in tokens:
        # Token span is [start, end_inclusive]; compare with [span_start, span_end)
        t_start = int(tok["start"])
        t_end_inc = int(tok["end"])
        t_end = t_end_inc + 1  # convert to half-open
        if not (t_end <= span_start or t_start >= span_end):
            ids.append(tok["id"])
    return ids


def _build_tei_from_brat(
    entry_path: str,
    plain_path: Optional[str] = None,
    ann_paths: Optional[List[str]] = None,
) -> etree._Element:
    """Build a TEITOK-style TEI tree from a BRAT .ann + .txt pair.

    Heuristics:
    - When all T-types look like UD POS tags (e.g. NOUN, VERB, ADP, ...),
      we treat T-annotations as the primary tokenisation and build one
      <tok> per T, with idx and space_after based on the original text.
      This matches examples like examples/brat/077b.ann.
    - Otherwise we fall back to simple whitespace tokenisation and keep
      T-annotations as standOff spans over those tokens.
    """
    plain, anns = _resolve_brat_paths(entry_path, plain_path=plain_path, ann_paths=ann_paths)

    with open(plain, "r", encoding="utf-8") as f:
        text = f.read()

    # First pass over .ann: collect T-annotations so we can decide whether
    # they define the tokenisation (UD-style) or are higher-level spans.
    t_spans: List[Dict[str, Any]] = []
    for ann_path in anns:
        with open(ann_path, "r", encoding="utf-8") as f_ann:
            for raw in f_ann:
                line = raw.rstrip("\n")
                if not line or line.startswith("#") or not line.startswith("T"):
                    continue
                try:
                    bratid, rest = line.split("\t", 1)
                    type_and_offsets, text_val = rest.split("\t", 1)
                except ValueError:
                    continue
                parts = type_and_offsets.split()
                if len(parts) < 3:
                    continue
                ann_type = parts[0]
                try:
                    begin = int(parts[1])
                    end = int(parts[2])
                except ValueError:
                    continue
                t_spans.append(
                    {
                        "id": bratid,
                        "type": ann_type,
                        "begin": begin,
                        "end": end,
                        "text": text_val.strip(),
                    }
                )

    # Detect two common patterns:
    # - "simple UD": all T-types == Token (case-insensitive) – e.g. examples/brat/simpleud.ann.
    # - "UD tokens": T-types are POS tags (NOUN, VERB, ...) with possibly a few technical extras.
    if t_spans:
        types = {t["type"] for t in t_spans}
        is_simple_ud = all(t["type"].lower() == "token" for t in t_spans)

        allowed_extra = {"NOTAG"}
        ud_like = [
            t for t in t_spans if t["type"] in _UD_POS_TAGS or t["type"] in allowed_extra
        ]
        has_real_ud = any(t["type"] in _UD_POS_TAGS for t in t_spans)
        use_ud_tokens = has_real_ud and len(ud_like) == len(t_spans)
    else:
        is_simple_ud = False
        use_ud_tokens = False

    if use_ud_tokens:
        # UD-style: one token per T-annotation, in textual order.
        t_spans_sorted = sorted(t_spans, key=lambda t: (t["begin"], t["end"]))
        tokens: List[Dict[str, Any]] = []
        for idx, t in enumerate(t_spans_sorted, start=1):
            start = int(t["begin"])
            end_excl = int(t["end"])
            end_inc = end_excl - 1
            form = t["text"] or text[start:end_excl]
            form = form.strip()
            space_after = end_excl < len(text) and text[end_excl].isspace()
            tokens.append(
                {
                    "id": f"w-{idx}",
                    "form": form,
                    "start": start,
                    "end": end_inc,
                    "space_after": space_after,
                    "_brat_id": t["id"],
                    "_type": t["type"],
                }
            )
    else:
        # Default: simple whitespace-based tokenisation.
        tokens = _tokenize_plain(text)

    base = os.path.basename(plain)
    stem, _ = os.path.splitext(base)
    when_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    tei = etree.Element("TEI")
    _ensure_tei_header(tei, source_filename=base, when=when_iso)

    text_el = etree.SubElement(tei, "text", id=stem)
    # Build a single sentence, but for UD-style data we will later split it
    # heuristically on sentence-final punctuation tokens if desired.
    s_el = etree.SubElement(text_el, "s", id="s-1")

    # Emit tokens with idx (char span) and space_after via tail, and
    # keep a mapping from token IDs to their TEI elements so that we
    # can attach UD-style features (pos, lemma, dependencies, IPA, etc.).
    tok_elems: Dict[str, etree._Element] = {}
    for tok in tokens:
        attrs = {
            "id": tok["id"],
            "idx": f"{tok['start']}-{tok['end']}",
        }
        t_el = etree.SubElement(s_el, "tok", **attrs)
        t_el.text = tok["form"]
        t_el.tail = " " if tok["space_after"] else ""
        tok_elems[tok["id"]] = t_el
    if len(s_el):
        s_el[-1].tail = ""

    # standOff with spanGrp/linkGrp mirroring brat2teitok.pl, unless we are in
    # UD-style modes where the same information is already captured directly
    # on <tok> (simple UD and UD-token modes).
    write_standoff = not (is_simple_ud or use_ud_tokens)
    stand_off: Optional[etree._Element] = None
    span_grp: Optional[etree._Element] = None
    link_grp: Optional[etree._Element] = None
    if write_standoff:
        stand_off = etree.SubElement(text_el, "standOff")
        span_grp = etree.SubElement(stand_off, "spanGrp")
        link_grp = etree.SubElement(stand_off, "linkGrp")

    # br2tt: brat ID → TEI standOff element ID (span/link)
    # br2tok: brat ID → token ID (w-...) when the annotation aligns to a token span
    br2tt: Dict[str, str] = {}
    br2tok: Dict[str, str] = {}
    # For UD-style tokenisation, pre-populate br2tok so that attributes
    # and relations can address tokens directly. Also collect UD-style
    # morphological features so we can aggregate them into feats=.
    token_ud_feats: Dict[str, Dict[str, str]] = {}
    if use_ud_tokens:
        for tok in tokens:
            brat_id = tok.get("_brat_id")
            if brat_id:
                br2tok[brat_id] = tok["id"]
                token_ud_feats.setdefault(tok["id"], {})
    br2txt: Dict[str, str] = {}
    counter = 1

    for ann_path in anns:
        with open(ann_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line or line.startswith("#"):
                    continue

                if line.startswith("R"):
                    # Relation: R1<TAB>RelType Arg1:T1 Arg2:T2
                    try:
                        bratid, rest = line.split("\t", 1)
                    except ValueError:
                        continue
                    parts = rest.split()
                    if len(parts) < 3:
                        continue
                    rel_type, arg1, arg2 = parts[0], parts[1], parts[2]
                    id1 = id2 = ""
                    head_tok_id: Optional[str] = None
                    dep_tok_id: Optional[str] = None
                    if ":" in arg1:
                        _, br1 = arg1.split(":", 1)
                        id1 = f"#{br2tt.get(br1, br1)}"
                        head_tok_id = br2tok.get(br1)
                    if ":" in arg2:
                        _, br2 = arg2.split(":", 1)
                        id2 = f"#{br2tt.get(br2, br2)}"
                        dep_tok_id = br2tok.get(br2)
                    if not id1 or not id2:
                        continue
                    if link_grp is not None:
                        link_el = etree.SubElement(
                            link_grp,
                            "link",
                            source=id1,
                            target=id2,
                            code=rel_type,
                            id=f"an-{counter}",
                            brat_id=bratid,
                            brat_def=f"{arg1}-{arg2}",
                        )
                        counter += 1
                        br2tt[bratid] = link_el.get("id") or ""
                    # UD-style smart mapping: if both arguments resolve to tokens,
                    # attach head/deprel on the dependent token.
                    if head_tok_id and dep_tok_id:
                        dep_el = tok_elems.get(dep_tok_id)
                        if dep_el is not None and not dep_el.get("head"):
                            dep_el.set("head", head_tok_id)
                            dep_el.set("deprel", rel_type)
                elif line.startswith("A"):
                    # Attribute over a T* annotation, often used for UD-style
                    # layers such as pos, lemma, IPA, pronunciation, etc.
                    try:
                        bratid, rest = line.split("\t", 1)
                    except ValueError:
                        continue
                    parts = rest.split()
                    if len(parts) < 2:
                        continue
                    # BRAT UD convention: "pos T1 DET", "lemma T1 the", etc.
                    attr_name = parts[0]
                    target_ann = parts[1]
                    value = " ".join(parts[2:]) if len(parts) > 2 else ""
                    attr_name_lc = attr_name.lower()

                    # Smart mapping for common token-level layers.
                    token_attr_key: Optional[str] = None
                    if attr_name_lc in {"pos", "upos"}:
                        token_attr_key = "upos"
                    elif attr_name_lc in {"xpos"}:
                        token_attr_key = "xpos"
                    elif attr_name_lc in {"lemma"}:
                        token_attr_key = "lemma"
                    elif attr_name_lc in {"feats"}:
                        token_attr_key = "feats"
                    elif attr_name_lc in {"ipa", "pronunciation", "pronunctiation"}:
                        token_attr_key = attr_name_lc

                    ud_morph_keys = {
                        "Case",
                        "Number",
                        "PronType",
                        "NounType",
                        "Tense",
                        "VerbForm",
                        "Mood",
                        "Polarity",
                        "AdvType",
                        "NumType",
                        "NumForm",
                    }

                    # UD-style morphological features: in UD-token mode, they go
                    # only into feats (no separate Case/Number/... attributes to
                    # avoid redundancy); outside UD mode, keep them as attributes.
                    if attr_name in ud_morph_keys:
                        if not use_ud_tokens:
                            token_attr_key = attr_name
                        # In UD mode, we don't set token_attr_key here; we handle
                        # these via token_ud_feats below.

                    if token_attr_key is not None:
                        tok_id = br2tok.get(target_ann)
                        if tok_id:
                            tok_el = tok_elems.get(tok_id)
                            if tok_el is not None and value:
                                tok_el.set(token_attr_key, value)
                        # Do not create an extra standOff span for these; they
                        # are better represented as token attributes in TEITOK.
                        continue

                    # UD-token mode: record morphological features for feats.
                    if use_ud_tokens and attr_name in ud_morph_keys:
                        tok_id = br2tok.get(target_ann)
                        if tok_id and value:
                            feats_map = token_ud_feats.setdefault(tok_id, {})
                            feats_map[attr_name] = value

                    # Fallback: treat as generic attribute on a previous span, if any,
                    # but only when we are actually emitting standOff.
                    if span_grp is None:
                        continue
                    target_id = br2tt.get(target_ann)
                    if not target_id:
                        continue
                    text_val = br2txt.get(target_ann, value)
                    span_el = etree.SubElement(
                        span_grp,
                        "span",
                        corresp=f"#{target_id}",
                        code=attr_name,
                        id=f"an-{counter}",
                        brat_id=bratid,
                    )
                    if text_val:
                        span_el.text = text_val
                    counter += 1
                    br2tt[bratid] = span_el.get("id") or ""
                elif line.startswith("T"):
                    # Text-bound annotation: T1<TAB>Type start end\ttext
                    try:
                        bratid, rest = line.split("\t", 1)
                    except ValueError:
                        continue
                    try:
                        type_and_offsets, text_val = rest.split("\t", 1)
                    except ValueError:
                        # Some BRAT exports may not include the text column; skip safely.
                        continue
                    parts = type_and_offsets.split()
                    if len(parts) < 3:
                        continue
                    ann_type = parts[0]
                    try:
                        begin = int(parts[1])
                        end = int(parts[2])
                    except ValueError:
                        continue
                    span_token_ids = _tokens_for_span(tokens, begin, end)
                    if not span_token_ids:
                        continue
                    # In UD-token mode, when a T-annotation aligns to a single token
                    # and its type is a UD POS tag, prefer attaching that as an
                    # attribute (upos) on the token, regardless of whether we also
                    # keep a span in standOff.
                    if use_ud_tokens and len(span_token_ids) == 1 and ann_type in _UD_POS_TAGS:
                        tok_id = span_token_ids[0]
                        tok_el = tok_elems.get(tok_id)
                        if tok_el is not None and not tok_el.get("upos"):
                            tok_el.set("upos", ann_type)
                    if span_grp is not None:
                        corresp = " ".join(f"#{tid}" for tid in span_token_ids)
                        span_el = etree.SubElement(
                            span_grp,
                            "span",
                            corresp=corresp,
                            code=ann_type,
                            id=f"an-{counter}",
                            brat_id=bratid,
                            range=f"{begin}-{end}",
                        )
                        span_el.text = text_val.strip()
                        counter += 1
                    br2tt[bratid] = (span_el.get("id") if span_grp is not None else "") or ""
                    br2txt[bratid] = text_val.strip()
                    # When a text-bound annotation cleanly aligns to a single token,
                    # remember that mapping so UD-style attributes and relations can
                    # address the token directly.
                    if len(span_token_ids) == 1:
                        br2tok[bratid] = span_token_ids[0]

    # After reading all annotations, synthesise UD-style feats strings
    # like Case=Ela|Number=Sing when we are in UD-token mode.
    if use_ud_tokens and token_ud_feats:
        for tok_id, feats_map in token_ud_feats.items():
            tok_el = tok_elems.get(tok_id)
            if tok_el is None:
                continue
            # If feats was already set explicitly, don't overwrite it.
            if tok_el.get("feats"):
                continue
            # Sort keys for deterministic output.
            parts = [f"{k}={v}" for k, v in sorted(feats_map.items()) if v]
            if parts:
                tok_el.set("feats", "|".join(parts))

    return tei


def load_brat(
    path: str,
    *,
    plain_path: Optional[str] = None,
    ann_paths: Optional[List[str]] = None,
    **kwargs: Any,
) -> Document:
    """Load BRAT (.ann + .txt) into a pivot Document with TEITOK-style TEI in meta."""
    tei = _build_tei_from_brat(path, plain_path=plain_path, ann_paths=ann_paths)

    base = os.path.basename(plain_path or path)
    stem, _ = os.path.splitext(base)
    doc = Document(id=stem)
    doc.meta["_teitok_tei_root"] = tei

    tokens_layer = doc.get_or_create_layer("tokens")
    sentences_layer = doc.get_or_create_layer("sentences")

    token_elems = _xpath_local(tei, "tok")
    token_index_by_xmlid: Dict[str, int] = {}
    for idx, t in enumerate(token_elems, start=1):
        xmlid = t.get("id") or t.get("{http://www.w3.org/XML/1998/namespace}id") or f"w-{idx}"
        token_index_by_xmlid[xmlid] = idx
        form = (t.text or "").strip()
        has_space_after = bool(t.tail and " " in (t.tail or ""))
        features: Dict[str, Any] = {
            "form": form,
            SPACE_AFTER_FEATURE: has_space_after,
        }
        idx_attr = t.get("idx")
        if idx_attr:
            features["idx"] = idx_attr
        # Copy common TEITOK token attributes into the pivot token features so that
        # downstream formats (e.g. CoNLL-U, FoLiA, TEI) can reuse them.
        for attr in (
            "lemma",
            "upos",
            "xpos",
            "feats",
            "head",
            "deprel",
            "deps",
            "reg",
            "expan",
            "corr",
            "trslit",
            "lex",
            "nform",
            "ort",
            "gram",
            "opos",
            "olemma",
            "ipa",
            "pronunciation",
            "pronunctiation",
        ):
            val = t.get(attr)
            if val is not None:
                features[attr] = val
        anchor = Anchor(type=AnchorType.TOKEN, token_start=idx, token_end=idx)
        node = Node(id=xmlid, type="token", anchors=[anchor], features=features)
        tokens_layer.nodes[node.id] = node

    # Single sentence covering all tokens, to keep downstream expectations simple.
    if token_index_by_xmlid:
        start = 1
        end = len(token_elems)
        sent_anchor = Anchor(type=AnchorType.TOKEN, token_start=start, token_end=end)
        sent_node = Node(id="s-1", type="sentence", anchors=[sent_anchor], features={})
        sentences_layer.nodes[sent_node.id] = sent_node

    return doc

