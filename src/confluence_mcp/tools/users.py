from __future__ import annotations

from typing import Any

from fastmcp import Context

from ..logging_setup import log_tool_call
from ._common import get_client


def _user(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "username": data.get("username"),
        "user_key": data.get("userKey"),
        "display_name": data.get("displayName"),
        "type": data.get("type"),
    }


async def get_current_user(ctx: Context) -> dict[str, Any]:
    """Return the user the server's token authenticates as."""
    async with log_tool_call("get_current_user"):
        return _user(await get_client(ctx).get("/rest/api/user/current"))


async def get_user(
    ctx: Context, username: str | None = None, user_key: str | None = None
) -> dict[str, Any]:
    """Look up a user by username or by user key (exactly one is required)."""
    if (username is None) == (user_key is None):
        raise ValueError("Pass exactly one of username or user_key")
    async with log_tool_call("get_user"):
        params = {"username": username} if username else {"key": user_key}
        return _user(await get_client(ctx).get("/rest/api/user", params=params))
