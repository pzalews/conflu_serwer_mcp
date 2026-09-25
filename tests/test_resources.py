from __future__ import annotations

import json

import httpx
import pytest
import respx
from fastmcp import Client

from confluence_mcp.server import create_server
from tests.conftest import BASE
from tests.test_content import page


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONFLUENCE_URL", BASE)
    monkeypatch.setenv("CONFLUENCE_TOKEN", "secret-token")


@respx.mock
async def test_page_resource_is_markdown() -> None:
    respx.get(f"{BASE}/rest/api/content/42").mock(return_value=httpx.Response(200, json=page()))
    async with Client(create_server()) as client:
        [contents] = await client.read_resource("confluence://page/42")
    assert contents.text.startswith("# Home\n\n_Space DOC · version 3 · ")
    assert contents.text.endswith("old\n")


@respx.mock
async def test_spaces_resource() -> None:
    respx.get(f"{BASE}/rest/api/space").mock(
        return_value=httpx.Response(200, json={"results": [{"key": "DOC", "name": "Docs"}]})
    )
    async with Client(create_server()) as client:
        [contents] = await client.read_resource("confluence://spaces")
    assert json.loads(contents.text) == [{"key": "DOC", "name": "Docs"}]


@respx.mock
async def test_tool_error_reaches_client_without_token() -> None:
    respx.get(f"{BASE}/rest/api/content/42").mock(return_value=httpx.Response(401))
    async with Client(create_server()) as client:
        result = await client.call_tool("get_page", {"page_id": "42"}, raise_on_error=False)
    assert result.is_error
    text = result.content[0].text
    assert "Authentication failed" in text
    assert "secret-token" not in text
