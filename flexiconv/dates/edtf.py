"""EDTF (ISO 8601-2) for the subset flexiconv writes and pando reads.

Covered: level 0 (dates, date-times, intervals) and the level-1 parts that corpus dates need:
long years (Y12345), unspecified year digits (156X, 15XX), qualifiers (? ~ %), and open
interval ends (..). Seasons, sets and level-2 features are not read.
"""
from __future__ import annotations

from typing import Optional

from .model import Interval, Point, Value, Ymd, days_in_month

QUALS = "?~%"


def _year_str(p: Point) -> str:
    y = p.year
    if abs(y) > 9999:
        return f"Y{y}"
    s = f"{abs(y):04d}"
    if p.unspecified:
        s = s[: -p.unspecified] + "X" * p.unspecified
    return ("-" if y < 0 else "") + s


def point_to_edtf(p: Point) -> str:
    s = _year_str(p)
    if p.month:
        s += f"-{p.month:02d}"
        if p.day:
            s += f"-{p.day:02d}"
            if p.time:
                s += "T" + p.time
    return s + p.qual


def to_edtf(v: Value) -> str:
    if isinstance(v, Interval):
        a = point_to_edtf(v.start) if v.start else ".."
        b = point_to_edtf(v.end) if v.end else ".."
        return f"{a}/{b}"
    return point_to_edtf(v)


def ymd_to_iso(d: Optional[Ymd]) -> str:
    if d is None:
        return ""
    y, m, dd = d
    ys = f"Y{y}" if abs(y) > 9999 else (("-" if y < 0 else "") + f"{abs(y):04d}")
    return f"{ys}-{m:02d}-{dd:02d}"


def _digits(s: str) -> bool:
    return s != "" and all("0" <= c <= "9" for c in s)


def _parse_time(t: str) -> Optional[str]:
    """hh:mm:ss with an optional Z or ±hh[:mm] zone; returned as given."""
    core, zone = t, ""
    if core.endswith("Z"):
        core, zone = core[:-1], "Z"
    else:
        for i in range(len(core) - 1, 0, -1):
            if core[i] in "+-":
                core, zone = core[:i], core[i:]
                break
    parts = core.split(":")
    if len(parts) != 3 or not all(len(x) == 2 and _digits(x) for x in parts):
        return None
    h, mi, se = (int(x) for x in parts)
    if h > 23 or mi > 59 or se > 60:
        return None
    if zone and zone != "Z":
        z = zone[1:].split(":")
        if not (1 <= len(z) <= 2 and all(len(x) == 2 and _digits(x) for x in z)):
            return None
    return t


def parse_point(s: str) -> Optional[Point]:
    """One EDTF date (no interval)."""
    if not s:
        return None
    qual = ""
    while s and s[-1] in QUALS:
        qual = s[-1] + qual
        s = s[:-1]
    if len(qual) > 1:
        return None
    time = None
    if "T" in s:
        s, t = s.split("T", 1)
        time = _parse_time(t)
        if time is None:
            return None
    neg = s.startswith("-")
    if neg:
        s = s[1:]
    if s.startswith("Y"):
        body = s[1:].split("-")[0]
        if not _digits(body) or len(body) < 5 or "-" in s[1:]:
            return None
        y = int(body)
        return Point(-y if neg else y, qual=qual)
    parts = s.split("-")
    if len(parts) > 3 or len(parts[0]) != 4:
        return None
    ys = parts[0]
    unspec = len(ys) - len(ys.rstrip("X"))
    if unspec and len(parts) > 1:
        return None
    if unspec > 3 or not _digits(ys[: 4 - unspec]) or not ys.rstrip("X") == ys[: 4 - unspec]:
        return None
    y = int(ys[: 4 - unspec] + "0" * unspec)
    if neg:
        y = -y
    month = day = None
    if len(parts) > 1:
        if len(parts[1]) != 2 or not _digits(parts[1]):
            return None
        month = int(parts[1])
        if not 1 <= month <= 12:
            return None
    if len(parts) > 2:
        if len(parts[2]) != 2 or not _digits(parts[2]):
            return None
        day = int(parts[2])
        if not 1 <= day <= days_in_month(y, month):
            return None
    if time is not None and day is None:
        return None
    return Point(y, month, day, unspec, qual, time)


def parse(s: str) -> Optional[Value]:
    """An EDTF string as a Point or Interval; None when it is not (supported) EDTF."""
    s = (s or "").strip()
    if not s:
        return None
    if "/" in s:
        a, _, b = s.partition("/")
        if "/" in b:
            return None
        start = None if a in ("..", "") else parse_point(a)
        end = None if b in ("..", "") else parse_point(b)
        if (start is None and a not in ("..", "")) or (end is None and b not in ("..", "")):
            return None
        if start is None and end is None:
            return None
        if start and end and start.earliest() > end.latest():
            return None
        return Interval(start, end)
    return parse_point(s)


def is_edtf(s: str) -> bool:
    return parse(s) is not None
