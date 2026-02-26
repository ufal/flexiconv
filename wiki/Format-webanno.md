# WebAnno TSV (`webanno`)

## Tool and format

- **Tool**: [WebAnno](https://webanno.github.io/webanno/) / [INCEpTION](https://inception-project.github.io/) — web-based annotation for NLP (tokens, spans, relations).
- **Full format name**: WebAnno TSV: tab-separated export with a format line, a header line `#T_XX=Layer|field1|field2|...`, then blocks of `#Text=`/`#MText=` (segment text) followed by token lines `sent-tok\tbegin-end\tform\tval1\tval2\t...`.
- **Format specification**: [WebAnno TSV format](https://webanno.github.io/webanno/releases/3.6.6/docs/user-guide.html#sect_webannotsv); [INCEpTION export](https://inception-project.github.io/releases/31.2/docs/user-guide/user-guide.html#sect_formats_export).

## Origin and purpose

- **Origin**: WebAnno and INCEpTION export annotation layers (tokenisation, lemma, POS, NER, etc.) as TSV. Token lines carry character spans and per-column values; multi-token spans use `value[annid]` so the same `annid` on several tokens defines one span.
- **Role in Flexiconv**: import WebAnno TSV into TEITOK-style TEI with `<s>`/`<tok>` (and token attributes from the TSV columns) and optional `<standOff>`/`<spanGrp>`/`<span>` for multi-token span annotations.

Handled by `flexiconv/io/webanno.py`.

## Minimal example

See `examples/webanno/sample.tsv`:

```
WebAnno TSV 3.2
#T_SP=webanno.custom.Token|Lemma|POS|NER
#Text=The cat sat on the mat .
1-1	0-3	The	the	DET	_
1-2	4-7	cat	cat	NOUN	_
...
1-5	16-19	the	the	DET	LOC[1]
1-6	20-23	mat	mat	NOUN	LOC[1]
...
```

Here `LOC[1]` on two tokens creates one span with `corresp="#w-1-5 #w-1-6"` and attribute `ner="LOC"`.

## Conversion semantics

- **Reading (`webanno` input)**:
  - **Segments**: Each `#Text=` or `#MText=` starts a new segment (`<s id="s-N">`). Token lines before any `#Text` start the first segment automatically.
  - **Tokens**: One `<tok id="w-{sent}-{tok}">` per token line; character span and `form` (text); spacing between tokens is taken from the segment text and written as `tok.tail`.
  - **Token attributes**: TSV columns after `form` (from the header `#T_XX=Layer|field1|field2|...`) become token attributes; `_` is empty. Values could be pipe-separated; each value is either a literal (→ attribute on the token) or `value[annid]` (→ part of a multi-token span).
  - **Multi-token spans**: For each `annid` appearing in `value[annid]` across tokens, Flexiconv emits a `<span id="ann-{id}" corresp="#w-... #w-..." ...>` in `<standOff><spanGrp>`. Span text is the concatenation of the token forms; field names (lowercased) become span attributes.

- **Writing (`webanno` output)**:
  - Not implemented; conversion is one-way to TEITOK TEI. Use `-t teitok` when converting to TEI, e.g. `flexiconv examples/webanno/sample.tsv out.xml -t teitok`.

## Detection

- **By extension**: `.webanno.tsv` or `.webanno` → `webanno`.
- **By content**: For `.tsv` files, if the second line matches `#T_.{2}=[^|\t]+\|`, the file is treated as WebAnno TSV.
