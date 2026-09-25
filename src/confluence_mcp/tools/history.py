from __future__ import annotations

from typing import Any

from fastmcp import Context

from ..content import Format, get_content, restore_version
from ..exceptions import NotFoundError
from ..logging_setup import log_tool_call
from ._common import get_client, page_params, require_writable

_VERSION_PATHS = ("/rest/experimental/content/{id}/version", "/rest/api/content/{id}/version")


async def get_page_history(ctx: Context, page_id: str, limit: int = 25) -> list[dict[str, Any]]:
    """List a page's versions, newest first."""
    async with log_tool_call("get_page_history", page_id=page_id):
        client = get_client(ctx)
        for template in _VERSION_PATHS:
            try:
                data = await client.get(template.format(id=page_id), params=page_params(limit, 0))
            except NotFoundError:
                continue
            return [
                {
                    "number": v.get("number"),
                    "when": v.get("when"),
                    "by": (v.get("by") or {}).get("displayName"),
                    "message": v.get("message") or None,
                }
                for v in data.get("results", [])
            ]
        raise NotFoundError(404, f"Version history not available for content {page_id}")


async def get_page_version(
    ctx: Context, page_id: str, version: int, format: Format = "markdown"
) -> dict[str, Any]:
    """Get the content of a specific historical version of a page."""
    async with log_tool_call("get_page_version", page_id=page_id):
        return await get_content(get_client(ctx), page_id, format, version=version)


async def restore_page_version(ctx: Context, page_id: str, version: int) -> dict[str, Any]:
    """Restore an old version by saving its content as a new version."""
    require_writable(ctx, "restore_page_version")
    async with log_tool_call("restore_page_version", page_id=page_id):
        return await restore_version(get_client(ctx), page_id, version)
