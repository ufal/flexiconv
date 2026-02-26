# TCF (`tcf`)

## Tool and format

- **Tool / ecosystem**: [WebLicht](https://weblicht.sfs.uni-tuebingen.de/) and the D-Spin toolchain for linguistic annotation services.
- **Full format name**: TCF (Text Corpus Format), XML interchange format for tokens, lemmas, POS, orthography, dependencies, named entities.
- **Format specification**: [TCF format](https://weblicht.sfs.uni-tuebingen.de/weblicht/wiki/index.php/TCF) on the WebLicht wiki; root elements such as `textcorpus`, `tokens`, `lemmas`, `POStags`, `parsing`, `namedEntities`. File extension `.tcf`.

## Origin and purpose

- **Origin**: TCF (Text Corpus Format), used in the D-Spin/WebLicht toolchain for linguistic annotation interchange. XML with tokens, lemmas, POS tags, orthography/correction, dependency parsing, and named entities.
- **Role in Flexiconv**: import TCF into TEITOK-style TEI with `<s>`, `<tok>` (lemma, pos, reg, head, deprel), and `<name>` for named entities; sentences and document structure are preserved.

Handled by `flexiconv/io/tcf.py`.

## Minimal example (conceptual)

TCF XML has elements such as `textcorpus`, `tokens`, `lemmas`, `POStags`, `parsing` (dependencies), `namedEntities`. Flexiconv maps tokens and their IDs to TEI `<tok>` and fills attributes from the corresponding TCF layers.

## Conversion semantics

- **Reading (`tcf` input)**:
  - Token list → `<tok>` with `xml:id`; lemma, POS, orthography/correction → token attributes. Dependency relations → `head`/`deprel` on the dependent token. Named entities → `<name>` wrapping the corresponding token span.
  - Sentence boundaries from TCF (if present) → `<s>`.

- **Writing (`tcf` output)**:
  - Not implemented; conversion is one-way to TEITOK TEI.
