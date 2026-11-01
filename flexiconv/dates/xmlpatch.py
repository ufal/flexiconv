"""Byte-preserving edits of one start tag in an existing XML file.

Only two edits exist: set attributes on an element's start tag, and insert a new element just
before an element's end tag. Everything outside the edited span stays byte for byte as it was;
`check()` proves that after the fact, and callers refuse the file when it does not hold.

The scanner walks the markup (comments, CDATA, processing instructions, the DOCTYPE with its
internal subset, quoted attribute values) without regular expressions, and numbers start tags
in document order, the order lxml's iter() uses, so an element found with lxml can be matched
to its bytes. Line numbers are compared as a second check.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


class PatchError(Exception):
    pass


@dataclass
class Attr:
    name: str
    value_start: int  # first character of the value (after the quote)
    value_end: int    # the closing quote
    end: int          # after the closing quote
    quote: str


@dataclass
class Tag:
    name: str
    start: int        # '<'
    end: int          # after '>'
    line: int
    self_closing: bool
    attrs: List[Attr] = field(default_factory=list)
    close_start: Optional[int] = None  # '<' of the matching end tag


def _skip_to(text: str, i: int, marker: str) -> int:
    j = text.find(marker, i)
    if j < 0:
        raise PatchError(f"unterminated markup at offset {i}")
    return j + len(marker)


def _skip_doctype(text: str, i: int) -> int:
    depth, quote = 0, ""
    while i < len(text):
        c = text[i]
        if quote:
            if c == quote:
                quote = ""
        elif c in "\"'":
            quote = c
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
        elif c == ">" and depth == 0:
            return i + 1
        i += 1
    raise PatchError("unterminated DOCTYPE")


def _start_tag(text: str, i: int) -> Tag:
    n = len(text)
    j = i + 1
    while j < n and not text[j].isspace() and text[j] not in "/>":
        j += 1
    tag = Tag(text[i + 1:j], i, -1, 0, False)
    while j < n:
        while j < n and text[j].isspace():
            j += 1
        if j >= n:
            break
        if text[j] == ">":
            tag.end = j + 1
            return tag
        if text.startswith("/>", j):
            tag.end, tag.self_closing = j + 2, True
            return tag
        k = j
        while k < n and not text[k].isspace() and text[k] not in "=/>":
            k += 1
        name = text[j:k]
        while k < n and text[k].isspace():
            k += 1
        if k >= n or text[k] != "=" or not name:
            raise PatchError(f"unreadable attribute in <{tag.name}> at offset {j}")
        k += 1
        while k < n and text[k].isspace():
            k += 1
        if k >= n or text[k] not in "\"'":
            raise PatchError(f"unquoted attribute value in <{tag.name}> at offset {k}")
        q = text[k]
        close = text.find(q, k + 1)
        if close < 0:
            raise PatchError(f"unterminated attribute value in <{tag.name}>")
        tag.attrs.append(Attr(name, k + 1, close, close + 1, q))
        j = close + 1
    raise PatchError(f"unterminated start tag <{tag.name}>")


def scan(text: str) -> List[Tag]:
    """All start tags in document order, each with its matching end tag position."""
    tags: List[Tag] = []
    stack: List[Tag] = []
    i, n, line, counted = 0, len(text), 1, 0
    while True:
        j = text.find("<", i)
        if j < 0:
            break
        line += text.count("\n", counted, j)
        counted = j
        if text.startswith("<!--", j):
            i = _skip_to(text, j + 4, "-->")
        elif text.startswith("<![CDATA[", j):
            i = _skip_to(text, j + 9, "]]>")
        elif text.startswith("<?", j):
            i = _skip_to(text, j + 2, "?>")
        elif text.startswith("<!", j):
            i = _skip_doctype(text, j)
        elif text.startswith("</", j):
            end = _skip_to(text, j + 2, ">")
            name = text[j + 2:end - 1].strip()
            if not stack or stack[-1].name != name:
                raise PatchError(f"end tag </{name}> does not match at offset {j}")
            stack.pop().close_start = j
            i = end
        else:
            tag = _start_tag(text, j)
            tag.line = line
            tags.append(tag)
            if not tag.self_closing:
                stack.append(tag)
            i = tag.end
    if stack:
        raise PatchError(f"<{stack[-1].name}> is never closed")
    return tags


def escape_attr(value: str, quote: str = '"') -> str:
    out = value.replace("&", "&amp;").replace("<", "&lt;")
    return out.replace('"', "&quot;") if quote == '"' else out.replace("'", "&apos;")


def escape_text(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def set_attrs(text: str, tag: Tag, values: Dict[str, str]) -> Tuple[str, int, int, str]:
    """The start tag with `values` set: existing attributes get a new value in place, new ones
    are added after the last attribute. Returns (new text, span start, old span end, new span)."""
    tag_text = text[tag.start:tag.end]
    edits = []  # (start, end, replacement) relative to the tag
    existing = {a.name: a for a in tag.attrs}
    for name, value in values.items():
        a = existing.get(name)
        if a is not None:
            edits.append((a.value_start - tag.start, a.value_end - tag.start, escape_attr(value, a.quote)))
    new_names = [n for n in values if n not in existing]
    if new_names:
        pos = (tag.attrs[-1].end if tag.attrs else tag.start + 1 + len(tag.name)) - tag.start
        added = "".join(f' {n}="{escape_attr(values[n])}"' for n in new_names)
        edits.append((pos, pos, added))
    new_tag = tag_text
    for s, e, r in sorted(edits, reverse=True):
        new_tag = new_tag[:s] + r + new_tag[e:]
    return text[:tag.start] + new_tag + text[tag.end:], tag.start, tag.end, new_tag


def insert_before_close(text: str, parent: Tag, markup: str) -> Tuple[str, int, int, str]:
    """Insert `markup` as the last child of `parent`, on its own line when the end tag is on
    its own line (indented one step deeper, tabs or spaces as the file has them)."""
    if parent.self_closing or parent.close_start is None:
        raise PatchError(f"<{parent.name}> has no end tag to insert before")
    pos = parent.close_start
    ws_start = pos
    while ws_start > 0 and text[ws_start - 1] in " \t":
        ws_start -= 1
    if ws_start > 0 and text[ws_start - 1] == "\n":
        indent = text[ws_start:pos]
        step = "\t" if "\t" in indent else "  "
        piece = step + markup + "\n" + indent
    else:
        piece = markup
    return text[:pos] + piece + text[pos:], pos, pos, piece


def check(old: str, new: str, start: int, old_end: int, piece: str) -> None:
    """Everything outside the edited span is unchanged."""
    if new[:start] != old[:start] or new[start + len(piece):] != old[old_end:]:
        raise PatchError("bytes outside the edited tag changed")
