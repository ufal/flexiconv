# Generic TEI P5 (`tei`)

## Tool and format

- **Format**: [TEI](https://tei-c.org/) (Text Encoding Initiative) P5 guidelines; generic XML for scholarly text.
- **Full format name**: TEI P5 (XML); elements such as `text`, `body`, `p`, `s`, `w`, `pc`. Flexiconv also accepts `<tok>` when present in TEITOK-like TEI, but that is not part of core TEI P5.
- **Format specification**: [TEI P5 Guidelines](https://tei-c.org/release/doc/tei-p5-doc/en/html/). Flexiconv uses a simple mapping (e.g. `<w>` → tokens, `<s>` → sentences); no full TEI profile.

## Origin and purpose

- **Origin**: TEI P5 (Text Encoding Initiative) guidelines.
- **Role in Flexiconv**: baseline TEI import/export for non-TEITOK TEI documents.

Handled primarily by `flexiconv/io/tei_p5.py`.

## Minimal example

```xml
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <text>
    <body>
      <p>
        <s xml:id="s1">
          <w xml:id="w1">The</w>
          <w xml:id="w2">cat</w>
          <w xml:id="w3">sat</w>
          <pc xml:id="w4">.</pc>
        </s>
      </p>
    </body>
  </text>
</TEI>
```

## Conversion semantics

- **Reading (`tei` input)**:
  - Tokens: `<w>` (and, where appropriate, `<pc>`) become `tokens` with `tokid` based on `xml:id`.
  - Sentences: `<s>` become `sentences` with spans over the corresponding tokens.
  - Structure: paragraph and division elements (`<p>`, `<div>`, etc.) become nodes in a `structure` layer.
  - The TEI header is preserved as metadata and can be passed through to TEITOK output.

- **Writing (`tei` output)**:
  - The pivot model (tokens and sentences) is serialized as **simple TEI P5**:
    - Tokens → `<w>` elements.
    - Sentences → `<s>` surrounding tokens.
    - Structure (when available) → `<p>`/`<div>` blocks.
  - This is intended as an interoperable “generic TEI” view, not a TEITOK-specific TEI profile.

