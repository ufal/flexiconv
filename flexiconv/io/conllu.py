from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
import os
import time

from ..core.model import Anchor, AnchorType, Document, Layer, Node

# (current, total, message) — total may be 0 when unknown
ProgressCallback = Callable[[int, int, str], None]


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


def _remap_conllu_head_to_tokid(
    head: str,
    local_to_tid: Dict[int, str],
) -> Optional[str]:
    """Map a CoNLL-U HEAD value to a TEITOK token id.

    ``0`` / ``_`` / empty → no head (root). Digit → ``local_to_tid[n]``.
    Already-non-numeric values (e.g. ``w-12``) are returned unchanged.
    """
    h = (head or "").strip()
    if not h or h == "_" or h == "0":
        return None
    if h.isdigit():
        return local_to_tid.get(int(h))
    return h


def _remap_conllu_deps_to_tokids(
    deps: str,
    local_to_tid: Dict[int, str],
) -> Optional[str]:
    """Map CoNLL-U DEPS (``2:nsubj|0:root``) heads to TEITOK token ids."""
    raw = (deps or "").strip()
    if not raw or raw == "_":
        return None
    parts_out: List[str] = []
    for part in raw.split("|"):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            parts_out.append(part)
            continue
        head_part, rel = part.split(":", 1)
        mapped = _remap_conllu_head_to_tokid(head_part, local_to_tid)
        if mapped is None:
            # Root in enhanced deps stays as 0:rel
            parts_out.append(f"0:{rel}" if head_part.strip() == "0" else part)
        else:
            parts_out.append(f"{mapped}:{rel}")
    return "|".join(parts_out) if parts_out else None


def _remap_tokid_head_to_conllu(
    head: str,
    tid_to_local: Dict[str, int],
) -> str:
    """Map a TEITOK-style head token id back to a CoNLL-U sentence-local HEAD."""
    h = (head or "").strip()
    if not h or h == "_":
        return "_"
    if h == "0":
        return "0"
    if h in tid_to_local:
        return str(tid_to_local[h])
    if h.isdigit():
        return h
    return "_"


def _remap_tokid_deps_to_conllu(
    deps: str,
    tid_to_local: Dict[str, int],
) -> str:
    """Map TEITOK-style DEPS heads back to CoNLL-U ordinals."""
    raw = (deps or "").strip()
    if not raw or raw == "_":
        return "_"
    parts_out: List[str] = []
    for part in raw.split("|"):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            parts_out.append(part)
            continue
        head_part, rel = part.split(":", 1)
        parts_out.append(f"{_remap_tokid_head_to_conllu(head_part, tid_to_local)}:{rel}")
    return "|".join(parts_out) if parts_out else "_"


def _conllu_chunk_revision_note(
    *,
    mode: str,
    index: int,
    source_path: str,
    total: Optional[int] = None,
    max_tokens: Optional[int] = None,
    max_sentences: Optional[int] = None,
) -> str:
    """Build a revisionDesc note for a split/chunked CoNLL-U → TEITOK output file."""
    source_name = os.path.basename(source_path)
    if total is not None:
        part = f"Part {index} of {total}"
    else:
        part = f"Part {index}"
    if mode == "split":
        detail = "from a split CoNLL-U → TEITOK conversion (# newtext)"
    else:
        limits: list[str] = []
        if max_tokens is not None:
            limits.append(f"max_tokens={max_tokens}")
        if max_sentences is not None:
            limits.append(f"max_sentences={max_sentences}")
        limit_note = f" ({', '.join(limits)})" if limits else ""
        detail = f"from a chunked CoNLL-U → TEITOK conversion{limit_note}"
    return f"{part} {detail} of {source_name}."


def apply_conllu_teitok_options(doc: Document, option: Optional[str]) -> None:
    """Apply CoNLL-U → TEITOK ``--option`` flags to a loaded document."""
    if not option:
        return
    for part in option.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, val = part.split("=", 1)
        key = key.strip().lower()
        val = val.strip().lower()
        if key == "ord" and val in {"no", "0", "false", "off", "none"}:
            doc.meta["_omit_conllu_ord"] = True


