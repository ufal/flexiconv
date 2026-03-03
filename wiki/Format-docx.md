# Word DOCX (`docx`)

## Tool and format

- **Tool**: Microsoft Word (and compatible applications).
- **Full format name**: Office Open XML WordprocessingML (DOCX); ZIP package of XML parts.
- **Format specification**: [ECMA-376](https://www.ecma-international.org/publications-and-standards/standards/ecma-376/) / ISO/IEC 29500; file extension `.docx`.

## Origin and purpose

- **Origin**: Microsoft Word’s OOXML-based `.docx` format.
- **Role in Flexiconv**: import rich-text Word documents into TEITOK-style TEI with basic structure and, where possible, layout cues.

Handled by `flexiconv/io/docx.py`.

## Minimal example (logical structure)

Simplified view of what Flexiconv aims to reconstruct:

```xml
<TEI>
  <text id="doc1">
    <body>
      <div type="section">
        <head>Title from DOCX</head>
        <p>
          <s id="s-1">
            <tok>The</tok>
            <tok>first</tok>
            <tok>paragraph.</tok>
          </s>
        </p>
      </div>
    </body>
  </text>
</TEI>
```

## Conversion semantics

- **Reading (`docx` input)**:
  - Paragraphs, headings, lists, and tables are mapped to a `structure` layer and TEI `<div>/<p>/<head>` elements.
  - Text is tokenised into `<tok>` with basic sentence segmentation.
  - Hyperlinks, images, and footnotes are represented in TEI where feasible (details in the module).

- **Writing (`docx` output)**:
  - Supported as a **simple export** from TEI / the pivot:
    - `<head>` elements become Word headings (levels inferred from `@type` when present, e.g. `h2`, `h3`).
    - `<p>` and similar block elements become paragraphs.
    - `<list><item>` becomes bullet-style paragraphs (using the template’s “List Bullet” style when available).
    - `<table><row><cell>` becomes Word tables with plain-text cell content.
  - Inline markup (`<hi>`, `<m>`, etc.) is currently flattened to plain text; the focus is on structure, not rich styling.

## Round-tripping and layout

- Flexiconv is designed for **semantic/structural** conversion, not for pixel-perfect layout preservation.
- As a result, a round-trip like `DOCX → TEI → DOCX` will typically **not** be graphically identical to the original:
  - Paragraph and heading structure, lists, and tables are preserved where possible.
  - Exact spacing, fonts, and paragraph spacing are left to the user’s Word template and styles.
- This also means that DOCX exported from TEI may have different paragraph spacing than the original; Word’s default “Normal”/heading styles control visual gaps between paragraphs.

