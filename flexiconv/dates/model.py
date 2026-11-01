"""Date values as the converters see them: points, intervals, and the result of one conversion.

Everything is proleptic Gregorian once conversion is done; other calendars are converted on
the way in (calendars.py). Years use astronomical numbering (year 0 = 1 BC), as EDTF does.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Optional, Tuple, Union

Ymd = Tuple[int, int, int]


def is_leap(y: int) -> bool:
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


def days_in_month(y: int, m: int) -> int:
    if m == 2:
        return 29 if is_leap(y) else 28
    return 30 if m in (4, 6, 9, 11) else 31


@dataclass(frozen=True)
class Point:
    """One date at year, month or day precision.

    `unspecified` is the number of trailing year digits that are unknown (155X = 1,
    15XX = 2); `qual` is the EDTF qualifier ('', '?' uncertain, '~' approximate, '%' both);
    `time` is kept verbatim when a full date carries one (hh:mm:ss with an optional zone).
    """

    year: int
    month: Optional[int] = None
    day: Optional[int] = None
    unspecified: int = 0
    qual: str = ""
    time: Optional[str] = None

    def earliest(self) -> Ymd:
        y = self.year
        if self.unspecified:
            unit = 10 ** self.unspecified
            y = (y // unit) * unit if y >= 0 else -((-y // unit) * unit + unit - 1)
        return (y, self.month or 1, self.day or 1)

    def latest(self) -> Ymd:
        y = self.year
        if self.unspecified:
            unit = 10 ** self.unspecified
            y = (y // unit) * unit + unit - 1 if y >= 0 else -((-y // unit) * unit)
        m = self.month or 12
        return (y, m, self.day or days_in_month(y, m))

    def precision(self) -> str:
        if self.unspecified == 1:
            return "decade"
        if self.unspecified == 2:
            return "century"
        if self.unspecified:
            return "millennium"
        if self.day:
            return "day"
        if self.month:
            return "month"
        return "year"

    def is_plain(self) -> bool:
        """A date that XSD (and so TEI @when) can hold as it is."""
        return not self.unspecified and not self.qual

    def with_qual(self, qual: str) -> "Point":
        return replace(self, qual=merge_qual(self.qual, qual))


@dataclass(frozen=True)
class Interval:
    """From `start` to `end`; None is an open end (EDTF '..')."""

    start: Optional[Point]
    end: Optional[Point]

    def earliest(self) -> Optional[Ymd]:
        return self.start.earliest() if self.start else None

    def latest(self) -> Optional[Ymd]:
        return self.end.latest() if self.end else None

    def precision(self) -> str:
        return "interval"

    def with_qual(self, qual: str) -> "Interval":
        return Interval(self.start.with_qual(qual) if self.start else None,
                        self.end.with_qual(qual) if self.end else None)


Value = Union[Point, Interval]


def merge_qual(a: str, b: str) -> str:
    q = set(a.replace("%", "?~")) | set(b.replace("%", "?~"))
    if q >= {"?", "~"}:
        return "%"
    return "".join(sorted(q))


@dataclass
class DateResult:
    """The outcome of converting one original value.

    status: ok (deterministic, declared rules), review (a proposal a curator should confirm),
    failed (nothing readable), empty (no date given, or an explicit "no date").
    """

    original: str
    status: str
    value: Optional[Value] = None
    edtf: str = ""
    earliest: str = ""
    latest: str = ""
    precision: str = ""
    best: str = ""
    best_derived: bool = False
    implicit: bool = False
    rule: str = ""
    notes: list = field(default_factory=list)

    def as_row(self) -> dict:
        return {
            "original": self.original,
            "status": self.status,
            "edtf": self.edtf,
            "earliest": self.earliest,
            "latest": self.latest,
            "precision": self.precision,
            "best": self.best,
            "best_derived": "1" if self.best_derived else "",
            "implicit": "1" if self.implicit else "",
            "rule": self.rule,
            "notes": "; ".join(self.notes),
        }
