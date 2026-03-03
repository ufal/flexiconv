# FLEx FLExText interlinear (`flex`)

## Tool and format

- **Tool**: [FieldWorks Language Explorer (FLEx)](https://software.sil.org/fieldworks/), SIL International software for language documentation and lexicon/interlinear text.
- **Full format name**: FLExText — XML export format for interlinear glossed text from FLEx (also used by SayMore and other tools). File extension `.flextext`; media type `text/xml`.
- **Format specification**: Described in [FLEx documentation](https://software.sil.org/fieldworks/) and [Technical Notes on FLEx Text Interlinear](https://downloads.languagetechnology.org/fieldworks/Documentation/Technical%20Notes%20on%20FLEx%20Text%20Interlinear.pdf). [CLARIN SIS](https://standards.clarin.eu/sis/views/view-format.xq?id=fFLExText): fFLExText.

## Origin and purpose

- **Origin**: FLEx exports interlinear texts as XML (FLExText) for re-import, ELAN compatibility, or conversion to other formats (e.g. XLingPaper).
- **Role in Flexiconv**: import FLExText files into TEITOK-style TEI with `<s>`, `<tok>`, and `<m>` (morpheme) for word-level and morpheme-level annotations.

Handled by `flexiconv/io/flex.py`.

## Minimal example

```xml
<interlinear-text>
  <paragraph>
    <phrase>
      <item type="gls" lang="en">The cat sat on the mat.</item>
      <word><item type="txt" lang="en">the</item><item type="gls" lang="en">DET</item></word>
      <word><item type="txt" lang="en">cat</item><item type="gls" lang="en">N</item></word>
    </phrase>
  </paragraph>
</interlinear-text>
```

Flexiconv maps each `phrase` → `<s>`, each `word` → `<tok>`, and phrase-level/item `type="gls"` (free translation) → `@gloss` on `<s>`. Word-level and morph-level `item` elements (e.g. `gls`, `pos`, `cf`, `msa`) become attributes on `<m>` (morpheme) children of `<tok>`.

## Conversion semantics

- **Reading (`flex` input)**:
  - Root must be `<interlinear-text>`. Structure: optional `<paragraph>` containing `<phrase>` elements; each phrase contains `<word>` elements and optional phrase-level `<item>` (e.g. type `gls` or `ft` for free translation).
  - Each `<word>` has `<item type="txt">` for the baseline form and optionally `<item type="gls">`, `<item type="pos">`, etc. Optional `<morph>` children with their own `<item>` elements (e.g. `txt`, `cf`, `gls`, `msa`).
  - One phrase → one `<s>` with `@original`, `@lang`, and optional `@gloss`. One word → one `<tok>`; word/morph items → token text and `<m>` morpheme children with attributes (e.g. `gls`, `cf`, `msa`).
  - Tokens and sentences layers are populated from the TEI for consistency with other formats.

- **Writing (`flex` output)**:
  - Not implemented; conversion is one-way to TEITOK TEI.

## Detection

- Input format is inferred from extension `.flextext` or from XML content: root element `<interlinear-text>` (so FLEx exports saved as `.xml` are also recognised).
