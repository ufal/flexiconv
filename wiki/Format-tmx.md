# TMX (`tmx`)

## Tool and format

- **Format name**: TMX (Translation Memory eXchange), XML standard for translation memories, originally from LISA/OSCAR.
- **Format specification**: [TMX 1.4b specification](https://www.gala-global.org/sites/default/files/tmx1.4b.pdf) (GALA); root `tmx`, `body`, `tu` (translation unit), `tuv` (variant per language), `seg`. File extension `.tmx`.

## Origin and purpose

- **Origin**: TMX (Translation Memory eXchange), an XML standard for translation memories. Contains `<tu>` (translation units) with `<tuv>` (translation unit variants) per language and segment text.
- **Role in Flexiconv**: import TMX into TEITOK-style TEI with `<div lang="...">` and aligned segments (e.g. `<ab tuid="...">`). Can write one TEI per language with `--option split` and an output directory.

Handled by `flexiconv/io/tmx.py`.

## Minimal example (conceptual)

```xml
<tmx>
  <body>
    <tu>
      <tuv xml:lang="en"><seg>Hello world.</seg></tuv>
      <tuv xml:lang="de"><seg>Hallo Welt.</seg></tuv>
    </tu>
  </body>
</tmx>
```

Flexiconv produces TEI with language-specific `<div>` and segment-level alignment where applicable.

## Conversion semantics

- **Reading (`tmx` input)**:
  - Each `<tu>` → aligned segments; each `<tuv>` → text in that language. Output is TEITOK-style TEI with `<div lang="...">` and segment elements. With `--option split`, one XML file per language is written into the given output directory.

- **Writing (`tmx` output)**:
  - Not implemented; conversion is one-way from TMX to TEITOK TEI.
