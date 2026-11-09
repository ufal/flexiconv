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
  - The page's own size goes on `<pb>` and `<surface>` as `bbox="0 0 W H"`, in pixels: it is what relates the boxes on the page to its image.

## Coordinates: pixels or relative

By default every `bbox` is absolute, in pixels of the page image: `bbox="x1 y1 x2 y2"` (corners), as TEITOK expects.

With `--option bbox=pct` the boxes on the page are **relative** instead, in the region syntax of the [IIIF Image API](https://iiif.io/api/image/3.0/#41-region): `bbox="pct:x,y,w,h"`, the left edge, top edge, width and height as percentages of the page (two decimals at most). The same values then fit any size of the image: a thumbnail, the full scan, or a rendering from a IIIF server. The `pct:` prefix is what marks them as relative. The page itself keeps its absolute size (`<pb bbox="0 0 W H">`), so relative boxes can always be turned back into pixels for that image.

```bash
flexiconv page.alto.xml page.xml --to teitok --option "bbox=pct"
```

ALTO does not always count in pixels: its `MeasurementUnit` can be `mm10` (tenths of a millimetre) or `inch1200` (1/1200 inch). Pixels then need the scan resolution:

```bash
flexiconv page.alto.xml page.xml --to teitok --option "dpi=300"
```

| MeasurementUnit | `dpi` given | What is written |
|---|---|---|
| `pixel` (or none) | – | pixels (or `pct:` with `bbox=pct`) |
| `mm10` / `inch1200` | yes | converted to pixels (or `pct:` with `bbox=pct`); baselines (`@points`) converted too |
| `mm10` / `inch1200` | no | `pct:` boxes, with a warning; no page size and no `@points`, since neither is known in pixels |
| `mm10` / `inch1200`, no page `WIDTH`/`HEIGHT` | no | no `bbox` at all, with a warning, rather than values that do not fit the image |

Options can be combined: `--option "bbox=pct;dpi=300"`. With `bbox=pct` and a page without `WIDTH`/`HEIGHT`, the boxes stay absolute (with a warning).

- **Writing (`alto` output)**:
  - Not implemented; conversion is one-way to TEITOK TEI.
