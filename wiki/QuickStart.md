# Quick start

This page shows common `flexiconv` usage patterns. See [Formats](Formats.md) and the per-format pages for format-specific details.

## Basic usage

```bash
# Auto-detect input format, write TEITOK-style TEI
flexiconv input.ext output.xml

# Explicit input (-f/--from) and output (-t/--to) formats
flexiconv -f conllu -t teitok treebank.conllu treebank.xml
```

## Working with TEITOK projects

Inside a TEITOK project (folder with `Resources/settings.xml`), you can omit the output path:

```bash
cd /path/to/teitok/project

# Writes to xmlfiles/sample.xml (TEITOK-style TEI)
flexiconv Originals/sample.ann
```

Key points:

- Default output format in a TEITOK project is **`teitok`**.
- Originals can be copied into `Originals/` with `--copy-original`.

## Running NLP with flexipipe

Flexiconv can optionally call `flexipipe` right after writing TEITOK XML:

```bash
# Let flexipipe decide everything based on the XML
flexiconv input.docx output.xml -t teitok --flexipipe

# Pass additional flexipipe arguments; {project} is the TEITOK project root
flexiconv Originals/sample.txt -t teitok --teitok-project /path/to/project \
  --flexipipe "--project {project} --language en"
```

This runs:

- `flexipipe [ARGS...] OUTPUT_XML`

so you never repeat the `flexipipe` word or the XML path yourself; you only supply extra arguments when needed.

## Spoken corpora (ELAN, TRS, TextGrid, EXMARaLDA, CHAT, SRT)

```bash
# ELAN EAF → TEITOK
flexiconv -f eaf -t teitok examples/eaf/sample.eaf sample.xml

# Transcriber TRS → TEITOK
flexiconv -f trs -t teitok examples/trs/sample.trs sample.xml

# Praat TextGrid → TEITOK
flexiconv -f textgrid -t teitok examples/textgrid/sample.TextGrid sample.xml
```

Each spoken format has a dedicated wiki page with details:

- [ELAN (`eaf`)](Format-eaf.md)
- [Transcriber (`trs`)](Format-trs.md)
- [Praat TextGrid (`textgrid`)](Format-textgrid.md)
- [EXMARaLDA (`exb`)](Format-exb.md)
- [CHAT (`chat`)](Format-chat.md)
- [SRT (`srt`)](Format-srt.md)

## Treebanks and corpora (CoNLL-U, VRT, TCF, TMX, FoLiA, BRAT)

```bash
# CoNLL-U treebank → TEITOK
flexiconv -f conllu -t teitok treebank.conllu treebank.xml

# Vertical/VRT corpus → TEITOK
flexiconv -f vert -t teitok examples/vert/desam-v20.vert desam-v20.xml

# TCF → TEITOK
flexiconv -f tcf -t teitok examples/tcf/sample.tcf sample.xml
```

See:

- [CoNLL-U (`conllu`)](Format-conllu.md)
- [Vertical/VRT (`vert`)](Format-vert.md)
- [TCF (`tcf`)](Format-tcf.md)
- [TMX (`tmx`)](Format-tmx.md)
- [FoLiA (`folia`)](Format-folia.md)
- [BRAT (`brat`)](Format-brat.md)

## Batch conversion

Convert a whole directory tree:

```bash
# Detect input format per file; write TEITOK XML under out/
flexiconv -R corpora/raw out -t teitok

# Force a single input format for all files
flexiconv -R -f vert corpora/vrt out -t teitok
```

## Help and inspection

```bash
flexiconv info formats          # list all formats with data types
flexiconv info format tcf       # details for a single format
flexiconv convert --help        # full CLI reference
```

## Deduplication

Flexiconv can find **exact** and **near-identical** duplicates among documents (TEITOK XML or any supported format with `--by-content`). You can build a SQLite index (with optional incremental updates) and list duplicate groups for cleanup or to avoid re-ingesting the same content.

```bash
# List exact duplicates from default index (inside a TEITOK project)
flexiconv duplicates

# Scan folders (all supported formats), report duplicate groups
flexiconv duplicates tmp examples --by-content

# Build index and optionally enable near-identical detection
flexiconv duplicates --index --output tmp/deduplication.sqlite --near-identical

# List near-identical groups; JSON output for scripts (e.g. TEITOK)
flexiconv duplicates --from-index tmp/deduplication.sqlite --near-identical --json --quiet
```

See [Deduplication](Deduplication.md) for full details: exact vs near-identical, index format, incremental updates, cross-format comparison, and progress/quiet behaviour.


