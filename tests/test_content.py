from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from confluence_mcp.client import ConfluenceClient
from confluence_mcp.content import (
    compact,
    create_content,
    find_by_title,
    get_content,
    restore_version,
    update_content,
)
from confluence_mcp.exceptions import MacroLossError, NotFoundError, VersionConflictError
from tests.conftest import BASE

TOC = '<ac:structured-macro ac:name="toc"/>'


def page(version: int = 3, storage: str = "<p>old</p>", **extra: Any) -> dict[str, Any]:
    return {
        "id": "42",
        "type": "page",
        "title": "Home",
        "space": {"key": "DOC", "name": "Docs"},
        "version": {"number": version, "when": "2026-01-01", "by": {"displayName": "Ann"}},
        "body": {"storage": {"value": storage}},
        "_links": {"webui": "/display/DOC/Home"},
        **extra,
    }


def test_compact_shape(client: ConfluenceClient) -> None:
    data = page(
        ancestors=[{"id": "1", "title": "Root"}],
        metadata={"labels": {"results": [{"name": "a"}]}},
    )
    out = compact(client, data, "markdown")
    assert out == {
        "id": "42",
        "type": "page",
        "title": "Home",
        "space": {"key": "DOC", "name": "Docs"},
        "version": {"number": 3, "when": "2026-01-01", "by": "Ann", "message": None},
        "url": f"{BASE}/display/DOC/Home",
        "labels": ["a"],
        "ancestors": [{"id": "1", "title": "Root"}],
        "format": "markdown",
        "body": "old\n",
    }


@respx.mock
async def test_get_content_storage_format(client: ConfluenceClient) -> None:
    route = respx.get(f"{BASE}/rest/api/content/42").mock(
        return_value=httpx.Response(200, json=page())
    )
    out = await get_content(client, "42", "storage")
    assert out["body"] == "<p>old</p>"
    assert "body.storage" in route.calls.last.request.url.params["expand"]


@respx.mock
async def test_get_content_historical(client: ConfluenceClient) -> None:
    route = respx.get(f"{BASE}/rest/api/content/42").mock(
        return_value=httpx.Response(200, json=page(version=1))
    )
    await get_content(client, "42", "markdown", version=1)
    params = route.calls.last.request.url.params
    assert params["status"] == "historical"
    assert params["version"] == "1"


@respx.mock
async def test_find_by_title_not_found(client: ConfluenceClient) -> None:
    respx.get(f"{BASE}/rest/api/content").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    with pytest.raises(NotFoundError, match="Missing"):
        await find_by_title(client, "DOC", "Missing", "markdown")


@respx.mock
async def test_create_converts_markdown_and_sets_parent(client: ConfluenceClient) -> None:
    route = respx.post(f"{BASE}/rest/api/content").mock(
        return_value=httpx.Response(200, json=page(version=1))
    )
    out = await create_content(client, "page", "DOC", "Home", "# Hi", "markdown", parent_id="7")
    sent = json.loads(route.calls.last.request.content)
    assert sent["body"]["storage"] == {"value": "<h1>Hi</h1>", "representation": "storage"}
    assert sent["ancestors"] == [{"id": "7"}]
    assert sent["space"] == {"key": "DOC"}
    assert "body" not in out


@respx.mock
async def test_update_bumps_version(client: ConfluenceClient) -> None:
    respx.get(f"{BASE}/rest/api/content/42").mock(return_value=httpx.Response(200, json=page()))
    put = respx.put(f"{BASE}/rest/api/content/42").mock(
        return_value=httpx.Response(200, json=page(version=4))
    )
    out = await update_content(client, "42", body="new", version_comment="why")
    sent = json.loads(put.calls.last.request.content)
    assert sent["version"] == {"number": 4, "message": "why"}
    assert sent["title"] == "Home"
    assert sent["type"] == "page"
    assert sent["body"]["storage"]["value"] == "<p>new</p>"
    assert "ancestors" not in sent
    assert out["version"]["number"] == 4


