"""Caller-supplied ids and space keys must never be able to alter a REST path."""

from __future__ import annotations

import inspect
from typing import Any

import pytest
import respx
from fastmcp import Client

from confluence_mcp.client import ConfluenceClient
from confluence_mcp.server import create_server
from confluence_mcp.tools import ALL_TOOLS
from confluence_mcp.tools._common import check_content_id, check_space_key, cql_string
from tests.conftest import BASE, make_ctx, make_settings

ID_PARAMS = {
    "page_id",
    "content_id",
    "blog_post_id",
    "comment_id",
    "attachment_id",
    "target_parent_id",
    "parent_id",
    "parent_comment_id",
}
BAD_ID = "123/../../space/KEY"
BAD_KEY = "KEY/../../content/1"
# search_text only puts the key into an escaped CQL string, never into a path.
_NOT_PATH = {("search_text", "space_key")}
_EXTRA: dict[str, dict[str, Any]] = {
    "get_page": {"title": "T"},
    "upload_attachment": {"text": "x"},
    "download_attachment": {"filename": "f.txt"},
}


def _cases() -> list[tuple[Any, str]]:
    cases = []
    for fn in ALL_TOOLS:
        for name in inspect.signature(fn).parameters:
            if (name in ID_PARAMS or name == "space_key") and (fn.__name__, name) not in _NOT_PATH:
                cases.append((fn, name))
    return cases


def _kwargs(fn: Any, target: str) -> dict[str, Any]:
    kwargs: dict[str, Any] = dict(_EXTRA.get(fn.__name__, {}))
    for name, param in inspect.signature(fn).parameters.items():
        if name == "ctx":
            continue
        if name in ID_PARAMS:
            if param.default is inspect.Parameter.empty or name == target:
                kwargs[name] = "42"
        elif name == "space_key":
            kwargs[name] = "DOC"
        elif param.default is inspect.Parameter.empty and name not in kwargs:
            kwargs[name] = {"labels": ["x"], "version": 1}.get(name, "x")
    if fn.__name__ == "download_attachment" and target == "attachment_id":
        kwargs.pop("filename")
    kwargs[target] = BAD_KEY if target == "space_key" else BAD_ID
    return kwargs


def test_cases_cover_known_tools() -> None:
    names = {f"{fn.__name__}.{p}" for fn, p in _cases()}
    for expected in (
        "delete_page.page_id",
        "move_page.target_parent_id",
        "get_space.space_key",
        "list_blog_posts.space_key",
        "download_attachment.attachment_id",
        "delete_attachment.attachment_id",
        "get_page_history.page_id",
        "remove_label.content_id",
        "delete_comment.comment_id",
    ):
        assert expected in names


@pytest.mark.parametrize(
    ("tool_fn", "param"), _cases(), ids=lambda v: v if isinstance(v, str) else v.__name__
)
@respx.mock(assert_all_called=False)
async def test_traversal_rejected_without_http(
    tool_fn: Any, param: str, respx_mock: respx.MockRouter
) -> None:
    settings = make_settings()
    client = ConfluenceClient(settings, retry_wait=0)
    try:
        with pytest.raises(ValueError, match=param):
            await tool_fn(ctx=make_ctx(client, settings), **_kwargs(tool_fn, param))
    finally:
        await client.aclose()
    assert not respx_mock.calls


async def test_default_space_is_validated() -> None:
    from confluence_mcp.tools.spaces import get_space

    settings = make_settings(confluence_default_space="A/../B")
    client = ConfluenceClient(settings, retry_wait=0)
    with respx.mock(assert_all_called=False) as mock:
        with pytest.raises(ValueError, match="space_key"):
            await get_space(make_ctx(client, settings))
        assert not mock.calls
    await client.aclose()


@pytest.mark.parametrize("value", ["1", "42", "1234567890", "att123"])
def test_content_id_accepts_digits(value: str) -> None:
    assert check_content_id(value, "page_id") == value


@pytest.mark.parametrize("value", ["", "abc", "1/2", "../1", "1 ", "１２", "att", "att1/../2"])
def test_content_id_rejects(value: str) -> None:
    with pytest.raises(ValueError, match="page_id"):
        check_content_id(value, "page_id")


@pytest.mark.parametrize("value", ["DOC", "ds", "~jdoe", "~john.doe", "TEAM_2", "~a-b"])
def test_space_key_accepts(value: str) -> None:
    assert check_space_key(value) == value


@pytest.mark.parametrize("value", ["", "A/B", "..", ".", "A?x=1", "A B", "A#b", "A%2F"])
def test_space_key_rejects(value: str) -> None:
    with pytest.raises(ValueError, match="space_key"):
        check_space_key(value)


def test_cql_string_escapes() -> None:
    assert cql_string('a "b" \\') == '"a \\"b\\" \\\\"'


@pytest.mark.parametrize(
    "uri", ["confluence://page/abc", "confluence://page/1..2", "confluence://space/A%23x"]
)
async def test_resources_validate(uri: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONFLUENCE_URL", BASE)
    monkeypatch.setenv("CONFLUENCE_TOKEN", "secret-token")
    with respx.mock(assert_all_called=False) as mock:
        route = mock.route().respond(200, json={"results": []})
        async with Client(create_server()) as mcp_client:
            with pytest.raises(Exception, match="page_id|space_key"):
                await mcp_client.read_resource(uri)
        assert not route.called


async def test_list_blog_posts_uses_shared_cql_escaping(monkeypatch: pytest.MonkeyPatch) -> None:
    from confluence_mcp.tools import blogposts

    seen: list[str] = []

    def fake_cql_string(value: str) -> str:
        seen.append(value)
        return cql_string(value)

    monkeypatch.setattr(blogposts, "cql_string", fake_cql_string)
    settings = make_settings()
    client = ConfluenceClient(settings, retry_wait=0)
    with respx.mock() as mock:
        route = mock.get(f"{BASE}/rest/api/content/search").respond(200, json={"results": []})
        await blogposts.list_blog_posts(make_ctx(client, settings), space_key="DOC")
    await client.aclose()
    assert seen == ["DOC"]
    assert 'space = "DOC"' in route.calls.last.request.url.params["cql"]
