from __future__ import annotations

import httpx
import pytest
import respx

from confluence_mcp.client import ConfluenceClient
from confluence_mcp.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ConfluenceAPIError,
    NotFoundError,
    PayloadTooLargeError,
    RateLimitError,
    ValidationError,
    VersionConflictError,
)
from tests.conftest import BASE, make_settings


@respx.mock
async def test_sends_auth_and_custom_headers() -> None:
    c = ConfluenceClient(make_settings(confluence_custom_headers="X-Proxy=abc"), retry_wait=0)
    route = respx.get(f"{BASE}/rest/api/space").mock(return_value=httpx.Response(200, json={}))
    await c.get("/rest/api/space")
    headers = route.calls.last.request.headers
    assert headers["Authorization"] == "Bearer secret-token"
    assert headers["X-Proxy"] == "abc"
    await c.aclose()


@respx.mock
async def test_context_path_kept() -> None:
    c = ConfluenceClient(make_settings(confluence_url=f"{BASE}/confluence"), retry_wait=0)
    route = respx.get(f"{BASE}/confluence/rest/api/space").mock(
        return_value=httpx.Response(200, json={})
    )
    await c.get("/rest/api/space")
    assert route.called
    await c.aclose()


@pytest.mark.parametrize(
    ("status", "exc"),
    [
        (400, ValidationError),
        (401, AuthenticationError),
        (403, AuthorizationError),
        (404, NotFoundError),
        (409, VersionConflictError),
        (413, PayloadTooLargeError),
        (418, ConfluenceAPIError),
    ],
)
@respx.mock
async def test_status_mapping(client: ConfluenceClient, status: int, exc: type[Exception]) -> None:
    respx.get(f"{BASE}/x").mock(
        return_value=httpx.Response(status, json={"statusCode": status, "message": "boom msg"})
    )
    with pytest.raises(exc) as info:
        await client.get("/x")
    if status != 401:
        assert "boom msg" in str(info.value)


@respx.mock
async def test_error_text_never_contains_token(client: ConfluenceClient) -> None:
    respx.get(f"{BASE}/x").mock(return_value=httpx.Response(401, text="nope"))
    with pytest.raises(AuthenticationError) as info:
        await client.get("/x")
    assert "secret-token" not in str(info.value)
    assert "CONFLUENCE_TOKEN (or CONFLUENCE_USERNAME/CONFLUENCE_PASSWORD)" in str(info.value)


@respx.mock
async def test_retries_get_on_503(client: ConfluenceClient) -> None:
    route = respx.get(f"{BASE}/x").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json={"ok": True})]
    )
    assert await client.get("/x") == {"ok": True}
    assert route.call_count == 2


@respx.mock
async def test_gives_up_after_three_attempts(client: ConfluenceClient) -> None:
    route = respx.get(f"{BASE}/x").mock(return_value=httpx.Response(502))
    with pytest.raises(ConfluenceAPIError):
        await client.get("/x")
    assert route.call_count == 3


@respx.mock
async def test_post_not_retried_on_5xx(client: ConfluenceClient) -> None:
    route = respx.post(f"{BASE}/x").mock(return_value=httpx.Response(500))
    with pytest.raises(ConfluenceAPIError):
        await client.post("/x", json={})
    assert route.call_count == 1


@respx.mock
async def test_post_retried_on_429_honouring_retry_after(client: ConfluenceClient) -> None:
    route = respx.post(f"{BASE}/x").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json={"id": "1"}),
        ]
    )
    assert await client.post("/x", json={}) == {"id": "1"}
    assert route.call_count == 2


@respx.mock
async def test_429_exhausted_raises_rate_limit(client: ConfluenceClient) -> None:
    respx.get(f"{BASE}/x").mock(return_value=httpx.Response(429, headers={"Retry-After": "0"}))
    with pytest.raises(RateLimitError):
        await client.get("/x")


@respx.mock
async def test_connect_error_retried_for_post(client: ConfluenceClient) -> None:
    route = respx.post(f"{BASE}/x").mock(
        side_effect=[httpx.ConnectError("down"), httpx.Response(200, json={})]
    )
    await client.post("/x", json={})
    assert route.call_count == 2


@respx.mock
async def test_paginate_follows_next(client: ConfluenceClient) -> None:
    route = respx.get(f"{BASE}/rest/api/space").mock(
        side_effect=[
            httpx.Response(
                200,
                json={"results": [{"key": "A"}], "start": 0, "_links": {"next": "/n"}},
            ),
            httpx.Response(200, json={"results": [{"key": "B"}], "start": 1, "_links": {}}),
        ]
    )
    assert await client.paginate("/rest/api/space") == [{"key": "A"}, {"key": "B"}]
    assert route.calls[1].request.url.params["start"] == "1"


@respx.mock
async def test_delete_returns_none_on_204(client: ConfluenceClient) -> None:
    respx.delete(f"{BASE}/x").mock(return_value=httpx.Response(204))
    assert await client.delete("/x") is None
