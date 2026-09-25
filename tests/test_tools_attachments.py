from __future__ import annotations

import base64
from typing import Any

import httpx
import pytest
import respx

from confluence_mcp.client import ConfluenceClient
from confluence_mcp.config import Settings
from confluence_mcp.exceptions import NotFoundError, PayloadTooLargeError
from confluence_mcp.tools.attachments import (
    delete_attachment,
    download_attachment,
    list_attachments,
    upload_attachment,
)
from tests.conftest import BASE, make_ctx, make_settings

DL = "/download/attachments/42/notes.txt?version=1&api=v2"


def att(size: int = 5, media: str = "text/plain", name: str = "notes.txt") -> dict[str, Any]:
    return {
        "id": "att9",
        "title": name,
        "extensions": {"mediaType": media, "fileSize": size},
        "version": {"number": 1},
        "_links": {"download": DL},
    }


@pytest.fixture
def ctx(client: ConfluenceClient, settings: Settings) -> Any:
    return make_ctx(client, settings)


@respx.mock
async def test_list_attachments(ctx: Any) -> None:
    respx.get(f"{BASE}/rest/api/content/42/child/attachment").mock(
        return_value=httpx.Response(200, json={"results": [att()]})
    )
    out = await list_attachments(ctx, "42")
    assert out["results"][0] == {
        "id": "att9",
        "filename": "notes.txt",
        "media_type": "text/plain",
        "size": 5,
        "version": 1,
        "download_url": f"{BASE}{DL}",
    }


@respx.mock
async def test_download_text_by_filename(ctx: Any) -> None:
    respx.get(f"{BASE}/rest/api/content/42/child/attachment").mock(
        return_value=httpx.Response(200, json={"results": [att()]})
    )
    respx.get(f"{BASE}/download/attachments/42/notes.txt").mock(
        return_value=httpx.Response(200, content=b"hello")
    )
    out = await download_attachment(ctx, "42", filename="notes.txt")
    assert out == {
        "filename": "notes.txt",
        "media_type": "text/plain",
        "size": 5,
        "encoding": "text",
        "content": "hello",
    }


@respx.mock
async def test_download_binary_by_id_is_base64(ctx: Any) -> None:
    respx.get(f"{BASE}/rest/api/content/att9").mock(
        return_value=httpx.Response(200, json=att(media="image/png", name="a.png"))
    )
    respx.get(f"{BASE}/download/attachments/42/notes.txt").mock(
        return_value=httpx.Response(200, content=b"\x89PNG")
    )
    out = await download_attachment(ctx, "42", attachment_id="att9")
    assert out["encoding"] == "base64"
    assert base64.b64decode(out["content"]) == b"\x89PNG"


@respx.mock
async def test_download_refuses_large_file_before_fetching(client: ConfluenceClient) -> None:
    settings = make_settings(confluence_attachment_max_bytes=4)
    respx.get(f"{BASE}/rest/api/content/42/child/attachment").mock(
        return_value=httpx.Response(200, json={"results": [att(size=5)]})
    )
    body = respx.get(f"{BASE}/download/attachments/42/notes.txt")
    with pytest.raises(PayloadTooLargeError):
        await download_attachment(make_ctx(client, settings), "42", filename="notes.txt")
    assert not body.called


@respx.mock
async def test_download_missing_filename(ctx: Any) -> None:
    respx.get(f"{BASE}/rest/api/content/42/child/attachment").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    with pytest.raises(NotFoundError):
        await download_attachment(ctx, "42", filename="nope.txt")


async def test_download_needs_exactly_one_selector(ctx: Any) -> None:
    with pytest.raises(ValueError):
        await download_attachment(ctx, "42")


@respx.mock
async def test_upload_new_attachment(ctx: Any) -> None:
    respx.get(f"{BASE}/rest/api/content/42/child/attachment").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    route = respx.post(f"{BASE}/rest/api/content/42/child/attachment").mock(
        return_value=httpx.Response(200, json={"results": [att()]})
    )
    out = await upload_attachment(ctx, "42", "notes.txt", text="hello", comment="v1")
    request = route.calls.last.request
    assert request.headers["X-Atlassian-Token"] == "no-check"
    assert b'filename="notes.txt"' in request.content
    assert b"hello" in request.content
    assert out["id"] == "att9"


@respx.mock
async def test_upload_existing_creates_new_version(ctx: Any) -> None:
    respx.get(f"{BASE}/rest/api/content/42/child/attachment").mock(
        return_value=httpx.Response(200, json={"results": [att()]})
    )
    route = respx.post(f"{BASE}/rest/api/content/42/child/attachment/att9/data").mock(
        return_value=httpx.Response(200, json=att())
    )
    await upload_attachment(ctx, "42", "notes.txt", content_base64=base64.b64encode(b"x").decode())
    assert route.called


async def test_upload_validation(ctx: Any) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        await upload_attachment(ctx, "42", "a.txt")
    with pytest.raises(ValueError, match="base64"):
        await upload_attachment(ctx, "42", "a.bin", content_base64="%%%")


async def test_upload_too_large(client: ConfluenceClient) -> None:
    settings = make_settings(confluence_attachment_max_bytes=2)
    with pytest.raises(PayloadTooLargeError):
        await upload_attachment(make_ctx(client, settings), "42", "a.txt", text="abc")


@respx.mock
async def test_delete_attachment(ctx: Any) -> None:
    respx.delete(f"{BASE}/rest/api/content/att9").mock(return_value=httpx.Response(204))
    assert (await delete_attachment(ctx, "att9"))["status"] == "deleted"


@respx.mock
async def test_download_link_resolved_under_context_path() -> None:
    settings = make_settings(confluence_url=f"{BASE}/confluence")
    client = ConfluenceClient(settings, retry_wait=0)
    respx.get(f"{BASE}/confluence/rest/api/content/42/child/attachment").mock(
        return_value=httpx.Response(200, json={"results": [att()]})
    )
    body = respx.get(f"{BASE}/confluence/download/attachments/42/notes.txt").mock(
        return_value=httpx.Response(200, content=b"hello")
    )
    out = await download_attachment(make_ctx(client, settings), "42", filename="notes.txt")
    assert body.called
    assert out["content"] == "hello"
    await client.aclose()
