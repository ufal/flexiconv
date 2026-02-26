# ALTO XML (`alto`)

## Tool and format

- **Format name**: ALTO (Analyzed Layout and Text Object), XML standard for digitisation and OCR used by libraries and archives.
- **Format specification**: [Library of Congress ALTO](https://www.loc.gov/standards/alto/); schema with `Layout`, `Page`, `PrintSpace`, `TextBlock`, `TextLine`, `String` and attributes `HPOS`, `VPOS`, `WIDTH`, `HEIGHT`, `CONTENT`. File extensions `.alto.xml` or `.alto`.

## Origin and purpose

- **Origin**: ALTO (Analyzed Layout and Text Object), used in digitisation and OCR workflows. XML with `Layout`/`Page`/`PrintSpace`/`TextBlock`/`TextLine`/`String`; coordinates via `HPOS`, `VPOS`, `WIDTH`, `HEIGHT`.
- **Role in Flexiconv**: import ALTO into TEITOK-style TEI with `<facsimile>`, `<surface>`, zones, and `<tok>` with `bbox`, similar to PAGE XML handling.

Handled by `flexiconv/io/alto.py`.

## Minimal example (conceptual)

```xml
<alto>
  <Layout>
    <Page>
      <PrintSpace>
        <TextBlock>
          <TextLine>
            <String HPOS="10" VPOS="20" WIDTH="90" HEIGHT="8" CONTENT="Hello"/>
          </TextLine>
        </TextBlock>
      </PrintSpace>
    </Page>
  </Layout>
</alto>
```

Flexiconv maps Page → surface, TextBlock/TextLine → zones, String → `<tok>` with `bbox` and text content.

## Conversion semantics

- **Reading (`alto` input)**:
  - ALTO coordinates (HPOS/VPOS/WIDTH/HEIGHT) → `bbox` (xmin ymin xmax ymax). Structure → `<pb>`, `<surface>`, zones, `<tok>`. Image filename from ALTO → facsimile when available.
  - Punctuation can be split from words unless disabled.

- **Writing (`alto` output)**:
  - Not implemented; conversion is one-way to TEITOK TEI.
