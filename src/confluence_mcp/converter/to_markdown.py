"""Confluence storage XHTML → Markdown."""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import quote

from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString
from markdownify import MarkdownConverter

from .macros import PANEL_MACROS, Element, cdata_text, find_elements

RAW_TOKEN = "XCFRAW{:04d}X"
_RAW_TOKEN_RE = re.compile(r"XCFRAW(\d{4})X")
_IGNORED_MACRO_ATTRS = {"ac:name", "ac:schema-version", "ac:macro-id"}
_BLOCK_IN_CELL = (
    "ul",
    "ol",
    "pre",
    "blockquote",
    "table",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
)


def _macro_known_attrs(el: Element) -> bool:
    return set(el.attrs) <= _IGNORED_MACRO_ATTRS


def _code_macro(el: Element) -> str | None:
    if not _macro_known_attrs(el):
        return None
    language = ""
    body: str | None = None
    for child in el.children():
        if child.name == "ac:parameter" and child.attrs.get("ac:name") == "language":
            language = child.inner.strip()
        elif child.name == "ac:plain-text-body" and body is None:
            body = cdata_text(child.inner)
        else:
            return None
    cls = f' class="language-{html.escape(language)}"' if language else ""
    return f"<pre><code{cls}>{html.escape(body or '')}</code></pre>"


def _panel_macro(el: Element, raws: list[str]) -> str | None:
    children = el.children()
    if not _macro_known_attrs(el) or len(children) != 1 or children[0].name != "ac:rich-text-body":
        return None
    kind = el.attrs["ac:name"].upper()
    return f"<blockquote><p>[!{kind}]</p>{_prepare(children[0].inner, raws)}</blockquote>"


def _link(el: Element, raws: list[str]) -> str | None:
    if el.attrs:
        return None
    page: Element | None = None
    text: str | None = None
    for child in el.children():
        if child.name == "ri:page" and page is None:
            page = child
        elif child.name == "ac:plain-text-link-body" and text is None:
            text = html.escape(cdata_text(child.inner))
        elif child.name == "ac:link-body" and text is None:
            text = _prepare(child.inner, raws)
        else:
            return None
    if page is None or not set(page.attrs) <= {"ri:content-title", "ri:space-key"}:
        return None
    title = html.unescape(page.attrs.get("ri:content-title", ""))
    space = page.attrs.get("ri:space-key")
    if not title or (space is None and "/" in title):
        return None
    target = f"{space}/{title}" if space else title
    href = (
        "confluence:" + quote(target, safe="/") if space else "confluence:" + quote(title, safe="")
    )
    return f'<a href="{html.escape(href)}">{text if text is not None else html.escape(title)}</a>'


def _image(el: Element) -> str | None:
    if not set(el.attrs) <= {"ac:alt"}:
        return None
    children = el.children()
    if len(children) != 1:
        return None
    ref = children[0]
    if ref.name == "ri:attachment" and set(ref.attrs) == {"ri:filename"}:
        src = "attachment:" + quote(html.unescape(ref.attrs["ri:filename"]), safe="")
    elif ref.name == "ri:url" and set(ref.attrs) == {"ri:value"}:
        src = html.unescape(ref.attrs["ri:value"])
    else:
        return None
    alt = html.unescape(el.attrs.get("ac:alt", ""))
    return f'<img src="{html.escape(src)}" alt="{html.escape(alt)}"/>'


def _task_list(el: Element, raws: list[str]) -> str | None:
    if el.attrs:
        return None
    items: list[str] = []
    for task in el.children():
        if task.name != "ac:task":
            return None
        status, body = None, None
        for part in task.children():
            if part.name == "ac:task-status":
                status = part.inner.strip()
            elif part.name == "ac:task-body":
                body = _prepare(part.inner, raws)
            elif part.name != "ac:task-id":
                return None
        if status not in ("complete", "incomplete") or body is None:
            return None
        items.append(f"<li>[{'x' if status == 'complete' else ' '}] {body}</li>")
    return "<ul>" + "".join(items) + "</ul>"


