# CoNLL-U (`conllu`)

## Tool and format

- **Format name**: CoNLL-U, the standard interchange format for [Universal Dependencies](https://universaldependencies.org/) (UD) treebanks.
- **Format specification**: [CoNLL-U format](https://universaldependencies.org/format.html): tab-separated token lines (ID, FORM, LEMMA, UPOS, XPOS, FEATS, HEAD, DEPREL, DEPS, MISC) and `#` comment lines. File extensions `.conllu`, `.conllup`, `.cupt`.

## Origin and purpose

- **Origin**: CoNLL-U is the standard format for Universal Dependencies treebanks. Tab-separated token lines (ID, FORM, LEMMA, UPOS, XPOS, FEATS, HEAD, DEPREL, DEPS, MISC) plus comment lines for sentence and document metadata.
- **Role in Flexiconv**: import CoNLL-U into the pivot model and TEITOK-style TEI with `<s>`, `<tok>` (lemma, upos, xpos, feats, head, deprel), and metadata in the TEI header. Export TEITOK/CoNLL-U back to CoNLL-U with standardised comments and SpaceAfter=No.

Handled by `flexiconv/io/conllu.py`.

## Minimal example

```
# sent_id = 1
# text = The cat sat.
1	The	the	DET	DT	_	3	det	_	_
2	cat	cat	NOUN	NN	_	3	nsubj	_	_
3	sat	sit	VERB	VBD	_	0	root	_	_
4	.	.	PUNCT	.	_	3	punct	_	_
```

## Conversion semantics

- **Reading (`conllu` input)**:
  - Each token line → `<tok>` with `lemma`, `upos`, `xpos`, `feats`, `head`, `deprel`. Sentence boundaries from blank lines; `# sent_id`, `# text` → sentence/metadata. Multi-word tokens and empty nodes are supported.
  - With `--option split`, one TEI file per `# newdoc` block is written to an output directory.

- **Writing (`conllu` output)**:
  - Pivot/TEITOK tokens and sentences → CoNLL-U lines. `space_after` is reflected as `SpaceAfter=No` in MISC. Use `-t conllu` to export.
