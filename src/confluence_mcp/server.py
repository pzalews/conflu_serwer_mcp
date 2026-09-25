from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastmcp import FastMCP

from .client import ConfluenceClient
from .config import Settings
from .logging_setup import configure_logging, get_logger
from .prompts import register_prompts
from .resources import register_resources
from .tools import register_all_tools

log = get_logger(__name__)


@asynccontextmanager
async def _lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        log_path=settings.confluence_log_path,
        json_logs=bool(settings.confluence_log_path),
    )
    client = ConfluenceClient(settings)
    log.info("confluence_mcp.startup", **settings.redacted())
    try:
        yield {"client": client, "settings": settings}
    finally:
        await client.aclose()
        log.info("confluence_mcp.shutdown")


def create_server() -> FastMCP:
    mcp = FastMCP(
        name="Confluence Server MCP",
        instructions=(
            "Tools for a self-hosted Confluence Server / Data Center. "
            "Find content with search_text or search (CQL), or browse with list_spaces → "
            "get_space → get_page_children. Page bodies are Markdown by default; raw "
            "<ac:…> blocks inside them are Confluence macros and must be kept unchanged "
            "unless you mean to change them. To edit: get_page → modify the full body → "
            "update_page with expected_version set to the version you read."
        ),
        lifespan=_lifespan,
    )
    register_all_tools(mcp)
    register_resources(mcp)
    register_prompts(mcp)
    return mcp


mcp = create_server()
