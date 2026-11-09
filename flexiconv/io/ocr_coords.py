"""
Page coordinates for OCR readers: absolute pixel boxes or relative pct: boxes.

TEITOK's ``@bbox`` is absolute: ``"x1 y1 x2 y2"`` in pixels of the page image.
A relative box says so explicitly, in IIIF Image API region syntax:
``"pct:x,y,w,h"``, percentages of the page's width and height. It fits any
size of the same image (thumbnail, full scan, a IIIF server's rendering).
Readers of either form tell them apart by the ``pct:`` prefix only.

OCR formats do not always count in pixels: ALTO's MeasurementUnit can be
``mm10`` (1/10 mm) or ``inch1200`` (1/1200 inch). Pixels then need the scan
resolution (dpi); relative boxes do not, since the page size is given in
the same unit.
"""

from __future__ import annotations

import re
import sys
from typing import Callable, Optional

# Units per inch for the non-pixel units OCR formats use.
_UNITS_PER_INCH = {"mm10": 254.0, "inch1200": 1200.0}

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _stderr_warning(message: str) -> None:
    sys.stderr.write(f"[flexiconv] warning: {message}\n")


def pct_value(v: float) -> str:
    """A percentage with at most two decimals and no trailing zeros (12.50 → 12.5, 3.00 → 3)."""
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


class PageCoords:
    """Turns one page's boxes in source units into TEITOK bbox values.

    mode: "abs" (pixels, the default) or "pct" (relative to the page).
    unit: the source unit ("pixel", "mm10", "inch1200").
    dpi: the scan resolution, needed for absolute boxes from a non-pixel unit.
    page_w, page_h: the page size in the source unit, needed for relative boxes.

    Where the chosen form cannot be made, the other one is used when it can
    (relative without a page size → absolute; absolute from mm10/inch1200
    without dpi → relative), with a warning; with neither, no bbox at all
    rather than values that do not fit the image.
    """

    def __init__(
        self,
        *,
        mode: str = "abs",
        unit: str = "pixel",
        dpi: Optional[float] = None,
        page_w: Optional[float] = None,
        page_h: Optional[float] = None,
        warn: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.warn = warn or _stderr_warning
        unit = (unit or "pixel").strip().lower()
        if unit == "pixel":
            self.factor: Optional[float] = 1.0
        elif unit in _UNITS_PER_INCH:
            self.factor = (dpi / _UNITS_PER_INCH[unit]) if dpi else None
        else:
            self.factor = None
            self.warn(f"unknown measurement unit '{unit}': coordinates are not converted to pixels")
        self.page_w = page_w if page_w and page_w > 0 else None
        self.page_h = page_h if page_h and page_h > 0 else None
        has_page = self.page_w is not None and self.page_h is not None

        mode = (mode or "abs").strip().lower()
        if mode not in ("abs", "pct"):
            self.warn(f"unknown bbox mode '{mode}': using absolute pixels")
            mode = "abs"
        if mode == "pct" and not has_page:
            self.warn("page without WIDTH/HEIGHT: relative boxes need the page size, using absolute ones")
            mode = "abs"
        if mode == "abs" and self.factor is None:
            if has_page:
                self.warn(f"coordinates in {unit} and no dpi given: writing relative boxes (pct:)")
                mode = "pct"
            else:
                self.warn(f"coordinates in {unit}, no dpi and no page size: no bbox written")
                mode = "none"
        self.mode = mode

    def bbox(self, x: float, y: float, w: float, h: float) -> str:
        """The bbox value for a box at (x, y) of size w × h in source units; "" when there is none."""
        if w <= 0 or h <= 0 or self.mode == "none":
            return ""
        if self.mode == "pct":
            return "pct:" + ",".join(pct_value(v) for v in (
                100 * x / self.page_w, 100 * y / self.page_h, 100 * w / self.page_w, 100 * h / self.page_h))
        f = self.factor
        return f"{int(x * f)} {int(y * f)} {int((x + w) * f)} {int((y + h) * f)}"

    def page_bbox(self) -> str:
        """The page itself, in absolute pixels ("0 0 W H"); "" when the pixel size is not known.

        Always absolute, also when the boxes on it are relative: it is what
        turns relative boxes back into pixels for this image.
        """
        if self.factor is None or self.page_w is None or self.page_h is None:
            return ""
        return f"0 0 {int(self.page_w * self.factor)} {int(self.page_h * self.factor)}"

    def points(self, raw: Optional[str]) -> Optional[str]:
        """A point list (e.g. a baseline "x1,y1 x2,y2") in pixels; None when it cannot be."""
        if not raw:
            return None
        if self.factor is None:
            return None
        if self.factor == 1.0:
            return raw
        f = self.factor
        return _NUMBER.sub(lambda m: str(int(float(m.group(0)) * f)), raw)


def parse_reader_option(option: Optional[str]) -> dict:
    """Split a --option string ("bbox=pct;dpi=300") into lower-cased keys and their values."""
    out: dict = {}
    for part in (option or "").split(";"):
        key, sep, val = part.partition("=")
        key = key.strip().lower()
        if key:
            out[key] = val.strip() if sep else ""
    return out
