from __future__ import annotations

from confluence_mcp.converter.to_markdown import to_markdown

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
