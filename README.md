## Flexiconv

Flexiconv is a **Python library, CLI, and desktop GUI** for converting between many corpus and document formats via a shared, token-centric pivot representation and a TEITOK-style TEI XML target.

Supported input families include:

- **TEI / TEITOK** (`teitok`, `tei`)
- **Rich text / documents** (`rtf`, `docx`, `html`, `md`, `txt`)
- **Spoken corpora** (`eaf`, `textgrid`, `exb`, `trs`, `chat`, `srt`, `doreco`)
- **OCR / page layout** (`hocr`, `pagexml`, `alto`)
- **Treebanks and corpora** (`conllu`, `tcf`, `vert`, `tmx`, `tbt`, `folia`, `brat`)

All conversions go via:

- A **pivot model** in `flexiconv.core` (tokens, sentences, layers, anchors).
- A **TEITOK-style TEI** representation (`flexiconv.io.teitok_xml`) that mirrors the conventions of `teitok-tools`.

### Install

Install from GitHub (requires Git):

```bash
pip install 'git+https://github.com/ufal/flexiconv'
```

To install optional extras (RTF, DOCX, Markdown support):

```bash
pip install 'git+https://github.com/ufal/flexiconv#egg=flexiconv[rtf,docx,md]'
```

For development, use an editable install from a clone:

```bash
git clone https://github.com/ufal/flexiconv
cd flexiconv
pip install -e .
```

### Quick start

Once installed:

```bash
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

### Desktop app (flexiConv)

A **standalone desktop GUI** is available for conversion and (planned) deduplication — no Python install required. Download the installer for your platform from the **[`apps/`](apps/)** folder (or from [Releases](https://github.com/ufal/flexiconv/releases) when published). See `apps/README.md` for supported platforms and how to build the apps from source.

### Documentation

- **Pivot model and mapping design**: see `dev/PIVOT_FORMAT.md` and `dev/FORMATS_AND_MAPPINGS.md`.
- **Deduplication**: exact and near-identical duplicate detection, SQLite index, incremental and cross-format — see `wiki/Deduplication.md`.
- **User-oriented docs and format pages**: see the `wiki/` folder; `wiki/README.md` is the index. Each supported format has a short page with:
  - Origin and typical use
  - A minimal example
  - How Flexiconv maps it to TEITOK / the pivot model.

