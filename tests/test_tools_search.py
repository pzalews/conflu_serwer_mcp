from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from confluence_mcp.client import ConfluenceClient
from confluence_mcp.config import Settings
from confluence_mcp.tools.search import search, search_text
from tests.conftest import BASE, make_ctx

HIT = {
    "content": {"id": "42", "type": "page", "title": "Deploy", "space": {"key": "OPS"}},
    "title": "Deploy",
    "excerpt": "how to @@@hl@@@deploy@@@endhl@@@",
    "url": "/display/OPS/Deploy",
    "lastModified": "2026-09-01T10:00:00.000Z",
    "resultGlobalContainer": {"title": "Operations"},
}


@pytest.fixture
def ctx(client: ConfluenceClient, settings: Settings) -> Any:
    return make_ctx(client, settings)


@respx.mock
async def test_search_compact_hits(ctx: Any) -> None:
    respx.get(f"{BASE}/rest/api/search").mock(
        return_value=httpx.Response(
            200, json={"results": [HIT], "start": 0, "limit": 25, "size": 1, "totalSize": 3}
        )
    )
    out = await search(ctx, cql="type = page")
    assert out["results"] == [
        {
            "id": "42",
            "type": "page",
            "title": "Deploy",
            "space": "OPS",
            "excerpt": "how to @@@hl@@@deploy@@@endhl@@@",
            "url": f"{BASE}/display/OPS/Deploy",
            "last_modified": "2026-09-01T10:00:00.000Z",
        }
    ]
    assert out["has_more"] is True


@respx.mock
async def test_search_text_escapes_quotes(ctx: Any) -> None:
    route = respx.get(f"{BASE}/rest/api/search").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    await search_text(ctx, text='say "hi" \\ bye', space_key="OPS", type="page")
    assert route.calls.last.request.url.params["cql"] == (
        'text ~ "say \\"hi\\" \\\\ bye" AND space = "OPS" AND type = page '
        "ORDER BY lastmodified DESC"
    )
