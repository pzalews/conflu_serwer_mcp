from __future__ import annotations

from pathlib import Path

import pytest

from confluence_mcp.converter import inventory, to_markdown, to_storage
from tests.xml_utils import normalize

FIXTURES = Path(__file__).parent / "fixtures"
ROUNDTRIP = sorted((FIXTURES / "roundtrip").glob("*.xml"))
LOSSY = sorted(p for p in (FIXTURES / "lossy").glob("*.xml") if ".expected" not in p.name)


@pytest.mark.parametrize("path", ROUNDTRIP, ids=lambda p: p.stem)
def test_roundtrip_fixture(path: Path) -> None:
    storage = path.read_text()
    assert normalize(to_storage(to_markdown(storage))) == normalize(storage)


@pytest.mark.parametrize("path", LOSSY, ids=lambda p: p.stem)
def test_lossy_fixture(path: Path) -> None:
    expected = path.with_name(path.stem + ".expected.xml").read_text()
    assert normalize(to_storage(to_markdown(path.read_text()))) == normalize(expected)


@pytest.mark.parametrize("path", ROUNDTRIP + LOSSY, ids=lambda p: p.stem)
def test_roundtrip_never_loses_macros(path: Path) -> None:
    storage = path.read_text()
    assert not inventory(storage) - inventory(to_storage(to_markdown(storage)))


@pytest.mark.parametrize("path", ROUNDTRIP, ids=lambda p: p.stem)
def test_markdown_is_stable(path: Path) -> None:
    md = to_markdown(path.read_text())
    assert to_markdown(to_storage(md)) == md


# ── storage → Markdown ────────────────────────────────────────────────────────


def test_md_headings_and_inline() -> None:
    md = to_markdown("<h2>T</h2><p><strong>b</strong> <em>i</em> <code>c</code></p>")
    assert md == "## T\n\n**b** *i* `c`\n"


def test_md_code_macro_becomes_fence() -> None:
    storage = (
        '<ac:structured-macro ac:name="code"><ac:parameter ac:name="language">sql'
        "</ac:parameter><ac:plain-text-body><![CDATA[SELECT 1 < 2]]></ac:plain-text-body>"
        "</ac:structured-macro>"
    )
    assert to_markdown(storage) == "```sql\nSELECT 1 < 2\n```\n"


def test_md_panel_becomes_callout() -> None:
    storage = (
        '<ac:structured-macro ac:name="tip"><ac:rich-text-body><p>Hi</p>'
        "</ac:rich-text-body></ac:structured-macro>"
    )
    assert to_markdown(storage) == "> [!TIP]\n>\n> Hi\n"


def test_md_page_links() -> None:
    storage = (
        '<p><ac:link><ri:page ri:content-title="A B" ri:space-key="S"/></ac:link> '
        '<ac:link><ri:page ri:content-title="C"/><ac:plain-text-link-body><![CDATA[see]]>'
        "</ac:plain-text-link-body></ac:link></p>"
    )
    assert to_markdown(storage) == "[A B](confluence:S/A%20B) [see](confluence:C)\n"


def test_md_attachment_image() -> None:
    storage = '<p><ac:image ac:alt="x"><ri:attachment ri:filename="a b.png"/></ac:image></p>'
    assert to_markdown(storage) == "![x](attachment:a%20b.png)\n"


def test_md_tasks() -> None:
    storage = (
        "<ac:task-list><ac:task><ac:task-id>1</ac:task-id><ac:task-status>complete"
        "</ac:task-status><ac:task-body>a</ac:task-body></ac:task></ac:task-list>"
    )
    assert to_markdown(storage) == "- [x] a\n"


def test_md_unknown_block_macro_on_own_paragraph() -> None:
    storage = '<p>a</p><ac:structured-macro ac:name="toc"/><p>b</p>'
    assert to_markdown(storage) == 'a\n\n<ac:structured-macro ac:name="toc"/>\n\nb\n'


def test_md_unknown_inline_macro_stays_inline() -> None:
    storage = '<p>x <ac:structured-macro ac:name="status"/> y</p>'
    assert to_markdown(storage) == 'x <ac:structured-macro ac:name="status"/> y\n'


def test_md_literal_angle_bracket_escaped() -> None:
    assert to_markdown("<p>a &lt;tag&gt; &amp;lt;</p>") == "a &lt;tag> &amp;lt;\n"


def test_md_empty() -> None:
    assert to_markdown("") == "\n"


# ── Markdown → storage ────────────────────────────────────────────────────────


