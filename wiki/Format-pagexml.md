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
  - Page → `<pb>`/`<surface>`; regions and lines → `<zone>`; words → `<tok>` with coordinates. Image reference from PAGE is kept in facsimile when present.
  - Punctuation splitting can be applied at word level (configurable).

- **Writing (`pagexml` output)**:
  - Not implemented; conversion is one-way to TEITOK TEI.
