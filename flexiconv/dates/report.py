"""The review table: written as TSV or JSON, and read back as corrections (fixes) or values.

The curator's loop: run without --write, open the TSV, put the right EDTF in the `edtf` column
of the rows that need it, and run again with --fixes on that file. A fix keyed by file and
original value applies to that file only; one without a file applies to every file.
"""
from __future__ import annotations

import csv
import json
import os
from typing import Dict, Iterable, List, Optional, TextIO

COLUMNS = ["file", "element", "source", "original", "status", "action", "edtf", "earliest", "latest",
           "precision", "best", "best_derived", "implicit", "rule", "notes"]


def _clean(v) -> str:
    return " ".join(str(v if v is not None else "").split())


def write_tsv(rows: Iterable[dict], out: TextIO) -> None:
    out.write("\t".join(COLUMNS) + "\n")
    for r in rows:
        out.write("\t".join(_clean(r.get(c, "")) for c in COLUMNS) + "\n")


def write_json(rows: Iterable[dict], out: TextIO) -> None:
    json.dump([{c: r.get(c, "") for c in COLUMNS} for r in rows], out, ensure_ascii=False, indent=1)
    out.write("\n")


def _norm(s: str) -> str:
    return " ".join((s or "").split())


def _read_table(path: str) -> List[List[str]]:
    with open(path, encoding="utf-8", newline="") as f:
        return [row for row in csv.reader(f, delimiter="\t") if row and any(c.strip() for c in row)]


class Fixes:
    """Curated EDTF values by original value, optionally per file."""

    def __init__(self) -> None:
        self.general: Dict[str, str] = {}
        self.by_file: Dict[str, Dict[str, str]] = {}

    @classmethod
    def load(cls, path: str) -> "Fixes":
        fx = cls()
        rows = _read_table(path)
        if not rows:
            return fx
        head = [h.strip().lower() for h in rows[0]]
        if "original" in head and "edtf" in head:
            oi, ei = head.index("original"), head.index("edtf")
            fi = head.index("file") if "file" in head else None
            body = rows[1:]
        else:
            oi, ei, fi, body = 0, 1, None, rows
        for row in body:
            if len(row) <= max(oi, ei) or not row[ei].strip():
                continue
            orig, val = _norm(row[oi]), row[ei].strip()
            if fi is not None and len(row) > fi and row[fi].strip():
                fx.by_file.setdefault(os.path.normpath(row[fi].strip()), {})[orig] = val
            else:
                fx.general[orig] = val
        return fx

    def for_file(self, path: str) -> Dict[str, str]:
        out = dict(self.general)
        out.update(self.by_file.get(os.path.normpath(path), {}))
        return out


class Values:
    """Dates from outside the files (a metadata spreadsheet): file → original value."""

    def __init__(self, table: Dict[str, str]):
        self.table = table

    @classmethod
    def load(cls, path: str) -> "Values":
        rows = _read_table(path)
        if rows and [h.strip().lower() for h in rows[0][:2]] == ["file", "date"]:
            rows = rows[1:]
        return cls({r[0].strip(): r[1] for r in rows if len(r) >= 2})

    def get(self, path: str) -> Optional[str]:
        """By path as given, then file name, then file name without extension."""
        name = os.path.basename(path)
        for key in (path, os.path.normpath(path), name, os.path.splitext(name)[0]):
            if key in self.table:
                return self.table[key]
        return None
