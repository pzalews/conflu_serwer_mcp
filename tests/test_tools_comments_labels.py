from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from confluence_mcp.client import ConfluenceClient
from confluence_mcp.config import Settings
from confluence_mcp.tools.comments import add_comment, delete_comment, list_comments, update_comment
from confluence_mcp.tools.labels import add_labels, get_labels, remove_label
from tests.conftest import BASE, make_ctx
from tests.test_content import page


@pytest.fixture
def ctx(client: ConfluenceClient, settings: Settings) -> Any:
    return make_ctx(client, settings)


@respx.mock
async def test_list_comments_with_reply(ctx: Any) -> None:
    route = respx.get(f"{BASE}/rest/api/content/42/child/comment").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "c2",
                        "version": {"number": 1, "when": "t", "by": {"displayName": "Bo"}},
                        "ancestors": [{"id": "c1"}],
                        "body": {"storage": {"value": "<p>reply</p>"}},
                    }
                ]
            },
        )
    )
    out = await list_comments(ctx, "42")
    assert out["results"] == [
        {
            "id": "c2",
            "author": "Bo",
            "when": "t",
            "version": 1,
            "parent_comment_id": "c1",
            "body": "reply\n",
        }
    ]
    assert route.calls.last.request.url.params["depth"] == "all"


@respx.mock
async def test_add_reply_uses_container_type(ctx: Any) -> None:
    respx.get(f"{BASE}/rest/api/content/42").mock(
        return_value=httpx.Response(200, json={"id": "42", "type": "blogpost"})
    )
    route = respx.post(f"{BASE}/rest/api/content").mock(
        return_value=httpx.Response(200, json={"id": "c3"})
    )
    assert await add_comment(ctx, "42", "**ok**", parent_comment_id="c1") == {
        "id": "c3",
        "status": "created",
    }
    sent = json.loads(route.calls.last.request.content)
    assert sent["container"] == {"id": "42", "type": "blogpost"}
    assert sent["ancestors"] == [{"id": "c1"}]
    assert sent["body"]["storage"]["value"] == "<p><strong>ok</strong></p>"


@respx.mock
async def test_update_and_delete_comment(ctx: Any) -> None:
    comment = page(type="comment", storage='<p>x</p><ac:structured-macro ac:name="toc"/>')
    respx.get(f"{BASE}/rest/api/content/c1").mock(return_value=httpx.Response(200, json=comment))
    put = respx.put(f"{BASE}/rest/api/content/c1").mock(
        return_value=httpx.Response(200, json=comment)
    )
    respx.delete(f"{BASE}/rest/api/content/c1").mock(return_value=httpx.Response(204))
    await update_comment(ctx, "c1", "plain")  # macro loss allowed for comments
    assert json.loads(put.calls.last.request.content)["type"] == "comment"
    assert (await delete_comment(ctx, "c1"))["status"] == "deleted"


@respx.mock
async def test_labels(ctx: Any) -> None:
    labels = {"results": [{"prefix": "global", "name": "a"}, {"prefix": "global", "name": "b"}]}
    respx.get(f"{BASE}/rest/api/content/42/label").mock(
        return_value=httpx.Response(200, json=labels)
    )
    post = respx.post(f"{BASE}/rest/api/content/42/label").mock(
        return_value=httpx.Response(200, json=labels)
    )
    delete = respx.delete(f"{BASE}/rest/api/content/42/label").mock(
        return_value=httpx.Response(204)
    )
    assert await get_labels(ctx, "42") == ["a", "b"]
    assert await add_labels(ctx, "42", ["b"]) == ["a", "b"]
    assert json.loads(post.calls.last.request.content) == [{"prefix": "global", "name": "b"}]
    await remove_label(ctx, "42", "a")
    assert delete.calls.last.request.url.params["name"] == "a"
