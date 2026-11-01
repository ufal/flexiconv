"""Converted dates into the TEI header of existing files, without touching anything else.

For each date element (by default TEITOK's text date, teiHeader/…/setting/date) the original
value is read, converted (convert.py), and written back as attributes on that same element:

    when-custom="1712-11-23/1734" datingMethod="https://www.loc.gov/standards/datetime/" when="1723"

- @when-custom (or the attribute chosen) holds the EDTF value, the one search engines read.
- @when gets the best guess only when the element has no @when yet (TEITOK: "best guess year").
- @notBefore / @notAfter only for ranges and coarse dates on elements without @when (TEI does
  not allow both), i.e. with --no-best; the EDTF value holds the range in any case.
- An attribute that already holds something else is a conflict: reported, never overwritten
  unless asked. A file is only rewritten when the bytes outside the edited start tag are
  unchanged and the result parses; otherwise it is left alone and reported.
- A missing element is created (with its missing parents) when an external value list gives the
  file a date.
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Tuple

from lxml import etree

from . import xmlpatch
from .convert import convert_date
from .edtf import is_edtf
from .model import DateResult, Interval, Point, days_in_month
from .profile import Profile

EDTF_URI = "https://www.loc.gov/standards/datetime/"
TEITOK_DATE = "teiHeader/profileDesc/settingDesc/setting/date"


@dataclass
class TeiOptions:
    element: str = TEITOK_DATE
    # where the original value is: "auto" (@when, else the text), "text", or "attr:NAME"
    source: str = "auto"
    edtf_attr: str = "when-custom"
    dating_method: str = EDTF_URI
    write_best: bool = True
    write_range: bool = True
    # another attribute with a date the result must agree with (e.g. ODE's Roman century)
    check_attr: Optional[str] = None
    accept_review: bool = False
    overwrite: bool = False


def _local(tag) -> str:
    return etree.QName(tag).localname if isinstance(tag, str) else ""


def _steps(path: str) -> List[Tuple[bool, str, Optional[Tuple[str, str]]]]:
    """'//sourceDesc//date[@type="x"]' → [(True, "sourceDesc", None), (True, "date", ("type", "x"))];
    the flag says the step may be any descendant (//) rather than a child (/)."""
    out = []
    p = path.strip()
    if not p.startswith("/"):
        p = "/" + p
    i = 0
    while i < len(p):
        deep = p.startswith("//", i)
        i += 2 if deep else 1
        j = i
        while j < len(p) and p[j] != "/":
            if p[j] == "[":
                j = p.index("]", j)
            j += 1
        step = p[i:j]
        i = j
        pred = None
        if "[" in step and step.endswith("]"):
            step, _, cond = step[:-1].partition("[")
            name, _, val = cond.lstrip("@").partition("=")
            pred = (name.strip(), val.strip().strip("\"'"))
        if step:
            out.append((deep, step, pred))
    return out


def _match(el, step) -> bool:
    _, name, pred = step
    if _local(el.tag) != name:
        return False
    return pred is None or el.get(pred[0]) == pred[1]


def _next(els, step) -> list:
    out, seen = [], set()
    for e in els:
        cands = e.iterdescendants() if step[0] else iter(e)
        for c in cands:
            if isinstance(c.tag, str) and _match(c, step) and id(c) not in seen:
                seen.add(id(c))
                out.append(c)
    return out


def find_elements(root, path: str) -> list:
    """Elements by a simple path from the root element: teiHeader/…/date, //setting/date,
    //sourceDesc//date[@type='x'] (local names, so with or without the TEI namespace)."""
    steps = _steps(path)
    if not steps:
        return []
    deep, name, pred = steps[0]
    if deep:
        current = [e for e in root.iter() if isinstance(e.tag, str) and _match(e, steps[0])]
    else:
        current = [e for e in root if isinstance(e.tag, str) and _match(e, steps[0])]
    for step in steps[1:]:
        current = _next(current, step)
    return current


def _deepest_existing(root, path: str) -> Tuple[Optional[object], list]:
    """For creating: the deepest element of the path that exists, and the steps still missing.
    Only for plain child paths (no //), where "missing" is well defined."""
    steps = _steps(path)
    if any(deep for deep, _, _ in steps):
        return None, steps
    el, i = root, 0
    while i < len(steps):
        nxt = [c for c in el if isinstance(c.tag, str) and _match(c, steps[i])]
        if not nxt:
            break
        el, i = nxt[0], i + 1
    return (el if i > 0 else None), steps[i:]


def _xsd_low(d: Tuple[int, int, int]) -> str:
    y, m, dd = d
    ys = ("-" if y < 0 else "") + f"{abs(y):04d}"
    if (m, dd) == (1, 1):
        return ys
    return f"{ys}-{m:02d}" if dd == 1 else f"{ys}-{m:02d}-{dd:02d}"


def _xsd_high(d: Tuple[int, int, int]) -> str:
    y, m, dd = d
    ys = ("-" if y < 0 else "") + f"{abs(y):04d}"
    if (m, dd) == (12, 31):
        return ys
    return f"{ys}-{m:02d}" if dd == days_in_month(y, m) else f"{ys}-{m:02d}-{dd:02d}"


def desired_attrs(r: DateResult, opts: TeiOptions, existing: Mapping[str, str]) -> Dict[str, str]:
    """The attributes to set. TEI allows @when with no other att.datable.w3c attribute, so the
    range goes into @notBefore/@notAfter only where there is no @when (and none is written);
    the EDTF value carries the range either way."""
    out = {opts.edtf_attr: r.edtf}
    if opts.dating_method:
        out["datingMethod"] = opts.dating_method
    has_when = "when" in existing
    has_range = any(k in existing for k in ("from", "to", "notBefore", "notAfter"))
    if opts.write_best and r.best and not has_when and not has_range and opts.edtf_attr != "when":
        out["when"] = r.best
        has_when = True
    v = r.value
    coarse = isinstance(v, Interval) or (isinstance(v, Point) and v.unspecified)
    if opts.write_range and coarse and not has_when:
        if v.earliest() is not None and "from" not in existing:
            out["notBefore"] = _xsd_low(v.earliest())
        if v.latest() is not None and "to" not in existing:
            out["notAfter"] = _xsd_high(v.latest())
    return out


def _source_value(el, opts: TeiOptions) -> Tuple[str, str]:
    if opts.source.startswith("attr:"):
        name = opts.source[5:]
        return el.get(name) or "", "@" + name
    text = " ".join("".join(el.itertext()).split())
    if opts.source == "text":
        return text, "text"
    when = (el.get("when") or "").strip()
    if when:
        return when, "@when"
    for a, b in (("from", "to"), ("notBefore", "notAfter")):
        lo, hi = (el.get(a) or "").strip(), (el.get(b) or "").strip()
        if lo or hi:
            return f"{lo or '..'}/{hi or '..'}", f"@{a}/@{b}"
    return text, "text"


def _overlap(a, b) -> bool:
    la, ha, lb, hb = a.earliest(), a.latest(), b.earliest(), b.latest()
    return (la is None or hb is None or la <= hb) and (lb is None or ha is None or lb <= ha)


def _with_check(r: DateResult, el, profile: Profile, opts: TeiOptions, fixes) -> DateResult:
    if not opts.check_attr or r.value is None or r.rule == "fix":
        return r  # a curator's fix is final
    other = (el.get(opts.check_attr) or "").strip()
    if not other:
        return r
    c = convert_date(other, profile, fixes)
    if c.value is not None and not _overlap(r.value, c.value):
        r.status = "review"
        r.notes.append(f"disagrees with @{opts.check_attr}={other!r} ({c.edtf})")
    return r


def _decide(r: DateResult, el, opts: TeiOptions) -> Tuple[str, Dict[str, str], List[str]]:
    """(action, attributes to set, notes)."""
    if r.status == "empty":
        return "no date", {}, []
    if r.status == "failed":
        return "not read", {}, []
    if r.status == "review" and not opts.accept_review:
        return "needs review", {}, []
    existing = dict(el.attrib)
    want = desired_attrs(r, opts, existing)
    notes, changes = [], {}
    for name, val in want.items():
        old = existing.get(name)
        if old == val:
            continue
        if old not in (None, "") and not opts.overwrite:
            hint = ""
            if name == opts.edtf_attr and not is_edtf(old):
                hint = " (not EDTF: choose another attribute with --edtf-attr)"
            notes.append(f"@{name} already holds {old!r}, not {val!r}{hint}")
            continue
        changes[name] = val
    if notes:
        return "conflict", {}, notes
    return ("unchanged" if not changes else "write"), changes, []


def _creation_markup(steps, attrs: Dict[str, str], original: str) -> str:
    """The missing elements, the date itself with the original wording as its text."""
    inner = ""
    for i, (_, name, pred) in enumerate(reversed(steps)):
        a = dict(attrs) if i == 0 else {}
        if pred:
            a = {pred[0]: pred[1], **a}
        at = "".join(f' {k}="{xmlpatch.escape_attr(v)}"' for k, v in a.items())
        content = xmlpatch.escape_text(original) if i == 0 else inner
        inner = f"<{name}{at}>{content}</{name}>" if content else f"<{name}{at}/>"
    return inner


def _parse(text: str):
    parser = etree.XMLParser(resolve_entities=False, huge_tree=True, remove_blank_text=False)
    return etree.fromstring(text.encode("utf-8"), parser)


def _elements(root) -> list:
    return [e for e in root.iter() if isinstance(e.tag, str)]


def _tag_for(text: str, root, el) -> xmlpatch.Tag:
    tags = xmlpatch.scan(text)
    els = _elements(root)
    if len(tags) != len(els):
        raise xmlpatch.PatchError("element count differs between parser and scanner (entities?)")
    t = tags[els.index(el)]
    if t.name.split(":")[-1] != _local(el.tag) or t.line != el.sourceline:
        raise xmlpatch.PatchError(f"could not match <{_local(el.tag)}> on line {el.sourceline} to the file")
    return t


def _read_text(path: str) -> str:
    with open(path, "rb") as f:
        data = f.read()
    body = data[3:] if data.startswith(b"\xef\xbb\xbf") else data
    if body.startswith(b"<?xml"):
        decl = body[: body.find(b"?>") + 2].decode("ascii", "replace")
        as_tag = decl.replace("<?xml", "<xml", 1).replace("?>", "/>")
        tags = xmlpatch.scan(as_tag)
        enc = next((as_tag[a.value_start:a.value_end] for a in tags[0].attrs if a.name == "encoding"), "utf-8")
        if enc.lower().replace("-", "").replace("_", "") not in ("utf8", "ascii", "usascii"):
            raise xmlpatch.PatchError(f"only UTF-8 files are edited (this one is {enc})")
    return data.decode("utf-8")


def _write_atomic(path: str, text: str) -> None:
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".flexiconv-dates-", dir=d)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(text.encode("utf-8"))
        try:
            os.chmod(tmp, os.stat(path).st_mode)
        except OSError:
            pass
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def process_file(path: str, profile: Profile, opts: TeiOptions, *, fixes=None,
                 value: Optional[str] = None, write: bool = False) -> List[dict]:
    """Convert the dates of one file; rows for the report. `value` (from a value list) replaces
    what the file says and allows creating the element when it is missing."""
    base = {"file": path}
    try:
        text = _read_text(path)
        root = _parse(text)
    except (OSError, UnicodeDecodeError, etree.XMLSyntaxError, xmlpatch.PatchError) as e:
        return [{**base, "action": "error", "notes": str(e)}]
    rows: List[dict] = []
    targets = find_elements(root, opts.element)
    edits = []  # (element or None, attrs, missing steps)
    if not targets:
        if value is None:
            return [{**base, "element": opts.element, "action": "no element"}]
        r = convert_date(value, profile, fixes)
        parent, missing = _deepest_existing(root, opts.element)
        row = {**base, "element": opts.element, "source": "value list", **r.as_row()}
        fake = etree.Element("date")
        action, changes, notes = _decide(r, fake, opts)
        if parent is None:
            action, notes = "error", ["cannot create this path (relative, or no part of it exists)"]
        if action == "write":
            edits.append((parent, changes, missing, value))
        rows.append({**row, "action": action, "notes": "; ".join(filter(None, [row.get("notes"), *notes]))})
    for n, el in enumerate(targets):
        raw, src = (value, "value list") if value is not None else _source_value(el, opts)
        r = _with_check(convert_date(raw, profile, fixes), el, profile, opts, fixes)
        action, changes, notes = _decide(r, el, opts)
        row = {**base, "element": f"{opts.element}[{n + 1}]", "source": src, **r.as_row()}
        if action == "write":
            edits.append((el, changes, None, None))
        rows.append({**row, "action": action, "notes": "; ".join(filter(None, [row.get("notes"), *notes]))})
    if not edits:
        return rows
    try:
        new = text
        for el, changes, missing, original in edits:
            new_root = _parse(new)
            # find the same element again in the current text, by its position
            idx = _elements(root).index(el)
            cur = _elements(new_root)[idx]
            tag = _tag_for(new, new_root, cur)
            if missing is None:
                out, s, e, piece = xmlpatch.set_attrs(new, tag, changes)
                xmlpatch.check(new, out, s, e, piece)
                after = _elements(_parse(out))[idx]
                if any(after.get(k) != v for k, v in changes.items()):
                    raise xmlpatch.PatchError("attributes did not come out as intended")
            else:
                out, s, e, piece = xmlpatch.insert_before_close(new, tag, _creation_markup(missing, changes, original))
                xmlpatch.check(new, out, s, e, piece)
                if len(_elements(_parse(out))) != len(_elements(new_root)) + len(missing):
                    raise xmlpatch.PatchError("inserted element count is off")
                if not find_elements(_parse(out), opts.element):
                    raise xmlpatch.PatchError("created element not found afterwards")
            new = out
        if write:
            _write_atomic(path, new)
    except (xmlpatch.PatchError, etree.XMLSyntaxError) as e:
        for row in rows:
            if row.get("action") == "write":
                row["action"] = "error"
                row["notes"] = "; ".join(filter(None, [row.get("notes"), f"left unchanged: {e}"]))
        return rows
    for row in rows:
        if row.get("action") == "write":
            row["action"] = "written" if write else "would write"
    return rows
