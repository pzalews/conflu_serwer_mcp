from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest

from confluence_mcp.client import ConfluenceClient
from confluence_mcp.config import Settings

BASE = "https://confluence.test"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Make tests independent of the developer's environment and .env file."""
    import os

    for key in list(os.environ):
        if key.startswith(("CONFLUENCE_", "MCP_")):
            monkeypatch.delenv(key)
    monkeypatch.chdir(os.path.dirname(__file__))  # no .env in tests/
    yield


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {"confluence_url": BASE, "confluence_token": "secret-token"}
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[ConfluenceClient]:
    c = ConfluenceClient(settings, retry_wait=0)
    yield c
    await c.aclose()


def make_ctx(client: Any, settings: Settings) -> MagicMock:
    ctx = MagicMock()
    ctx.lifespan_context = {"client": client, "settings": settings}
    return ctx
