# Praat TextGrid (`textgrid`)

## Tool and format

- **Tool**: [Praat](https://www.fon.hum.uva.nl/praat/) (phonetics software by Paul Boersma and David Weenink).
- **Full format name**: Praat TextGrid format (plain-text, not XML).
- **Format specification**: Described in the [Praat manual](https://www.fon.hum.uva.nl/praat/manual/TextGrid_file_format.html); file extensions `.TextGrid` or `.textgrid`.

## Origin and purpose

- **Origin**: Praat (phonetics software). TextGrid files describe interval tiers and point tiers aligned to a timeline (e.g. words, syllables, phonemes).
- **Role in Flexiconv**: import Praat annotations as TEITOK-style TEI with time-aligned `<u>` (or `<tok>` with `start`/`end` when word-level), and a `recordingStmt` for linked audio.

Handled by `flexiconv/io/textgrid.py`.

## Minimal example (conceptual)

TextGrid is a Praat text format (not XML). Tiers contain intervals with start/end times and labels. Flexiconv produces:

```xml
<u start="0.0" end="1.2" who="words">Hello</u>
<u start="1.2" end="2.0" who="words">world.</u>
```

Word-level tiers can be output as `<tok start="..." end="...">` with optional nested `<syll>`/`<ph>` when syllable/phoneme tiers are present.

## Conversion semantics

- **Reading (`textgrid` input)**:
  - Interval tiers → `<u>` elements (or `<tok>` for word tiers) with `start`/`end` in seconds.
  - Point tiers and nested syllable/phoneme alignment are supported; hierarchy is preserved as `<tok>` containing `<syll>`/`<ph>` where applicable.
  - Linked sound file → `recordingStmt/media`.
  - Spacing between tokens is inferred (no space before punctuation, etc.).

- **Writing (`textgrid` output)**:
  - Not implemented; conversion is one-way to TEITOK TEI.
