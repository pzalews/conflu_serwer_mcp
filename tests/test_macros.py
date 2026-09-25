from __future__ import annotations

from collections import Counter

from confluence_mcp.converter.macros import cdata, cdata_text, find_elements, inventory


def test_find_outermost_elements_only() -> None:
    text = (
        '<p>a</p><ac:structured-macro ac:name="info"><ac:rich-text-body>'
        '<ac:structured-macro ac:name="jira"/></ac:rich-text-body></ac:structured-macro>'
        '<ri:page ri:content-title="T"/>'
    )
    els = find_elements(text)
    assert [e.name for e in els] == ["ac:structured-macro", "ri:page"]
    assert els[0].attrs == {"ac:name": "info"}
    assert els[0].text.endswith("</ac:structured-macro>")
    assert els[1].attrs == {"ri:content-title": "T"}


def test_nested_same_name_matched_correctly() -> None:
    text = (
        '<ac:structured-macro ac:name="expand"><ac:rich-text-body>'
        '<ac:structured-macro ac:name="expand"><ac:rich-text-body>x</ac:rich-text-body>'
        "</ac:structured-macro></ac:rich-text-body></ac:structured-macro>tail"
    )
    [el] = find_elements(text)
    assert text[el.end :] == "tail"


def test_children_have_absolute_offsets() -> None:
    text = '<ac:link><ri:page ri:content-title="T"/><ac:link-body>x</ac:link-body></ac:link>'
    [el] = find_elements(text)
    kids = el.children()
    assert [k.name for k in kids] == ["ri:page", "ac:link-body"]
    assert kids[1].inner == "x"


def test_cdata_content_is_not_scanned() -> None:
    text = "<ac:plain-text-body><![CDATA[<ac:fake>]]></ac:plain-text-body>"
    [el] = find_elements(text)
    assert el.children() == []


def test_markdown_mode_skips_code() -> None:
    md = "`<ac:a/>` and\n\n```\n<ac:b/>\n```\n\n<ac:c/>"
    assert [e.text for e in find_elements(md, markdown=True)] == ["<ac:c/>"]


def test_unclosed_element_runs_to_end() -> None:
    [el] = find_elements('<p>x</p><ac:structured-macro ac:name="toc"><p>y</p>')
    assert el.text == '<ac:structured-macro ac:name="toc"><p>y</p>'


def test_cdata_roundtrip_with_terminator() -> None:
    wrapped = cdata("a ]]> b")
    assert wrapped == "<![CDATA[a ]]]]><![CDATA[> b]]>"
    assert cdata_text(wrapped) == "a ]]> b"


def test_inventory_counts_macros_and_structures() -> None:
    storage = (
        '<ac:structured-macro ac:name="jira"/><ac:structured-macro ac:name="jira">'
        '</ac:structured-macro><ac:macro ac:name="toc"/><ac:link><ri:page/></ac:link>'
        '<ac:image><ri:url ri:value="u"/></ac:image><ac:task-list></ac:task-list>'
        '<ac:plain-text-body><![CDATA[<ac:structured-macro ac:name="fake"/>]]>'
        "</ac:plain-text-body>"
    )
    assert inventory(storage) == Counter(
        {"jira": 2, "toc": 1, "ac:link": 1, "ac:image": 1, "ac:task-list": 1}
    )
