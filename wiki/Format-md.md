# Markdown (`md`)

## Format

- **Full format name**: Markdown; lightweight markup in plain text. Multiple dialects (CommonMark, GitHub Flavored Markdown, etc.).
- **Format specification**: [CommonMark](https://commonmark.org/); [GitHub Flavored Markdown](https://github.github.com/gfm/). Flexiconv converts Markdown via HTML into structural TEI.

## Origin and purpose

- **Origin**: Markdown text files (`.md`, `.markdown`).
- **Role in Flexiconv**: import Markdown and normalise it via HTML into structural TEI (paragraphs, headings, lists).

Handled by `flexiconv/io/md.py`.

## Minimal example

```markdown
# Title

This is a paragraph with *emphasis* and **strong** text.
```

## Conversion semantics

- **Reading (`md` input)**:
  - Markdown is converted to HTML, then passed through the HTML importer.
  - Headings, paragraphs, lists, and code blocks become `structure` nodes and TEI block elements.
  - Text is imported as structural blocks; tokenisation and sentence splitting are intentionally left to downstream tools (e.g. flexipipe).

- **Writing (`md` output)**:
  - Not a primary output format; use `txt`, `html`, or `tei` / `teitok` for exporting.

