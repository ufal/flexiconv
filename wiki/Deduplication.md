# Deduplication detection

Flexiconv can find **exact** and **near-identical** duplicates among documents by comparing normalized text. This is useful for corpus cleanup, avoiding re-ingestion of the same content, and detecting conversions of the same source (e.g. RTF and DOCX of the same text).

## Command

```bash
flexiconv duplicates [PATH ...] [OPTIONS]
```

- **No paths** (inside a TEITOK project): uses `xmlfiles/` and reads the default index `tmp/deduplication.sqlite` if present.
- **Paths**: scan the given files or directories. With `--by-content`, all supported formats in those trees are included (not only `.xml`).

Use `flexiconv duplicates --help` for all options.

## Exact duplicate detection

Two documents are **exact duplicates** when their **normalized text** is identical:

- **TEITOK XML (default):** Space-normalized inner text of the `<text>` element. Spaces inside or outside inline elements (e.g. `<hi>`) are normalized so that layout differences do not change the fingerprint.
- **Any format (`--by-content`):** The same text that “convert to text” would produce: load the file into the pivot document, extract plain text (structure/sentences or body paragraphs), collapse runs of whitespace to a single space. So an RTF and a DOCX of the same content get the same hash.

Hashing is SHA-256 of that normalized string. **Near-identical** texts (one word different, small typo) get a different hash and are **not** grouped as exact duplicates unless you use near-identical detection (below).

## Index (SQLite or text)

With **`--index`**, Flexiconv can write an index for fast lookup and for use by tools like EasyCorp:

- **SQLite** (default in a TEITOK project, or with `--output path/to/deduplication.sqlite`): Tables `dedup_index(hash, filename)` and, for incremental updates, `dedup_meta(path, mtime, size, hash)`. Optional tables for near-identical: `near_dup_sigs(path, mtime, size, sig)` and `near_dup_lsh(band_id, bucket, path)`.
- **Text file:** With EasyCorp’s text backend, the index is `logs/easycorp_hashes.txt` (lines `hash\tfilename`).

Paths in the index are stored **relative** to the common scan root (e.g. `subfolder/doc.xml`) so that same-name files in different folders stay distinct.

### Listing from the index

```bash
# List exact duplicate groups from the default index (TEITOK project)
flexiconv duplicates

# From an explicit index file
flexiconv duplicates --from-index tmp/deduplication.sqlite

# JSON output (e.g. for scripts or TEITOK)
flexiconv duplicates --from-index tmp/deduplication.sqlite --json --quiet
```

When you omit `--from-index` inside a TEITOK project and do not pass paths, Flexiconv uses `tmp/deduplication.sqlite` by default.

### Incremental index (`--incremental`)

For large corpora, re-hashing every file on each run is expensive. With **`--incremental`** (and a SQLite index):

- Files whose **mtime** and **size** are unchanged are skipped (no read, no hash).
- New or changed files are hashed and the index is updated.
- Paths that no longer exist in the scan are removed from the index.

First run builds the full index and fills the meta table; later runs only process new or changed files. Example:

```bash
flexiconv duplicates --index --output /path/to/deduplication.sqlite --incremental
```

## Cross-format comparison (`--by-content`)

To compare **different formats** (e.g. RTF, DOCX, XML, TXT) as the same content:

- Use **`--by-content`**: each file is loaded, converted to plain text (same pipeline as “convert to text”), normalized, and hashed. Any supported input format in the scanned paths is included; directory scans are not limited to `.xml`.
- Build an index over mixed folders, then list duplicates from that index.

Example:

```bash
# One-off: list duplicate groups in tmp/ and examples/ (all supported formats)
flexiconv duplicates tmp examples --by-content

# Build index for later use
flexiconv duplicates tmp examples --by-content --index --output tmp/deduplication.sqlite
```

## Near-identical detection (`--near-identical`)

Documents that are **almost** the same (e.g. a few words different, or reformatting) can be grouped using **MinHash** and **LSH**:

- **Build:** With `--index` and `--near-identical`, Flexiconv stores a MinHash signature (word-shingle based) and LSH bands in the same SQLite file. Same text source as exact hashing (TEITOK `<text>` or convert-to-text with `--by-content`).
- **List:** `flexiconv duplicates --from-index path/to/index.sqlite --near-identical` finds candidate pairs via LSH, then verifies similarity from the stored signatures and clusters them (union-find). Only groups with similarity **≥ threshold** are reported.
- **Threshold:** `--threshold F` (default **0.8**, range 0.0–1.0). Higher = stricter (more similar); lower = more pairs, including looser matches.

Example:

```bash
# Build index with near-identical signatures
flexiconv duplicates --index --output tmp/deduplication.sqlite --near-identical

# List near-identical groups (default threshold 0.8)
flexiconv duplicates --from-index tmp/deduplication.sqlite --near-identical

# Looser threshold, JSON output
flexiconv duplicates --from-index tmp/deduplication.sqlite --near-identical --threshold 0.5 --json --quiet
```

Near-identical mode **requires** a SQLite index (no text-file backend).

## Progress and machine-readable output

- **Progress bar:** When scanning or building the index, Flexiconv prints progress to **stderr** (e.g. `files: 123/456`), so **stdout** stays clean for piping or parsing.
- **`--quiet` / `-q`:** Disables the progress bar. Use when you parse stdout (e.g. JSON in TEITOK or other scripts).
- **`--json`:** Output is a JSON array of duplicate groups (arrays of paths). Combine with `--quiet` when parsing programmatically.

## Summary

| Goal | Command / options |
|------|-------------------|
| List exact duplicates (default index) | `flexiconv duplicates` |
| List from custom index | `flexiconv duplicates --from-index path.sqlite` |
| Scan folders, any format | `flexiconv duplicates path1 path2 --by-content` |
| Build/update index | `flexiconv duplicates --index [--output path.sqlite]` |
| Fast updates on large corpora | Add `--incremental` with SQLite index |
| Near-identical groups | `--near-identical` when building and when listing from index; use `--threshold` to tune |
| Script-friendly output | `--json --quiet` |
