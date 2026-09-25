"""Markdown → Confluence storage XHTML."""

from __future__ import annotations

import html
import re
from urllib.parse import unquote

import markdown
from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString

from .macros import PANEL_MACROS, cdata, find_elements

_RAW_TOKEN = "XCFRAW{:04d}X"
_RAW_TOKEN_RE = re.compile(r"XCFRAW(\d{4})X")
_GEN_TOKEN = "XCFGEN{:04d}X"
_GEN_TOKEN_RE = re.compile(r"XCFGEN(\d{4})X")
_CALLOUT_RE = re.compile(r"^\s*\[!(" + "|".join(PANEL_MACROS) + r")\]\s*", re.IGNORECASE)
_TASK_RE = re.compile(r"^\[([ xX])\]\s+")
_EXTENSIONS = ["tables", "fenced_code", "sane_lists"]
_SEPARATOR = "XCFSEPX"
_QUOTE_GAP_RE = re.compile(r"(^>[^\n]*\n)(?:[ \t]*\n)+(?=>)", re.MULTILINE)


def _protect_raw(md: str) -> tuple[str, list[str]]:
    """Swap raw ac:/ri: elements (outside code) for tokens before Markdown runs."""
    raws: list[str] = []
    out: list[str] = []
    pos = 0
    for el in find_elements(md, markdown=True):
        out.append(md[pos : el.start])
        raws.append(el.text)
        out.append(_RAW_TOKEN.format(len(raws) - 1))
        pos = el.end
    out.append(md[pos:])
    return "".join(out), raws


def _inner_html(tag: Tag) -> str:
    return "".join(str(c) for c in tag.contents)


def _macro(name: str, body: str, params: dict[str, str] | None = None) -> str:
    ps = "".join(
        f'<ac:parameter ac:name="{k}">{html.escape(v, quote=False)}</ac:parameter>'
        for k, v in (params or {}).items()
    )
    return (
        f'<ac:structured-macro ac:name="{name}" ac:schema-version="1">'
        f"{ps}{body}</ac:structured-macro>"
    )


