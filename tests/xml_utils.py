"""Normalise storage XHTML for equality checks in tests."""

from __future__ import annotations

import html.entities
import re

from lxml import etree

_WRAP = (
    '<root xmlns:ac="http://atlassian.com/content" '
    'xmlns:ri="http://atlassian.com/resource/identifier">{}</root>'
)
_XML_ENTITIES = {"amp", "lt", "gt", "quot", "apos"}
_DROP_ATTRS = {
    "{http://atlassian.com/content}macro-id",
    "{http://atlassian.com/content}schema-version",
}


def _numeric_entities(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        name = m.group(1)
        if name in _XML_ENTITIES or name not in html.entities.name2codepoint:
            return m.group(0)
        return f"&#{html.entities.name2codepoint[name]};"

    return re.sub(r"&(\w+);", repl, text)


def normalize(storage: str) -> str:
    """Canonical form: attributes sorted, macro-id/schema-version dropped, whitespace
    between elements removed, runs of whitespace in text collapsed (CDATA kept)."""
    parser = etree.XMLParser(strip_cdata=False, remove_blank_text=True)
    root = etree.fromstring(_WRAP.format(_numeric_entities(storage)), parser)
    for el in root.iter():
        for attr in _DROP_ATTRS & set(el.attrib):
            del el.attrib[attr]
        attrs = sorted(el.attrib.items())
        el.attrib.clear()
        el.attrib.update(attrs)
        in_cdata = el.tag == "{http://atlassian.com/content}plain-text-body"
        if not in_cdata:
            if el.text is not None:
                el.text = re.sub(r"\s+", " ", el.text).strip() or None
        if el.tail is not None:
            el.tail = re.sub(r"\s+", " ", el.tail).strip() or None
    return etree.tostring(root, encoding="unicode")
