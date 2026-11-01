# Date test data

Self-authored fixtures for `flexiconv dates` and for every tool that reads EDTF (pando).

- `edtf-bounds.tsv`: EDTF values with their earliest and latest day and their precision
  (`-` = open end). A reader of EDTF agrees with flexiconv when it gives the same three columns
  for each row. Years are astronomical, as in EDTF: `-0043` is 44 BC, `0000` is 1 BC.
- `conversions.tsv`: original values, the profile settings used (JSON), and the expected status
  and EDTF value.
