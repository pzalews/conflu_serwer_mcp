"""Shared read/create/update logic for pages, blog posts and comments.

This is the only place that implements format conversion, version bumps and the
update safeguards (expected_version check, macro-loss check).
"""

from __future__ import annotations

from typing import Any, Literal

from .client import ConfluenceClient
from .converter import inventory, to_markdown, to_storage
from .exceptions import MacroLossError, NotFoundError, VersionConflictError

Format = Literal["markdown", "storage"]
ContentType = Literal["page", "blogpost", "comment"]

EXPAND_READ = "body.storage,version,space,ancestors,metadata.labels"


def to_storage_body(body: str, fmt: Format) -> str:
    return to_storage(body) if fmt == "markdown" else body


def render_body(storage: str, fmt: Format) -> str:
    return to_markdown(storage) if fmt == "markdown" else storage


def web_url(client: ConfluenceClient, content: dict[str, Any]) -> str | None:
    webui = content.get("_links", {}).get("webui")
    return f"{client.base_url}{webui}" if webui else None


def compact(
    client: ConfluenceClient, content: dict[str, Any], fmt: Format | None = None
) -> dict[str, Any]:
    """Reduce a Confluence content JSON to the fields an assistant needs.

    ``fmt`` given → include the body rendered in that format.
    """
    version = content.get("version") or {}
    space = content.get("space") or {}
    result: dict[str, Any] = {
        "id": content.get("id"),
        "type": content.get("type"),
        "title": content.get("title"),
        "space": {"key": space.get("key"), "name": space.get("name")} if space else None,
        "version": {
            "number": version.get("number"),
            "when": version.get("when"),
            "by": (version.get("by") or {}).get("displayName"),
            "message": version.get("message") or None,
        }
        if version
        else None,
        "url": web_url(client, content),
    }
    labels = content.get("metadata", {}).get("labels", {}).get("results")
    if labels is not None:
        result["labels"] = [label.get("name") for label in labels]
    if "ancestors" in content:
        result["ancestors"] = [
            {"id": a.get("id"), "title": a.get("title")} for a in content["ancestors"]
        ]
    if fmt is not None:
        storage = content.get("body", {}).get("storage", {}).get("value", "")
        result["format"] = fmt
        result["body"] = render_body(storage, fmt)
    return result


async def get_content(
    client: ConfluenceClient, content_id: str, fmt: Format, *, version: int | None = None
) -> dict[str, Any]:
    params: dict[str, Any] = {"expand": EXPAND_READ}
    if version is not None:
        params.update(status="historical", version=version)
    data = await client.get(f"/rest/api/content/{content_id}", params=params)
    return compact(client, data, fmt)


async def find_by_title(
    client: ConfluenceClient, space_key: str, title: str, fmt: Format, type_: str = "page"
) -> dict[str, Any]:
    data = await client.get(
        "/rest/api/content",
        params={"spaceKey": space_key, "title": title, "type": type_, "expand": EXPAND_READ},
    )
    results = data.get("results", [])
    if not results:
        raise NotFoundError(404, f"No {type_} titled {title!r} in space {space_key}")
    return compact(client, results[0], fmt)


async def create_content(
    client: ConfluenceClient,
    type_: ContentType,
    space_key: str,
    title: str,
    body: str,
    fmt: Format,
    parent_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": type_,
        "title": title,
        "space": {"key": space_key},
        "body": {"storage": {"value": to_storage_body(body, fmt), "representation": "storage"}},
    }
    if parent_id:
        payload["ancestors"] = [{"id": parent_id}]
    data = await client.post("/rest/api/content", json=payload)
    return compact(client, data)


async def update_content(
    client: ConfluenceClient,
    content_id: str,
    *,
    body: str | None = None,
    fmt: Format = "markdown",
    title: str | None = None,
    expected_version: int | None = None,
    allow_macro_loss: bool = False,
    version_comment: str | None = None,
) -> dict[str, Any]:
    """Update content body and/or title with a version bump and safeguards."""
    current = await client.get(
        f"/rest/api/content/{content_id}", params={"expand": "body.storage,version,space"}
    )
    current_version = int(current["version"]["number"])
    if expected_version is not None and expected_version != current_version:
        raise VersionConflictError(
            f"Content {content_id} is at version {current_version}, not {expected_version}; "
            "re-read it and apply your change to the current version.",
            current_version=current_version,
        )
    old_storage: str = current.get("body", {}).get("storage", {}).get("value", "")
    new_storage = old_storage if body is None else to_storage_body(body, fmt)
    lost = inventory(old_storage) - inventory(new_storage)
    if lost and not allow_macro_loss:
        raise MacroLossError(lost)
    version: dict[str, Any] = {"number": current_version + 1}
    if version_comment:
        version["message"] = version_comment
    payload: dict[str, Any] = {
        "id": content_id,
        "type": current["type"],
        "title": title or current["title"],
        "version": version,
        "body": {"storage": {"value": new_storage, "representation": "storage"}},
    }
    data = await client.put(f"/rest/api/content/{content_id}", json=payload)
    return compact(client, data)


async def restore_version(
    client: ConfluenceClient, content_id: str, version: int
) -> dict[str, Any]:
    old = await client.get(
        f"/rest/api/content/{content_id}",
        params={"status": "historical", "version": version, "expand": "body.storage"},
    )
    storage = old.get("body", {}).get("storage", {}).get("value", "")
    return await update_content(
        client,
        content_id,
        body=storage,
        fmt="storage",
        title=old.get("title"),
        allow_macro_loss=True,
        version_comment=f"Restored version {version}",
    )
