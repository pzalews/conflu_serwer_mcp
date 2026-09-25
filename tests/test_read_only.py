"""Every write tool must be blocked in read-only mode before any HTTP call.

The set of write tools is derived from the source (tools that call
require_writable), so new write tools are covered automatically.
"""

from __future__ import annotations

import inspect
import types
from typing import Any, Union, get_args, get_origin, get_type_hints

import pytest
import respx

from confluence_mcp.exceptions import ReadOnlyModeError
from confluence_mcp.tools import ALL_TOOLS
from tests.conftest import make_ctx, make_settings

WRITE_TOOLS = [fn for fn in ALL_TOOLS if "require_writable(" in inspect.getsource(fn)]

_DUMMY: dict[Any, Any] = {str: "x", int: 1, bool: False, list[str]: ["x"]}


def _dummy_kwargs(fn: Any) -> dict[str, Any]:
    hints = get_type_hints(fn)
    kwargs: dict[str, Any] = {}
    for name, param in inspect.signature(fn).parameters.items():
        if name == "ctx" or param.default is not inspect.Parameter.empty:
            continue
        hint = hints[name]
        if get_origin(hint) in (Union, types.UnionType):
            hint = next(a for a in get_args(hint) if a is not type(None))
        kwargs[name] = _DUMMY[hint]
    return kwargs


def test_expected_write_tools_detected() -> None:
    assert {fn.__name__ for fn in WRITE_TOOLS} == {
        "create_page", "update_page", "delete_page", "move_page",
        "create_blog_post", "update_blog_post",
        "add_comment", "update_comment", "delete_comment",
        "add_labels", "remove_label",
        "upload_attachment", "delete_attachment",
        "restore_page_version",
    }  # fmt: skip


@pytest.mark.parametrize("tool_fn", WRITE_TOOLS, ids=lambda f: f.__name__)
@respx.mock(assert_all_called=False)
async def test_write_tool_blocked_in_read_only(tool_fn: Any, respx_mock: respx.MockRouter) -> None:
    from confluence_mcp.client import ConfluenceClient

    settings = make_settings(confluence_read_only=True, confluence_default_space="DOC")
    client = ConfluenceClient(settings, retry_wait=0)
    with pytest.raises(ReadOnlyModeError, match=tool_fn.__name__):
        await tool_fn(ctx=make_ctx(client, settings), **_dummy_kwargs(tool_fn))
    assert not respx_mock.calls
    await client.aclose()
