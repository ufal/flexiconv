# PAGE XML (`pagexml`)

## Tool and format

- **Format name**: PAGE (Page Analysis and Ground-Truth Elements), XML schema for document layout and OCR/HTR ground truth.
- **Format specification**: [PAGE XML schema and documentation](https://www.primaresearch.org/schema/PAGE/); root element `PcGts`, with `Page`, `TextRegion`, `TextLine`, `Word`, `Coords`. Often used with file extension `.page.xml` or similar.

## Origin and purpose

- **Origin**: PAGE (Page Analysis and Ground-Truth Elements), an XML standard for document layout and OCR/HTR. Root element is `PcGts`; contains `Page`, `TextRegion`, `TextLine`, `Word`, with `Coords` for polygons.
- **Role in Flexiconv**: import PAGE XML into TEITOK-style TEI with `<facsimile>`, `<surface>`, `<zone>`, and `<tok>` with bounding boxes (`bbox` or `points`).

Handled by `flexiconv/io/page_xml.py`.

## Minimal example (conceptual)

```xml
<PcGts>
  <Page>
    <TextRegion>
      <TextLine>
        <Word><Coords points="10,20 100,20 100,28 10,28"/></Word>
      </TextLine>
    </TextRegion>
  </Page>
</PcGts>
```

Flexiconv maps Page → surface, TextRegion/TextLine → zones, Word → `<tok>` with bbox.

## Conversion semantics

- **Reading (`pagexml` input)**:
  - Page → `<pb>`/`<surface>` (`<pb corresp="#facs-N">` links to the surface); regions and lines → `<zone>`; words → `<tok>` with coordinates. Image reference from PAGE is kept in facsimile when present.
  - `TextRegion/@type` or `structure {type:…;}` in `@custom` → `type` on the TEI `<div>` (and `subtype` on the matching facsimile zone). `readingOrder {index:…;}` reorders regions on the page.
  - Punctuation splitting can be applied at word level (configurable).

- **Writing (`pagexml` output)**:
  - Not implemented; conversion is one-way to TEITOK TEI.

## Merging per-page files

Transkribus and similar tools often export one PageXML file per page in a folder. Flexiconv can merge those into a single TEITOK XML (with sequential `<pb>` breaks and shared facsimile ids), using the same mapping as a multi-page PageXML file:

```bash
flexiconv path/to/page/ merged.xml -f pagexml -t teitok --pagexml-merge
```

Files are sorted in natural order (`page-2` before `page-10`). Use `-R` to include subdirectories. Equivalent: `--option merge` with `-f pagexml`.

Without `--pagexml-merge`, `-R` on a directory writes one TEITOK file per PageXML input (batch mode).
