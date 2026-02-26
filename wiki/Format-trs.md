# Transcriber TRS (`trs`)

## Tool and format

- **Tool**: [Transcriber](https://trans.sourceforge.net/) (speech segmentation and transcription tool).
- **Full format name**: Transcriber transcription format (TRS); XML with `Trans`, `Episode`, `Section`, `Turn`, `Sync`.
- **Format specification**: The [Transcriber format](https://trans.sourceforge.net/) is documented on the project site; file extension `.trs`.

## Origin and purpose

- **Origin**: Transcriber (tool for segmenting and transcribing speech). `.trs` is an XML format with `Episode` / `Section` / `Turn` and `Sync` elements for time alignment.
- **Role in Flexiconv**: import TRS files into TEITOK-style TEI with `<u>` (or `<ab>`/`<ug>`) and `<tok>` with `start`/`end`, plus `recordingStmt` for the audio file.

Handled by `flexiconv/io/trs.py`.

## Minimal example

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Trans audio_filename="sample.wav">
  <Episode>
    <Section startTime="0.0" endTime="2.5">
      <Turn startTime="0.0" endTime="2.5" speaker="spk1">
        <Sync time="0.0"/>
        Hello
        <Sync time="1.2"/>
        world.
      </Turn>
    </Section>
  </Episode>
</Trans>
```

## Conversion semantics

- **Reading (`trs` input)**:
  - `Turn` → utterance spans; `Sync` time points segment the text into tokens with `start`/`end` on `<tok>`.
  - `audio_filename` (or equivalent) → `recordingStmt/media` in the TEI header.
  - Structure is reflected as `<ab>`/`<ug>`/`<u>` with time attributes; tokens get `start`/`end` where Sync points allow.

- **Writing (`trs` output)**:
  - Not implemented; conversion is one-way to TEITOK TEI.
