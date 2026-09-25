from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from confluence_mcp.client import ConfluenceClient
from confluence_mcp.config import Settings
from confluence_mcp.exceptions import NotFoundError
from confluence_mcp.tools.history import get_page_history, get_page_version
from confluence_mcp.tools.spaces import get_space, list_spaces
from confluence_mcp.tools.users import get_current_user, get_user
from tests.conftest import BASE, make_ctx
from tests.test_content import page

SPACE = {
    "key": "DOC",
    "name": "Docs",
    "type": "global",
    "description": {"plain": {"value": "All docs"}},
    "homepage": {"id": "1"},
    "_links": {"webui": "/display/DOC"},
}


@pytest.fixture
def ctx(client: ConfluenceClient, settings: Settings) -> Any:
    return make_ctx(client, settings)


@respx.mock
async def test_spaces(ctx: Any) -> None:
    route = respx.get(f"{BASE}/rest/api/space").mock(
        return_value=httpx.Response(200, json={"results": [SPACE], "size": 1})
    )
    respx.get(f"{BASE}/rest/api/space/DOC").mock(return_value=httpx.Response(200, json=SPACE))
    listed = await list_spaces(ctx, type="global")
    assert route.calls.last.request.url.params["type"] == "global"
    expected = {
        "key": "DOC",
        "name": "Docs",
        "type": "global",
        "description": "All docs",
        "homepage_id": "1",
        "url": f"{BASE}/display/DOC",
    }
    assert listed["results"] == [expected]
    assert await get_space(ctx, "DOC") == expected


@respx.mock
async def test_users(ctx: Any) -> None:
    user = {"username": "ann", "userKey": "k1", "displayName": "Ann", "type": "known"}
    respx.get(f"{BASE}/rest/api/user/current").mock(return_value=httpx.Response(200, json=user))
    by_key = respx.get(f"{BASE}/rest/api/user").mock(return_value=httpx.Response(200, json=user))
    assert (await get_current_user(ctx))["user_key"] == "k1"
    await get_user(ctx, user_key="k1")
    assert by_key.calls.last.request.url.params["key"] == "k1"
    with pytest.raises(ValueError):
        await get_user(ctx)


@respx.mock
async def test_history_falls_back_to_second_endpoint(ctx: Any) -> None:
    respx.get(f"{BASE}/rest/experimental/content/42/version").mock(return_value=httpx.Response(404))
    respx.get(f"{BASE}/rest/api/content/42/version").mock(
        return_value=httpx.Response(
            200,
            json={"results": [{"number": 2, "when": "t", "by": {"displayName": "Ann"}}]},
        )
    )
    assert await get_page_history(ctx, "42") == [
        {"number": 2, "when": "t", "by": "Ann", "message": None}
    ]


@respx.mock
async def test_history_unavailable(ctx: Any) -> None:
    respx.get(f"{BASE}/rest/experimental/content/42/version").mock(return_value=httpx.Response(404))
    respx.get(f"{BASE}/rest/api/content/42/version").mock(return_value=httpx.Response(404))
    with pytest.raises(NotFoundError, match="history"):
        await get_page_history(ctx, "42")


@respx.mock
async def test_get_page_version(ctx: Any) -> None:
    route = respx.get(f"{BASE}/rest/api/content/42").mock(
        return_value=httpx.Response(200, json=page(version=1, storage="<p>v1</p>"))
    )
    out = await get_page_version(ctx, "42", 1)
    assert out["body"] == "v1\n"
    assert route.calls.last.request.url.params["version"] == "1"
