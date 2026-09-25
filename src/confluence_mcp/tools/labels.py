from __future__ import annotations

from typing import Any

from fastmcp import Context

from ..logging_setup import log_tool_call
from ._common import check_content_id, get_client, require_writable


def _names(data: dict[str, Any]) -> list[str]:
    return [str(label.get("name")) for label in data.get("results", [])]


async def get_labels(ctx: Context, content_id: str) -> list[str]:
    """List the labels on a page or blog post."""
    check_content_id(content_id, "content_id")
    async with log_tool_call("get_labels", page_id=content_id):
        return _names(await get_client(ctx).get(f"/rest/api/content/{content_id}/label"))


async def add_labels(ctx: Context, content_id: str, labels: list[str]) -> list[str]:
    """Add labels (lowercase, no spaces) to a page or blog post; returns all labels."""
    require_writable(ctx, "add_labels")
    check_content_id(content_id, "content_id")
    async with log_tool_call("add_labels", page_id=content_id):
        payload = [{"prefix": "global", "name": name} for name in labels]
        data = await get_client(ctx).post(f"/rest/api/content/{content_id}/label", json=payload)
        return _names(data)


async def remove_label(ctx: Context, content_id: str, label: str) -> dict[str, Any]:
    """Remove one label from a page or blog post."""
    require_writable(ctx, "remove_label")
    check_content_id(content_id, "content_id")
    async with log_tool_call("remove_label", page_id=content_id):
        await get_client(ctx).delete(
            f"/rest/api/content/{content_id}/label", params={"name": label}
        )
        return {"id": content_id, "removed": label}