class _Builder:
    def __init__(self, soup: BeautifulSoup) -> None:
        self.soup = soup
        self.generated: list[str] = []

    def replace(self, tag: Tag, storage: str) -> None:
        self.generated.append(storage)
        tag.replace_with(NavigableString(_GEN_TOKEN.format(len(self.generated) - 1)))

    def code_blocks(self) -> None:
        for pre in self.soup.find_all("pre"):
            code = pre.find("code")
            if not isinstance(code, Tag):
                continue
            lang = next((c[9:] for c in code.get("class") or [] if c.startswith("language-")), "")
            text = code.get_text()
            text = text[:-1] if text.endswith("\n") else text
            body = f"<ac:plain-text-body>{cdata(text)}</ac:plain-text-body>"
            self.replace(pre, _macro("code", body, {"language": lang} if lang else None))

    def links(self) -> None:
        for a in self.soup.find_all("a", href=re.compile(r"^confluence:")):
            target = str(a["href"])[len("confluence:") :]
            space, sep, title = target.partition("/") if "/" in target else ("", "", target)
            title = unquote(title)
            space_attr = f' ri:space-key="{html.escape(unquote(space))}"' if sep else ""
            page = f'<ri:page ri:content-title="{html.escape(title)}"{space_attr}/>'
            text = a.get_text()
            if text == title and not a.find(True):
                body = ""
            elif a.find(True) or _GEN_TOKEN_RE.search(_inner_html(a)):
                body = f"<ac:link-body>{_inner_html(a)}</ac:link-body>"
            else:
                body = f"<ac:plain-text-link-body>{cdata(text)}</ac:plain-text-link-body>"
            self.replace(a, f"<ac:link>{page}{body}</ac:link>")

    def images(self) -> None:
        for img in self.soup.find_all("img"):
            src = str(img.get("src", ""))
            if src.startswith("attachment:"):
                ref = f'<ri:attachment ri:filename="{html.escape(unquote(src[11:]))}"/>'
            else:
                ref = f'<ri:url ri:value="{html.escape(src)}"/>'
            alt = str(img.get("alt", ""))
            alt_attr = f' ac:alt="{html.escape(alt)}"' if alt else ""
            self.replace(img, f"<ac:image{alt_attr}>{ref}</ac:image>")

    def task_lists(self) -> None:
        task_id = 0
        for ul in self.soup.find_all("ul"):
            items = ul.find_all("li", recursive=False)
            if not items:
                continue

            # First pass: validate that ALL items qualify as tasks
            validations: list[tuple[Tag, Tag, re.Match[str]]] = []
            for li in items:
                paragraph = li.find("p") if isinstance(li.contents[0], Tag) else None
                holder = paragraph if isinstance(paragraph, Tag) else li
                first = holder.contents[0] if holder.contents else None
                if not isinstance(first, NavigableString):
                    break
                m = _TASK_RE.match(str(first))
                if not m:
                    break
                validations.append((li, holder, m))
            else:
                # All items qualified; now mutate and build
                tasks: list[str] = []
                for _li, holder, m in validations:
                    first = holder.contents[0]
                    if isinstance(first, NavigableString):
                        first.replace_with(str(first)[m.end() :])
                    task_id += 1
                    status = "incomplete" if m.group(1) == " " else "complete"
                    tasks.append(
                        f"<ac:task><ac:task-id>{task_id}</ac:task-id>"
                        f"<ac:task-status>{status}</ac:task-status>"
                        f"<ac:task-body>{_inner_html(holder).strip()}</ac:task-body></ac:task>"
                    )
                self.replace(ul, "<ac:task-list>" + "".join(tasks) + "</ac:task-list>")

    def callouts(self) -> None:
        for bq in reversed(self.soup.find_all("blockquote")):
            first = bq.find(True)
            if not isinstance(first, Tag) or first.name != "p" or not first.contents:
                continue
            lead = first.contents[0]
            m = _CALLOUT_RE.match(str(lead)) if isinstance(lead, NavigableString) else None
            if not m:
                continue
            lead.replace_with(str(lead)[m.end() :])
            if not first.get_text(strip=True) and not first.find(True):
                first.decompose()
            body = f"<ac:rich-text-body>{_inner_html(bq).strip()}</ac:rich-text-body>"
            self.replace(bq, _macro(m.group(1).lower(), body))

    def tables(self) -> None:
        for table in self.soup.find_all("table"):
            rows = table.find_all("tr")
            for section in table.find_all(["thead", "tbody"]):
                section.unwrap()
            tbody = self.soup.new_tag("tbody")
            for row in rows:
                tbody.append(row.extract())
            table.clear()
            table.append(tbody)


def _restore(text: str, generated: list[str], raws: list[str]) -> str:
    while _GEN_TOKEN_RE.search(text):
        text = _GEN_TOKEN_RE.sub(lambda m: generated[int(m.group(1))], text)
    text = re.sub(r"<p>((?:\s*XCFRAW\d{4}X)+)\s*</p>", lambda m: m.group(1).strip(), text)
    return _RAW_TOKEN_RE.sub(lambda m: raws[int(m.group(1))], text)


def to_storage(md: str) -> str:
    """Convert Markdown (as produced by ``to_markdown``) to Confluence storage XHTML."""
    protected, raws = _protect_raw(md)
    # Python-Markdown joins '> a' + blank line + '> b' into one blockquote; CommonMark
    # (and our callouts) treat them as two, so put a separator paragraph between them.
    protected = _QUOTE_GAP_RE.sub(r"\1\n" + _SEPARATOR + "\n\n", protected)
    rendered = markdown.markdown(protected, extensions=_EXTENSIONS, output_format="xhtml")
    soup = BeautifulSoup(rendered, "html.parser")
    builder = _Builder(soup)
    builder.code_blocks()
    builder.tables()
    builder.images()
    builder.links()
    builder.task_lists()
    builder.callouts()
    text = re.sub(r"<p>" + _SEPARATOR + r"</p>\n?", "", str(soup))
    return _restore(text, builder.generated, raws).strip()
