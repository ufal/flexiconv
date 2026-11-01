"""Date conversion to EDTF (ISO 8601-2) for corpus metadata.

Messy original dates (02/12/1945, [1945], ca. 1550, siglo XVI, 1712-11-23 - 1734, Hebrew or
Julian dates, dates in words) are converted once, by declared conventions (Profile), into an
EDTF value with its range and a best guess; search engines then only need to read EDTF.

    from flexiconv.dates import Profile, convert_date
    r = convert_date("ca. 1550", Profile(century="hundreds"))
    r.edtf, r.earliest, r.latest, r.best, r.status   # '1550~', '1550-01-01', '1550-12-31', '1550', 'ok'

Converting beforehand (flexiconv dates) is the recommended route: the results can be reviewed
and corrected, and the corrections fed back (--fixes). Tools that call convert_date while
indexing should use a declared profile and treat `review` results as undated.
"""
from __future__ import annotations

from .convert import convert_date
from .edtf import is_edtf, parse as parse_edtf, to_edtf
from .model import DateResult, Interval, Point
from .profile import Profile

__all__ = ["convert_date", "DateResult", "Profile", "Point", "Interval", "parse_edtf", "to_edtf", "is_edtf"]
