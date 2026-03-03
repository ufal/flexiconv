# EPUB (`epub`)

## Format

- **Full format name**: EPUB (electronic publication); ZIP-based container for XHTML content, CSS, and resources.
- **Format specification**: [EPUB 2/3](https://www.w3.org/publishing/epub3/epub-packages.html). Flexiconv reads the package document (OPF) and spine, then processes the referenced XHTML content files.

## Origin and purpose

- **Origin**: EPUB ebooks from text editors, conversion tools, or publishing workflows.
- **Role in Flexiconv**: import EPUB as TEITOK-style TEI with one `<div type="chapter">` per spine item and embedded original XHTML for reference. Export back to EPUB is **not** supported.

Handled by `flexiconv/io/epub.py` (optional extra: `flexiconv[pdf]` also pulls in pdfminer; EPUB itself has no extra dependencies beyond lxml).

## Conversion semantics

- **Reading (`epub` input)**:
  - Flexiconv opens the EPUB as a ZIP and processes:
    - `META-INF/container.xml` to locate the root OPF package.
    - the OPF manifest and spine to determine content documents and reading order.
  - For each spine item whose media type is XHTML/HTML:
    - The corresponding `.xhtml` is parsed with `lxml.html`.
    - Block-level elements are mapped to TEI under `<body>`:
      - `<h1>`…`<h6>` → `<head>`.
      - `<p>`/`<div>` → `<p>`.
      - `<ul>`/`<ol>` + `<li>` → `<list><item>…</item></list>`.
      - Simple `<table>`/`<tr>`/`<td>` → `<table><row><cell><p>…</p></cell></row></table>`.
    - Each spine document becomes a `<div type="chapter" n="…"
      source="ch.xhtml">…</div>` under TEI `<body>`.
  - Inline markup:
    - `<strong>`/`<b>` → `<hi style="font-weight: bold;">…</hi>`.
    - `<em>`/`<i>` → `<hi style="font-style: italic;">…</hi>`.
    - `<a href="…">…</a>` → `<ref target="…">…</ref>`.
    - `<img>` elements can be turned into `<figure><graphic url="…"/></figure>` when images are extracted.
  - Images referenced in the manifest are optionally copied to a directory; its path is stored in `meta['_teitok_image_dir']`.
  - The resulting TEI tree is stored in `meta['_teitok_tei_root']` so `-t teitok` reuses it directly.

- **Embedding original XHTML**:
  - For each spine document, the raw XHTML source is embedded in `<text><back>` as:
    - `<sourceDoc n="ch.xhtml" type="application/xhtml+xml"><![CDATA[...]]></sourceDoc>`.
  - This makes the TEI file self-contained: it holds both the TEI view and the original EPUB XHTML.

- **Writing (`epub` output)**:
  - Not implemented; conversion is one-way from EPUB to TEI / the pivot model.

