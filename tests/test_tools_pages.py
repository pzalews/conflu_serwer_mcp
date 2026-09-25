from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from confluence_mcp.client import ConfluenceClient
from confluence_mcp.config import Settings
from confluence_mcp.tools.blogposts import create_blog_post, list_blog_posts
from confluence_mcp.tools.pages import (
    create_page,
    delete_page,
    get_page,
    get_page_ancestors,
    get_page_children,
    move_page,
    update_page,
)
from tests.conftest import BASE, make_ctx, make_settings
from tests.test_content import page


@pytest.fixture
def ctx(client: ConfluenceClient, settings: Settings) -> Any:
    return make_ctx(client, settings)


@respx.mock
async def test_get_page_by_id(ctx: Any) -> None:
    respx.get(f"{BASE}/rest/api/content/42").mock(return_value=httpx.Response(200, json=page()))
    out = await get_page(ctx, page_id="42")
    assert out["body"] == "old\n"
    assert out["format"] == "markdown"


@respx.mock
async def test_get_page_by_title_uses_default_space(client: ConfluenceClient) -> None:
    settings = make_settings(confluence_default_space="DOC")
    route = respx.get(f"{BASE}/rest/api/content").mock(
        return_value=httpx.Response(200, json={"results": [page()]})
    )
    await get_page(make_ctx(client, settings), title="Home")
    params = route.calls.last.request.url.params
    assert (params["spaceKey"], params["title"], params["type"]) == ("DOC", "Home", "page")


async def test_get_page_requires_id_or_title(ctx: Any) -> None:
    with pytest.raises(ValueError, match="page_id"):
        await get_page(ctx)


async def test_title_lookup_without_space_fails(ctx: Any) -> None:
    with pytest.raises(ValueError, match="space_key is required"):
        await get_page(ctx, title="Home")


@respx.mock
async def test_children_list_shape(ctx: Any) -> None:
    route = respx.get(f"{BASE}/rest/api/content/42/child/page").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [{"id": "7", "title": "Kid", "_links": {"webui": "/x"}}],
                "start": 0,
                "limit": 25,
                "size": 1,
                "_links": {"next": "/more"},
            },
        )
    )
    out = await get_page_children(ctx, "42", limit=500)
    assert out == {
        "results": [{"id": "7", "title": "Kid", "url": f"{BASE}/x"}],
        "start": 0,
        "limit": 25,
        "size": 1,
        "has_more": True,
    }
    assert route.calls.last.request.url.params["limit"] == "100"


@respx.mock
async def test_ancestors(ctx: Any) -> None:
    respx.get(f"{BASE}/rest/api/content/42").mock(
        return_value=httpx.Response(200, json={"ancestors": [{"id": "1", "title": "Root"}]})
    )
    assert await get_page_ancestors(ctx, "42") == [{"id": "1", "title": "Root"}]


@respx.mock
async def test_create_page(ctx: Any) -> None:
    route = respx.post(f"{BASE}/rest/api/content").mock(
        return_value=httpx.Response(200, json=page(version=1))
    )
    await create_page(ctx, title="T", body="<p>x</p>", space_key="DOC", format="storage")
    sent = json.loads(route.calls.last.request.content)
    assert sent["type"] == "page"
    assert sent["body"]["storage"]["value"] == "<p>x</p>"


@respx.mock
async def test_update_page_passes_safeguards(ctx: Any) -> None:
    respx.get(f"{BASE}/rest/api/content/42").mock(return_value=httpx.Response(200, json=page()))
    route = respx.put(f"{BASE}/rest/api/content/42").mock(
        return_value=httpx.Response(200, json=page(version=4))
    )
    await update_page(ctx, "42", body="new", expected_version=3)
    assert json.loads(route.calls.last.request.content)["version"]["number"] == 4


@respx.mock
async def test_delete_and_move(ctx: Any) -> None:
    respx.delete(f"{BASE}/rest/api/content/42").mock(return_value=httpx.Response(204))
    move = respx.put(f"{BASE}/rest/api/content/42/move/append/9").mock(
        return_value=httpx.Response(200, json={"pageId": 42})
    )
    assert (await delete_page(ctx, "42"))["status"] == "trashed"
    assert (await move_page(ctx, "42", "9"))["parent_id"] == "9"
    assert move.called


@respx.mock
async def test_blog_posts(ctx: Any) -> None:
    search = respx.get(f"{BASE}/rest/api/content/search").mock(
        return_value=httpx.Response(200, json={"results": [page(type="blogpost")], "size": 1})
    )
    create = respx.post(f"{BASE}/rest/api/content").mock(
        return_value=httpx.Response(200, json=page(type="blogpost"))
    )
    listed = await list_blog_posts(ctx, space_key="DOC")
    assert listed["results"][0]["type"] == "blogpost"
    assert search.calls.last.request.url.params["cql"] == (
        'type = blogpost AND space = "DOC" ORDER BY created DESC'
    )
    await create_blog_post(ctx, title="News", body="hi", space_key="DOC")
    assert json.loads(create.calls.last.request.content)["type"] == "blogpost"
