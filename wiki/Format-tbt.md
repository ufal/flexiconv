# Toolbox interlinear (`tbt`)

## Tool and format

- **Tool**: [SIL Toolbox](https://www.sil.org/resources/software/toolbox) (formerly Shoebox), field linguistics software from SIL International.
- **Full format name**: Toolbox (or Shoebox) interlinear text format: plain text with backslash-prefixed field names (e.g. `\tx`, `\mb`, `\gl`) and blank-line-separated records.
- **Format specification**: Described in [Toolbox documentation](https://www.sil.org/resources/software/toolbox); no single formal schema; format is line-based. File extensions `.tbt`, `.tbtx`.

## Origin and purpose

- **Origin**: Toolbox (formerly Shoebox), used for interlinearised field linguistics. Data is in a text file with backslash-prefixed field names (e.g. `\tx`, `\mb`, `\gl`) and blank-line-separated records.
- **Role in Flexiconv**: import Toolbox files into TEITOK-style TEI with `<s>`, `<tok>`, and optional `<morph>` (or tier attributes) for morphological tiers.

Handled by `flexiconv/io/tbt.py`.

## Minimal example

```
\tx The cat sat .
\mb the cat sit .
\gl DET NOUN VERB .

\tx Another sentence .
\mb another sentence .
\gl DET NOUN PUNCT .
```

Flexiconv maps `\tx` to the main token line; other tiers (e.g. `\mb`, `\gl`) become morphological or attribute data on `<tok>` or `<morph>`.

## Conversion semantics

- **Reading (`tbt` input)**:
  - Records are separated by blank lines. `\tx` defines the primary token sequence; other fields (e.g. `\mb`, `\gl`, `\pos`) are mapped to token attributes or `<morph tier="...">` children.
  - Sentence boundaries from records or structure → `<s>`.

- **Writing (`tbt` output)**:
  - Not implemented; conversion is one-way to TEITOK TEI.
