from __future__ import annotations

from typing import Any, Literal

from fastmcp import Context

from ..logging_setup import log_tool_call
from ._common import get_client, list_result, page_params, resolve_space

_EXPAND = "description.plain,homepage"


def _space(ctx: Context, data: dict[str, Any]) -> dict[str, Any]:
    webui = data.get("_links", {}).get("webui")
    return {
        "key": data.get("key"),
        "name": data.get("name"),
        "type": data.get("type"),
        "description": data.get("description", {}).get("plain", {}).get("value") or None,
        "homepage_id": (data.get("homepage") or {}).get("id"),
        "url": f"{get_client(ctx).base_url}{webui}" if webui else None,
    }


async def list_spaces(
    ctx: Context,
    type: Literal["global", "personal"] | None = None,
    limit: int = 25,
    start: int = 0,
) -> dict[str, Any]:
    """List Confluence spaces visible to the token's user. Start here to discover space keys."""
    async with log_tool_call("list_spaces"):
        params: dict[str, Any] = {**page_params(limit, start), "expand": _EXPAND}
        if type:
            params["type"] = type
        data = await get_client(ctx).get("/rest/api/space", params=params)
        return list_result(data, [_space(ctx, s) for s in data.get("results", [])])


async def get_space(ctx: Context, space_key: str | None = None) -> dict[str, Any]:
    """Get a space's details, including the id of its home page."""
    key = resolve_space(ctx, space_key)
    async with log_tool_call("get_space", space=key):
        data = await get_client(ctx).get(f"/rest/api/space/{key}", params={"expand": _EXPAND})
        return _space(ctx, data)
