"""Words the readers recognise around dates, for the languages corpora mostly come in.

Kept as plain tables so a corpus can add its own (Profile.extra_approx and friends) without
touching the readers. Matching is case-insensitive on whole words.
"""
from __future__ import annotations

# Before a date: "about". Gives the EDTF qualifier '~'.
APPROX_PREFIXES = (
    "ca.", "ca", "c.", "c", "circa", "cca.", "cca", "around", "about", "approx.", "approximately",
    "hacia", "h.", "hacia el año", "hacia el", "aprox.", "aproximadamente", "cerca de",
    "vers", "env.", "environ", "um", "etwa", "ungefähr", "verso", "intorno al", "kolem", "asi",
    "circa.", "rond", "omstreeks", "omtrent", "por volta de", "cerca de",
)

# The whole value says there is no date.
NO_DATE = (
    "s.f.", "s/f", "s. f.", "sin fecha", "s.d.", "s. d.", "sans date", "n.d.", "nd", "no date",
    "unknown", "desconocido", "desconocida", "sconosciuto", "unbekannt", "o.j.", "neznámé",
    "?", "-", "_", "--", "s.a.", "sine anno", "sine dato",
)

# "century" words, after or before a Roman or Arabic number: "siglo XVI", "XVI century", "16th c."
CENTURY_WORDS = (
    "century", "c.", "cent.", "siglo", "s.", "sec.", "secolo", "século", "séc.", "siècle", "s",
    "jahrhundert", "jh.", "jh", "století", "stol.", "eeuw", "e eeuw", "segle",
)

# Ordinal suffixes after an Arabic century number: 16th, 16e, 16.
ORDINAL_SUFFIXES = ("st", "nd", "rd", "th", "e", "ème", "er", ".", "º", "°", "o")

# Between the two ends of a range written out in words.
RANGE_WORDS = ("to", "till", "until", "a", "al", "hasta", "à", "au", "bis", "–", "—", "-", "and", "y", "et", "und")

# Before a range: "between 1700 and 1720", "entre 1700 y 1720".
RANGE_INTROS = ("between", "from", "entre", "de", "desde", "del", "zwischen", "von", "mezi", "od", "tussen", "van", "tra", "fra", "dal")

# Open ranges: "before 1734" (terminus ante quem) and "after 1712" (terminus post quem).
BEFORE = ("before", "antes de", "antes del", "ante", "ante quem", "a.q.", "vor", "avant", "prima del", "před", "voor")
AFTER = ("after", "después de", "despues de", "después del", "post", "post quem", "p.q.", "nach", "après", "dopo il", "po", "na")

# Era words. Years before Christ become astronomical years (44 BC = -0043), as EDTF counts.
BC = ("bc", "b.c.", "bce", "b.c.e.", "a.c.", "a. c.", "a.n.e.", "av. j.-c.", "av. j.c.", "v. chr.", "v.chr.", "př. n. l.", "př.n.l.")
AD = ("ad", "a.d.", "ce", "c.e.", "d.c.", "d. c.", "n.e.", "ap. j.-c.", "n. chr.", "n.chr.", "n. l.", "n.l.")

# Era words that name the calendar of the year before them: 1364 AH is an Islamic year.
ERA_CALENDARS = {"ah": "islamic", "a.h.": "islamic"}
