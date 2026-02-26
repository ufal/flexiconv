# RTF (`rtf`)

## Format

- **Full format name**: Rich Text Format (RTF); document format used by many word processors.
- **Format specification**: [RTF 1.9 specification](https://www.microsoft.com/en-us/download/details.aspx?id=10725) (Microsoft); binary/text hybrid with control words. Flexiconv extracts plain text for conversion.

## Origin and purpose

- **Origin**: Rich Text Format (RTF), a document format used by many word processors.
- **Role in Flexiconv**: import RTF documents as plain text with basic paragraph/sentence segmentation.

Handled by `flexiconv/io/rtf.py` with optional external dependencies.

## Minimal example (logical text)

RTF itself is verbose; Flexiconv focuses on the extracted text, for example:

```text
This is a first sentence.
This is a second sentence.
```

## Conversion semantics

- **Reading (`rtf` input)**:
  - Flexiconv uses an RTF reader to extract plain text.
  - Line breaks and/or punctuation are used to derive sentences (configurable via `--linebreaks` when writing `txt`).
  - Resulting text becomes:
    - `tokens` via whitespace tokenisation.
    - `sentences` via simple segmentation.
    - Optional `structure` layer approximating paragraphs.

- **Writing (`rtf` output)**:
  - Flexiconv can write a **text-only RTF**:
    - Each sentence becomes a separate paragraph.
    - Formatting information from the original RTF is not preserved (this is a convenience exporter).

