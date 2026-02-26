## Flexiconv

Flexiconv is a **Python library and CLI** for converting between many corpus and document formats via a shared, token-centric pivot representation and a TEITOK-style TEI XML target.

Supported input families include:

- **TEI / TEITOK** (`teitok`, `tei`)
- **Rich text / documents** (`rtf`, `docx`, `html`, `md`, `txt`)
- **Spoken corpora** (`eaf`, `textgrid`, `exb`, `trs`, `chat`, `srt`, `doreco`)
- **OCR / page layout** (`hocr`, `pagexml`, `alto`)
- **Treebanks and corpora** (`conllu`, `tcf`, `vert`, `tmx`, `tbt`, `folia`, `brat`)

All conversions go via:

- A **pivot model** in `flexiconv.core` (tokens, sentences, layers, anchors).
- A **TEITOK-style TEI** representation (`flexiconv.io.teitok_xml`) that mirrors the conventions of `teitok-tools`.

### Quick start

Once installed (editable install for development):

```bash
python -m pip install -e .

# Single-file conversion (format auto-detected where possible)
flexiconv input.ext output.xml

# Explicit formats
flexiconv -f vert -t teitok examples/vert/desam-v20.vert

# Batch-convert a folder (recursively)
flexiconv -R path/to/input_dir path/to/output_dir -t teitok

# Inspect formats
flexiconv info formats
flexiconv info format vert
```

### Documentation

- **Pivot model and mapping design**: see `dev/PIVOT_FORMAT.md` and `dev/FORMATS_AND_MAPPINGS.md`.
- **User-oriented docs and format pages**: see the `wiki/` folder; `wiki/README.md` is the index. Each supported format has a short page with:
  - Origin and typical use
  - A minimal example
  - How Flexiconv maps it to TEITOK / the pivot model.

