"""Helpers shared by all tool modules."""

from __future__ import annotations

import re
from typing import Any

from fastmcp import Context

from ..client import ConfluenceClient
from ..config import Settings
from ..exceptions import ReadOnlyModeError

MAX_LIMIT = 100

# Attachment ids come back from Confluence Server as "att<digits>".
_CONTENT_ID_RE = re.compile(r"(?:att)?[0-9]+")
# Space keys are letters/digits/underscore; personal spaces are "~username", and
# usernames may contain '.', '@' and '-'. Nothing here can form a path separator.
_SPACE_KEY_RE = re.compile(r"(?!\.{1,2}$)[A-Za-z0-9_~.@-]+")


def check_content_id(value: str, name: str = "content_id") -> str:
    """Validate a caller-supplied content/attachment/comment id before it enters a path."""
    if not isinstance(value, str) or not _CONTENT_ID_RE.fullmatch(value):
        raise ValueError(f"{name} must be a numeric Confluence id, got {value!r}")
    return value


def check_space_key(value: str) -> str:
    """Validate a space key before it enters a REST path."""
    if not isinstance(value, str) or not _SPACE_KEY_RE.fullmatch(value):
        raise ValueError(f"space_key is not a valid Confluence space key: {value!r}")
    return value


def cql_string(value: str) -> str:
    """Quote a value as a CQL string literal."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


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
    return check_space_key(resolved)


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
