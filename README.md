## Flexiconv

Flexiconv is a **Python library, CLI, and desktop GUI** for converting between many corpus and document formats via a shared, token-centric pivot representation and a TEITOK-style TEI XML target.

Supported input families include:

- **TEI / TEITOK** (`teitok`, `tei`)
- **Rich text / documents** (`rtf`, `docx`, `pdf`, `odt`, `html`, `md`, `txt`, `epub`)
- **Spoken corpora / oral transcription** (`eaf`, `textgrid`, `exb`, `trs`, `chat`, `srt`, `doreco`)
- **OCR / page layout** (`hocr`, `pagexml`, `alto`)
- **Treebanks and corpora / stand-off annotation** (`conllu`, `tcf`, `vert`, `tmx`, `tbt`, `folia`, `brat`, `webanno`)

All conversions go via:

- A **pivot model** in `flexiconv.core` (layers, anchors, nodes, spans) that can represent crossing annotations.
- A **TEITOK-style TEI** representation (`flexiconv.io.teitok_xml`) that mirrors the conventions of `teitok-tools` and acts as a TEI/XML view of the pivot.

The focus is on **semantic and structural fidelity** (sections, paragraphs, lists, tables, tokens, annotations), not on pixel-perfect reproduction of the original layout. Round-tripping formats (e.g. `DOCX → TEI → DOCX` or `PDF → TEI → HTML`) will typically preserve structure and content, but not exact visual identity; final page layout is left to tools like Word, browsers, or typesetters.

### Install

Install from GitHub (requires Git):

```bash
pip install 'git+https://github.com/ufal/flexiconv'
```

To install optional extras (RTF, DOCX, ODT, Markdown, PDF support):

```bash
pip install 'git+https://github.com/ufal/flexiconv#egg=flexiconv[rtf,docx,odt,md,pdf]'
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

A **standalone desktop GUI** is available for conversion and (planned) deduplication — no Python install required. Download the installer for your platform from the **[`apps/`](apps/)** folder (or from [Releases](https://github.com/ufal/flexiconv/releases) when published). See [apps/README.md](apps/README.md) for supported platforms and how to build the apps from source.

### Documentation

- **Pivot model and mapping design**: see [examples/md/FORMATS_AND_MAPPINGS.md](examples/md/FORMATS_AND_MAPPINGS.md); the pivot is implemented in `flexiconv.core.model` and reflected in the format pages under [wiki/](wiki/).
- **Deduplication**: exact and near-identical duplicate detection, SQLite index, incremental and cross-format — see [wiki/Deduplication.md](wiki/Deduplication.md).
- **User-oriented docs and format pages**: see the [wiki/](wiki/) folder; [wiki/README.md](wiki/README.md) is the index. Each supported format has a short page with:
  - Origin and typical use
  - A minimal example
  - How Flexiconv maps it to TEITOK / the pivot model.

