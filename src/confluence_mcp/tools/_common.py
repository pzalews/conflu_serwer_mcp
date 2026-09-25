"""Helpers shared by all tool modules."""

from __future__ import annotations

from typing import Any

from fastmcp import Context

from ..client import ConfluenceClient
from ..config import Settings
from ..exceptions import ReadOnlyModeError

MAX_LIMIT = 100


def get_client(ctx: Context) -> ConfluenceClient:
    client: ConfluenceClient = ctx.lifespan_context["client"]
    return client


def get_settings(ctx: Context) -> Settings:
    settings: Settings = ctx.lifespan_context["settings"]
    return settings


def require_writable(ctx: Context, tool_name: str) -> None:
    """Every write tool calls this first, before any HTTP request."""
    if get_settings(ctx).confluence_read_only:
        raise ReadOnlyModeError(tool_name)


def resolve_space(ctx: Context, space_key: str | None) -> str:
    resolved = space_key or get_settings(ctx).confluence_default_space
    if not resolved:
        raise ValueError("space_key is required when CONFLUENCE_DEFAULT_SPACE is not set")
    return resolved


def page_params(limit: int, start: int) -> dict[str, int]:
    return {"limit": max(1, min(limit, MAX_LIMIT)), "start": max(0, start)}


def list_result(data: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    """Uniform shape for paged list results."""
    start = int(data.get("start", 0))
    size = int(data.get("size", len(items)))
    total = data.get("totalSize")
    has_more = "next" in data.get("_links", {}) or (total is not None and start + size < int(total))
    return {
        "results": items,
        "start": start,
        "limit": data.get("limit"),
        "size": size,
        "has_more": has_more,
    }
