# Dates

Flexiconv converts the dates in corpus metadata into **EDTF** (Extended Date/Time Format, ISO 8601-2), a
standard way to write dates that can be uncertain, approximate, partly unknown, or ranges. It writes the
result into the TEI header of the files. Search tools then only have to read EDTF; all the interpretation
happens here, once, where you can check and correct it.

| original | EDTF | meaning |
| --- | --- | --- |
| `02/12/1945` (day first) | `1945-12-02` | a day |
| `[1945]` | `1945` | a year, not written in the text itself |
| `ca. 1550` | `1550~` | approximately 1550 |
| `1945?` | `1945?` | uncertain |
| `1550s` | `155X` | a decade |
| `siglo XVI` | `15XX` or `1501/1600` | a century, by the convention you choose |
| `1712-11-23 - 1734` | `1712-11-23/1734` | somewhere in this range |
| `antes de 1734` | `../1734` | before 1734 |
| `44 BC` | `-0043` | EDTF counts year 0 (= 1 BC) |
| `1364 AH` | `1944-12-17/1945-12-05` | an Islamic year, as Gregorian days |
| `2 de desembre de 1945` | `1945-12-02` | from words (a proposal to check) |

## Command

```bash
flexiconv dates [PATH ...] [OPTIONS]      # files or directories; inside a TEITOK project: xmlfiles/
flexiconv dates --value "ca. 1550" --value "siglo XVI" --century hundreds   # try values
```

**Nothing is written without `--write`.** Without it you get the review table (TSV on stdout, or
`--report FILE`, `.json` for JSON), with for every date element: the original, the EDTF value, the earliest
and latest day, the precision, the best guess, the rule that read it, notes, and what would happen.

Optional packages: calendar conversion needs `convertdate`, dates in words need `dateparser`:

```bash
pip install 'flexiconv[dates]'
```

## Declaring how your dates are written

Flexiconv does not guess conventions. When a reading depends on something you did not declare,
the result is marked `review` and is not written (unless `--accept-review`).

| option | for | example |
| --- | --- | --- |
| `--order DMY\|MDY\|YMD` | numeric dates such as `02/12/1945` | without it, only unambiguous ones (`13/02/1945`) are read; others give the year and `review` |
| `--pattern '%d/%m/%Y %H:%M'` | exact formats, repeatable, first match wins | for a corpus that mixes `27/6/2025 22:57:11` and `6/27/25 22:26` |
| `--two-digit-century 19` | two-digit years | `25` = 1925 |
| `--century ordinal\|hundreds` | `XVI`, `siglo XVI`, `16th c.` | ordinal: 1501–1600; hundreds: 1500–1599 |
| `--round-years hundreds` | a bare round year standing for a whole period | `1600` = 1600–1699 (`16XX`) |
| `--slash-years dual\|range` | `1712/13` | dual dating (= 1713) or a range |
| `--calendar NAME` | source dates in another calendar | `julian`, `hebrew`, `islamic`, `persian`, … (`--list-calendars`) |
| `--julian-until 1582-10-04` | Julian dates up to the switch, Gregorian after | |
| `--year-start 03-25` | years starting on 25 March (old style) | 10 Feb 1712 → 1713-02-10 |
| `--language es,ca` | dates in words | always `review` unless `--accept-text` |
| `--format READER` | which readers to use, in order | `edtf pattern iso numeric year century decade unspecified words` |

The same settings can go in a JSON file, `--profile corpus-dates.json` (keys as the options, with `_`):

```json
{"order": "DMY", "century": "hundreds", "languages": ["es"], "calendar": "julian", "julian_until": "1582-10-04"}
```

