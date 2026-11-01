"""One original date string → EDTF, with its range, best guess and a status.

The general steps (no-date words, brackets, "about" words, qualifiers, era words, ranges and
open ranges) live here; what a date itself looks like is up to the readers. Everything a
reading depends on comes from the Profile; what it does not declare makes the result `review`.
"""
from __future__ import annotations

from typing import Mapping, Optional

from . import edtf
from .calendars import to_gregorian
from .model import DateResult, Interval, Point, Value
from .profile import Profile
from .readers import Hit, chain
from .vocab import AD, AFTER, APPROX_PREFIXES, BC, BEFORE, ERA_CALENDARS, NO_DATE, RANGE_INTROS, RANGE_WORDS

_MAX_DEPTH = 4


def _norm(s: str) -> str:
    return " ".join((s or "").replace(" ", " ").split())


def _strip_prefix(t: str, words) -> "tuple[Optional[str], str]":
    low = t.lower()
    for w in sorted(words, key=len, reverse=True):
        if low.startswith(w):
            rest = t[len(w):]
            if w[-1].isalpha() and rest and rest[0].isalpha():
                continue
            rest = rest.strip()
            if rest:
                return w, rest
    return None, t


def _strip_suffix(t: str, words) -> "tuple[Optional[str], str]":
    low = t.lower()
    for w in sorted(words, key=len, reverse=True):
        if low.endswith(w) and len(t) > len(w):
            before = t[: -len(w)]
            if w[0].isalpha() and before[-1].isalpha():
                continue
            return w, before.strip()
    return None, t


def _span(a: Value, b: Value) -> Interval:
    start = a.start if isinstance(a, Interval) else a
    end = b.end if isinstance(b, Interval) else b
    return Interval(start, end)


def _merge(hit: Hit, value: Value, rule: str, *others: Hit) -> Hit:
    out = Hit(value, rule, hit.review, list(hit.notes), hit.gregorian)
    for o in others:
        out.review = out.review or o.review
        out.gregorian = out.gregorian and o.gregorian
        out.notes += [n for n in o.notes if n not in out.notes]
    return out


class _Reader:
    def __init__(self, profile: Profile):
        self.profile = profile
        self.first, self.last = chain(profile)
        self.approx = tuple(APPROX_PREFIXES) + tuple(profile.extra_approx)

    def plain(self, t: str, readers) -> Optional[Hit]:
        for name, reader in readers:
            hit = reader(t, self.profile)
            if hit is not None:
                return hit
        return None

    def read(self, t: str, depth: int = 0) -> Optional[Hit]:
        t = t.strip().strip(",;").strip()
        if not t or depth > _MAX_DEPTH:
            return None
        hit = self.plain(t, self.first)
        if hit is not None:
            return hit
        for step in (self._approx, self._qualifier, self._era, self._negative, self._open_range, self._range):
            hit = step(t, depth)
            if hit is not None:
                return hit
        return self.plain(t, self.last) if depth == 0 else None

    def _negative(self, t: str, depth: int) -> Optional[Hit]:
        """-44: not EDTF (that needs -0044); astronomical or meant as 44 BC is not clear."""
        if t.startswith("-") and t[1:].isdigit() and len(t) < 5:
            y = -int(t[1:])
            return Hit(Point(y), "year", review=True, notes=[
                f"{t} read as astronomical year {y} (= {1 - y} BC); write '{-y} BC' if {-y} BC is meant"])
        return None

    def _approx(self, t: str, depth: int) -> Optional[Hit]:
        w, rest = _strip_prefix(t, self.approx)
        if w is None:
            return None
        hit = self.read(rest, depth + 1)
        return _merge(hit, hit.value.with_qual("~"), hit.rule) if hit else None

    def _qualifier(self, t: str, depth: int) -> Optional[Hit]:
        for suffix, qual in (("(?)", "?"), ("?", "?"), ("~", "~"), ("%", "%")):
            if t.endswith(suffix) and len(t) > len(suffix):
                hit = self.read(t[: -len(suffix)], depth + 1)
                if hit:
                    return _merge(hit, hit.value.with_qual(qual), hit.rule)
        if t.startswith("?") and len(t) > 1:
            hit = self.read(t[1:], depth + 1)
            if hit:
                return _merge(hit, hit.value.with_qual("?"), hit.rule)
        return None

    def _era_year(self, t: str, depth: int) -> Optional[Hit]:
        """The year before an era word: any number of digits is a year there (44 BC, 711 AH)."""
        if t.isdigit():
            return Hit(Point(int(t)), "year")
        return self.read(t, depth + 1)

    def _era(self, t: str, depth: int) -> Optional[Hit]:
        w, rest = _strip_suffix(t, BC)
        if w is not None:
            hit = self._era_year(rest, depth)
            if hit and isinstance(hit.value, Point) and hit.value.year > 0 and not hit.value.unspecified:
                p = hit.value
                return _merge(hit, Point(1 - p.year, p.month, p.day, 0, p.qual, p.time), hit.rule + " BC")
            return None
        w, rest = _strip_suffix(t, tuple(ERA_CALENDARS))
        if w is not None:
            hit = self._era_year(rest, depth)
            if hit is None:
                return None
            cal = ERA_CALENDARS[w]
            notes = list(hit.notes)
            v = to_gregorian(hit.value, cal, None, None, notes)
            out = Hit(v, f"{hit.rule} {cal}", hit.review, notes + [f"{cal} year ({t})"], gregorian=True)
            return out
        w, rest = _strip_suffix(t, AD)
        if w is None:
            w, rest = _strip_prefix(t, AD)
        if w is not None:
            return self._era_year(rest, depth)
        return None

    def _open_range(self, t: str, depth: int) -> Optional[Hit]:
        for words, side in ((BEFORE, "before"), (AFTER, "after")):
            w, rest = _strip_prefix(t, words)
            if w is None:
                continue
            hit = self.read(rest, depth + 1)
            if hit is None:
                continue
            v = hit.value
            if side == "before":
                end = v.end if isinstance(v, Interval) else v
                return _merge(hit, Interval(None, end), hit.rule + " (before)")
            start = v.start if isinstance(v, Interval) else v
            return _merge(hit, Interval(start, None), hit.rule + " (after)")
        return None

    def _range(self, t: str, depth: int) -> Optional[Hit]:
        _, body = _strip_prefix(t, RANGE_INTROS)
        seps = [" " + w + " " for w in RANGE_WORDS] + ["–", "—", "/", "-"]
        for sep in seps:
            start = 0
            while True:
                i = body.find(sep, start)
                if i <= 0:
                    break
                start = i + 1
                left, right = body[:i].strip(), body[i + len(sep):].strip()
                if not left or not right:
                    continue
                hit = self._pair(left, right, sep.strip(), depth)
                if hit is not None:
                    return hit
        return None

    def _pair(self, left: str, right: str, sep: str, depth: int) -> Optional[Hit]:
        a = self.read(left, depth + 1)
        if a is None:
            return None
        av = a.value
        if right.isdigit() and len(right) <= 2 and isinstance(av, Point) and av.month is None \
                and not av.unspecified and av.year >= 100:
            full = int(str(av.year)[: -len(right)] + right)
            if full <= av.year:
                return None
            if sep == "/" and len(right) <= 2 and full == av.year + 1:
                rule = self.profile.slash_years
                if rule == "dual":
                    return _merge(a, Point(full, qual=av.qual), a.rule + " dual year")
                hit = _merge(a, Interval(av, Point(full, qual=av.qual)), a.rule + " range")
                if rule is None:
                    hit.review = True
                    hit.notes.append(f"{left}/{right}: dual year or range not declared (slash_years); read as a range")
                return hit
            return _merge(a, Interval(av, Point(full, qual=av.qual)), a.rule + " range")
        b = self.read(right, depth + 1)
        if b is None:
            return None
        bv = b.value
        lo = av.earliest()
        hi = bv.latest()
        if lo is None or hi is None or lo > hi:
            return None
        return _merge(a, _span(av, bv), a.rule + " range", b)


