# Vertical / VRT (`vert`)

## Tool and format

- **Tool / ecosystem**: Vertical format is used by [Manatee](https://corpus.manatee.cz/) / [KonText](https://kontext.korpus.cz/), [CWB](https://cwb.sourceforge.io/) (Corpus Workbench), and related corpus tools. Often produced by `teitok2vrt.pl` or CWB decode.
- **Full format name**: Vertical (VRT): one token per line, optional XML tags (`<doc>`, `<text>`, `<s>`), tab- or space-separated columns. No single formal spec; column names often come from a Manatee/CWB registry file.
- **Format specification**: Described in [CWB documentation](https://cwb.sourceforge.io/) and [Manatee/KonText](https://corpus.manatee.cz/) docs; file extensions `.vrt`, `.vert`.

## Origin and purpose

- **Origin**: Vertical format (one token per line, optional XML structure). Used by Manatee, CWB, KonText, and similar corpus back-ends. Often generated from TEITOK via `teitok2vrt.pl` or from CWB decode.
- **Role in Flexiconv**: import VRT/vertical files into TEITOK-style TEI with `<div>`/`<s>`/`<tok>`. Column names can come from a Manatee/CWB registry or from `--option cols=form,lemma,pos,...`. Optional split: one TEI file per `<doc>`/`<text>` when using `--option split` and an output directory.

Handled by `flexiconv/io/vert.py`.

## Minimal example

```
<doc id="doc1">
<s>
The	the	DET
cat	cat	NOUN
sat	sit	VERB
.	.	PUNCT
</s>
</doc>
```

Or without tags, one token per line with blank lines as sentence boundaries; columns can be specified with `--option "cols=form,lemma,pos"`.

## Conversion semantics

- **Reading (`vert` input)**:
  - Token lines (tab/space-separated) → `<tok>`; first column = form, remaining columns → token attributes (lemma, pos, etc.). Column names from registry or `--option cols=...`.
  - `<doc>`/`<text>` start/end → new `<div>` (or separate files with `--option split`). `<s>`/`</s>` or blank lines → sentence boundaries.
  - Spacing is reconstructed heuristically (`--spacing-mode guess` or `none`). Use `--vert-no-doc-split` to keep everything in one `<body>` without splitting on doc/text.

- **Writing (`vert` output)**:
  - Not implemented; use TEITOK or teitok-tools for TEI → VRT.
