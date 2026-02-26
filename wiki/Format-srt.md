# SRT subtitles (`srt`)

## Tool and format

- **Format name**: SubRip Subtitle format (SRT); plain-text with numbered cues and timecodes. No single “tool” owner; used by many players and editors.
- **Format specification**: De facto standard; see e.g. [Wikipedia SRT](https://en.wikipedia.org/wiki/SubRip); file extension `.srt`.

## Origin and purpose

- **Origin**: SubRip subtitle format. Plain-text with numbered cue blocks, timecodes, and text lines. Common for video subtitles.
- **Role in Flexiconv**: import SRT as TEITOK-style TEI with `<u start="..." end="...">` per subtitle and a `recordingStmt` when media is referenced or inferred.

Handled by `flexiconv/io/srt.py`.

## Minimal example

```
1
00:00:00,000 --> 00:00:02,500
Hello world.

2
00:00:02,500 --> 00:00:05,000
Second subtitle.
```

## Conversion semantics

- **Reading (`srt` input)**:
  - Each cue → one `<u>` with `start` and `end` in seconds (or TEI time format). Text inside the cue becomes tokenised `<tok>` inside that `<u>`.
  - Optional link to media can be stored in `recordingStmt` when available or configured.

- **Writing (`srt` output)**:
  - Flexiconv can write SRT from TEI that has time-aligned `<u>` (e.g. from ELAN, TRS, or TextGrid import). Use `-t srt` to export.
