# HTML (`html`)

## Format

- **Full format name**: HTML (HyperText Markup Language); W3C standard.
- **Format specification**: [HTML Living Standard](https://html.spec.whatwg.org/) (WHATWG) / [W3C HTML](https://www.w3.org/TR/html52/). Flexiconv parses HTML to extract structure and text for TEITOK TEI.

## Origin and purpose

- **Origin**: HTML / XHTML documents from the web or other sources.
- **Role in Flexiconv**: import HTML as structural text (paragraphs, headings, lists) that can be further processed or converted.

Handled by `flexiconv/io/html.py`.

## Minimal example

```html
<html>
  <body>
    <h1>Title</h1>
    <p>The first paragraph.</p>
    <p>The second paragraph.</p>
  </body>
</html>
```

## Conversion semantics

- **Reading (`html` input)**:
  - Block-level elements (`<p>`, headings, list items, blockquotes, divs) become `structure` nodes and TEI `<p>/<head>/<list>` etc.
  - Text content is imported as plain text paragraphs/headings; tokenisation and sentence splitting are intentionally left to downstream tools (e.g. flexipipe).
  - Inline markup (e.g. `<em>`, `<strong>`) is currently ignored by the HTML loader; use downstream processing to reconstruct inline annotation if needed.

- **Writing (`html` output)**:
  - The `html` output format writes a **simple HTML view**:
    - Sentences or paragraphs become `<p>` elements.
    - When available, inline styles/renditions can be represented with spans.
  - Intended for quick inspection rather than full-fidelity round-tripping.