Calendars are those of [convertdate](https://pypi.org/project/convertdate/). A day converts to a day;
a month or year of a calendar whose years do not match Gregorian ones becomes the range of days it
covers. Julian months and years keep their number. Times keep the time zone they were written with:
for historical material the local date is the date.

Some things are read without any declaration: brackets (`[1945]`, marked implicit), "about" words
(`ca.`, `c.`, `circa`, `hacia`, `um`, `vers`, …), `?` and `~`, era words (`BC`, `a.C.`, `AD`, `AH`),
ranges (`1712-1734`, `1933-40`, `entre 1700 y 1720`), open ranges (`antes de 1734`, `after 1712`),
unknown digits (`15XX`, `15..`), decades (`1550s`), and no-date markers (`s.f.`, `n.d.`, `unknown`).

## Where the dates are, and what is written

By default the date is TEITOK's text date, `teiHeader/profileDesc/settingDesc/setting/date`. Use
`--element` for another one: a path from the root (`teiHeader/fileDesc/publicationStmt/date`) or with
`//` for any depth (`//setting/date`, `//sourceDesc//date[@type='original']`).

The original value is `@when` if the element has one, else `@from`/`@to` (or `@notBefore`/`@notAfter`),
else its text; `--source text` or `--source attr:NAME` choose explicitly.

On that element Flexiconv sets:

- **`@when-custom`** with the EDTF value, and **`@datingMethod`** pointing to the EDTF standard. Use
  `--edtf-attr NAME` when `@when-custom` is already used for something else (ODE keeps its Roman
  century there).
- **`@when`** with the best guess, only when the element has no `@when` and no range attributes (in
  TEITOK, `@when` is the best-guess year). The best guess is the date itself, or the middle year of a
  range or coarse date (marked `best_derived` in the table). Your own best guess stays: an existing
  `@when` is never changed. `--no-best` leaves it out.
- **`@notBefore` / `@notAfter`** for ranges and coarse dates, only where there is no `@when` (TEI does
  not allow both; the EDTF value holds the range anyway). `--no-range` leaves them out.

An attribute that already holds a different value is a **conflict**: reported, not changed (unless
`--overwrite`). `--check-attr NAME` compares the result with a date in another attribute and marks
disagreements for review (for example `--check-attr when-custom` on ODE, against its Roman centuries).

A missing element is created, with its missing parents and the original wording as its text, when you
give the dates in a table: `--values dates.tsv` with lines `file<TAB>date` (file by path, name, or name
without `.xml`).

**The files are otherwise left exactly as they were.** Flexiconv changes only the date's start tag (or
inserts the new element), checks that every byte outside it is unchanged and that the file still
parses, and writes through a temporary file. A file that does not pass is left alone and reported as
`error`. Running the same command again changes nothing. Only UTF-8 files are edited.

## Reviewing and correcting

1. Run without `--write` and save the table: `flexiconv dates --report dates.tsv …`.
2. Look at the rows with status `review`, `failed` and action `conflict`. Put the right EDTF value in the
   `edtf` column of the rows you want to correct.
3. Run again with `--fixes dates.tsv --write`. A corrected row applies to that file; a fixes file with
   only `original<TAB>edtf` lines applies to every file with that original value. A fix is taken as it
   is, without further checks.

## Statuses and actions

| status | meaning |
| --- | --- |
| `ok` | read by declared or unambiguous rules |
| `review` | a proposal: something was not declared, came from words, or disagrees with `--check-attr` |
| `failed` | not readable |
| `empty` | no date, or an explicit "no date" |

| action | meaning |
| --- | --- |
| `would write` / `written` | the attributes in the table are (to be) set |
| `unchanged` | the file already has them |
| `needs review` | not written; correct it, or use `--accept-review` |
| `conflict` | an attribute holds something else; see the notes |
| `not read` / `no date` / `no element` | nothing to write |
| `error` | the file could not be read or safely edited; it was left as it was |

## From Python

```python
from flexiconv.dates import Profile, convert_date

r = convert_date("1712-11-23 - 1734", Profile(order="DMY"))
r.status, r.edtf, r.earliest, r.latest, r.best   # 'ok', '1712-11-23/1734', '1712-11-23', '1734-12-31', '1723'
```

Other tools (an indexer, for example) can call `convert_date` while they work. Converting beforehand
with `flexiconv dates` is still the better route: the results can be checked and corrected in the files.
If you do convert on the fly, use a declared profile and treat `review` results as undated.

Test data for anything that reads EDTF is in `data/dates/` (`edtf-bounds.tsv`: values with their earliest
and latest day).
