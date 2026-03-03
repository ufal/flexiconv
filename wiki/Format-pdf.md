# PDF (`pdf`)

## Format

- **Full format name**: Portable Document Format (PDF); page-oriented document format with text, vector graphics, and images.
- **Format specification**: ISO 32000 (PDF); Flexiconv uses [`pdfminer.six`](https://github.com/pdfminer/pdfminer.six) to extract text and layout information.

## Origin and purpose

- **Origin**: PDF documents from word processors, typesetting systems, or scanners (after OCR).
- **Role in Flexiconv**: import PDF as TEITOK-style TEI with paragraphs, headings, lists, simple tables, inline styling, and optional images, suitable for corpus ingestion or further processing. Export back to PDF is **not** supported.

Handled by `flexiconv/io/pdf.py` (optional extra: `flexiconv[pdf]`).

## Conversion semantics

- **Reading (`pdf` input)**:
  - Flexiconv uses pdfminer to walk text lines and basic layout:
    - Text blocks and lines become TEI `<p>` elements under `<div type="page">`.
    - Bullet-like markers (•, -, –, `\u00B7`) at line start become `<list><item>…</item></list>`.
    - Simple tables are detected geometrically (aligned text in multiple columns on the same line) and mapped to `<table><row><cell><p>…</p></cell></row></table>`.
    - Inline font information (size, bold, italic) becomes `<hi style="…">` spans.
    - A basic `<head>` is inferred from the first large-font line on the first page when possible.
  - Extracted images are written to a directory (by default a temporary one) and referenced from `<figure><graphic url="…">`; the directory path is stored in `meta['_teitok_image_dir']`.
  - The resulting TEI tree (with `<text>/<body>/<div type="page">`) is stored in `meta['_teitok_tei_root']` so `-t teitok` reuses it directly; `meta['plain_text']` and a simple `structure` layer are also filled for plain-text style outputs.

- **Options (`--option` for `pdf`)**:
  - `pdf=smart` (default): enable layout-aware heuristics:
    - use font-size and bullets to detect headings and lists,
    - group table rows/columns based on geometry,
    - emit `<hi style="…">` spans for inline styling.
  - `pdf=simple` / `pdf=nosmart` / `pdf=0`: simpler interpretation:
    - paragraphs per text block/line,
    - minimal heuristics; fewer lists/tables/headings inferred.
  - `tei=clean` / `tei=noclean`:
    - `tei=clean` (default) tidies spaces around `<hi>` spans so trailing spaces are moved into `tail` (better pretty-printing).
    - `tei=noclean` keeps `<hi>` text exactly as pdfminer delivered it.
  - Options are passed via `--option`, for example:
    - `--option "pdf=simple"` (disable smart heuristics),
    - `--option "pdf=smart;tei=noclean"` (smart layout, no whitespace cleanup).

- **Writing (`pdf` output)**:
  - Not implemented; conversion is one-way from PDF to TEI / the pivot model.