def load_conllu(path: str, *, doc_id: Optional[str] = None) -> Document:
    """
    Load a CoNLL-U file into a pivot Document.

    This is intentionally conservative and focuses on:
    - Standardizing metadata from comment lines into document meta / attrs.
    - Creating a 'tokens' layer with one Node per token.
    - Creating a 'sentences' layer with one Node per sentence, anchored by token indices.
    - Remapping CoNLL-U HEAD/DEPS sentence ordinals to TEITOK token ids (``w-N``);
      root (``HEAD=0``) leaves ``head`` unset. Original ordinals are kept on
      ``ord`` / ``ohead`` for validation (TEITOK convention; omit with
      ``--option ord=no``).

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

    # Create token nodes with global token indices.
    # Track per-sentence CoNLL-U local ID → TEITOK token id so HEAD/DEPS can be
    # remapped from sentence ordinals to TEITOK-style token ids (``w-N``).
    token_idx = 0
    sent_token_ranges: List[Tuple[int, int]] = []
    current_sent = 0
    sent_start_idx = 0
    sent_local_to_tid: Dict[int, Dict[int, str]] = {}
    pending_heads: List[Tuple[str, int, str, str]] = []  # node_id, sent_idx, raw_head, raw_deps

    for tok in tokens:
        # Start of a new sentence?
        if tok.sent_idx != current_sent:
            if token_idx > sent_start_idx:
                sent_token_ranges.append((sent_start_idx + 1, token_idx))
            current_sent = tok.sent_idx
            sent_start_idx = token_idx

        token_idx += 1
        tok_id_misc = tok.misc.get("tokId")
        node_id = tok_id_misc if tok_id_misc else f"w-{token_idx}"
        sent_local_to_tid.setdefault(tok.sent_idx, {})[tok.local_id] = node_id
        anchor = Anchor(type=AnchorType.TOKEN, token_start=token_idx, token_end=token_idx)
        features: Dict[str, Any] = {
            "form": tok.form,
            "ord": str(tok.local_id),
        }
        if tok.head:
            features["ohead"] = tok.head
        if tok.lemma:
            features["lemma"] = tok.lemma
        if tok.upos:
            features["upos"] = tok.upos
        if tok.xpos:
            features["xpos"] = tok.xpos
        if tok.feats:
            features["feats"] = tok.feats
        if tok.deprel:
            features["deprel"] = tok.deprel
        # head/deps remapped after the sentence's local→tid map is complete
        if tok.head or tok.deps:
            pending_heads.append((node_id, tok.sent_idx, tok.head, tok.deps))
        # Map SpaceAfter=No into boolean space_after
        space_after = True
        if "SpaceAfter" in tok.misc and tok.misc["SpaceAfter"] == "No":
            space_after = False
        features["space_after"] = space_after
        # Preserve other MISC keys under a misc_ namespace
        for k, v in tok.misc.items():
            if k in {"SpaceAfter", "tokId"}:
                continue
            features[f"misc_{k}"] = v
        # CoNLL-U-Plus extra columns become direct features on the token.
        for k, v in tok.extras.items():
            features[k] = v
        node = Node(
            id=node_id,
            type="token",
            anchors=[anchor],
            features=features,
        )
        tokens_layer.nodes[node.id] = node

    if token_idx > sent_start_idx:
        sent_token_ranges.append((sent_start_idx + 1, token_idx))

    # Remap CoNLL-U ordinal HEAD/DEPS to TEITOK token ids.
    for node_id, sent_idx, raw_head, raw_deps in pending_heads:
        node = tokens_layer.nodes.get(node_id)
        if node is None:
            continue
        local_map = sent_local_to_tid.get(sent_idx, {})
        mapped_head = _remap_conllu_head_to_tokid(raw_head, local_map)
        if mapped_head:
            node.features["head"] = mapped_head
        mapped_deps = _remap_conllu_deps_to_tokids(raw_deps, local_map)
        if mapped_deps:
            node.features["deps"] = mapped_deps

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
            id=sent_id_val or f"s-{i+1}",
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

        # TEITOK-style head/deps use token ids; CoNLL-U needs sentence-local ordinals.
        tid_to_local: Dict[str, int] = {
            tok_node.id: local_i for local_i, (_, tok_node) in enumerate(sent_tokens, start=1)
        }

        for tok_idx_in_sent, (_, tok_node) in enumerate(sent_tokens, start=1):
            f = tok_node.features
            form = str(f.get("form", "") or "_")
            lemma = str(f.get("lemma") or "_")
            upos = str(f.get("upos") or "_")
            xpos = str(f.get("xpos") or "_")
            feats = str(f.get("feats") or "_")
            deprel = str(f.get("deprel") or "_")
            ohead = f.get("ohead")
            if ohead not in (None, ""):
                head = str(ohead)
            else:
                raw_head = str(f.get("head") or "")
                if not raw_head:
                    head = "0" if deprel == "root" else "_"
                else:
                    head = _remap_tokid_head_to_conllu(raw_head, tid_to_local)
            raw_deps = str(f.get("deps") or "")
            deps = _remap_tokid_deps_to_conllu(raw_deps, tid_to_local) if raw_deps else "_"
            col_id = str(f.get("ord") or tok_idx_in_sent)
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
                col_id,
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


def _safe_conllu_slug(s: str) -> str:
    """Sanitize a string for use in output filenames."""
    return "".join(
        ch if (ch.isalnum() or ch in "._-") else "_" for ch in s
    ).strip("._-") or "text"


def _is_conllu_token_line(line: str) -> bool:
    """True if line is a surface-token CoNLL-U row (integer ID, not MWT/empty)."""
    if not line or line.startswith("#"):
        return False
    tid = line.split("\t", 1)[0]
    if "-" in tid or "." in tid:
        return False
    try:
        int(tid)
    except ValueError:
        return False
    return True


def _write_conllu_segment_to_teitok(
    path: str,
    out_dir: str,
    stem: str,
    global_header: list[str],
    text_id: Optional[str],
    seg_lines: list[str],
    idx: int,
    *,
    progress_callback: Optional[ProgressCallback] = None,
    progress_current: int = 0,
    progress_total: int = 0,
    conllu_option: Optional[str] = None,
    chunk_mode: Optional[str] = None,
    chunk_total: Optional[int] = None,
    max_tokens: Optional[int] = None,
    max_sentences: Optional[int] = None,
) -> str:
    """Write one CoNLL-U segment as TEITOK XML via load_conllu + save_teitok."""
    import tempfile

    from .teitok_xml import save_teitok

    name_part = _safe_conllu_slug(text_id) if text_id else f"{idx:04d}"
    out_xml = os.path.join(out_dir, f"{stem}-{name_part}.xml")

    def _prog(message: str) -> None:
        if progress_callback is not None:
            progress_callback(progress_current, progress_total, message)

    # Use a local temp file (not out_dir) — out_dir is often a slow external volume.
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=f"flexiconv_{stem}_{name_part}_",
        suffix=".conllu",
    )
    try:
        n_lines = len(global_header) + len(seg_lines)
        _prog(f"Chunk {idx}: writing temp CoNLL-U ({n_lines:,} lines)")
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as tf:
            for gl in global_header:
                tf.write(gl + "\n")
            for l in seg_lines:
                tf.write(l + "\n")
            tf.write("\n")

        _prog(f"Chunk {idx}: parsing CoNLL-U into pivot")
        doc = load_conllu(tmp_path)
        apply_conllu_teitok_options(doc, conllu_option)
        if chunk_mode:
            doc.meta["_conllu_chunk_revision"] = _conllu_chunk_revision_note(
                mode=chunk_mode,
                index=idx,
                source_path=path,
                total=chunk_total,
                max_tokens=max_tokens,
                max_sentences=max_sentences,
            )

        n_toks = len(doc.layers["tokens"].nodes) if "tokens" in doc.layers else 0
        n_sents = len(doc.layers["sentences"].nodes) if "sentences" in doc.layers else 0
        _prog(
            f"Chunk {idx}: building/writing TEITOK XML "
            f"({n_sents:,} sents, {n_toks:,} toks) → {os.path.basename(out_xml)}"
        )
        save_teitok(doc, out_xml, source_path=path)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    return out_xml


def _write_conllu_segments_to_teitok(
    path: str,
    out_dir: str,
    stem: str,
    global_header: list[str],
    segments: list[tuple[Optional[str], list[str]]],
    *,
    progress_callback: Optional[ProgressCallback] = None,
    conllu_option: Optional[str] = None,
    chunk_mode: Optional[str] = "split",
) -> list[str]:
    """Write CoNLL-U segments as TEITOK XML files via load_conllu + save_teitok."""
    written: list[str] = []
    total = len(segments)
    for idx, (text_id, seg_lines) in enumerate(segments, start=1):
        if progress_callback is not None:
            progress_callback(
                idx - 1,
                total,
                f"Writing TEITOK chunk {idx}/{total}",
            )
        out_xml = _write_conllu_segment_to_teitok(
            path,
            out_dir,
            stem,
            global_header,
            text_id,
            seg_lines,
            idx,
            progress_callback=progress_callback,
            progress_current=idx - 1,
            progress_total=total,
            conllu_option=conllu_option,
            chunk_mode=chunk_mode,
            chunk_total=total,
        )
        written.append(out_xml)
    if progress_callback is not None and total:
        progress_callback(total, total, f"Wrote {total} TEITOK chunk(s)")
    return written


def split_conllu_to_teitok_files(
    path: str,
    out_dir: str,
    *,
    conllu_option: Optional[str] = None,
) -> list[str]:
    """
    Split a CoNLL-U file into one TEI/TEITOK XML file per '# newtext' block.

    Filenames are derived from, in order of preference:
    - a 'text_id'/'newtext_id' style comment within the block, or
    - a sequential counter after the input basename.
    """
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

    return _write_conllu_segments_to_teitok(
        path, out_dir, stem, global_header, segments, conllu_option=conllu_option
    )


def chunk_conllu_to_teitok_files(
    path: str,
    out_dir: str,
    *,
    max_tokens: Optional[int] = None,
    max_sentences: Optional[int] = None,
    progress_callback: Optional[ProgressCallback] = None,
    conllu_option: Optional[str] = None,
) -> list[str]:
    """
    Chunk a CoNLL-U file into TEITOK XML files under size limits.

    Sentences are packed in order into output files. A new file is started when
    adding the next sentence would exceed ``max_tokens`` and/or ``max_sentences``
    (whichever limits are set). A single oversized sentence still becomes its
    own file (sentences are never split).

    ``# newdoc`` and ``# newtext`` markers are hard boundaries: the current chunk
    is flushed before the marked sentence, even if limits are not yet reached.

    The input is streamed (not fully loaded) so large corpora can be processed
    with bounded memory. When ``progress_callback`` is set it receives
    ``(bytes_done, bytes_total, message)`` during packing/writing.

    At least one of ``max_tokens`` / ``max_sentences`` must be a positive int.
    """
    if max_tokens is not None and max_tokens <= 0:
        raise ValueError("max_tokens must be a positive integer")
    if max_sentences is not None and max_sentences <= 0:
        raise ValueError("max_sentences must be a positive integer")
    if max_tokens is None and max_sentences is None:
        raise ValueError("at least one of max_tokens or max_sentences is required")

    basename = os.path.basename(path)
    stem, _ = os.path.splitext(basename)
    try:
        total_bytes = os.path.getsize(path)
    except OSError:
        total_bytes = 0

    def _progress(done: int, message: str) -> None:
        if progress_callback is not None:
            progress_callback(done, total_bytes, message)

    _progress(0, f"Scanning {basename}")

    global_header: list[str] = []
    current_lines: list[str] = []
    current_tokens = 0
    hard_before = False
    seen_token = False

    chunk_lines: list[str] = []
    chunk_tokens = 0
    chunk_sents = 0
    written: list[str] = []
    total_sents_seen = 0
    total_tokens_seen = 0

    last_report = 0.0
    report_interval_s = 1.0

    def _maybe_report_scan(byte_pos: int, *, force: bool = False) -> None:
        nonlocal last_report
        now = time.monotonic()
        if not force and (now - last_report) < report_interval_s:
            return
        last_report = now
        _progress(
            byte_pos,
            (
                f"Packing sentences ({total_sents_seen:,} sents, "
                f"{total_tokens_seen:,} toks, {len(written)} file(s) written)"
            ),
        )

    def _write_current_chunk(byte_pos: int) -> None:
        nonlocal chunk_lines, chunk_tokens, chunk_sents, last_report
        if not chunk_lines:
            return
        idx = len(written) + 1
        _progress(
            byte_pos,
            (
                f"Writing TEITOK chunk {idx} "
                f"({chunk_sents:,} sents, {chunk_tokens:,} toks)"
            ),
        )
        out_xml = _write_conllu_segment_to_teitok(
            path,
            out_dir,
            stem,
            global_header,
            None,
            chunk_lines,
            idx,
            progress_callback=progress_callback,
            progress_current=byte_pos,
            progress_total=total_bytes,
            conllu_option=conllu_option,
            chunk_mode="chunk",
            max_tokens=max_tokens,
            max_sentences=max_sentences,
        )
        written.append(out_xml)
        _progress(
            byte_pos,
            (
                f"Wrote {os.path.basename(out_xml)} "
                f"({chunk_sents:,} sents, {chunk_tokens:,} toks; "
                f"{len(written)} file(s) so far)"
            ),
        )
        chunk_lines = []
        chunk_tokens = 0
        chunk_sents = 0
        last_report = time.monotonic()

    def _flush_sentence_into_chunk(byte_pos: int) -> None:
        nonlocal current_lines, current_tokens, hard_before
        nonlocal chunk_lines, chunk_tokens, chunk_sents
        nonlocal total_sents_seen, total_tokens_seen
        if not (current_lines and current_tokens > 0):
            current_lines = []
            current_tokens = 0
            hard_before = False
            return

        n_toks = current_tokens
        hard = hard_before
        sent_lines = current_lines
        current_lines = []
        current_tokens = 0
        hard_before = False

        if hard and chunk_lines:
            _write_current_chunk(byte_pos)
        would_exceed_toks = (
            max_tokens is not None
            and chunk_sents > 0
            and chunk_tokens + n_toks > max_tokens
        )
        would_exceed_sents = (
            max_sentences is not None
            and chunk_sents > 0
            and chunk_sents + 1 > max_sentences
        )
        if would_exceed_toks or would_exceed_sents:
            _write_current_chunk(byte_pos)
        if chunk_lines:
            chunk_lines.append("")
        chunk_lines.extend(sent_lines)
        chunk_tokens += n_toks
        chunk_sents += 1
        total_sents_seen += 1
        total_tokens_seen += n_toks
        _maybe_report_scan(byte_pos)

    with open(path, "r", encoding="utf-8") as f:
        bytes_done = 0
        while True:
            raw = f.readline()
            if raw == "":
                break
            bytes_done += len(raw.encode("utf-8"))
            byte_pos = bytes_done if total_bytes else 0
            line = raw.rstrip("\n\r")

            if not line:
                if current_tokens > 0:
                    _flush_sentence_into_chunk(byte_pos)
                elif current_lines and not seen_token:
                    global_header.extend(current_lines)
                    global_header.append(line)
                    current_lines = []
                continue

            if line.startswith("#"):
                if line.startswith("# newdoc") or line.startswith("# newtext"):
                    if current_tokens > 0:
                        _flush_sentence_into_chunk(byte_pos)
                    hard_before = True
                if not seen_token and current_tokens == 0 and not current_lines:
                    content = line[1:].strip()
                    key = content.split("=", 1)[0].strip().lower().replace(" ", "_")
                    if key in {
                        "sent_id",
                        "text",
                        "newdoc",
                        "newdoc_id",
                        "newtext",
                        "newtext_id",
                        "text_id",
                        "newpar",
                        "newpar_id",
                    } or content.startswith("newdoc") or content.startswith("newtext"):
                        current_lines.append(line)
                    else:
                        global_header.append(line)
                    continue
                current_lines.append(line)
                continue

            seen_token = True
            current_lines.append(line)
            if _is_conllu_token_line(line):
                current_tokens += 1

        # EOF
        byte_pos = total_bytes or bytes_done
        if current_tokens > 0:
            _flush_sentence_into_chunk(byte_pos)
        elif current_lines and not seen_token:
            global_header.extend(current_lines)
        _write_current_chunk(byte_pos)

    if not written:
        # Empty / comment-only input: still emit one file from the raw content.
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        written.append(
            _write_conllu_segment_to_teitok(
                path, out_dir, stem, global_header, None, lines, 1,
                conllu_option=conllu_option,
                chunk_mode="chunk",
                max_tokens=max_tokens,
                max_sentences=max_sentences,
            )
        )

    _progress(
        total_bytes,
        (
            f"Done: {len(written)} file(s), {total_sents_seen:,} sents, "
            f"{total_tokens_seen:,} toks"
        ),
    )
    return written

