"""flexiconv dates: convert date values to EDTF, in files or one by one.

Without --write nothing is changed: the review table shows what would be written. See
wiki/Dates.md for the whole workflow.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from typing import List

from .calendars import available as calendars_available
from .convert import convert_date
from .profile import Profile
from .report import Fixes, Values, write_json, write_tsv
from .teidates import EDTF_URI, TEITOK_DATE, TeiOptions, process_file


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="flexiconv dates",
        description="Convert dates to EDTF (ISO 8601-2) by declared conventions, and write them into "
                    "the TEI header of existing files without changing anything else. Nothing is "
                    "written without --write.",
    )
    p.add_argument("paths", nargs="*", metavar="PATH",
                   help="XML files or directories (*.xml, recursively). Inside a TEITOK project: xmlfiles/ by default.")
    p.add_argument("--value", action="append", default=[], metavar="TEXT",
                   help="Convert this value and print the result (repeatable); no files are read.")
    p.add_argument("--list-calendars", action="store_true", help="List the calendars that can be converted.")

    g = p.add_argument_group("how the dates are written (the profile)")
    g.add_argument("--profile", metavar="JSON", help="Profile file; the options below override it.")
    g.add_argument("--format", action="append", dest="formats", metavar="READER",
                   help="Readers to use, in order (edtf, pattern, iso, numeric, year, century, decade, unspecified, words).")
    g.add_argument("--pattern", action="append", dest="patterns", metavar="STRPTIME",
                   help="A date pattern such as '%%d/%%m/%%Y %%H:%%M' (repeatable; first match wins).")
    g.add_argument("--order", choices=["DMY", "MDY", "YMD"], help="Order of numeric dates such as 02/12/1945.")
    g.add_argument("--two-digit-century", type=int, metavar="NN", help="Century of two-digit years (19: 25 = 1925).")
    g.add_argument("--century", choices=["ordinal", "hundreds"],
                   help="Centuries: ordinal (XVI = 1501-1600) or hundreds (XVI = 1500-1599).")
    g.add_argument("--round-years", choices=["hundreds"], help="A bare round year (1600) stands for 1600-1699.")
    g.add_argument("--slash-years", choices=["dual", "range"], help="1712/13: dual dating (= 1713) or a range.")
    g.add_argument("--calendar", metavar="NAME", help="Calendar of the source dates (see --list-calendars).")
    g.add_argument("--julian-until", metavar="YYYY-MM-DD", help="With --calendar julian: last Julian day (e.g. 1582-10-04).")
    g.add_argument("--year-start", metavar="MM-DD", help="Start of the civil year in the source (03-25 = Annunciation style).")
    g.add_argument("--language", metavar="LANGS", help="Languages of dates in words, comma-separated (es,ca,pt).")
    g.add_argument("--accept-text", action="store_true", help="Accept dates read from words without review.")

    t = p.add_argument_group("where the dates are in the files")
    t.add_argument("--element", default=None, metavar="PATH",
                   help=f"Date element: a path from the root, or //name/name anywhere (default: {TEITOK_DATE}).")
    t.add_argument("--source", default=None, metavar="WHERE",
                   help="Original value: auto (@when, else the text), text, or attr:NAME.")
    t.add_argument("--values", metavar="TSV", help="Dates from a table (file<TAB>date); creates missing elements.")
    t.add_argument("--edtf-attr", default=None, metavar="NAME", help="Attribute for the EDTF value (default when-custom).")
    t.add_argument("--dating-method", default=None, metavar="URI",
                   help=f"Value of @datingMethod ('' to leave it out; default {EDTF_URI}).")
    t.add_argument("--no-best", action="store_true", help="Do not add @when (the best guess) where it is missing.")
    t.add_argument("--no-range", action="store_true", help="Do not add @notBefore / @notAfter.")
    t.add_argument("--check-attr", metavar="NAME", help="Flag results that disagree with the date in this attribute.")

    w = p.add_argument_group("review and writing")
    w.add_argument("--fixes", metavar="TSV", help="Corrections: the review table with edited edtf column, or original<TAB>edtf.")
    w.add_argument("--accept-review", action="store_true", help="Also write results marked review.")
    w.add_argument("--overwrite", action="store_true", help="Replace attributes that already hold another value.")
    w.add_argument("--write", action="store_true", help="Change the files (default: only report).")
    w.add_argument("--report", metavar="FILE", help="Write the review table here (.json for JSON; default: stdout).")
    w.add_argument("--json", action="store_true", help="Report as JSON.")
    return p


def _profile(a) -> Profile:
    base = Profile.from_json(a.profile).__dict__ if a.profile else {}
    over = {
        "formats": a.formats, "patterns": a.patterns, "order": a.order,
        "two_digit_century": a.two_digit_century, "century": a.century, "round_years": a.round_years,
        "slash_years": a.slash_years, "calendar": a.calendar, "julian_until": a.julian_until,
        "year_start": a.year_start,
        "languages": [x.strip() for x in a.language.split(",") if x.strip()] if a.language else None,
        "accept_text": a.accept_text or None,
    }
    merged = {**base, **{k: v for k, v in over.items() if v is not None}}
    return Profile.from_dict(merged)


def _options(a) -> TeiOptions:
    o = TeiOptions()
    if a.element:
        o.element = a.element
    if a.source:
        o.source = a.source
    if a.edtf_attr:
        o.edtf_attr = a.edtf_attr
    if a.dating_method is not None:
        o.dating_method = a.dating_method
    o.write_best = not a.no_best
    o.write_range = not a.no_range
    o.check_attr = a.check_attr
    o.accept_review = a.accept_review
    o.overwrite = a.overwrite
    return o


def _files(paths: List[str]) -> List[str]:
    out = []
    for p in paths:
        if os.path.isdir(p):
            for d, _, names in os.walk(p):
                out += [os.path.join(d, n) for n in sorted(names) if n.lower().endswith(".xml")]
        else:
            out.append(p)
    return out


def _default_paths() -> List[str]:
    from ..io.teitok_xml import _find_teitok_project_root
    root = _find_teitok_project_root(os.getcwd())
    if root and os.path.isdir(os.path.join(root, "xmlfiles")):
        return [os.path.join(root, "xmlfiles")]
    return []


def _run(a, profile: Profile, fixes, values):
    if a.value:
        return [{"source": "--value", **convert_date(v, profile, fixes.general if fixes else None).as_row()}
                for v in a.value]
    paths = a.paths or _default_paths()
    if not paths:
        return None
    opts = _options(a)
    rows = []
    for path in _files(paths):
        rows += process_file(path, profile, opts, fixes=fixes.for_file(path) if fixes else None,
                             value=values.get(path) if values else None, write=a.write)
    return rows


def main(argv: List[str]) -> int:
    a = _parser().parse_args(argv)
    if a.list_calendars:
        cals = calendars_available()
        print("\n".join(cals) if cals else "No calendars: pip install 'flexiconv[dates]'")
        return 0
    try:
        profile = _profile(a)
        fixes = Fixes.load(a.fixes) if a.fixes else None
        values = Values.load(a.values) if a.values else None
    except (OSError, ValueError) as e:
        print(f"flexiconv dates: {e}", file=sys.stderr)
        return 2

    try:
        rows = _run(a, profile, fixes, values)
    except RuntimeError as e:  # a missing optional package
        print(f"flexiconv dates: {e}", file=sys.stderr)
        return 2
    if rows is None:
        print("flexiconv dates: give files or a directory (or run inside a TEITOK project)", file=sys.stderr)
        return 2

    out = open(a.report, "w", encoding="utf-8") if a.report else sys.stdout
    try:
        if a.json or (a.report and a.report.lower().endswith(".json")):
            write_json(rows, out)
        else:
            write_tsv(rows, out)
    finally:
        if a.report:
            out.close()
    counts = Counter(r.get("action") or r.get("status") for r in rows)
    print("flexiconv dates: " + ", ".join(f"{k} {n}" for k, n in sorted(counts.items())), file=sys.stderr)
    return 1 if counts.get("error") else 0