@respx.mock
async def test_update_expected_version_mismatch(client: ConfluenceClient) -> None:
    respx.get(f"{BASE}/rest/api/content/42").mock(return_value=httpx.Response(200, json=page()))
    put = respx.put(f"{BASE}/rest/api/content/42")
    with pytest.raises(VersionConflictError) as info:
        await update_content(client, "42", body="x", expected_version=2)
    assert info.value.current_version == 3
    assert not put.called


@respx.mock
async def test_update_409_from_put(client: ConfluenceClient) -> None:
    respx.get(f"{BASE}/rest/api/content/42").mock(return_value=httpx.Response(200, json=page()))
    respx.put(f"{BASE}/rest/api/content/42").mock(
        return_value=httpx.Response(409, json={"message": "Version must be incremented"})
    )
    with pytest.raises(VersionConflictError):
        await update_content(client, "42", body="x", expected_version=3)


@respx.mock
async def test_update_rejects_macro_loss(client: ConfluenceClient) -> None:
    respx.get(f"{BASE}/rest/api/content/42").mock(
        return_value=httpx.Response(200, json=page(storage=f"<p>a</p>{TOC}"))
    )
    put = respx.put(f"{BASE}/rest/api/content/42")
    with pytest.raises(MacroLossError, match="toc×1"):
        await update_content(client, "42", body="only text")
    with pytest.raises(MacroLossError):
        await update_content(client, "42", body="<p>x</p>", fmt="storage")
    assert not put.called


@respx.mock
async def test_update_macro_loss_override(client: ConfluenceClient) -> None:
    respx.get(f"{BASE}/rest/api/content/42").mock(
        return_value=httpx.Response(200, json=page(storage=TOC))
    )
    put = respx.put(f"{BASE}/rest/api/content/42").mock(
        return_value=httpx.Response(200, json=page(version=4))
    )
    await update_content(client, "42", body="gone", allow_macro_loss=True)
    assert put.called


@respx.mock
async def test_update_keeping_raw_macro_passes(client: ConfluenceClient) -> None:
    respx.get(f"{BASE}/rest/api/content/42").mock(
        return_value=httpx.Response(200, json=page(storage=f"<p>a</p>{TOC}"))
    )
    put = respx.put(f"{BASE}/rest/api/content/42").mock(
        return_value=httpx.Response(200, json=page(version=4))
    )
    await update_content(client, "42", body=f"b\n\n{TOC}\n")
    assert TOC in json.loads(put.calls.last.request.content)["body"]["storage"]["value"]


@respx.mock
async def test_title_only_update_keeps_body(client: ConfluenceClient) -> None:
    respx.get(f"{BASE}/rest/api/content/42").mock(
        return_value=httpx.Response(200, json=page(storage=TOC))
    )
    put = respx.put(f"{BASE}/rest/api/content/42").mock(
        return_value=httpx.Response(200, json=page(version=4))
    )
    await update_content(client, "42", title="Renamed")
    sent = json.loads(put.calls.last.request.content)
    assert sent["title"] == "Renamed"
    assert sent["body"]["storage"]["value"] == TOC


@respx.mock
async def test_restore_version(client: ConfluenceClient) -> None:
    def get_side_effect(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("status") == "historical":
            return httpx.Response(200, json=page(version=1, storage="<p>v1</p>"))
        return httpx.Response(200, json=page(version=3, storage=f"<p>v3</p>{TOC}"))

    respx.get(f"{BASE}/rest/api/content/42").mock(side_effect=get_side_effect)
    put = respx.put(f"{BASE}/rest/api/content/42").mock(
        return_value=httpx.Response(200, json=page(version=4))
    )
    await restore_version(client, "42", 1)
    sent = json.loads(put.calls.last.request.content)
    assert sent["body"]["storage"]["value"] == "<p>v1</p>"
    assert sent["version"] == {"number": 4, "message": "Restored version 1"}


def test_macro_loss_message_does_not_push_override() -> None:
    from collections import Counter

    msg = str(MacroLossError(Counter({"toc": 1})))
    assert "toc×1" in msg
    assert "Markdown conversion or the edit would remove" in msg
    assert 'format="storage"' in msg and "Re-read the page" in msg
    assert "allow_macro_loss=true only if removing them is intended" in msg
