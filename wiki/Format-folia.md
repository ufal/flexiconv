# FoLiA (`folia`)

## Tool and format

- **Tool**: [FoLiA](https://proycon.github.io/folia/) (Format for Linguistic Annotation), developed at the Centre for Language and Speech Technology (CLST), Radboud University.
- **Full format name**: FoLiA; XML format for linguistic annotation with elements such as `text`, `s`, `w`, `t`, `lemma`, `pos`, `dependency`.
- **Format specification**: [FoLiA documentation](https://proycon.github.io/folia/); schema and tag set documented there. File extensions `.folia.xml`, `.folia`.

## Origin and purpose

- **Origin**: FoLiA (Format for Linguistic Annotation), an XML format for richly annotated linguistic data. Defines elements such as `<w>`, `<t>`, `<lemma>`, `<pos>`, and `<dependency>` for tokens and structure.
- **Role in Flexiconv**: import FoLiA into TEITOK-style TEI with `<s>`, `<tok>` (lemma, pos, head, deprel from dependencies), and TEI header from FoLiA metadata.

Handled by `flexiconv/io/folia.py`.

## Minimal example (conceptual)

```xml
<folia>
  <text>
    <s id="s1">
      <w id="w1"><t>The</t><lemma>the</lemma><pos class="DET"/></w>
      <w id="w2"><t>cat</t><lemma>cat</lemma><pos class="NOUN"/></w>
      ...
    </s>
  </text>
</folia>
```

Flexiconv maps `<w>` → `<tok>`, children → attributes; dependencies (`<dependency>` with dep/hd and wref) → `head`/`deprel` on the dependent token.

## Conversion semantics

- **Reading (`folia` input)**:
  - `<text>` lang → `text@xml:lang`. `<s>` → `<s>`. `<w>` → `<tok>` with text from `<t>` and attributes from `<lemma>`, `<pos>`, etc. Space between tokens from FoLiA `@space` or default.
  - Dependencies: dep/hd with wref → set `head` and `deprel` on the dependent `<tok>`.

- **Writing (`folia` output)**:
  - Not implemented; conversion is one-way to TEITOK TEI.