def test_st_fence_becomes_code_macro() -> None:
    assert normalize(to_storage("```js\nlet a = '<ac:x/>';\n```\n")) == normalize(
        '<ac:structured-macro ac:name="code"><ac:parameter ac:name="language">js'
        "</ac:parameter><ac:plain-text-body><![CDATA[let a = '<ac:x/>';]]>"
        "</ac:plain-text-body></ac:structured-macro>"
    )


def test_st_callout_same_line_body() -> None:
    assert normalize(to_storage("> [!warning] Careful\n> now\n")) == normalize(
        '<ac:structured-macro ac:name="warning"><ac:rich-text-body><p>Careful now</p>'
        "</ac:rich-text-body></ac:structured-macro>"
    )


def test_st_plain_blockquote_stays_blockquote() -> None:
    assert normalize(to_storage("> just a quote\n")) == normalize(
        "<blockquote><p>just a quote</p></blockquote>"
    )


def test_st_task_list_ids_sequential_across_lists() -> None:
    out = to_storage("- [ ] a\n- [X] b\n\ntext\n\n- [ ] c\n")
    assert out.count("<ac:task-id>") == 3
    assert "<ac:task-id>3</ac:task-id>" in out
    assert "<ac:task-status>complete</ac:task-status><ac:task-body>b" in out


def test_st_regular_list_not_task_list() -> None:
    assert "<ac:task-list>" not in to_storage("- a\n- [ ] b\n")


def test_st_gfm_table_has_single_tbody() -> None:
    out = normalize(to_storage("| h |\n|---|\n| v |\n"))
    assert out == normalize("<table><tbody><tr><th>h</th></tr><tr><td>v</td></tr></tbody></table>")


def test_st_links_and_images() -> None:
    out = to_storage("[Doc](confluence:S/A%20B) [x](https://e.com) ![i](attachment:f.png)\n")
    assert normalize(out) == normalize(
        '<p><ac:link><ri:page ri:content-title="A B" ri:space-key="S"/>'
        "<ac:plain-text-link-body><![CDATA[Doc]]></ac:plain-text-link-body></ac:link> "
        '<a href="https://e.com">x</a> '
        '<ac:image ac:alt="i"><ri:attachment ri:filename="f.png"/></ac:image></p>'
    )


def test_st_raw_macro_in_code_span_is_text() -> None:
    assert to_storage("use `<ac:link>` here\n") == "<p>use <code>&lt;ac:link&gt;</code> here</p>"


def test_st_consecutive_callouts_stay_separate() -> None:
    out = to_storage("> [!INFO]\n>\n> a\n\n> [!NOTE]\n>\n> b\n")
    assert out.count("<ac:structured-macro") == 2
    assert "[!NOTE]" not in out


def test_st_adjacent_raw_blocks_not_wrapped_in_p() -> None:
    md = '<ac:structured-macro ac:name="toc"/>\n<ac:structured-macro ac:name="jira"/>\n'
    assert to_storage(md) == (
        '<ac:structured-macro ac:name="toc"/>\n<ac:structured-macro ac:name="jira"/>'
    )


def test_st_image_inside_page_link_roundtrips() -> None:
    """Images nested inside page links must be converted to ac:image, not dropped."""
    storage = (
        '<p><ac:link><ri:page ri:content-title="P"/><ac:link-body>'
        '<ac:image ac:alt="x"><ri:attachment ri:filename="a.png"/></ac:image>'
        "</ac:link-body></ac:link></p>"
    )
    result = to_storage(to_markdown(storage))
    assert normalize(result) == normalize(storage)
    assert "<img" not in result


def test_st_partial_task_list_keeps_markers() -> None:
    """If not all items in a list are tasks, the whole list stays as <ul> with markers intact."""
    result = to_storage("- [ ] a\n- **[ ]** b\n")
    assert "<ac:task-list>" not in result
    assert "<li>[ ] a</li>" in result


# ── final-review fixes ────────────────────────────────────────────────────────


def _roundtrips(storage: str) -> None:
    md = to_markdown(storage)
    assert normalize(to_storage(md)) == normalize(storage), md
    assert to_markdown(to_storage(md)) == md


def test_table_cell_pipe_roundtrips() -> None:
    _roundtrips(
        "<table><tbody><tr><th>h1</th><th>h2</th></tr>"
        "<tr><td>a | b</td><td><strong>x</strong></td></tr></tbody></table>"
    )


