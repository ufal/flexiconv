# Word DOCX (`docx`)

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
  - Not currently a primary goal; Flexiconv focuses on **importing** DOCX into TEITOK TEI and the pivot model.

