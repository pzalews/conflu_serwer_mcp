"""HTTP client for the Confluence Server REST API.

Knows auth, retries, status→exception mapping and pagination; nothing about
page content formats.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from tenacity import AsyncRetrying, RetryCallState, retry_if_exception, stop_after_attempt

from .config import Settings
from .exceptions import (
    AuthenticationError,
    AuthorizationError,
    ConfluenceAPIError,
    NotFoundError,
    PayloadTooLargeError,
    RateLimitError,
    ValidationError,
    VersionConflictError,
)
from .logging_setup import get_logger

log = get_logger(__name__)

_IDEMPOTENT = {"GET", "PUT", "DELETE"}
_MAX_RETRY_AFTER = 30.0


class _RetryableRateLimit(RateLimitError):
    def __init__(self, message: str, retry_after: float | None) -> None:
        super().__init__(429, message)
        self.retry_after = retry_after


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:500] or response.reason_phrase
    if isinstance(body, dict) and body.get("message"):
        return str(body["message"])
    return response.text[:500]


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    try:
        return min(float(value), _MAX_RETRY_AFTER) if value else None
    except ValueError:
        return None


def _raise_for_status(response: httpx.Response) -> None:
    status = response.status_code
    if status < 400:
        return
    message = _error_message(response)
    if status == 400:
        raise ValidationError(400, message)
    if status == 401:
        raise AuthenticationError(
            401,
            "Authentication failed — check CONFLUENCE_TOKEN "
            "(or CONFLUENCE_USERNAME/CONFLUENCE_PASSWORD)",
        )
    if status == 403:
        raise AuthorizationError(403, message or "Insufficient permissions")
    if status == 404:
        raise NotFoundError(404, message or "Not found")
    if status == 409:
        raise VersionConflictError(message or "Conflict — content was modified concurrently")
    if status == 413:
        raise PayloadTooLargeError(413, message or "Payload too large")
    if status == 429:
        raise _RetryableRateLimit(message or "Rate limited", _retry_after(response))
    raise ConfluenceAPIError(status, message)


class ConfluenceClient:
    def __init__(self, settings: Settings, *, retry_wait: float = 0.5) -> None:
        self._settings = settings
        self._retry_wait = retry_wait
        headers = {
            "Accept": "application/json",
            **settings.get_auth_headers(),
            **settings.get_custom_headers(),
        }
        self._http = httpx.AsyncClient(
            base_url=settings.confluence_url,
            headers=headers,
            timeout=httpx.Timeout(settings.confluence_timeout_seconds, connect=10.0),
            follow_redirects=True,
        )

    @property
    def base_url(self) -> str:
        return self._settings.confluence_url

    async def aclose(self) -> None:
        await self._http.aclose()

    def _should_retry(self, method: str) -> Any:
        def check(exc: BaseException) -> bool:
            if isinstance(exc, RateLimitError):
                return True
            if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
                return True  # request never reached the server
            if method not in _IDEMPOTENT:
                return False
            if isinstance(exc, httpx.TransportError):
                return True
            return isinstance(exc, ConfluenceAPIError) and exc.status_code >= 500

        return check

    def _wait(self, state: RetryCallState) -> float:
        exc = state.outcome.exception() if state.outcome else None
        retry_after = getattr(exc, "retry_after", None)
        if retry_after is not None:
            return float(retry_after)
        return float(min(self._retry_wait * 2 ** (state.attempt_number - 1), 4.0))

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        files: dict[str, Any] | None = None,
        data: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Send a request with retries; raise a typed exception for HTTP errors."""
        retrying = AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=self._wait,
            retry=retry_if_exception(self._should_retry(method)),
            reraise=True,
        )
        response: httpx.Response | None = None
        async for attempt in retrying:
            with attempt:
                start = time.monotonic()
                response = await self._http.request(
                    method,
                    path,
                    params=params,
                    json=json,
                    files=files,
                    data=data,
                    headers=headers,
                )
                log.info(
                    "confluence.request",
                    method=method,
                    path=path,
                    status=response.status_code,
                    duration_ms=round((time.monotonic() - start) * 1000),
                )
                _raise_for_status(response)
        assert response is not None
        return response

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = await self.request("GET", path, params=params)
        return response.json() if response.content else None

    async def post(
        self,
        path: str,
        json: Any = None,
        *,
        params: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        data: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        response = await self.request(
            "POST", path, params=params, json=json, files=files, data=data, headers=headers
        )
        return response.json() if response.content else None

    async def put(self, path: str, json: Any = None) -> Any:
        response = await self.request("PUT", path, json=json)
        return response.json() if response.content else None

    async def delete(self, path: str, params: dict[str, Any] | None = None) -> None:
        await self.request("DELETE", path, params=params)

    async def get_bytes(self, path: str) -> tuple[bytes, str]:
        """Download a binary resource (path may be relative to the base URL)."""
        response = await self.request("GET", path)
        return response.content, response.headers.get("Content-Type", "")

    async def paginate(
        self, path: str, params: dict[str, Any] | None = None, *, max_items: int = 500
    ) -> list[dict[str, Any]]:
        """Collect ``results`` across pages by following ``_links.next``."""
        page_params: dict[str, Any] = {**(params or {}), "start": 0, "limit": 100}
        results: list[dict[str, Any]] = []
        while len(results) < max_items:
            data = await self.get(path, params=page_params)
            batch: list[dict[str, Any]] = data.get("results", [])
            results.extend(batch)
            if not batch or "next" not in data.get("_links", {}):
                break
            page_params["start"] = data.get("start", page_params["start"]) + len(batch)
        return results[:max_items]