def _xsd(p: Point) -> str:
    y = p.year
    ys = str(y) if abs(y) > 9999 else (("-" if y < 0 else "") + f"{abs(y):04d}")
    if p.day:
        return f"{ys}-{p.month:02d}-{p.day:02d}"
    if p.month:
        return f"{ys}-{p.month:02d}"
    return ys


def _best(v: Value) -> "tuple[str, bool]":
    """A best guess TEI @when can hold, and whether it was derived (a midpoint)."""
    if isinstance(v, Point) and not v.unspecified:
        return _xsd(Point(v.year, v.month, v.day)), False
    lo, hi = v.earliest(), v.latest()
    if lo is None or hi is None:
        return "", False
    return _xsd(Point((lo[0] + hi[0]) // 2)), True


def _round_year(v: Value, profile: Profile, notes: list) -> Value:
    if (profile.round_years == "hundreds" and isinstance(v, Point) and v.month is None
            and not v.unspecified and v.year > 0 and v.year % 100 == 0):
        notes.append(f"round year {v.year} read as {v.year}–{v.year + 99} (round_years)")
        return Point(v.year, unspecified=2, qual=v.qual)
    return v


def finish(original: str, v: Value, status: str, rule: str, notes: list, implicit: bool = False) -> DateResult:
    best, derived = _best(v)
    return DateResult(
        original=original, status=status, value=v, edtf=edtf.to_edtf(v),
        earliest=edtf.ymd_to_iso(v.earliest()), latest=edtf.ymd_to_iso(v.latest()),
        precision=v.precision(), best=best, best_derived=derived, implicit=implicit,
        rule=rule, notes=notes,
    )


def convert_date(raw: str, profile: Optional[Profile] = None,
                 fixes: Optional[Mapping[str, str]] = None) -> DateResult:
    """Read one original date value.

    `fixes` maps an original value (whitespace-normalised) to the EDTF a curator decided on;
    such values are taken as they are (rule "fix").
    """
    profile = profile or Profile()
    original = raw if raw is not None else ""
    t = _norm(original)
    if not t:
        return DateResult(original, "empty", rule="empty")
    if fixes and t in fixes:
        v = edtf.parse(fixes[t])
        if v is None:
            return DateResult(original, "failed", rule="fix", notes=[f"fix is not EDTF: {fixes[t]!r}"])
        return finish(original, v, "ok", "fix", [])
    no_date = {w.lower() for w in NO_DATE} | {w.lower() for w in profile.extra_no_date}
    implicit = False
    if t.startswith("[") and t.endswith("]"):
        implicit, t = True, t[1:-1].strip()
    if t.lower() in no_date:
        return DateResult(original, "empty", rule="no date", implicit=implicit)
    hit = _Reader(profile).read(t)
    if hit is None:
        return DateResult(original, "failed", rule="", implicit=implicit, notes=["not read"])
    notes = list(hit.notes)
    v = _round_year(hit.value, profile, notes)
    if not hit.gregorian:
        v = to_gregorian(v, profile.calendar, profile.julian_until, profile.year_start, notes)
    if implicit:
        notes.append("implicit (bracketed)")
    return finish(original, v, "review" if hit.review else "ok", hit.rule, notes, implicit)
