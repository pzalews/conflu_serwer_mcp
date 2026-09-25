from __future__ import annotations

from typing import Any, Literal

from fastmcp import Context

from ..logging_setup import log_tool_call
from ._common import get_client, list_result, page_params


def _cql_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


async def _run_search(ctx: Context, cql: str, limit: int, start: int) -> dict[str, Any]:
    client = get_client(ctx)
    data = await client.get(
        "/rest/api/search",
        params={"cql": cql, "expand": "content.space", **page_params(limit, start)},
    )
    hits = []
    for item in data.get("results", []):
        content = item.get("content") or {}
        container = item.get("resultGlobalContainer") or {}
        hits.append(
            {
                "id": content.get("id"),
                "type": content.get("type") or item.get("entityType"),
                "title": content.get("title") or item.get("title"),
                "space": (content.get("space") or {}).get("key") or container.get("title"),
                "excerpt": item.get("excerpt"),
                "url": f"{client.base_url}{item['url']}" if item.get("url") else None,
                "last_modified": item.get("lastModified"),
            }
        )
    return list_result(data, hits)


async def search(ctx: Context, cql: str, limit: int = 25, start: int = 0) -> dict[str, Any]:
    """Search with a CQL query, e.g. 'space = DOC AND type = page AND title ~ "deploy"'."""
    async with log_tool_call("search"):
        return await _run_search(ctx, cql, limit, start)


async def search_text(
    ctx: Context,
    text: str,
    space_key: str | None = None,
    type: Literal["page", "blogpost"] | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Full-text search, newest first. Optionally restrict to a space and content type."""
    clauses = [f"text ~ {_cql_string(text)}"]
    if space_key:
        clauses.append(f"space = {_cql_string(space_key)}")
    if type:
        clauses.append(f"type = {type}")
    cql = " AND ".join(clauses) + " ORDER BY lastmodified DESC"
    async with log_tool_call("search_text", space=space_key):
        return await _run_search(ctx, cql, limit, 0)
