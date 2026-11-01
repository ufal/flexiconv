"""Source calendars and year starts → proleptic Gregorian, via convertdate.

Only the calendars convertdate offers are supported. A day converts to a day; a month or year
of a calendar whose years do not line up with Gregorian ones (Hebrew, Islamic, …) becomes the
interval of Gregorian days it covers. Julian months and years keep their number: the year
label is the same, and a ten-day shift at the edges is not what anyone dates by.
"""
from __future__ import annotations

import importlib
import inspect
from typing import Optional

from .model import Interval, Point, Value

# The first month of the year, where it is not 1 (Hebrew years start in Tishrei).
_FIRST_MONTH = {"hebrew": 7}


def available() -> list:
    try:
        import convertdate  # noqa: F401
    except ImportError:
        return []
    import pkgutil
    import convertdate as cd
    out = []
    for m in pkgutil.iter_modules(cd.__path__):
        if m.name in ("gregorian", "utils", "data", "holidays", "daycount", "julianday", "ordinal", "iso"):
            continue
        mod = importlib.import_module("convertdate." + m.name)
        # only calendars with years, months and days (not the Maya long count or day counts)
        if hasattr(mod, "to_jd") and hasattr(mod, "from_jd") and \
                list(inspect.signature(mod.to_jd).parameters)[:3] == ["year", "month", "day"]:
            out.append(m.name)
    return sorted(out)


def _module(name: str):
    try:
        import convertdate  # noqa: F401
    except ImportError as e:
        raise RuntimeError(f"calendar {name!r} needs convertdate: pip install 'flexiconv[dates]'") from e
    if name not in available():
        raise ValueError(f"unknown calendar {name!r} (convertdate has: {', '.join(available())})")
    return importlib.import_module("convertdate." + name)


def _gregorian(jd: float) -> Point:
    from convertdate import gregorian
    y, m, d = gregorian.from_jd(jd)
    return Point(int(y), int(m), int(d))


def _month_end_jd(mod, y: int, m: int) -> float:
    for d in (31, 30, 29, 28):
        try:
            if tuple(int(x) for x in mod.from_jd(mod.to_jd(y, m, d))) == (y, m, d):
                return mod.to_jd(y, m, d)
        except (ValueError, IndexError):
            continue
    raise ValueError(f"no month {m} in year {y}")


def _convert_point(p: Point, name: str, notes: list) -> Value:
    mod = _module(name)
    if p.unspecified:
        notes.append(f"{name} date with unknown digits kept as written")
        return p
    if p.day:
        g = _gregorian(mod.to_jd(p.year, p.month, p.day))
        return Point(g.year, g.month, g.day, qual=p.qual, time=p.time)
    if name == "julian":
        notes.append("julian month/year kept as written")
        return p
    if p.month:
        start = mod.to_jd(p.year, p.month, 1)
        end = _month_end_jd(mod, p.year, p.month)
    else:
        first = _FIRST_MONTH.get(name, 1)
        start = mod.to_jd(p.year, first, 1)
        end = mod.to_jd(p.year + 1, first, 1) - 1
    return Interval(_gregorian(start).with_qual(p.qual), _gregorian(end).with_qual(p.qual))


def _shift_year_start(p: Point, year_start: str) -> Point:
    """Old-style years (start 25 March): 10 Feb 1712 is 10 Feb 1713 in a January-start year."""
    sm, sd = (int(x) for x in year_start.split("-"))
    if p.day and (p.month, p.day) < (sm, sd):
        return Point(p.year + 1, p.month, p.day, p.unspecified, p.qual, p.time)
    return p


def _before_switch(p: Point, until: Optional[str]) -> bool:
    if until is None:
        return True
    y, m, d = (int(x) for x in until.split("-"))
    return p.earliest() <= (y, m, d)


def to_gregorian(v: Value, calendar: Optional[str], julian_until: Optional[str],
                 year_start: Optional[str], notes: list) -> Value:
    def one(p: Optional[Point]) -> Optional[Value]:
        if p is None:
            return None
        if year_start:
            p = _shift_year_start(p, year_start)
        if not calendar or calendar == "gregorian":
            return p
        if calendar == "julian" and not _before_switch(p, julian_until):
            return p
        return _convert_point(p, calendar, notes)

    if isinstance(v, Interval):
        a, b = one(v.start), one(v.end)
        a = a.start if isinstance(a, Interval) else a
        b = b.end if isinstance(b, Interval) else b
        return Interval(a, b)
    return one(v)
