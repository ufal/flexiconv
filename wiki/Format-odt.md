# OpenDocument Text (`odt`)

## Format

- **Full format name**: OpenDocument Text (ODT); part of the OASIS OpenDocument standard.
- **Format specification**: [OpenDocument v1.x](https://www.oasis-open.org/standards#opendocumentv1.3) (OASIS). Flexiconv uses [`odfpy`](https://pypi.org/project/odfpy/) to read `.odt` files.

## Origin and purpose

- **Origin**: ODT documents from LibreOffice, OpenOffice, and other OpenDocument-compatible word processors.
- **Role in Flexiconv**: import ODT as plain paragraphs/headings in TEITOK-style TEI, suitable for corpus ingestion or further processing. Export back to ODT is **not** supported.

Handled by `flexiconv/io/odt.py` (optional extra: `flexiconv[odt]`).

## Minimal example (logical text)

An ODT document with a title and two paragraphs:

> Title line  
> First paragraph.  
> Second paragraph.

is mapped to TEI roughly as:

```xml
<TEI>
  <text id="sample">
    <body>
      <p rend="heading">Title line</p>
      <p>First paragraph.</p>
      <p>Second paragraph.</p>
    </body>
  </text>
</TEI>
```

## Conversion semantics

- **Reading (`odt` input)**:
  - Flexiconv reads the `.odt` via odfpy and walks `text:P` and `text:H` elements in document order.
  - Each non-empty paragraph/heading becomes a TEI `<p>` under `<body>`:
    - Headings are marked with `rend="heading"`.
  - Basic document metadata (title, creator, language) is copied into the TEI header when present.
  - The resulting TEI tree is stored in `meta['_teitok_tei_root']` so `-t teitok` reuses it directly.
  - Inline styling and more advanced layout are currently ignored; content is treated as plain text paragraphs.

- **Writing (`odt` output)**:
  - Not implemented; conversion is one-way from ODT to TEI / the pivot model.

