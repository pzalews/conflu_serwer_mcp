from __future__ import annotations

from typing import Any

from fastmcp import Context

from ..content import Format, compact, create_content, get_content, update_content
from ..logging_setup import log_tool_call
from ._common import get_client, list_result, page_params, require_writable, resolve_space


async def list_blog_posts(
    ctx: Context, space_key: str | None = None, limit: int = 25, start: int = 0
) -> dict[str, Any]:
    """List blog posts in a space, newest first."""
    key = resolve_space(ctx, space_key)
    async with log_tool_call("list_blog_posts", space=key):
        client = get_client(ctx)
        cql = f'type = blogpost AND space = "{key}" ORDER BY created DESC'
        data = await client.get(
            "/rest/api/content/search",
            params={"cql": cql, "expand": "space,version", **page_params(limit, start)},
        )
        return list_result(data, [compact(client, c) for c in data.get("results", [])])


async def get_blog_post(
    ctx: Context, blog_post_id: str, format: Format = "markdown"
) -> dict[str, Any]:
    """Get a blog post. Body format and macro rules are the same as get_page."""
    async with log_tool_call("get_blog_post", page_id=blog_post_id):
        return await get_content(get_client(ctx), blog_post_id, format)


async def create_blog_post(
    ctx: Context,
    title: str,
    body: str,
    space_key: str | None = None,
    format: Format = "markdown",
) -> dict[str, Any]:
    """Create a blog post. body follows the same Markdown rules as create_page."""
    require_writable(ctx, "create_blog_post")
    key = resolve_space(ctx, space_key)
    async with log_tool_call("create_blog_post", space=key):
        return await create_content(get_client(ctx), "blogpost", key, title, body, format)


async def update_blog_post(
    ctx: Context,
    blog_post_id: str,
    body: str | None = None,
    title: str | None = None,
    format: Format = "markdown",
    expected_version: int | None = None,
    allow_macro_loss: bool = False,
    version_comment: str | None = None,
) -> dict[str, Any]:
    """Update a blog post. Same version and macro safeguards as update_page."""
    require_writable(ctx, "update_blog_post")
    async with log_tool_call("update_blog_post", page_id=blog_post_id):
        return await update_content(
            get_client(ctx),
            blog_post_id,
            body=body,
            fmt=format,
            title=title,
            expected_version=expected_version,
            allow_macro_loss=allow_macro_loss,
            version_comment=version_comment,
        )
