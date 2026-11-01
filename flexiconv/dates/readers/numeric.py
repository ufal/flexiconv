"""Dates written with digits: EDTF/ISO, declared strptime patterns, day-month-year, bare years."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from .. import edtf
from ..model import Point, days_in_month
from ..profile import Profile
from . import Hit

SEPARATORS = "/.-"


def _digits(s: str) -> bool:
    return s != "" and all("0" <= c <= "9" for c in s)


def read_edtf(text: str, profile: Profile) -> Optional[Hit]:
    v = edtf.parse(text)
    return Hit(v, "edtf") if v is not None else None


def _time(rest: str) -> "tuple[Optional[str], list]":
    """A time after a date ("13:02:45", "8:09", "13:02:45.120+02:00"), as EDTF hh:mm:ss[zone]."""
    rest = rest.strip()
    if not rest:
        return None, []
    zone = ""
    if rest.endswith("Z"):
        rest, zone = rest[:-1], "Z"
    else:
        for i in range(len(rest) - 1, 0, -1):
            if rest[i] in "+-" and ":" in rest[:i]:
                rest, zone = rest[:i], rest[i:]
                break
    notes = []
    if "." in rest:
        rest = rest.split(".", 1)[0]
        notes.append("fractions of a second dropped")
    parts = rest.split(":")
    if not (2 <= len(parts) <= 3) or not all(_digits(p) and len(p) <= 2 for p in parts):
        return None, ["time not read: " + rest]
    while len(parts) < 3:
        parts.append("00")
    h, m, s = (int(p) for p in parts)
    if h > 23 or m > 59 or s > 60:
        return None, ["time not read: " + rest]
    if zone and zone != "Z" and len(zone) == 3:
        zone += ":00"
    return f"{h:02d}:{m:02d}:{s:02d}{zone}", notes


def _split_date_time(text: str) -> "tuple[str, str]":
    if "T" in text:
        a, _, b = text.partition("T")
        return a, b
    if " " in text:
        a, _, b = text.partition(" ")
        return a, b
    return text, ""


def _point(y: int, m: int, d: int, time: Optional[str]) -> Optional[Point]:
    if not 1 <= m <= 12 or not 1 <= d <= days_in_month(y, m):
        return None
    return Point(y, m, d, time=time)


def read_iso(text: str, profile: Profile) -> Optional[Hit]:
    """Year-first dates that are not strict EDTF: 1945/12/02, 1945-2-3, 1945-12-02 13:02:45."""
    date, rest = _split_date_time(text)
    sep = next((c for c in date if c in SEPARATORS), None)
    if sep is None:
        return None
    parts = date.split(sep)
    if len(parts) not in (2, 3) or not all(_digits(p) for p in parts) or len(parts[0]) != 4:
        return None
    if not all(1 <= len(p) <= 2 for p in parts[1:]):
        return None
    y, m = int(parts[0]), int(parts[1])
    if len(parts) == 2:
        if rest or not 1 <= m <= 12:
            return None
        return Hit(Point(y, m), "iso")
    time, notes = _time(rest)
    if rest and time is None:
        return None
    p = _point(y, m, int(parts[2]), time)
    return Hit(p, "iso", notes=notes) if p else None


def _year(ys: str, profile: Profile) -> "tuple[Optional[int], bool, list]":
    """A year from a day-month-year date; two-digit years need the declared century."""
    if len(ys) >= 3:
        return int(ys), False, []
    if profile.two_digit_century is not None:
        return profile.two_digit_century * 100 + int(ys), False, []
    return 2000 + int(ys) if int(ys) < 50 else 1900 + int(ys), True, [
        "two-digit year: century not declared (two_digit_century)"]


def read_numeric(text: str, profile: Profile) -> Optional[Hit]:
    """02/12/1945, 2.12.1945, 6/27/25 8:09 — day and month order as declared, or unambiguous."""
    date, rest = _split_date_time(text)
    sep = next((c for c in date if c in SEPARATORS), None)
    if sep is None:
        return None
    parts = date.split(sep)
    if len(parts) != 3 or not all(_digits(p) for p in parts):
        return None
    a, b, ys = parts
    if len(a) > 2 or len(b) > 2 or len(ys) > 4:
        return None
    y, review, notes = _year(ys, profile)
    a, b = int(a), int(b)
    order = profile.order
    if order == "YMD":
        return None
    if order is None:
        if a > 12 and b <= 12:
            order = "DMY"
        elif b > 12 and a <= 12:
            order = "MDY"
        elif a == b:
            order = "DMY"
        else:
            return Hit(Point(y), "numeric", review=True, notes=notes + [
                f"day and month order not declared (order): {a}/{b} could be either; year only"])
    d, m = (a, b) if order == "DMY" else (b, a)
    time, tnotes = _time(rest)
    if rest and time is None:
        return None
    p = _point(y, m, d, time)
    if p is None:
        return None
    return Hit(p, "numeric", review=review, notes=notes + tnotes)


def read_patterns(text: str, profile: Profile) -> Optional[Hit]:
    """The profile's strptime patterns, first match wins (Python's own month names: English)."""
    for pat in profile.patterns:
        try:
            dt = datetime.strptime(text, pat)
        except ValueError:
            continue
        has_day = "%d" in pat or "%j" in pat
        has_month = has_day or any(x in pat for x in ("%m", "%b", "%B"))
        has_time = any(x in pat for x in ("%H", "%I"))
        y = dt.year
        if "%y" in pat and profile.two_digit_century is not None:
            y = profile.two_digit_century * 100 + dt.year % 100
        time = f"{dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}" if has_time and has_day else None
        p = Point(y, dt.month if has_month else None, dt.day if has_day else None, time=time)
        return Hit(p, "pattern " + pat)
    return None


def read_bare_year(text: str, profile: Profile) -> Optional[Hit]:
    """A year alone: 945, 1945, 12345; one or two digits need the declared century."""
    if not _digits(text):
        return None
    if len(text) <= 2:
        if profile.two_digit_century is None:
            return None
        return Hit(Point(profile.two_digit_century * 100 + int(text)), "year")
    return Hit(Point(int(text)), "year")
