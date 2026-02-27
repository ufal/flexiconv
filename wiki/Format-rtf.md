# RTF (`rtf`)

## Format

- **Full format name**: Rich Text Format (RTF); document format used by many word processors.
- **Format specification**: [RTF 1.9 specification](https://www.microsoft.com/en-us/download/details.aspx?id=10725) (Microsoft); binary/text hybrid with control words. Flexiconv parses text content and basic inline formatting.

## Origin and purpose

- **Origin**: Rich Text Format (RTF), a document format used by many word processors.
- **Role in Flexiconv**: import RTF documents as rich text with paragraphs and basic inline formatting (bold/italic) that can be preserved in TEI / TEITOK.

Handled by `flexiconv/io/rtf.py` with optional external dependencies.

## Minimal example (logical text)

RTF itself is verbose; Flexiconv focuses on the extracted structure and inline styling, for example an RTF fragment like:

```rtf
{\rtf1\ansi This is \b bold\b0  and \i italic\i0 .}\par
```

maps to TEI content such as:

```xml
<p>This is <hi rend="bold">bold</hi> and <hi rend="italic">italic</hi>.</p>
```

## Conversion semantics

- **Reading (`rtf` input)**:
  - Flexiconv parses the RTF to:
    - `meta['rtf_source']`: original RTF;
    - `meta['plain_text']`: plain-text representation;
    - a `structure` layer with paragraph nodes anchored by character offsets;
    - a `rendition` layer with character spans for basic inline formatting (currently bold/italic).
  - A TEITOK-style TEI tree with `<p>` and inline `<hi rend=\"...\">` is built from `structure`+`rendition` and stored in `meta['_teitok_tei_root']`, so `-t teitok` can reuse it directly.
  - Tokenisation and sentence segmentation are intentionally left to flexipipe or other NLP tools.

- **Writing (`rtf` output)**:
  - If `meta['rtf_source']` is present, Flexiconv writes it back verbatim.
  - Otherwise, it can write a **text-only RTF** from the `tokens`/`sentences` layers:
    - Each sentence becomes a separate `\par` paragraph.
    - Inline formatting is not reconstructed in this fallback mode.

