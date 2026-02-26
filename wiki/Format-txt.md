# Plain text (`txt`)

## Origin and purpose

- **Origin**: UTF-8 plain text files (`.txt`).
- **Role in Flexiconv**: simplest input format; used for baseline tokenisation and sentence segmentation.

Handled by `flexiconv/io/txt.py`.

## Minimal example

```text
This is the first sentence.
This is the second sentence.
```

## Conversion semantics

- **Reading (`txt` input)**:
  - Text is read as UTF-8.
  - Sentences are derived based on the `--linebreaks` option when writing `txt`, and punctuation heuristics when mapping to TEITOK:
    - `sentence`: every newline ends a sentence.
    - `paragraph`: blank lines separate paragraphs; punctuation and heuristics decide sentences.
    - `double`: double newlines separate paragraphs.
  - Tokens are created via whitespace tokenisation; `space_after` / tails are reconstructed from original spacing.

- **Writing (`txt` output)**:
  - `tokens` and `sentences` are rendered back to plain text.
  - The `--linebreaks` option controls whether sentences or paragraphs become lines, and whether blank lines separate blocks.

