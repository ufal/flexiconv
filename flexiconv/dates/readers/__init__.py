"""Readers: each turns one cleaned-up date string into a Point or Interval, or gives up.

A reader gets the string after the general steps in convert.py (brackets, "about" words,
qualifiers, era words and ranges are already taken off) and the corpus Profile. It returns a
Hit, or None when the string is not its kind. New kinds of dates get a reader of their own and
an entry in REGISTRY.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from ..model import Value
from ..profile import Profile


@dataclass
class Hit:
    value: Value
    rule: str
    review: bool = False
    notes: list = field(default_factory=list)
    # already Gregorian (an era word named its calendar), so the profile calendar is not applied
    gregorian: bool = False


Reader = Callable[[str, Profile], Optional[Hit]]

from . import centuries, numeric, words  # noqa: E402

REGISTRY: "dict[str, Reader]" = {
    "edtf": numeric.read_edtf,
    "iso": numeric.read_iso,
    "pattern": numeric.read_patterns,
    "numeric": numeric.read_numeric,
    "year": numeric.read_bare_year,
    "century": centuries.read_century,
    "decade": centuries.read_decade,
    "unspecified": centuries.read_unspecified,
    "words": words.read_words,
}

# Tried in this order unless the profile lists its own. Readers in LAST run only once the
# general steps (ranges, "before", era words, …) found nothing: "words" would otherwise read
# "entre 1700 y 1720" as 1700. It only runs when the profile names languages.
DEFAULT_CHAIN = ("edtf", "pattern", "iso", "numeric", "year", "century", "decade", "unspecified", "words")
LAST = ("words",)


def chain(profile: Profile) -> "tuple[list, list]":
    """The profile's readers as (first, last) lists of (name, reader)."""
    names = profile.formats or DEFAULT_CHAIN
    unknown = [n for n in names if n not in REGISTRY]
    if unknown:
        raise ValueError("unknown date reader(s): " + ", ".join(unknown)
                         + " (known: " + ", ".join(REGISTRY) + ")")
    first = [(n, REGISTRY[n]) for n in names if n not in LAST]
    last = [(n, REGISTRY[n]) for n in names if n in LAST]
    return first, last
