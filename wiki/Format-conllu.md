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
  - Each token line → `<tok>` with `lemma`, `upos`, `xpos`, `feats`, `head`, `deprel`, `deps`. Sentence boundaries from blank lines.
  - **Multi-word tokens** (`3-4 del`): `<tok id="w-3">del<dtok id="d-3-1" form="de" …/><dtok id="d-3-2" form="el" …/></tok>`, the TEITOK convention. `N` in `w-N` / `d-N-k` counts the `<tok>`s (surface tokens); heads point to the `<dtok>`s. `SpaceAfter` and `FEATS` (`Typo=Yes`) of the range line stay on the `<tok>`.
  - **Empty nodes** (`5.1`): `<notok id="e-N-k" ord="5.1" form="…" lemma="…" upos="…" deps="…"/>` right after the word they follow: an empty element (no text), so a zero-width region in pando. `DEPS` references to them use that id.
  - **MISC**: one attribute per item, `misc_Gloss="sea"`; a bare item is `misc_Flag=""`. Items whose key cannot be an XML attribute name (`LMSeg:a-b`) or whose value is empty (`Gloss=`) are kept verbatim in `@misc`. `SpaceAfter=No` becomes the absence of a space after the token.
  - **Comments**: every `# key = value` of a sentence becomes an attribute of its `<s>` (`sent_id`, `text`, `translit`, `text_en`, …; a key that is no XML name gets `_` for the characters it cannot have); comment lines without `=` go, one per line, into `@conllu_comments`. File and document comments (`global.*`, `meta::*`, `generator`, `model`) go to the teiHeader as `<note n="conllu:KEY">`.
  - **Documents and paragraphs**: `# newdoc id = X` → `<doc id="X">`, `# newpar id = Y` → `<p org_id="Y">` (as teitok-tools `conllu2teitok.pl`).
  - CoNLL-U sentence-local `HEAD` / `DEPS` ordinals are remapped to TEITOK token `@id` values (e.g. `3` → `w-12`). Root (`HEAD=0`) omits `@head`. Token ids follow TEITOK convention (`w-1`, `w-2`, …), or `tokId` from MISC when present. Original CoNLL-U ordinals are kept as `ord` / `ohead` on each `<tok>` for validation (as in teitok-tools `conllu2teitok.pl`; omit with `--option ord=no`).
  - Multi-file TEITOK output (OUTPUT must be an existing directory; `-t teitok`):
    - `--option split` — one TEI file per `# newtext` block.
    - `--option max_tokens=N` and/or `max_sentences=N` — pack sentences into chunks that stay under the given limits (a single oversized sentence still becomes its own file). `# newdoc` / `# newtext` are hard boundaries. Example: `--option "max_tokens=100000;max_sentences=10000"`. Each output file records the chunk in `revisionDesc` (a second `<change n="chunk">`).

- **Writing (`conllu` output)**:
  - Pivot/TEITOK tokens and sentences → CoNLL-U lines. TEITOK-style `@head` / `@deps` token ids are converted back to sentence-local ordinals. `space_after` is reflected as `SpaceAfter=No` in MISC. Use `-t conllu` to export.
  - Everything above is read back from TEITOK: `<dtok>`s give range lines, `<notok>`s with a decimal `@ord` or `@deps` give empty nodes (other `<notok>`s, e.g. PROIEL's empty tokens, are no UD words), `<s>` attributes give comments, `<doc>` / `<p>` give `newdoc` / `newpar`, the header notes give the file comments. A UD file comes back with the same rows and comments; only the order of comments and of MISC items can differ.
