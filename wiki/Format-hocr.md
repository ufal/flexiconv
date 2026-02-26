# hOCR (`hocr`)

## Tool and format

- **Format name**: hOCR (OCR output in HTML); open standard for embedding OCR word/line bounding boxes in HTML via `class` and `title` attributes.
- **Format specification**: [hOCR 1.2 specification](https://kba.github.io/hocr-spec/1.2/); typically served as HTML with `ocr_page`, `ocr_line`, `ocrx_word` classes.

## Origin and purpose

- **Origin**: hOCR is an open standard for representing OCR output in HTML. Word and line bounding boxes are encoded in `class` and `title` attributes (e.g. `ocrx_word`, `bbox`).
- **Role in Flexiconv**: import hOCR HTML into TEITOK-style TEI with `<tok>` elements carrying `bbox` and optional facsimile/surface/zone structure for page layout.

Handled by `flexiconv/io/hocr.py`.

## Minimal example (conceptual)

HTML with elements like:

```html
<span class="ocr_line" title="bbox 10 20 100 30">
  <span class="ocrx_word" title="bbox 10 20 40 28">Hello</span>
  <span class="ocrx_word" title="bbox 45 20 100 28">world</span>
</span>
```

Flexiconv maps these to TEI `<tok bbox="...">` and optional `<lb/>`, zones, and facsimile references.

## Conversion semantics

- **Reading (`hocr` input)**:
  - `ocrx_word` spans → `<tok>` with `bbox` (xmin ymin xmax ymax). Page/line structure → zones and optional `<facsimile>`.
  - By default, punctuation is split from words (e.g. `word.` → two tokens). Use `--hocr-no-split-punct` to keep punctuation attached.
  - Hyphenation at line breaks can be merged with `--hocr-hyphen-truncation` (word- at end of line + next line’s first word → one `<tok><gtok><lb/><gtok></tok>`).

- **Writing (`hocr` output)**:
  - TEITOK TEI with bbox/facsimile can be exported back to hOCR for round-trip. Use `-t hocr`.
