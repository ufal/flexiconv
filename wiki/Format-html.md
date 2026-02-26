# HTML (`html`)

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
  - Block-level elements (`<p>`, headings, list items) become `structure` nodes and TEI `<p>/<head>/<list>` etc.
  - Text content is tokenised into `<tok>` and grouped into sentences where appropriate.
  - Inline markup (e.g. `<em>`, `<strong>`) can be reflected as TEI inline elements or span layers.

- **Writing (`html` output)**:
  - The `html` output format writes a **simple HTML view**:
    - Sentences or paragraphs become `<p>` elements.
    - When available, inline styles/renditions can be represented with spans.
  - Intended for quick inspection rather than full-fidelity round-tripping.

