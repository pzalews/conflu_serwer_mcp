from __future__ import annotations

import base64
import binascii
import mimetypes
from typing import Any

from fastmcp import Context

from ..client import ConfluenceClient
from ..exceptions import NotFoundError, PayloadTooLargeError
from ..logging_setup import log_tool_call
from ._common import (
    check_content_id,
    get_client,
    get_settings,
    list_result,
    page_params,
    require_writable,
)

_TEXT_TYPES = {"application/json", "application/xml", "application/javascript"}


def _attachment(client: ConfluenceClient, data: dict[str, Any]) -> dict[str, Any]:
    ext = data.get("extensions") or {}
    download = data.get("_links", {}).get("download")
    return {
        "id": data.get("id"),
        "filename": data.get("title"),
        "media_type": ext.get("mediaType") or data.get("metadata", {}).get("mediaType"),
        "size": ext.get("fileSize"),
        "version": (data.get("version") or {}).get("number"),
        "download_url": f"{client.base_url}{download}" if download else None,
    }


def _is_text(media_type: str) -> bool:
    media_type = media_type.split(";")[0].strip().lower()
    return (
        media_type.startswith("text/")
        or media_type in _TEXT_TYPES
        or media_type.endswith(("+xml", "+json"))
    )


async def _find_by_filename(
    client: ConfluenceClient, content_id: str, filename: str
) -> dict[str, Any] | None:
    data = await client.get(
        f"/rest/api/content/{content_id}/child/attachment",
        params={"filename": filename, "expand": "version"},
    )
    results: list[dict[str, Any]] = data.get("results", [])
    return results[0] if results else None


async def list_attachments(
    ctx: Context, content_id: str, limit: int = 25, start: int = 0
) -> dict[str, Any]:
    """List attachments of a page or blog post."""
    check_content_id(content_id, "content_id")
    async with log_tool_call("list_attachments", page_id=content_id):
        client = get_client(ctx)
        data = await client.get(
            f"/rest/api/content/{content_id}/child/attachment",
            params={"expand": "version", **page_params(limit, start)},
        )
        return list_result(data, [_attachment(client, a) for a in data.get("results", [])])


async def download_attachment(
    ctx: Context,
    content_id: str,
    filename: str | None = None,
    attachment_id: str | None = None,
) -> dict[str, Any]:
    """Download an attachment by filename or attachment id.

    Text types are returned as text, everything else base64-encoded. Files larger
    than CONFLUENCE_ATTACHMENT_MAX_BYTES are refused.
    """
    if (filename is None) == (attachment_id is None):
        raise ValueError("Pass exactly one of filename or attachment_id")
    check_content_id(content_id, "content_id")
    if attachment_id is not None:
        check_content_id(attachment_id, "attachment_id")
    max_bytes = get_settings(ctx).confluence_attachment_max_bytes
    async with log_tool_call("download_attachment", page_id=content_id):
        client = get_client(ctx)
        if filename is not None:
            meta = await _find_by_filename(client, content_id, filename)
            if meta is None:
                raise NotFoundError(404, f"No attachment {filename!r} on content {content_id}")
        else:
            meta = await client.get(
                f"/rest/api/content/{attachment_id}", params={"expand": "version"}
            )
        info = _attachment(client, meta)
        if info["size"] is not None and int(info["size"]) > max_bytes:
            raise PayloadTooLargeError(
                413, f"Attachment is {info['size']} bytes; limit is {max_bytes}"
            )
        raw, content_type = await client.get_bytes(meta["_links"]["download"])
        if len(raw) > max_bytes:
            raise PayloadTooLargeError(413, f"Attachment is {len(raw)} bytes; limit is {max_bytes}")
        media_type = info["media_type"] or content_type or "application/octet-stream"
        result = {"filename": info["filename"], "media_type": media_type, "size": len(raw)}
        if _is_text(media_type):
            try:
                return {**result, "encoding": "text", "content": raw.decode("utf-8")}
            except UnicodeDecodeError:
                pass
        return {**result, "encoding": "base64", "content": base64.b64encode(raw).decode()}


async def upload_attachment(
    ctx: Context,
    content_id: str,
    filename: str,
    content_base64: str | None = None,
    text: str | None = None,
    comment: str | None = None,
    media_type: str | None = None,
) -> dict[str, Any]:
    """Attach a file to a page or blog post; pass exactly one of content_base64 or text.

    Uploading an existing filename adds a new version of that attachment.
    """
    require_writable(ctx, "upload_attachment")
    check_content_id(content_id, "content_id")
    if (content_base64 is None) == (text is None):
        raise ValueError("Pass exactly one of content_base64 or text")
    if content_base64 is not None:
        try:
            raw = base64.b64decode(content_base64, validate=True)
        except binascii.Error as exc:
            raise ValueError(f"content_base64 is not valid base64: {exc}") from exc
    else:
        raw = (text or "").encode("utf-8")
    max_bytes = get_settings(ctx).confluence_attachment_max_bytes
    if len(raw) > max_bytes:
        raise PayloadTooLargeError(413, f"Upload is {len(raw)} bytes; limit is {max_bytes}")
    mime = media_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    async with log_tool_call("upload_attachment", page_id=content_id):
        client = get_client(ctx)
        existing = await _find_by_filename(client, content_id, filename)
        path = f"/rest/api/content/{content_id}/child/attachment"
        if existing is not None:
            path += f"/{existing['id']}/data"
        form = {"minorEdit": "true", **({"comment": comment} if comment else {})}
        data = await client.post(
            path,
            files={"file": (filename, raw, mime)},
            data=form,
            headers={"X-Atlassian-Token": "no-check"},
        )
        attachment = data["results"][0] if "results" in data else data
        return _attachment(client, attachment)


async def delete_attachment(ctx: Context, attachment_id: str) -> dict[str, Any]:
    """Delete an attachment (moves it to the trash)."""
    require_writable(ctx, "delete_attachment")
    check_content_id(attachment_id, "attachment_id")
    async with log_tool_call("delete_attachment", page_id=attachment_id):
        await get_client(ctx).delete(f"/rest/api/content/{attachment_id}")
        return {"id": attachment_id, "status": "deleted"}
