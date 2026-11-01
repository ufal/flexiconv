"""Coarse dates: centuries (XVI, siglo XVI, 16th c.), decades (1550s), unknown digits (15XX)."""
from __future__ import annotations

from typing import Optional

from ..model import Interval, Point
from ..profile import Profile
from ..vocab import CENTURY_WORDS, ORDINAL_SUFFIXES
from . import Hit

ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
_ROMAN_PARTS = ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
                (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"))


def roman_to_int(s: str) -> Optional[int]:
    s = s.upper()
    if not s or any(c not in ROMAN for c in s):
        return None
    total = 0
    for i, c in enumerate(s):
        v = ROMAN[c]
        total += -v if i + 1 < len(s) and ROMAN[s[i + 1]] > v else v
    # only canonical numerals (XIV, not IIII or VX)
    n, out = total, ""
    for val, sym in _ROMAN_PARTS:
        while n >= val:
            out += sym
            n -= val
    return total if out == s and total > 0 else None


def _strip_words(text: str) -> str:
    """Take century words off both ends: "siglo XVI", "s.XVI", "XVI century", "16th c."."""
    t = text.strip()
    low = t.lower()
    for w in sorted(CENTURY_WORDS, key=len, reverse=True):
        if low.startswith(w) and (w.endswith(".") or len(t) == len(w) or not t[len(w)].isalpha()):
            t = t[len(w):].strip()
            low = t.lower()
            break
    for w in sorted(CENTURY_WORDS, key=len, reverse=True):
        if low.endswith(w) and len(t) > len(w) and not t[-len(w) - 1].isalpha():
            t = t[: -len(w)].strip()
            break
    return t


def _century_number(t: str) -> Optional[int]:
    n = roman_to_int(t)
    if n is not None:
        return n
    low = t.lower()
    for suf in sorted(ORDINAL_SUFFIXES, key=len, reverse=True):
        if low.endswith(suf) and low[: -len(suf)].isdigit():
            return int(low[: -len(suf)])
    return None


def read_century(text: str, profile: Profile) -> Optional[Hit]:
    t = _strip_words(text)
    if t.isdigit():
        # a bare number is a year, not a century, unless a century word said otherwise
        if t == text.strip():
            return None
        n = int(t)
    else:
        n = _century_number(t)
    if n is None or not 1 <= n <= 30:
        return None
    convention, review, notes = profile.century, False, []
    if convention is None:
        convention, review = "hundreds", True
        notes.append("century convention not declared (century); read as hundreds")
    if convention == "ordinal":
        value = Interval(Point((n - 1) * 100 + 1), Point(n * 100))
    else:
        value = Point((n - 1) * 100, unspecified=2)
    return Hit(value, "century " + convention, review=review, notes=notes)


def read_decade(text: str, profile: Profile) -> Optional[Hit]:
    """1550s, 1550's, 1550-ies; 1500s is the century (1500–1599), as in English usage."""
    t = text.strip()
    low = t.lower()
    for suf in ("'s", "’s", "s", "-ies", "ies"):
        if low.endswith(suf) and low[: -len(suf)].isdigit():
            num = low[: -len(suf)]
            break
    else:
        return None
    if len(num) != 4 or not num.endswith("0"):
        return None
    y = int(num)
    if y % 100 == 0:
        return Hit(Point(y, unspecified=2), "decade", review=True,
                   notes=[f"{t} read as the hundred years from {y}; a decade would be {num[:3]}X"])
    return Hit(Point(y, unspecified=1), "decade")


def read_unspecified(text: str, profile: Profile) -> Optional[Hit]:
    """Years with unknown last digits: 15XX, 15xx, 15.., 15--, 15__, 15??."""
    t = text.strip()
    if len(t) != 4:
        return None
    head = t.rstrip("Xx.-_?")
    k = 4 - len(head)
    if not 1 <= k <= 3 or not head.isdigit():
        return None
    tail = t[len(head):]
    if len(set(tail)) != 1:
        return None
    return Hit(Point(int(head + "0" * k), unspecified=k), "unspecified")