@pytest.mark.parametrize(
    "storage",
    [
        "<ul><li>a<ul><li>b</li></ul></li></ul>",
        "<ol><li>one<ol><li>sub</li></ol></li></ol>",
    ],
)
def test_nested_lists_roundtrip(storage: str) -> None:
    _roundtrips(storage)


def test_st_two_space_nested_list() -> None:
    assert normalize(to_storage("- a\n  - b\n")) == normalize(
        "<ul><li>a<ul><li>b</li></ul></li></ul>"
    )


def test_st_list_directly_after_paragraph() -> None:
    assert normalize(to_storage("Intro:\n- a\n- b\n")) == normalize(
        "<p>Intro:</p><ul><li>a</li><li>b</li></ul>"
    )


def test_st_fenced_code_inside_callout() -> None:
    assert normalize(to_storage("> [!INFO]\n> ```py\n> x < y\n> ```\n")) == normalize(
        '<ac:structured-macro ac:name="info"><ac:rich-text-body>'
        '<ac:structured-macro ac:name="code"><ac:parameter ac:name="language">py'
        "</ac:parameter><ac:plain-text-body><![CDATA[x < y]]></ac:plain-text-body>"
        "</ac:structured-macro></ac:rich-text-body></ac:structured-macro>"
    )


def test_st_output_is_xhtml() -> None:
    out = to_storage("a  \nb\n\n---\n\n<br>\n")
    assert "<br/>" in out and "<hr/>" in out
    assert "<br>" not in out and "<hr>" not in out
    normalize(out)  # parses as XML


@pytest.mark.parametrize(
    "storage",
    [
        "<p>- not a list</p>",
        "<p># not heading</p>",
        "<p>+ plus</p>",
        "<p>* star</p>",
        "<p>&gt; not quote</p>",
        "<p>2026. A year</p>",
        "<p>1) paren</p>",
        "<p>a<br/>- after break</p>",
    ],
)
def test_markdown_like_paragraph_text_roundtrips(storage: str) -> None:
    _roundtrips(storage)


def test_raw_macro_in_link_body_roundtrips() -> None:
    _roundtrips(
        '<p><ac:link><ri:page ri:content-title="P"/>'
        '<ac:link-body>see <ac:emoticon ac:name="tick"/></ac:link-body></ac:link></p>'
    )


@pytest.mark.parametrize(
    "storage",
    [
        '<p>Due <time datetime="2026-10-01"/> ok</p>',
        '<p>Due <time datetime="2026-10-01">1 Oct</time> ok</p>',
    ],
)
def test_time_element_passes_through(storage: str) -> None:
    _roundtrips(storage)
    assert "<time" in to_markdown(storage)


@pytest.mark.parametrize("tag", ["s", "del"])
def test_strikethrough_roundtrips(tag: str) -> None:
    md = to_markdown(f"<p>a <{tag}>gone</{tag}> b</p>")
    assert md == "a ~~gone~~ b\n"
    assert normalize(to_storage(md)) == normalize("<p>a <s>gone</s> b</p>")


@pytest.mark.parametrize("storage", ["<p>x<sup>2</sup></p>", "<p>H<sub>2</sub>O</p>"])
def test_sup_sub_roundtrip(storage: str) -> None:
    _roundtrips(storage)


def test_headerless_table_passes_through() -> None:
    storage = (
        "<table><tbody><tr><td>a</td><td>b</td></tr><tr><td>c</td><td>d</td></tr></tbody></table>"
    )
    _roundtrips(storage)
    assert "<th" not in to_storage(to_markdown(storage))


@pytest.mark.parametrize(
    "storage",
    [
        '<p><ac:link><ri:attachment ri:filename="spec v2.pdf"/></ac:link></p>',
        '<p><ac:link><ri:attachment ri:filename="x.pdf"/>'
        "<ac:plain-text-link-body><![CDATA[the spec]]></ac:plain-text-link-body></ac:link></p>",
    ],
)
def test_attachment_link_roundtrips(storage: str) -> None:
    _roundtrips(storage)


def test_st_attachment_link_markdown() -> None:
    assert normalize(to_storage("[f](attachment:x.pdf)\n")) == normalize(
        '<p><ac:link><ri:attachment ri:filename="x.pdf"/>'
        "<ac:plain-text-link-body><![CDATA[f]]></ac:plain-text-link-body></ac:link></p>"
    )
    assert to_markdown('<p><ac:link><ri:attachment ri:filename="a b.pdf"/></ac:link></p>') == (
        "[a b.pdf](attachment:a%20b.pdf)\n"
    )
