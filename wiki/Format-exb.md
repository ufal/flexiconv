# EXMARaLDA basic transcription (`exb`)

## Tool and format

- **Tool**: [EXMARaLDA](https://exmaralda.org/) (Extensible Markup Language for Discourse Annotation), Hamburg University.
- **Full format name**: EXMARaLDA basic transcription format (EXB).
- **Format specification**: [EXMARaLDA documentation](https://exmaralda.org/en/); the basic transcription is an XML format with tiers and timeline.

## Origin and purpose

- **Origin**: EXMARaLDA (Extensible Markup Language for Discourse Annotation). The “basic transcription” (`.exb`) is an XML format for time-aligned, multi-tier transcriptions linked to media.
- **Role in Flexiconv**: import EXMARaLDA transcripts into TEITOK-style TEI with `<u>` elements with `start`/`end` and speaker information, and a `recordingStmt` for media.

Handled by `flexiconv/io/exb.py`.

## Minimal example (conceptual)

EXB XML contains `tier` elements with `event` segments and timeline references. Flexiconv maps them to TEI:

```xml
<u start="0.0" end="1.5" who="SPK1">Hello world.</u>
```

## Conversion semantics

- **Reading (`exb` input)**:
  - Each timeline segment (event) → `<u>` with `@start`, `@end`, `@who` (speaker).
  - Media references → `recordingStmt/media` in the TEI header.
  - Pivot model gets an `utterances` layer and timelines/media for downstream use.

- **Writing (`exb` output)**:
  - Flexiconv can write EXMARaLDA basic transcription from TEITOK TEI that contains time-aligned `<u>` (e.g. after EAF or TRS import). Use `-t exb` to export.
