"""Text-level scanning of Confluence storage elements (ac:*/ri:*) and macro inventory.

Scanning works on the raw text so unknown elements can be passed through byte-for-byte.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

PANEL_MACROS = ("info", "note", "warning", "tip")

_TAG_RE = re.compile(
    r"<(/?)((?:ac|ri):[\w-]+|time)((?:\s+[\w:-]+\s*=\s*(?:\"[^\"]*\"|'[^']*'))*)\s*(/?)>"
)
_ATTR_RE = re.compile(r"([\w:-]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)')")
_CDATA_RE = re.compile(r"<!\[CDATA\[.*?\]\]>", re.DOTALL)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_FENCE_RE = re.compile(
    r"^(?P<fence>`{3,}|~{3,})[^\n]*\n.*?(?:^(?P=fence)[ \t]*$|\Z)", re.DOTALL | re.MULTILINE
)
_CODE_SPAN_RE = re.compile(r"(`+)(?!`).+?(?<!`)\1(?!`)", re.DOTALL)
_MACRO_NAME_RE = re.compile(r"<ac:(?:structured-)?macro\b[^>]*?\bac:name\s*=\s*[\"']([^\"']+)[\"']")
_STRUCTURE_RE = re.compile(r"<(ac:image|ac:task-list|ac:link)(?=[\s/>])")


@dataclass
class Element:
    """One ac:/ri: element located in a text."""

    name: str
    attrs: dict[str, str]
    start: int
    end: int
    inner_start: int
    inner_end: int
    source: str = field(repr=False)

    @property
    def text(self) -> str:
        return self.source[self.start : self.end]

    @property
    def inner(self) -> str:
        return self.source[self.inner_start : self.inner_end]

    def children(self) -> list[Element]:
        return [
            Element(
                c.name,
                c.attrs,
                c.start + self.inner_start,
                c.end + self.inner_start,
                c.inner_start + self.inner_start,
                c.inner_end + self.inner_start,
                self.source,
            )
            for c in find_elements(self.inner)
        ]


def _protected_ranges(text: str, markdown: bool) -> list[tuple[int, int]]:
    patterns = [_CDATA_RE, _COMMENT_RE]
    if markdown:
        patterns += [_FENCE_RE, _CODE_SPAN_RE]
    ranges = [(m.start(), m.end()) for p in patterns for m in p.finditer(text)]
    return sorted(ranges)


def _in_ranges(pos: int, ranges: list[tuple[int, int]]) -> bool:
    return any(a <= pos < b for a, b in ranges)


def find_elements(text: str, *, markdown: bool = False) -> list[Element]:
    """Return the outermost ac:/ri: (and ``<time>``) elements in ``text`` in document order.

    CDATA sections and comments are skipped; with ``markdown=True`` fenced code
    blocks and inline code spans are skipped too. An element whose closing tag is
    missing extends to the end of the text.
    """
    ranges = _protected_ranges(text, markdown)
    tags = [m for m in _TAG_RE.finditer(text) if not _in_ranges(m.start(), ranges)]
    result: list[Element] = []
    i = 0
    while i < len(tags):
        m = tags[i]
        closing, name, attr_text, self_closing = m.group(1), m.group(2), m.group(3), m.group(4)
        if closing:  # stray closing tag: ignore
            i += 1
            continue
        attrs = {
            a.group(1): a.group(2) if a.group(2) is not None else a.group(3) or ""
            for a in _ATTR_RE.finditer(attr_text)
        }
        if self_closing:
            result.append(Element(name, attrs, m.start(), m.end(), m.end(), m.end(), text))
            i += 1
            continue
        depth = 1
        j = i + 1
        while j < len(tags) and depth:
            t = tags[j]
            if t.group(2) == name and not t.group(4):
                depth += -1 if t.group(1) else 1
            j += 1
        if depth:  # unclosed: take the rest of the text
            result.append(Element(name, attrs, m.start(), len(text), m.end(), len(text), text))
            break
        close = tags[j - 1]
        result.append(Element(name, attrs, m.start(), close.end(), m.end(), close.start(), text))
        i = j
    return result


def cdata_text(inner: str) -> str:
    """Concatenate the contents of all CDATA sections in ``inner``."""
    return "".join(m.group(0)[9:-3] for m in _CDATA_RE.finditer(inner))


def cdata(text: str) -> str:
    """Wrap ``text`` in CDATA, splitting any ``]]>`` it contains."""
    return "<![CDATA[" + text.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def inventory(storage: str) -> Counter[str]:
    """Count macros (by name) and structural elements in storage XHTML."""
    stripped = _COMMENT_RE.sub("", _CDATA_RE.sub("", storage))
    counts: Counter[str] = Counter(m.group(1) for m in _MACRO_NAME_RE.finditer(stripped))
    counts.update(m.group(1) for m in _STRUCTURE_RE.finditer(stripped))
    return counts
