"""Dates written out in words ("2 de desembre de 1945"), via dateparser.

Always a proposal (review) unless the profile accepts them: the parser can misread prose, and a
curator should see what it made of it. Runs only when the profile names its languages.
"""
from __future__ import annotations

from typing import Optional

from ..model import Point
from ..profile import Profile
from . import Hit

_PARSERS: dict = {}


def _parser(languages: tuple):
    if languages not in _PARSERS:
        try:
            from dateparser.date import DateDataParser
        except ImportError as e:  # pragma: no cover - depends on the extra
            raise RuntimeError("dates written in words need dateparser: pip install 'flexiconv[dates]'") from e
        # a fixed reference date, so missing parts never come from "today"
        _PARSERS[languages] = DateDataParser(languages=list(languages), settings={
            "PREFER_DAY_OF_MONTH": "first", "RELATIVE_BASE": __import__("datetime").datetime(1, 1, 1),
            "REQUIRE_PARTS": ["year"], "RETURN_TIME_AS_PERIOD": True,
        })
    return _PARSERS[languages]


def _as_point(data) -> Optional[Point]:
    if data is None or data.date_obj is None:
        return None
    d, period = data.date_obj, data.period
    if period == "year":
        return Point(d.year)
    if period == "month":
        return Point(d.year, d.month)
    return Point(d.year, d.month, d.day)


def _parse(text: str, languages: tuple):
    return _parser(languages).get_date_data(text)


def _is_month(word: str, languages: tuple) -> bool:
    d = _parse(f"{word} 2000", languages)
    return d is not None and d.date_obj is not None and d.period == "month" and d.date_obj.year == 2000


def _compact(text: str, languages: tuple) -> Optional[Point]:
    """Keep only numbers and month names: "El dia 2 de desembre del año del Señor 1945" → "2 desembre 1945"."""
    kept = [w.strip(",.;:") for w in text.split()]
    kept = [w for w in kept if w.isdigit() or (w.isalpha() and len(w) > 2 and _is_month(w, languages))]
    if not any(w.isdigit() and len(w) >= 3 for w in kept):
        return None
    if not any(w.isalpha() for w in kept):
        # numbers only: without a month name, a day number is not readable; keep the year
        years = [w for w in kept if len(w) >= 3]
        return Point(int(years[0])) if len(years) == 1 else None
    return _as_point(_parse(" ".join(kept), languages))


def _search(text: str, languages: tuple) -> Optional[Point]:
    """For prose around a date: numbers and month names only, else the longest part that parses."""
    p = _compact(text, languages)
    if p is not None:
        return p
    words = text.split()
    for size in range(len(words), 0, -1):
        for start in range(0, len(words) - size + 1):
            chunk = " ".join(words[start:start + size])
            if not any(c.isdigit() for c in chunk):
                continue
            p = _as_point(_parse(chunk, languages))
            if p is not None:
                return p
    return None


def read_words(text: str, profile: Profile) -> Optional[Hit]:
    if not profile.languages or not any(c.isalpha() for c in text):
        return None
    langs = tuple(profile.languages)
    p = _as_point(_parse(text, langs))
    note = "read from words"
    if p is None:
        if len(text.split()) > 12:
            return None
        p = _search(text, langs)
        note = "read from part of the text"
    if p is None:
        return None
    return Hit(p, "words", review=not profile.accept_text, notes=[note])
