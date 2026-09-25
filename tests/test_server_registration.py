from __future__ import annotations

import asyncio

from confluence_mcp.server import create_server

EXPECTED_TOOLS = {
    "list_spaces", "get_space",
    "get_page", "get_page_children", "get_page_ancestors", "create_page", "update_page",
    "delete_page", "move_page",
    "list_blog_posts", "get_blog_post", "create_blog_post", "update_blog_post",
    "search", "search_text",
    "list_comments", "add_comment", "update_comment", "delete_comment",
    "get_labels", "add_labels", "remove_label",
    "list_attachments", "download_attachment", "upload_attachment", "delete_attachment",
    "get_page_history", "get_page_version", "restore_page_version",
    "get_current_user", "get_user",
}  # fmt: skip


def test_all_tools_registered() -> None:
    tools = asyncio.run(create_server().list_tools())
    assert {t.name for t in tools} == EXPECTED_TOOLS
    assert len(EXPECTED_TOOLS) == 31


def test_ctx_not_exposed_in_tool_schema() -> None:
    tools = asyncio.run(create_server().list_tools())
    for tool in tools:
        assert "ctx" not in tool.parameters.get("properties", {}), tool.name


def test_format_parameter_is_enum() -> None:
    tools = {t.name: t for t in asyncio.run(create_server().list_tools())}
    fmt = tools["get_page"].parameters["properties"]["format"]
    assert fmt["enum"] == ["markdown", "storage"]


def test_resources_registered() -> None:
    mcp = create_server()
    resources = asyncio.run(mcp.list_resources())
    templates = asyncio.run(mcp.list_resource_templates())
    uris = {str(r.uri) for r in resources} | {t.uri_template for t in templates}
    assert uris == {
        "confluence://spaces",
        "confluence://space/{space_key}",
        "confluence://page/{page_id}",
    }


def test_prompts_registered() -> None:
    prompts = asyncio.run(create_server().list_prompts())
    assert {p.name for p in prompts} == {
        "summarize_page",
        "draft_page_from_notes",
        "find_and_answer",
    }
