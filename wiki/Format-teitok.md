# TEITOK TEI (`teitok`)

## Tool and format

- **Tool**: [TEITOK](https://teitok.ufal.cz/) corpus platform (formerly TEI-TOKENISE).
- **Full format name**: TEITOK-style TEI (TEI P5 with TEITOK conventions: `<tok>`, `<dtok>`, `<s>`, `<u>`, rich token attributes, optional stand-off).
- **Format specification**: TEITOK project documentation and [TEI P5](https://tei-c.org/release/doc/tei-p5-doc/en/html/); TEITOK-specific elements and attributes are documented in the TEITOK manual and `teitok-tools` scripts.

## Origin and purpose

- **Origin**: TEITOK corpus platform.
- **Role in Flexiconv**: primary authoritative format for TEITOK-based corpora; most conversions target TEITOK-style TEI XML.

Flexiconv’s TEITOK support lives mainly in `flexiconv/io/teitok_xml.py`.

## Minimal example

```xml
<TEI>
  <text id="sample">
    <body>
      <div>
        <s id="s-1">
          <tok xml:id="w-1" lemma="The" upos="DET">The</tok>
          <tok xml:id="w-2" lemma="cat" upos="NOUN">cat</tok>
          <tok xml:id="w-3" lemma="sit" upos="VERB" head="2" deprel="root">sat</tok>
          <tok xml:id="w-4" lemma="." upos="PUNCT">.</tok>
        </s>
      </div>
    </body>
  </text>
</TEI>
```

## Conversion semantics

- **Reading (`teitok` input)**:
  - Tokens: `<tok>` / `<dtok>` become nodes in the `tokens` layer; attributes (`lemma`, `upos`, `xpos`, `feats`, `head`, `deprel`, etc.) become token features.
  - Sentences: `<s>` elements become nodes in the `sentences` layer; milestone-style `<s/>` with `sameAs` are expanded to explicit sentence spans.
  - Structure: `<div>`, `<p>`, `<u>`, `<name>`, `<seg>`, etc. create `structure` and span layers.
  - TEI header is preserved and mapped into document metadata when relevant.

- **Writing (`teitok` output)**:
  - The pivot model (tokens, sentences, structure, spans) is serialized back into TEITOK-style TEI, following TEITOK conventions for IDs, `tokid`, and optional stand-off annotations.
  - When running inside a TEITOK project, output goes to `xmlfiles/` and stand-off annotations (when relevant) are written to `Annotations/`.

