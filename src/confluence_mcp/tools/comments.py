from __future__ import annotations

from typing import Any

from fastmcp import Context

from ..content import Format, render_body, to_storage_body, update_content
from ..logging_setup import log_tool_call
from ._common import get_client, list_result, page_params, require_writable


def _comment(data: dict[str, Any], fmt: Format) -> dict[str, Any]:
    version = data.get("version") or {}
    ancestors = data.get("ancestors") or []
    storage = data.get("body", {}).get("storage", {}).get("value", "")
    return {
        "id": data.get("id"),
        "author": (version.get("by") or {}).get("displayName"),
        "when": version.get("when"),
        "version": version.get("number"),
        "parent_comment_id": ancestors[-1].get("id") if ancestors else None,
        "body": render_body(storage, fmt),
    }


async def list_comments(
    ctx: Context, content_id: str, format: Format = "markdown", limit: int = 25, start: int = 0
) -> dict[str, Any]:
    """List comments (including replies) on a page or blog post."""
    async with log_tool_call("list_comments", page_id=content_id):
        data = await get_client(ctx).get(
            f"/rest/api/content/{content_id}/child/comment",
            params={
                "expand": "body.storage,version,ancestors",
                "depth": "all",
                **page_params(limit, start),
            },
        )
        return list_result(data, [_comment(c, format) for c in data.get("results", [])])


async def add_comment(
    ctx: Context,
    content_id: str,
    body: str,
    format: Format = "markdown",
    parent_comment_id: str | None = None,
) -> dict[str, Any]:
    """Add a comment to a page or blog post, or reply to a comment (parent_comment_id)."""
    require_writable(ctx, "add_comment")
    async with log_tool_call("add_comment", page_id=content_id):
        client = get_client(ctx)
        container = await client.get(f"/rest/api/content/{content_id}")
        payload: dict[str, Any] = {
            "type": "comment",
            "container": {"id": content_id, "type": container.get("type", "page")},
            "body": {
                "storage": {"value": to_storage_body(body, format), "representation": "storage"}
            },
        }
        if parent_comment_id:
            payload["ancestors"] = [{"id": parent_comment_id}]
        data = await client.post("/rest/api/content", json=payload)
        return {"id": data.get("id"), "status": "created"}


async def update_comment(
    ctx: Context, comment_id: str, body: str, format: Format = "markdown"
) -> dict[str, Any]:
    """Replace the text of a comment (version bumped automatically)."""
    require_writable(ctx, "update_comment")
    async with log_tool_call("update_comment", page_id=comment_id):
        return await update_content(
            get_client(ctx), comment_id, body=body, fmt=format, allow_macro_loss=True
        )


async def delete_comment(ctx: Context, comment_id: str) -> dict[str, Any]:
    """Delete a comment."""
    require_writable(ctx, "delete_comment")
    async with log_tool_call("delete_comment", page_id=comment_id):
        await get_client(ctx).delete(f"/rest/api/content/{comment_id}")
        return {"id": comment_id, "status": "deleted"}
