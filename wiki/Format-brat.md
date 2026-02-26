# BRAT stand-off (`brat`)

## Tool and format

- **Tool**: [brat](https://brat.nlplab.org/) (Brat Rapid Annotation Tool), stand-off annotation for text.
- **Full format name**: brat annotation format: a `.txt` file (raw text) plus one or more `.ann` files with T (text-bound), A (attribute), and R (relation) lines using character offsets or annotation IDs.
- **Format specification**: [brat documentation](https://brat.nlplab.org/documentation.html); [annotation format](https://brat.nlplab.org/standoff.html). Example files in `examples/brat/`.

## Origin and purpose

- **Origin**: BRAT (Brat Rapid Annotation Tool) uses stand-off annotation: a `.txt` file for the text and one or more `.ann` files with T (text-bound), A (attribute), and R (relation) lines referencing character offsets or other annotations.
- **Role in Flexiconv**: import BRAT into TEITOK-style TEI with `<tok>` (and optional standOff `<spanGrp>`/`<linkGrp>`). “Smart” import: when the `.ann` looks like UD (e.g. T-types are POS tags, or all “Token”), Flexiconv maps POS, lemma, feats, head, deprel onto `<tok>` and can suppress redundant standOff.

Handled by `flexiconv/io/brat.py`.

## Minimal example

**doc.txt:**
```
The cat sat.
```

**doc.ann:**
```
T1	Token 0 3	The
T2	Token 4 7	cat
T3	Token 8 11	sat
T4	Token 11 12	.
A1	Lemma T1	the
A2	Lemma T2	cat
...
```

Use `--option "plain=/path/to/doc.txt;ann=/path/to/doc.ann"` if files are not in the same directory.

## Conversion semantics

- **Reading (`brat` input)**:
  - Point to `.ann` or `.txt`; Flexiconv finds the other file in the same directory (or use `--option` to set paths). Tokenisation: either whitespace over `.txt` or, in “UD token” mode, one `<tok>` per T-annotation when T-types look like UD POS tags.
  - T → span or (in UD mode) token; A (pos, lemma, feats, etc.) → token attributes; R → dependency `head`/`deprel` on dependent token. UD morphological features (Case, Number, …) are aggregated into `feats="Case=Ela|Number=Sing"`. When UD-style is detected, standOff can be omitted to avoid duplication.

- **Writing (`brat` output)**:
  - Not implemented; conversion is one-way to TEITOK TEI.
