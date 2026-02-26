# Formats

This page lists all formats currently supported by Flexiconv, grouped by data type. Each format has its own short page with:

- The **tool** the format comes from (with link) and the **full format name**
- A link to the **format specification** or documentation where available
- A minimal **example**
- How Flexiconv **maps** it to the pivot model and/or TEITOK TEI

Use `flexiconv info formats` for the authoritative, runtime view.

**Example files.** The [`examples/`](../examples/) folder in the repository contains sample files for many of these formats, drawn from real corpus projects. You can use them to try conversions, e.g. `flexiconv examples/vert/desam-v20.vert out.xml` or `flexiconv examples/trs/sample.trs out.xml`.

## TEI / TEITOK

- [TEITOK TEI (`teitok`)](Format-teitok.md)
- [Generic TEI P5 (`tei`)](Format-tei.md)

## Rich text / documents

- [RTF (`rtf`)](Format-rtf.md)
- [Word DOCX (`docx`)](Format-docx.md)
- [HTML (`html`)](Format-html.md)
- [Markdown (`md`)](Format-md.md)
- [Plain text (`txt`)](Format-txt.md)

## Spoken corpora and transcripts

- [ELAN EAF (`eaf`)](Format-eaf.md)
- [Praat TextGrid (`textgrid`)](Format-textgrid.md)
- [EXMARaLDA basic transcription (`exb`)](Format-exb.md)
- [Transcriber TRS (`trs`)](Format-trs.md)
- [CHAT / CLAN (`chat`)](Format-chat.md)
- [SRT subtitles (`srt`)](Format-srt.md)
- [DoReCo ELAN (`doreco`)](Format-doreco.md)

## OCR / page layout

- [hOCR (`hocr`)](Format-hocr.md)
- [PAGE XML (`pagexml`)](Format-pagexml.md)
- [ALTO XML (`alto`)](Format-alto.md)

## Treebanks and corpora

- [CoNLL-U (`conllu`)](Format-conllu.md)
- [Vertical / VRT (`vert`)](Format-vert.md)
- [TCF (`tcf`)](Format-tcf.md)
- [TMX (`tmx`)](Format-tmx.md)
- [FoLiA (`folia`)](Format-folia.md)
- [BRAT stand-off (`brat`)](Format-brat.md)
- [Toolbox interlinear (`tbt`)](Format-tbt.md)

Each page describes both directions where applicable (e.g. read-only vs read/write), and points to the corresponding I/O module under `flexiconv/io/`.

