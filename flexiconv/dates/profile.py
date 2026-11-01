"""The declared conventions of a corpus (or field, or source): how its dates are to be read.

Nothing here is guessed. A value whose reading depends on a convention the profile does not
declare comes out as `review`, never as a silent choice.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from typing import Optional


@dataclass
class Profile:
    # Readers to try, in order (see readers.REGISTRY); empty = the default chain.
    formats: list = field(default_factory=list)
    # strptime patterns tried before the readers, in order ("%d/%m/%Y %H:%M:%S").
    patterns: list = field(default_factory=list)
    # Order of numeric dates like 02/12/1945: DMY, MDY or YMD; None = only unambiguous ones.
    order: Optional[str] = None
    # Two-digit years: the century to put in front ("19" → 25 = 1925); None = review.
    two_digit_century: Optional[int] = None
    # Roman / numbered centuries: "ordinal" (XVI = 1501–1600) or "hundreds" (XVI = 1500–1599).
    century: Optional[str] = None
    # A bare round year (1600) stands for a whole period: "hundreds" (1600 = 16XX); None = a year.
    round_years: Optional[str] = None
    # "1712/13": "dual" (old-style year start; = 1713) or "range" (1712–1713); None = review.
    slash_years: Optional[str] = None
    # Calendar of the source dates (any convertdate calendar); None = Gregorian.
    calendar: Optional[str] = None
    # With calendar "julian": dates up to and including this day are Julian, later ones Gregorian.
    julian_until: Optional[str] = None
    # Start of the civil year in the source, as MM-DD (03-25 = Annunciation style); None = 01-01.
    year_start: Optional[str] = None
    # Languages for dates written out in words (dateparser codes: es, ca, pt, …).
    languages: list = field(default_factory=list)
    # Accept the proposals of the words reader without review.
    accept_text: bool = False
    # Corpus-specific additions to the word lists in vocab.py.
    extra_approx: list = field(default_factory=list)
    extra_no_date: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "Profile":
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(d) - known)
        if unknown:
            raise ValueError("unknown date profile setting(s): " + ", ".join(unknown))
        p = cls(**{k: v for k, v in d.items() if k in known})
        p.check()
        return p

    @classmethod
    def from_json(cls, path: str) -> "Profile":
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    def check(self) -> None:
        def one_of(name, val, allowed):
            if val is not None and val not in allowed:
                raise ValueError(f"date profile: {name} must be one of {', '.join(allowed)} (got {val!r})")
        one_of("order", self.order, ("DMY", "MDY", "YMD"))
        one_of("century", self.century, ("ordinal", "hundreds"))
        one_of("round_years", self.round_years, ("hundreds",))
        one_of("slash_years", self.slash_years, ("dual", "range"))
        if self.year_start is not None:
            parts = self.year_start.split("-")
            if len(parts) != 2 or not all(x.isdigit() for x in parts):
                raise ValueError(f"date profile: year_start must be MM-DD (got {self.year_start!r})")
        if self.julian_until is not None and self.calendar != "julian":
            raise ValueError("date profile: julian_until needs calendar julian")
