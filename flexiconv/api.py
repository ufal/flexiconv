"""Programmatic API for flexiconv (conversion and deduplication).

Used by the GUI and other integrators. Supports progress callbacks and cancel checks
for long-running operations.
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from typing import Callable, Optional

from .registry import registry
from .io.teitok_xml import (
    _find_teitok_project_root,
    find_duplicate_teitok_files,
    teitok_text_fingerprint,
    teitok_text_fingerprint_hash,
)
from .io.near_dup import (
    lsh_bands,
    minhash_signature,
    signature_from_blob,
    signature_similarity,
    signature_to_blob,
    shingle_text,
)
from .io.txt import document_to_plain_text, normalize_text_for_fingerprint
from .mime import detect_mime, path_to_input_format, path_to_output_format

# Type aliases for the API
DuplicateGroups = list[list[str]]
ProgressCallback = Callable[[int, int, str], None]
CancelCheck = Callable[[], bool]


class CancelError(Exception):
    """Raised when the user cancels an operation (cancel_check returned True)."""


def _ensure_formats() -> None:
    """Ensure built-in formats are registered (idempotent)."""
    from .cli import _register_builtin_formats
    _register_builtin_formats()


def _default_ext_for_format(fmt_name: str) -> str:
    _FMT = {
        "teitok": ".xml", "tei": ".xml", "rtf": ".rtf", "txt": ".txt",
        "html": ".html", "hocr": ".hocr", "conllu": ".conllu", "srt": ".srt",
        "doreco": ".eaf", "exb": ".exb", "docx": ".docx",
    }
    return _FMT.get((fmt_name or "").lower(), ".xml")


def _default_output_path(input_path: str, to_format: Optional[str]) -> str:
    """Default output path when not given (next to input with sensible extension)."""
    from .cli import _default_output_in_teitok_project, _linux_safe_basename
    default = _default_output_in_teitok_project(input_path)
    if default is not None:
        return default
    base = _linux_safe_basename(input_path)
    stem, _ = os.path.splitext(base)
    ext = _default_ext_for_format(to_format or "")
    return os.path.join(os.path.dirname(input_path), stem + ext)


@dataclass
class ConvertResult:
    """Result of a single-file conversion."""
    success: bool
    error_message: Optional[str] = None
    stderr_snippet: Optional[str] = None


def run_convert(
    input_path: str,
    output_path: Optional[str] = None,
    from_format: Optional[str] = None,
    to_format: Optional[str] = None,
    options: Optional[dict] = None,
    progress_callback: Optional[ProgressCallback] = None,
    cancel_check: Optional[CancelCheck] = None,
) -> ConvertResult:
    """Run single-file conversion.

    Options dict can include: force, linebreaks, hocr_no_split_punct,
    hocr_hyphen_truncation, eaf_style, option, prettyprint, spacing_mode,
    vert_no_doc_split, teitok_project, copy_original.
    """
    _ensure_formats()
    opts = options or {}
    input_path = os.path.abspath(input_path)
    if not os.path.isfile(input_path):
        return ConvertResult(success=False, error_message=f"Input file not found: {input_path}")

    if output_path is None:
        output_path = _default_output_path(input_path, to_format)
    else:
        output_path = os.path.abspath(output_path)
        # If output is a directory, write into it with input basename + format extension (like CLI).
        if os.path.isdir(output_path):
            base = os.path.basename(input_path)
            stem, _ = os.path.splitext(base)
            ext = _default_ext_for_format(to_format or "")
            output_path = os.path.join(output_path, stem + ext)
        elif not os.path.exists(output_path) and not os.path.splitext(os.path.basename(output_path))[1]:
            os.makedirs(output_path, exist_ok=True)
            base = os.path.basename(input_path)
            stem, _ = os.path.splitext(base)
            ext = _default_ext_for_format(to_format or "")
            output_path = os.path.join(output_path, stem + ext)
        # Ensure parent directory exists (e.g. default ~/Flexiconv)
        parent_dir = os.path.dirname(output_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

    if progress_callback:
        progress_callback(0, 1, "Detecting format...")

    if cancel_check and cancel_check():
        raise CancelError("Conversion cancelled")

    in_fmt_name = from_format or path_to_input_format(input_path)
    out_fmt_name = to_format or path_to_output_format(output_path)
    if not in_fmt_name:
        return ConvertResult(success=False, error_message="Could not detect input format; use from_format.")
    if not out_fmt_name:
        return ConvertResult(success=False, error_message="Could not detect output format; use to_format.")

    out_fmt = registry.get_output(out_fmt_name)
    if out_fmt is None:
        if registry.get_input(out_fmt_name) is not None:
            return ConvertResult(success=False, error_message=f"Output format '{out_fmt_name}' has no writer.")
        return ConvertResult(success=False, error_message=f"Unknown output format: {out_fmt_name}")

    in_fmt = registry.get_input(in_fmt_name)
    if in_fmt is None:
        return ConvertResult(success=False, error_message=f"Unknown input format: {in_fmt_name}")

    if os.path.isfile(output_path) and not opts.get("force", False):
        return ConvertResult(success=False, error_message=f"Refusing to overwrite: {output_path} (set force=True).")

    if progress_callback:
        progress_callback(0, 1, "Loading...")

    if cancel_check and cancel_check():
        raise CancelError("Conversion cancelled")

    loader_kwargs = {}
    if in_fmt_name == "txt":
        loader_kwargs["linebreaks"] = opts.get("linebreaks", "paragraph")
    if in_fmt_name == "hocr":
        loader_kwargs["split_punct"] = not opts.get("hocr_no_split_punct", False)
        loader_kwargs["hyphen_truncation"] = opts.get("hocr_hyphen_truncation", False)
    if in_fmt_name == "eaf":
        loader_kwargs["style"] = opts.get("eaf_style", "generic")
    if in_fmt_name == "vert":
        loader_kwargs["spacing_mode"] = opts.get("spacing_mode", "guess")
        loader_kwargs["split_on_doc"] = not opts.get("vert_no_doc_split", True)
    if opts.get("option") and in_fmt_name == "vert":
        for part in (opts["option"] or "").split(";"):
            part = part.strip()
            if not part or "=" not in part:
                continue
            key, val = part.split("=", 1)
            key, val = key.strip().lower(), val.strip()
            if key == "registry" and val:
                loader_kwargs["registry"] = val
            elif key in ("cols", "columns") and val:
                loader_kwargs["columns"] = [c.strip() for c in val.split(",") if c.strip()]

    try:
        try:
            doc = in_fmt.loader(path=input_path, **loader_kwargs)
        except TypeError:
            doc = in_fmt.loader(input_path, **loader_kwargs)
    except Exception as e:
        return ConvertResult(success=False, error_message=str(e), stderr_snippet=None)

    if progress_callback:
        progress_callback(1, 1, "Saving...")

    if cancel_check and cancel_check():
        raise CancelError("Conversion cancelled")

    saver_kwargs = {}
    if out_fmt_name == "teitok":
        saver_kwargs["source_path"] = input_path
        mime = detect_mime(input_path)
        if mime:
            doc.meta["source_mime"] = mime
        if opts.get("teitok_project"):
            saver_kwargs["teitok_project_root"] = opts["teitok_project"]
        if opts.get("copy_original"):
            saver_kwargs["copy_original_to_originals"] = True
        if opts.get("prettyprint"):
            saver_kwargs["prettyprint"] = True
        # Optional style stripping: --option styles=no (or styles=false/0/off)
        opt_raw = (opts.get("option") or "").strip()
        if opt_raw:
            for part in opt_raw.split(";"):
                part = part.strip()
                if not part or "=" not in part:
                    continue
                key, val = part.split("=", 1)
                key = key.strip().lower()
                val = val.strip().lower()
                if key == "styles":
                    if val in {"no", "0", "false", "off", "none"}:
                        saver_kwargs["strip_styles"] = True
    if out_fmt_name == "docx":
        saver_kwargs["source_path"] = input_path
    if out_fmt_name == "txt":
        saver_kwargs["linebreaks"] = opts.get("linebreaks", "paragraph")

    try:
        out_fmt.saver(doc, path=output_path, **saver_kwargs)
    except TypeError:
        out_fmt.saver(doc, output_path)
    except Exception as e:
        return ConvertResult(success=False, error_message=str(e), stderr_snippet=None)

    return ConvertResult(success=True)


def _expand_paths(paths: list[str], by_content: bool) -> list[str]:
    """Expand directories to file lists. by_content: use path_to_input_format; else *.xml."""
    from .mime import path_to_input_format
    out = []
    for x in paths:
        x_abs = os.path.abspath(os.path.normpath(x))
        if os.path.isdir(x_abs):
            for root, _dirs, files in os.walk(x_abs):
                for f in files:
                    full = os.path.join(root, f)
                    if by_content:
                        if path_to_input_format(full) is not None:
                            out.append(full)
                    elif f.lower().endswith(".xml"):
                        out.append(full)
        else:
            out.append(x_abs)
    return out


def _content_fingerprint_hash(path: str) -> Optional[str]:
    """Hash of convert-to-text content (any supported format)."""
    import hashlib
    fmt_name = path_to_input_format(path)
    if not fmt_name:
        return None
    in_fmt = registry.get_input(fmt_name)
    if not in_fmt or not getattr(in_fmt, "loader", None):
        return None
    loader_kwargs = {}
    if fmt_name == "txt":
        loader_kwargs["linebreaks"] = "paragraph"
    if fmt_name == "hocr":
        loader_kwargs["split_punct"] = True
    try:
        try:
            doc = in_fmt.loader(path=path, **loader_kwargs)
        except TypeError:
            doc = in_fmt.loader(path)
    except Exception:
        return None
    text = document_to_plain_text(doc)
    normalized = normalize_text_for_fingerprint(text)
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _normalized_text_for_path(path: str, by_content: bool) -> Optional[str]:
    if by_content:
        fmt_name = path_to_input_format(path)
        if not fmt_name:
            return None
        in_fmt = registry.get_input(fmt_name)
        if not in_fmt or not getattr(in_fmt, "loader", None):
            return None
        try:
            try:
                doc = in_fmt.loader(path=path, **loader_kwargs)
            except TypeError:
                doc = in_fmt.loader(path)
        except Exception:
            return None
        text = document_to_plain_text(doc)
        return normalize_text_for_fingerprint(text) or None
    try:
        return teitok_text_fingerprint(path)
    except Exception:
        return None


def run_duplicates_scan(
    paths: list[str],
    by_content: bool = False,
    progress_callback: Optional[ProgressCallback] = None,
    cancel_check: Optional[CancelCheck] = None,
) -> DuplicateGroups:
    """Scan paths (directories expanded) and return duplicate groups. No index file."""
    _ensure_formats()
    expanded = _expand_paths(paths, by_content)
    total = len(expanded)
    if total == 0:
        return []

    if by_content:
        hash_to_paths = {}
        for i, path in enumerate(expanded):
            if cancel_check and cancel_check():
                raise CancelError("Scan cancelled")
            if progress_callback:
                progress_callback(i, total, f"Scanning {os.path.basename(path)}")
            h = _content_fingerprint_hash(path)
            if h is not None:
                hash_to_paths.setdefault(h, []).append(path)
        return [g for g in hash_to_paths.values() if len(g) > 1]
    else:
        def iter_with_progress():
            for i, path in enumerate(expanded):
                if cancel_check and cancel_check():
                    raise CancelError("Scan cancelled")
                if progress_callback:
                    progress_callback(i, total, f"Scanning {os.path.basename(path)}")
                yield path
        return find_duplicate_teitok_files(iter_with_progress())


@dataclass
class IndexResult:
    """Result of building/updating the deduplication index."""
    indexed: int = 0
    skipped: int = 0
    groups: DuplicateGroups = field(default_factory=list)
    error: Optional[str] = None


def _path_relative_to_base(path: str, base: Optional[str]) -> str:
    if base:
        try:
            rel = os.path.relpath(os.path.abspath(path), os.path.abspath(base))
            return rel.replace(os.sep, "/")
        except ValueError:
            pass
    return os.path.basename(path)


def _common_base(paths: list[str]) -> Optional[str]:
    if not paths:
        return None
    try:
        abs_paths = [os.path.abspath(p) for p in paths]
        if len(abs_paths) == 1:
            return os.path.dirname(abs_paths[0])
        return os.path.commonpath(abs_paths)
    except (ValueError, TypeError):
        return None


def run_duplicates_index(
    paths: list[str],
    index_path: str,
    by_content: bool = False,
    incremental: bool = False,
    near_identical: bool = False,
    threshold: float = 0.8,
    progress_callback: Optional[ProgressCallback] = None,
    cancel_check: Optional[CancelCheck] = None,
) -> IndexResult:
    """Build or update SQLite index; return summary (indexed, skipped, groups)."""
    _ensure_formats()
    expanded = sorted(_expand_paths(paths, by_content))
    if not expanded:
        return IndexResult(error="No files to index")

    base = _common_base(expanded)
    index_path = os.path.abspath(os.path.normpath(index_path))
    parent = os.path.dirname(index_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    conn = sqlite3.connect(index_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS dedup_index (hash TEXT NOT NULL, filename TEXT NOT NULL, PRIMARY KEY (hash, filename))"
        )
        if incremental:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS dedup_meta (path TEXT PRIMARY KEY, mtime REAL NOT NULL, size INTEGER NOT NULL, hash TEXT NOT NULL)"
            )
        else:
            conn.execute("DELETE FROM dedup_index")
        if near_identical:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS near_dup_sigs (path TEXT PRIMARY KEY, mtime REAL NOT NULL, size INTEGER NOT NULL, sig BLOB NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS near_dup_lsh (band_id INTEGER NOT NULL, bucket TEXT NOT NULL, path TEXT NOT NULL, PRIMARY KEY (band_id, bucket, path))"
            )
            if not incremental:
                conn.execute("DELETE FROM near_dup_sigs")
                conn.execute("DELETE FROM near_dup_lsh")
        conn.commit()
    except Exception as e:
        conn.close()
        return IndexResult(error=str(e))

    hash_to_files = {}
    current_rels = set()
    total = len(expanded)
    indexed = 0
    skipped = 0

    for i, path in enumerate(expanded):
        if cancel_check and cancel_check():
            conn.close()
            raise CancelError("Index build cancelled")
        if progress_callback:
            progress_callback(i, total, f"Indexing {os.path.basename(path)}")

        rel = _path_relative_to_base(path, base)
        current_rels.add(rel)
        mtime = size = None
        try:
            mtime = os.path.getmtime(path)
            size = os.path.getsize(path)
        except OSError:
            pass

        if incremental and mtime is not None and size is not None:
            row = conn.execute("SELECT mtime, size, hash FROM dedup_meta WHERE path = ?", (rel,)).fetchone()
            if row is not None and row[0] == mtime and row[1] == size:
                hash_to_files.setdefault(row[2], []).append(rel)
                skipped += 1
                continue

        h = _content_fingerprint_hash(path) if by_content else teitok_text_fingerprint_hash(path)
        try:
            conn.execute("DELETE FROM dedup_index WHERE filename = ?", (rel,))
            conn.execute("DELETE FROM dedup_meta WHERE path = ?", (rel,))
        except Exception:
            pass
        if h is not None:
            try:
                conn.execute("INSERT INTO dedup_index (hash, filename) VALUES (?, ?)", (h, rel))
                if mtime is not None and size is not None:
                    conn.execute(
                        "INSERT OR REPLACE INTO dedup_meta (path, mtime, size, hash) VALUES (?, ?, ?, ?)",
                        (rel, mtime, size, h),
                    )
                hash_to_files.setdefault(h, []).append(rel)
                indexed += 1
            except Exception:
                pass

        if near_identical:
            text = _normalized_text_for_path(path, by_content)
            if text:
                shingles = shingle_text(text)
                if shingles:
                    sig = minhash_signature(shingles)
                    try:
                        conn.execute("DELETE FROM near_dup_sigs WHERE path = ?", (rel,))
                        conn.execute("DELETE FROM near_dup_lsh WHERE path = ?", (rel,))
                        conn.execute(
                            "INSERT OR REPLACE INTO near_dup_sigs (path, mtime, size, sig) VALUES (?, ?, ?, ?)",
                            (rel, mtime or 0, size or 0, signature_to_blob(sig)),
                        )
                        for band_id, bucket in lsh_bands(sig):
                            conn.execute("INSERT OR REPLACE INTO near_dup_lsh (band_id, bucket, path) VALUES (?, ?, ?)", (band_id, bucket, rel))
                    except Exception:
                        pass

    if incremental:
        try:
            meta_paths = set(row[0] for row in conn.execute("SELECT path FROM dedup_meta").fetchall())
            to_remove = meta_paths - current_rels
            for p in to_remove:
                conn.execute("DELETE FROM dedup_meta WHERE path = ?", (p,))
                conn.execute("DELETE FROM dedup_index WHERE filename = ?", (p,))
                if near_identical:
                    conn.execute("DELETE FROM near_dup_sigs WHERE path = ?", (p,))
                    conn.execute("DELETE FROM near_dup_lsh WHERE path = ?", (p,))
        except Exception:
            pass

    conn.commit()
    conn.close()

    groups = [sorted(files) for files in hash_to_files.values() if len(files) > 1]
    return IndexResult(indexed=indexed, skipped=skipped, groups=groups)


def run_duplicates_list(
    index_path: str,
    near_identical: bool = False,
    threshold: float = 0.8,
) -> DuplicateGroups:
    """Read duplicate groups from an existing SQLite index."""
    _ensure_formats()
    index_path = os.path.abspath(os.path.normpath(index_path))
    if not os.path.isfile(index_path):
        return []

    conn = sqlite3.connect(index_path)
    try:
        if near_identical:
            try:
                rows = conn.execute("SELECT path, sig FROM near_dup_sigs").fetchall()
            except sqlite3.OperationalError:
                conn.close()
                return []
            if not rows:
                conn.close()
                return []
            path_to_sig = {}
            for path, sig_blob in rows:
                if path and sig_blob:
                    path_to_sig[path] = signature_from_blob(sig_blob)
            buckets = {}
            for band_id, bucket, path in conn.execute("SELECT band_id, bucket, path FROM near_dup_lsh").fetchall():
                key = (band_id, bucket)
                buckets.setdefault(key, set()).add(path)
            candidate_pairs = set()
            for path, sig in path_to_sig.items():
                for band_id, bucket in lsh_bands(sig):
                    key = (band_id, bucket)
                    for other in buckets.get(key, set()):
                        if other != path:
                            candidate_pairs.add((min(path, other), max(path, other)))
            uf = {}

            def find(x):
                if x not in uf:
                    uf[x] = x
                if uf[x] != x:
                    uf[x] = find(uf[x])
                return uf[x]

            def union(x, y):
                uf[find(x)] = find(y)

            for p, q in candidate_pairs:
                if signature_similarity(path_to_sig[p], path_to_sig[q]) >= threshold:
                    union(p, q)
            roots = {}
            for path in path_to_sig:
                r = find(path)
                roots.setdefault(r, []).append(path)
            groups = [sorted(comp) for comp in roots.values() if len(comp) >= 2]
            conn.close()
            return groups

        cur = conn.execute("SELECT hash, filename FROM dedup_index")
        hash_to_files = {}
        for row in cur.fetchall():
            h, fn = (row[0] or "").strip(), (row[1] or "").strip()
            if h and fn:
                hash_to_files.setdefault(h, []).append(fn)
        conn.close()
        return [sorted(files) for files in hash_to_files.values() if len(files) > 1]
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        return []
