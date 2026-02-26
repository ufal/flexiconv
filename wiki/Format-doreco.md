# DoReCo ELAN (`doreco`)

## Tool and format

- **Tool / project**: [DoReCo](https://doreco.info/) (Database of Reference Corpora); uses ELAN with a specific tier convention.
- **Full format name**: DoReCo uses the same file format as [ELAN EAF](Format-eaf.md) (ELAN Annotation Format), with DoReCo-specific tier names and types.
- **Format specification**: [DoReCo documentation](https://doreco.info/documentation); EAF structure as in the [ELAN user guide](https://archive.mpi.nl/tla/elan/manual).

## Origin and purpose

- **Origin**: DoReCo (Database of Reference Corpora) project. Uses ELAN `.eaf` files with a specific tier naming and structure convention for reference corpora.
- **Role in Flexiconv**: import DoReCo-style EAF with preset tier mappings (e.g. translation, orthography) so that tiers map consistently to TEITOK TEI structure.

Handled by `flexiconv/io/doreco.py`; uses EAF parsing with `--eaf-style doreco`.

## Minimal example

Same file format as [ELAN EAF](Format-eaf.md); the difference is the **tier interpretation**. DoReCo conventions (tier names and types) are applied so that the main transcription, translations, and other tiers map to the right TEI elements or attributes.

## Conversion semantics

- **Reading (`doreco` input)**:
  - Same as EAF, but with DoReCo-specific tier mapping (e.g. which tier is “orthography”, which is “translation”). Use `flexiconv -f doreco` or `-f eaf --eaf-style doreco`.
  - Output is TEITOK-style TEI with `<u>`, media, and DoReCo tiers reflected in structure or attributes.

- **Writing (`doreco` output)**:
  - Flexiconv can write DoReCo-style EAF from TEITOK TEI that was produced from DoReCo EAF (round-trip of structure and tiers). Use `-t doreco`.
