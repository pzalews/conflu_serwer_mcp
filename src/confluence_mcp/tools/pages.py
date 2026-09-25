from __future__ import annotations

from typing import Any

from fastmcp import Context

from ..content import Format, create_content, find_by_title, get_content, update_content
from ..logging_setup import log_tool_call
from ._common import (
    check_content_id,
    get_client,
    list_result,
    page_params,
    require_writable,
    resolve_space,
)


async def get_page(
    ctx: Context,
    page_id: str | None = None,
    title: str | None = None,
    space_key: str | None = None,
    format: Format = "markdown",
) -> dict[str, Any]:
    """Get a page by id, or by title within a space.

    The body is Markdown by default. Raw <ac:…>/<ri:…> blocks in it are Confluence
    macros that have no Markdown form: keep them unchanged when editing unless you
    intend to change them. Use format="storage" for the exact Confluence XHTML.
    The returned version.number can be passed to update_page as expected_version.
    """
    client = get_client(ctx)
    if page_id:
        check_content_id(page_id, "page_id")
        async with log_tool_call("get_page", page_id=page_id):
            return await get_content(client, page_id, format)
    if not title:
        raise ValueError("Pass page_id, or title (with space_key or CONFLUENCE_DEFAULT_SPACE)")
    key = resolve_space(ctx, space_key)
    async with log_tool_call("get_page", space=key):
        return await find_by_title(client, key, title, format)


async def get_page_children(
    ctx: Context, page_id: str, limit: int = 25, start: int = 0
) -> dict[str, Any]:
    """List the direct child pages of a page."""
    check_content_id(page_id, "page_id")
    async with log_tool_call("get_page_children", page_id=page_id):
        client = get_client(ctx)
        data = await client.get(
            f"/rest/api/content/{page_id}/child/page", params=page_params(limit, start)
        )
        items = [
            {
                "id": c.get("id"),
                "title": c.get("title"),
                "url": f"{client.base_url}{c.get('_links', {}).get('webui', '')}",
            }
            for c in data.get("results", [])
        ]
        return list_result(data, items)


async def get_page_ancestors(ctx: Context, page_id: str) -> list[dict[str, Any]]:
    """List a page's ancestors from the space root down to its parent."""
    check_content_id(page_id, "page_id")
    async with log_tool_call("get_page_ancestors", page_id=page_id):
        data = await get_client(ctx).get(
            f"/rest/api/content/{page_id}", params={"expand": "ancestors"}
        )
        return [{"id": a.get("id"), "title": a.get("title")} for a in data.get("ancestors", [])]


async def create_page(
    ctx: Context,
    title: str,
    body: str,
    space_key: str | None = None,
    parent_id: str | None = None,
    format: Format = "markdown",
) -> dict[str, Any]:
    """Create a page. body is Markdown by default (or storage XHTML with format="storage").

    Markdown extras: ```lang fences → code macro; "> [!INFO]" / [!NOTE] / [!WARNING] /
    [!TIP] callouts → panels; [text](confluence:SPACE/Page%20Title) → page link;
    ![alt](attachment:file.png) → attached image; "- [ ] task" → task list.
    """
    require_writable(ctx, "create_page")
    if parent_id is not None:
        check_content_id(parent_id, "parent_id")
    key = resolve_space(ctx, space_key)
    async with log_tool_call("create_page", space=key):
        return await create_content(get_client(ctx), "page", key, title, body, format, parent_id)


async def update_page(
    ctx: Context,
    page_id: str,
    body: str | None = None,
    title: str | None = None,
    format: Format = "markdown",
    expected_version: int | None = None,
    allow_macro_loss: bool = False,
    version_comment: str | None = None,
) -> dict[str, Any]:
    """Replace a page's body and/or title; the version number is bumped automatically.

    Read the page first and edit its full body — body replaces the whole page.
    Pass expected_version (from get_page) to fail instead of overwriting someone
    else's concurrent edit. The update is rejected if it would drop macros present
    in the current page (keep the raw <ac:…> blocks); set allow_macro_loss=true only
    when removing them is intended. Omit body to only rename.
    """
    require_writable(ctx, "update_page")
    check_content_id(page_id, "page_id")
    async with log_tool_call("update_page", page_id=page_id):
        return await update_content(
            get_client(ctx),
            page_id,
            body=body,
            fmt=format,
            title=title,
            expected_version=expected_version,
            allow_macro_loss=allow_macro_loss,
            version_comment=version_comment,
        )


async def delete_page(ctx: Context, page_id: str) -> dict[str, Any]:
    """Move a page to the space trash (it can be restored from the trash in Confluence)."""
    require_writable(ctx, "delete_page")
    check_content_id(page_id, "page_id")
    async with log_tool_call("delete_page", page_id=page_id):
        await get_client(ctx).delete(f"/rest/api/content/{page_id}")
        return {"id": page_id, "status": "trashed"}


async def move_page(ctx: Context, page_id: str, target_parent_id: str) -> dict[str, Any]:
    """Move a page (with its children) under another page in the same space."""
    require_writable(ctx, "move_page")
    check_content_id(page_id, "page_id")
    check_content_id(target_parent_id, "target_parent_id")
    async with log_tool_call("move_page", page_id=page_id):
        await get_client(ctx).put(f"/rest/api/content/{page_id}/move/append/{target_parent_id}")
        return {"id": page_id, "parent_id": target_parent_id, "status": "moved"}