def _convert_known(el: Element, raws: list[str]) -> str | None:
    if el.name == "ac:structured-macro":
        name = el.attrs.get("ac:name", "")
        if name == "code":
            return _code_macro(el)
        if name in PANEL_MACROS:
            return _panel_macro(el, raws)
        return None
    if el.name == "ac:link":
        return _link(el, raws)
    if el.name == "ac:image":
        return _image(el)
    if el.name == "ac:task-list":
        return _task_list(el, raws)
    return None


def _prepare(storage: str, raws: list[str]) -> str:
    """Replace ac:/ri: elements with plain HTML (known) or raw tokens (unknown)."""
    out: list[str] = []
    pos = 0
    for el in find_elements(storage):
        out.append(storage[pos : el.start])
        converted = _convert_known(el, raws)
        if converted is None:
            raws.append(el.text)
            converted = RAW_TOKEN.format(len(raws) - 1)
        out.append(converted)
        pos = el.end
    out.append(storage[pos:])
    return "".join(out)


def _is_complex_table(table: Tag) -> bool:
    if table.find("table"):
        return True
    for cell in table.find_all(["td", "th"]):
        if cell.get("rowspan", "1") != "1" or cell.get("colspan", "1") != "1":
            return True
        if cell.find(_BLOCK_IN_CELL) or len(cell.find_all("p")) > 1:
            return True
    return False


_ENTITY_LIKE_RE = re.compile(r"&(?=#?\w+;)")


# The markdownify type stub does not declare escape/convert_table.
_MarkdownConverterBase: Any = MarkdownConverter


class _Converter(_MarkdownConverterBase):  # type: ignore[misc]
    def escape(self, text: str, parent_tags: set[str]) -> str:
        # Literal '<' and entity-like '&' would otherwise be read back as HTML.
        text = str(super().escape(text, parent_tags))
        return _ENTITY_LIKE_RE.sub("&amp;", text).replace("<", "&lt;")

    def convert_table(self, el: Tag, text: str, parent_tags: set[str]) -> str:
        if _is_complex_table(el):
            return "\n\n" + str(el) + "\n\n"
        return str(super().convert_table(el, text, parent_tags))


def _code_language(el: Tag) -> str:
    code = el.find("code")
    for cls in (code.get("class") or []) if isinstance(code, Tag) else []:
        if cls.startswith("language-"):
            return str(cls[len("language-") :])
    return ""


_OPTIONS: dict[str, Any] = {
    "heading_style": "ATX",
    "bullets": "-",
    "code_language_callback": _code_language,
    "escape_misc": False,
}


def _split_top_level(soup: BeautifulSoup, node: NavigableString) -> None:
    """Give each top-level raw token (and any stray text) its own paragraph."""
    for part in re.split(r"(XCFRAW\d{4}X)", str(node)):
        if part.strip():
            p = soup.new_tag("p")
            p.string = part.strip()
            node.insert_before(p)
    node.extract()


def to_markdown(storage: str) -> str:
    """Convert Confluence storage XHTML to Markdown.

    Known constructs become Markdown; any other ac:/ri: element is kept as raw
    XHTML (on its own line when block-level) so that ``to_storage`` restores it.
    """
    raws: list[str] = []
    prepared = _prepare(storage, raws)
    soup = BeautifulSoup(prepared, "html.parser")
    for node in list(soup.find_all(string=_RAW_TOKEN_RE)):
        if node.parent is soup and isinstance(node, NavigableString):
            _split_top_level(soup, node)
    markdown = _Converter(**_OPTIONS).convert_soup(soup)
    markdown = _RAW_TOKEN_RE.sub(lambda m: raws[int(m.group(1))], markdown)
    return re.sub(r"\n{3,}", "\n\n", markdown).strip() + "\n"
