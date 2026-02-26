# ELAN EAF (`eaf`)

## Tool and format

- **Tool**: [ELAN](https://archive.mpi.nl/tla/elan) (EUDICO Linguistic Annotator), from the Max Planck Institute for Psycholinguistics.
- **Full format name**: ELAN Annotation Format (EAF).
- **Format specification**: The [ELAN user guide](https://archive.mpi.nl/tla/elan/manual) describes the EAF XML structure; the file extension is `.eaf`.

## Role in Flexiconv

Import ELAN transcriptions into TEITOK-style TEI with `<u>` elements carrying `start`/`end` and speaker/tier metadata, plus a `recordingStmt` for media. Handled by `flexiconv/io/eaf.py`.

Example files for EAF (and related formats) are in the repository’s `examples/` folder where available.

## Minimal example (conceptual)

EAF is XML with `TIME_ORDER`, `TIER`, and `ALIGNABLE_ANNOTATION` (or `REF_ANNOTATION`) elements. Flexiconv maps each alignable annotation to a TEI `<u>`:

```xml
<u who="spk1" start="0.0" end="1.5">Hello world.</u>
```

Media descriptors become `recordingStmt/media` in the TEI header.

## Conversion semantics

- **Reading (`eaf` input)**:
  - One `<u>` per ALIGNABLE_ANNOTATION with `@start`, `@end` (seconds), `@who` from tier participant, and optional tier name.
  - REF_ANNOTATIONs (e.g. translations, glosses) are attached as attributes or child content where applicable.
  - Media files from MEDIA_DESCRIPTOR → `recordingStmt` and document `media` / `timelines` in the pivot.
  - Use `--eaf-style generic` or `doreco` for DoReCo-specific tier mappings.

- **Writing (`eaf` output)**:
  - Not implemented; Flexiconv focuses on EAF → TEITOK. Round-trip via TEI is possible in principle using the pivot `utterances` layer.
