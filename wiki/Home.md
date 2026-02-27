# Flexiconv

Flexiconv is a **format conversion toolkit** for TEITOK-based corpora and related formats. It focuses on:

- Converting between TEITOK-style TEI, TEI P5, and many corpus / treebank / OCR / transcription formats.
- Keeping a **token-centric pivot model** so that conversions can be combined or reused.
- Integrating well with TEITOK projects (`xmlfiles/`, `Annotations/`) and tools like `teitok-tools` and `flexipipe`.

If you have installed the wrapper, you can run `flexiconv` instead of `python -m flexiconv`.

## Commands

| Command | Purpose |
| --- | --- |
| `flexiconv INPUT [OUTPUT]` | Single-file conversion (default command) |
| `flexiconv convert` | Explicit convert subcommand (same core options) |
| `flexiconv info` | Inspect formats and their data types |
| `flexiconv install` | Install optional extras (RTF, TEI-CORPO integration, Annatto) |
| `flexiconv update` | Show how to upgrade Flexiconv and extras |

Use `flexiconv convert --help` for full options.

## Examples

### Single-file conversion

```bash
# Auto-detect input format, write TEITOK-style TEI
flexiconv examples/vert/desam-v20.vert desam-v20.xml

# Explicit input and output formats
flexiconv -f tcf -t teitok examples/tcf/sample.tcf sample.xml
```

### Working inside a TEITOK project

When you run Flexiconv from inside a TEITOK project (a folder with `Resources/settings.xml`), the default behaviour is:

- If you omit OUTPUT: write to `xmlfiles/{safe_basename}.xml`.
- TEITOK-related metadata (source file, MIME type) is stored in the TEI header.

```bash
# From inside a TEITOK project root
flexiconv Originals/sample.tmx
# → writes xmlfiles/sample.xml (TEITOK-style TEI)
```

### Batch conversion (directories)

Flexiconv can convert a whole folder recursively:

```bash
# Detect input format per file; write TEITOK XML next to the input tree
flexiconv -R corpora/raw corpora/xml -t teitok

# Fix the input format for all files
flexiconv -R -f vert corpora/vrt corpora/xml -t teitok
```

### Chaining NLP with flexipipe

After writing TEITOK XML you can optionally run `flexipipe` in one step:

```bash
# Use flexipipe defaults; XML path is appended automatically
flexiconv input.docx output.xml -t teitok --flexipipe

# Inside a TEITOK project, pass the project root to flexipipe
flexiconv Originals/sample.txt -t teitok --teitok-project /path/to/project \
  --flexipipe "--project {project}"
```

In both cases Flexiconv runs:

- `flexipipe [ARGS...] OUTPUT_XML`

where `OUTPUT_XML` is the TEITOK file it just wrote, and `{project}` (if used) is replaced by the detected / given TEITOK project root.

See [Formats](Formats.md) for an overview of all supported formats and links to per-format pages.

**Example files.** The repository’s [`examples/`](../examples/) folder contains sample files for many supported formats (e.g. `examples/trs/sample.trs`, `examples/vert/desam-v20.vert`), typically taken from real corpus projects. Use them to try conversions without your own data.
