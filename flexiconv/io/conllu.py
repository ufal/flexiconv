from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import os

from ..core.model import Anchor, AnchorType, Document, Layer, Node


@dataclass
class _ConlluToken:
    sent_idx: int
    local_id: int  # ID within the sentence (1-based)
    form: str
    lemma: str
    upos: str
    xpos: str
    feats: str
    head: str
    deprel: str
    deps: str
    misc: Dict[str, str]
    extras: Dict[str, str] = field(default_factory=dict)


def _parse_misc(raw: str) -> Dict[str, str]:
    misc: Dict[str, str] = {}
    if not raw or raw == "_":
        return misc
    for part in raw.split("|"):
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            misc[k] = v
        else:
            misc[part] = "Yes"
    return misc


def _format_misc(misc: Dict[str, str]) -> str:
    if not misc:
        return "_"
    parts: List[str] = []
    for k in sorted(misc.keys()):
        v = misc[k]
        if v == "Yes" or v == "":
            parts.append(k)
        else:
            parts.append(f"{k}={v}")
    return "|".join(parts) if parts else "_"


def load_conllu(path: str, *, doc_id: Optional[str] = None) -> Document:
    """
    Load a CoNLL-U file into a pivot Document.

    This is intentionally conservative and focuses on:
    - Standardizing metadata from comment lines into document meta / attrs.
    - Creating a 'tokens' layer with one Node per token.
    - Creating a 'sentences' layer with one Node per sentence, anchored by token indices.

    Multi-word token range lines (e.g. '3-4 don't') are ignored; only the surface tokens
    with integer IDs are loaded. SpaceAfter=No in MISC is mapped to a boolean feature
    'space_after' on the token nodes.
    """
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    # File-level and document-level metadata
    file_level_attrs: Dict[str, str] = {}
    language: Optional[str] = None

    sentences_meta: List[Dict[str, Any]] = []
    current_sent_meta: Dict[str, Any] = {}
    tokens: List[_ConlluToken] = []

    sent_idx = 0
    local_id = 0
    # CoNLL-U-Plus:
    # - plus_columns: full list from "# global.columns = ..."
    # - extra_col_names: columns beyond the standard 10 ID..MISC (when ID present).
    # - idless_mode: some tools use FORM as the first column and omit ID, HEAD, DEPREL,...
    plus_columns: List[str] = []
    extra_col_names: List[str] = []
    idless_mode: bool = False

    def _flush_sentence() -> None:
        nonlocal sent_idx, local_id, current_sent_meta
        if local_id == 0:
            current_sent_meta = {}
            return
        sentences_meta.append(current_sent_meta)
        sent_idx += 1
        local_id = 0
        current_sent_meta = {}

    for raw in lines:
        line = raw.rstrip("\n")
        if not line:
            _flush_sentence()
            continue
        if line.startswith("#"):
            content = line[1:].strip()
            # CoNLL-U-Plus: global.columns header defining token columns.
            if content.startswith("global.columns") and "=" in content:
                _, val = content.split("=", 1)
                cols_spec = (val or "").strip()
                names = [c.strip() for c in cols_spec.split() if c.strip()]
                plus_columns = names
                has_id = any(n.upper() == "ID" for n in names)
                idless_mode = not has_id
                # When ID is present and columns follow the standard order
                # (ID FORM LEMMA UPOS XPOS FEATS HEAD DEPREL DEPS MISC ...),
                # consider everything beyond the standard 10 as extra.
                if has_id and len(names) > 10:
                    extra_col_names = names[10:]
                else:
                    extra_col_names = []
                continue
            # language and file-level generator/model etc.
            if content.startswith("language") and "=" in content:
                _, val = content.split("=", 1)
                language = (val or "").strip()
                continue
            if "=" in content:
                key, val = content.split("=", 1)
                key = key.strip()
                val = val.strip()
                if key in {"sent_id", "text"}:
                    current_sent_meta[key] = val
                else:
                    # Treat everything else as file-level metadata for now
                    file_level_attrs.setdefault(key, val)
            # Ignore other comments (newdoc/newpar markers are not structurally modelled yet)
            continue

        cols = line.split("\t")
        # Standard CoNLL-U / CoNLL-U-Plus with explicit ID column.
        if not idless_mode:
            if len(cols) < 10:
                # Malformed line; skip
                continue
            tid = cols[0]
            # Skip multi-word token lines (e.g. 3-4)
            if "-" in tid or "." in tid:
                continue
            try:
                local_int = int(tid)
            except ValueError:
                continue
            local_id = max(local_id, local_int)
            base = cols[1:11]
            form, lemma, upos, xpos, feats, head, deprel, deps, misc_raw = base
            misc = _parse_misc(misc_raw)
            # CoNLL-U-Plus: capture extra columns beyond the standard 10, if header declared them.
            extras: Dict[str, str] = {}
            if extra_col_names and len(cols) > 10:
                for idx_extra, name in enumerate(extra_col_names, start=10):
                    if idx_extra >= len(cols):
                        break
                    val_extra = cols[idx_extra]
                    if not val_extra or val_extra == "_":
                        continue
                    norm_name = name.lower().replace(":", "_")
                    extras[norm_name] = val_extra
        else:
            # "ID-less" CoNLL-U-Plus variant: FORM is the first column and there is
            # no explicit ID, HEAD/DEPREL/DEPS/MISC may be absent. We use the
            # global.columns header to map column names to values and synthesise IDs.
            if not plus_columns or not cols:
                continue
            # End of sentence is still signaled by blank line; within a sentence,
            # each non-empty line is a token.
            local_id += 1
            local_int = local_id
            # Map header names (upper-cased) to column values.
            col_map: Dict[str, str] = {}
            for i, val in enumerate(cols):
                if i >= len(plus_columns):
                    break
                name = plus_columns[i]
                if not name:
                    continue
                col_map[name.upper()] = val

            def _get(name: str) -> str:
                return col_map.get(name, "_")

            form = _get("FORM")
            lemma = _get("LEMMA")
            upos = _get("UPOS")
            xpos = _get("XPOS")
            feats = _get("FEATS")
            head = _get("HEAD")
            deprel = _get("DEPREL")
            deps = _get("DEPS")
            misc_raw = _get("MISC")
            misc = _parse_misc(misc_raw)
            extras = {}
            # Any non-standard column becomes an extra feature.
            standard_cols = {"FORM", "LEMMA", "UPOS", "XPOS", "FEATS", "HEAD", "DEPREL", "DEPS", "MISC", "ID"}
            for name_upper, val in col_map.items():
                if name_upper in standard_cols:
                    continue
                if not val or val == "_":
                    continue
                norm_name = name_upper.lower().replace(":", "_")
                extras[norm_name] = val

        tok = _ConlluToken(
            sent_idx=sent_idx,
            local_id=local_int,
            form=form if form != "_" else "",
            lemma=lemma if lemma != "_" else "",
            upos=upos if upos != "_" else "",
            xpos=xpos if xpos != "_" else "",
            feats=feats if feats != "_" else "",
            head=head if head != "_" else "",
            deprel=deprel if deprel != "_" else "",
            deps=deps if deps != "_" else "",
            misc=misc,
            extras=extras,
        )
        tokens.append(tok)

    # Flush last sentence if file does not end with blank line
    _flush_sentence()

    doc = Document(id=doc_id or path)
    if language:
        doc.meta["language"] = language
    if file_level_attrs:
        doc.meta["_conllu_file_attrs"] = file_level_attrs

    tokens_layer: Layer = doc.get_or_create_layer("tokens")
    sentences_layer: Layer = doc.get_or_create_layer("sentences")

    # Create token nodes with global token indices
    token_idx = 0
    sent_token_ranges: List[Tuple[int, int]] = []
    current_sent = 0
    sent_start_idx = 0
    for tok in tokens:
        # Start of a new sentence?
        if tok.sent_idx != current_sent:
            if token_idx > sent_start_idx:
                sent_token_ranges.append((sent_start_idx + 1, token_idx))
            current_sent = tok.sent_idx
            sent_start_idx = token_idx

        token_idx += 1
        anchor = Anchor(type=AnchorType.TOKEN, token_start=token_idx, token_end=token_idx)
        features: Dict[str, Any] = {
            "form": tok.form,
        }
        if tok.lemma:
            features["lemma"] = tok.lemma
        if tok.upos:
            features["upos"] = tok.upos
        if tok.xpos:
            features["xpos"] = tok.xpos
        if tok.feats:
            features["feats"] = tok.feats
        if tok.head:
            features["head"] = tok.head
        if tok.deprel:
            features["deprel"] = tok.deprel
        if tok.deps:
            features["deps"] = tok.deps
        # Map SpaceAfter=No into boolean space_after
        space_after = True
        if "SpaceAfter" in tok.misc and tok.misc["SpaceAfter"] == "No":
            space_after = False
        features["space_after"] = space_after
        # Preserve other MISC keys under a misc_ namespace
        for k, v in tok.misc.items():
            if k == "SpaceAfter":
                continue
            features[f"misc_{k}"] = v
        # CoNLL-U-Plus extra columns become direct features on the token.
        for k, v in tok.extras.items():
            features[k] = v
        node = Node(
            id=f"t{token_idx}",
            type="token",
            anchors=[anchor],
            features=features,
        )
        tokens_layer.nodes[node.id] = node

    if token_idx > sent_start_idx:
        sent_token_ranges.append((sent_start_idx + 1, token_idx))

    # Create sentence nodes
    for i, (start, end) in enumerate(sent_token_ranges):
        anchor = Anchor(type=AnchorType.TOKEN, token_start=start, token_end=end)
        meta = sentences_meta[i] if i < len(sentences_meta) else {}
        features: Dict[str, Any] = {}
        sent_id_val = meta.get("sent_id")
        text_val = meta.get("text")
        if sent_id_val:
            features["sent_id"] = sent_id_val
        if text_val:
            features["text"] = text_val
        # Store any remaining sentence-level metadata
        for k, v in meta.items():
            if k in {"sent_id", "text"}:
                continue
            features[k] = v
        node = Node(
            id=sent_id_val or f"s{i+1}",
            type="sentence",
            anchors=[anchor],
            features=features,
        )
        sentences_layer.nodes[node.id] = node

    return doc


