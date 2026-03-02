# RTF (`rtf`)

## Format

- **Full format name**: Rich Text Format (RTF); document format used by many word processors.
- **Format specification**: [RTF 1.9 specification](https://www.microsoft.com/en-us/download/details.aspx?id=10725) (Microsoft); binary/text hybrid with control words. Flexiconv parses text content and basic inline formatting.

## Origin and purpose

- **Origin**: Rich Text Format (RTF), a document format used by many word processors.
- **Role in Flexiconv**: import RTF documents as rich text with paragraphs and basic inline formatting (bold/italic) that can be preserved in TEI / TEITOK.

Handled by `flexiconv/io/rtf.py` with a small built-in RTF parser (no external dependencies).

## Minimal example (logical text)

RTF itself is verbose; Flexiconv focuses on the extracted structure and inline styling, for example an RTF fragment like:

```rtf
{\rtf1\ansi This is \b bold\b0  and \i italic\i0 .}\par
```

maps to TEI content such as:

```xml
<p>This is <hi style="font-weight: bold;">bold</hi> and <hi style="font-style: italic;">italic</hi>.</p>
```

## Conversion semantics

- **Reading (`rtf` input)**:
  - Flexiconv parses RTF control words directly into a **TEITOK-style TEI tree**:
    - Paragraphs and headings become `<p>` and `<head>` (first large-font paragraph).
    - Bullet lists become `<list><item>…</item></list>`.
    - Simple tables (`\trowd`/`\cell`/`\row`) become `<table><row><cell><p>…</p></cell></row></table>`.
    - Inline bold/italic/underline/font-size become `<hi style=\"…\">` spans.
  - The TEI tree is stored in `meta['_teitok_tei_root']` so `-t teitok` reuses it verbatim; `meta['rtf_source']` keeps the original RTF for round-tripping.
  - Tokenisation and sentence segmentation are intentionally left to flexipipe or other NLP tools.

- **Writing (`rtf` output)**:
  - If `meta['rtf_source']` is present, Flexiconv writes it back verbatim.
  - Otherwise, generic TEI→RTF is not supported and an error is raised (no attempt is made to synthesise RTF from arbitrary TEI).

