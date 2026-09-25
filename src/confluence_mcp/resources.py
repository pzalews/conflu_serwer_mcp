from __future__ import annotations

import json
from typing import Any

from fastmcp import Context, FastMCP

from .content import get_content
from .tools._common import get_client


def register_resources(mcp: FastMCP) -> None:

    @mcp.resource("confluence://spaces")
    async def spaces_resource(ctx: Context) -> str:
        """All spaces visible to the server's user (key and name)."""
        spaces: list[dict[str, Any]] = await get_client(ctx).paginate("/rest/api/space")
        return json.dumps([{"key": s.get("key"), "name": s.get("name")} for s in spaces], indent=2)

    @mcp.resource("confluence://space/{space_key}")
    async def space_resource(space_key: str, ctx: Context) -> str:
        """A space's details and its top-level pages."""
        client = get_client(ctx)
        space = await client.get(
            f"/rest/api/space/{space_key}", params={"expand": "description.plain,homepage"}
        )
        pages = await client.get(
            f"/rest/api/space/{space_key}/content/page", params={"depth": "root", "limit": 100}
        )
        summary = {
            "key": space.get("key"),
            "name": space.get("name"),
            "description": space.get("description", {}).get("plain", {}).get("value"),
            "homepage_id": (space.get("homepage") or {}).get("id"),
            "root_pages": [
                {"id": p.get("id"), "title": p.get("title")} for p in pages.get("results", [])
            ],
        }
        return json.dumps(summary, indent=2)

    @mcp.resource("confluence://page/{page_id}", mime_type="text/markdown")
    async def page_resource(page_id: str, ctx: Context) -> str:
        """A page as Markdown with a short metadata header."""
        page = await get_content(get_client(ctx), page_id, "markdown")
        version = (page.get("version") or {}).get("number")
        space = (page.get("space") or {}).get("key")
        header = f"# {page['title']}\n\n_Space {space} · version {version} · {page['url']}_\n\n"
        return header + str(page["body"])