def save_conllu(
    document: Document,
    path: str,
    *,
    generator: str = "flexiconv",
    model: Optional[str] = None,
) -> None:
    """
    Write a CoNLL-U file from a pivot Document.

    This expects:
    - A 'tokens' layer with token nodes anchored by TOKEN indices (1-based).
    - A 'sentences' layer with sentence nodes anchored by TOKEN ranges.

    It standardizes common metadata:
    - File-level: generator, model (and any previously parsed _conllu_file_attrs).
    - Sentence-level: sent_id and text, taken from the sentence node features.
    """
    tokens_layer = document.layers.get("tokens")
    sentences_layer = document.layers.get("sentences")
    if not tokens_layer or not sentences_layer:
        raise ValueError("save_conllu requires 'tokens' and 'sentences' layers in the Document.")

    # Collect and order tokens by token_start
    token_nodes: List[Node] = sorted(
        tokens_layer.nodes.values(),
        key=lambda n: (n.anchors[0].token_start or 0),
    )
    idx_to_token: Dict[int, Node] = {}
    for n in token_nodes:
        if not n.anchors:
            continue
        tidx = n.anchors[0].token_start
        if tidx is None:
            continue
        idx_to_token[tidx] = n

    # Order sentences by token_start
    sent_nodes: List[Node] = sorted(
        sentences_layer.nodes.values(),
        key=lambda n: (n.anchors[0].token_start or 0),
    )

    lines: List[str] = []

    # File-level metadata: previously parsed attributes plus generator/model/language
    file_attrs: Dict[str, str] = {}
    parsed_file_attrs = document.meta.get("_conllu_file_attrs")
    if isinstance(parsed_file_attrs, dict):
        file_attrs.update({str(k): str(v) for k, v in parsed_file_attrs.items()})

    if generator:
        file_attrs.setdefault("generator", generator)
    if model:
        file_attrs.setdefault("model", model)
    language = document.meta.get("language")
    if language:
        file_attrs.setdefault("language", str(language))

    for key in sorted(file_attrs.keys()):
        if key == "language":
            # Language is output last
            continue
        lines.append(f"# {key} = {file_attrs[key]}")
    if "language" in file_attrs:
        lines.append(f"# language = {file_attrs['language']}")

    # Sentences with their tokens
    for si, s in enumerate(sent_nodes):
        if s.anchors:
            start = s.anchors[0].token_start or 0
            end = s.anchors[0].token_end or 0
        else:
            start = 0
            end = 0
        if lines:
            lines.append("")  # blank line before each sentence (after header)

        sent_id_val = s.features.get("sent_id") or s.id
        text_val = s.features.get("text")
        if sent_id_val:
            lines.append(f"# sent_id = {sent_id_val}")
        if text_val:
            lines.append(f"# text = {text_val}")

        # Output all other sentence-level features as comments
        for key, value in sorted(s.features.items()):
            if key in {"sent_id", "text"}:
                continue
            lines.append(f"# {key} = {value}")

        # Collect tokens for this sentence, in order
        sent_tokens: List[Tuple[int, Node]] = []
        for tidx in range(start, end + 1):
            tok = idx_to_token.get(tidx)
            if tok is not None:
                sent_tokens.append((tidx, tok))

        for tok_idx_in_sent, (_, tok_node) in enumerate(sent_tokens, start=1):
            f = tok_node.features
            form = str(f.get("form", "") or "_")
            lemma = str(f.get("lemma") or "_")
            upos = str(f.get("upos") or "_")
            xpos = str(f.get("xpos") or "_")
            feats = str(f.get("feats") or "_")
            head = str(f.get("head") or "_")
            deprel = str(f.get("deprel") or "_")
            deps = str(f.get("deps") or "_")
            # Reconstruct MISC
            misc: Dict[str, str] = {}
            # Map space_after boolean back to SpaceAfter=No
            space_after = f.get("space_after")
            if space_after is False:
                misc["SpaceAfter"] = "No"
            # Any misc_* feature becomes a MISC key
            for key, value in f.items():
                if key.startswith("misc_"):
                    k = key[len("misc_") :]
                    misc[str(k)] = str(value)
            misc_str = _format_misc(misc)
            cols = [
                str(tok_idx_in_sent),
                form,
                lemma,
                upos,
                xpos,
                feats,
                head,
                deprel,
                deps,
                misc_str,
            ]
            lines.append("\t".join(cols))

    # Ensure exactly one trailing blank line
    if not lines or lines[-1] != "":
        lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def split_conllu_to_teitok_files(
    path: str,
    out_dir: str,
) -> list[str]:
    """
    Split a CoNLL-U file into one TEI/TEITOK XML file per '# newtext' block.

    Filenames are derived from, in order of preference:
    - a 'text_id'/'newtext_id' style comment within the block, or
    - a sequential counter after the input basename.
    """
    from .teitok_xml import save_teitok

    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    basename = os.path.basename(path)
    stem, _ = os.path.splitext(basename)

    global_header: list[str] = []
    segments: list[tuple[Optional[str], list[str]]] = []
    current_lines: list[str] = []
    current_text_id: Optional[str] = None
    seen_newtext = False

    def _flush_segment() -> None:
        nonlocal current_lines, current_text_id
        if current_lines:
            segments.append((current_text_id, current_lines))
        current_lines = []
        current_text_id = None

    for raw in lines:
        line = raw.rstrip("\n")
        if line.startswith("# newtext"):
            if seen_newtext:
                _flush_segment()
            seen_newtext = True
            current_lines.append(line)
            continue

        if not seen_newtext:
            # Before the first # newtext: treat as global header (kept in every split).
            global_header.append(line)
            continue

        # Inside a # newtext block.
        stripped = line.lstrip("#").strip()
        if "=" in stripped:
            key, val = stripped.split("=", 1)
            key = key.strip().lower().replace(" ", "_")
            val = val.strip()
            if key in {"text_id", "newtext_id"} and val:
                current_text_id = val
        current_lines.append(line)

    # Flush last block or whole file when there was no explicit # newtext.
    if seen_newtext:
        _flush_segment()
    else:
        # Treat entire file as a single segment.
        segments.append((None, lines))

    written: list[str] = []

    def _safe_slug(s: str) -> str:
        # Sanitize for filenames: ASCII letters/digits/._-, everything else '_'
        return "".join(
            ch if (ch.isalnum() or ch in "._-") else "_" for ch in s
        ).strip("._-") or "text"

    for idx, (text_id, seg_lines) in enumerate(segments, start=1):
        name_part = _safe_slug(text_id) if text_id else f"{idx:04d}"
        tmp_path = os.path.join(out_dir, f".tmp_{stem}_{name_part}.conllu")
        out_xml = os.path.join(out_dir, f"{stem}-{name_part}.xml")

        with open(tmp_path, "w", encoding="utf-8") as tf:
            for gl in global_header:
                tf.write(gl + "\n")
            for l in seg_lines:
                tf.write(l + "\n")
            tf.write("\n")

        # Reuse existing loader+saver to build TEITOK TEI.
        doc = load_conllu(tmp_path)
        save_teitok(doc, out_xml, source_path=path)

        try:
            os.remove(tmp_path)
        except OSError:
            pass

        written.append(out_xml)

    return written

