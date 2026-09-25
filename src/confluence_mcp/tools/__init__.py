from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastmcp import FastMCP

from .attachments import delete_attachment, download_attachment, list_attachments, upload_attachment
from .blogposts import create_blog_post, get_blog_post, list_blog_posts, update_blog_post
from .comments import add_comment, delete_comment, list_comments, update_comment
from .history import get_page_history, get_page_version, restore_page_version
from .labels import add_labels, get_labels, remove_label
from .pages import (
    create_page,
    delete_page,
    get_page,
    get_page_ancestors,
    get_page_children,
    move_page,
    update_page,
)
from .search import search, search_text
from .spaces import get_space, list_spaces
from .users import get_current_user, get_user

ALL_TOOLS: list[Callable[..., Any]] = [
    list_spaces,
    get_space,
    get_page,
    get_page_children,
    get_page_ancestors,
    create_page,
    update_page,
    delete_page,
    move_page,
    list_blog_posts,
    get_blog_post,
    create_blog_post,
    update_blog_post,
    search,
    search_text,
    list_comments,
    add_comment,
    update_comment,
    delete_comment,
    get_labels,
    add_labels,
    remove_label,
    list_attachments,
    download_attachment,
    upload_attachment,
    delete_attachment,
    get_page_history,
    get_page_version,
    restore_page_version,
    get_current_user,
    get_user,
]


def register_all_tools(mcp: FastMCP) -> None:
    for fn in ALL_TOOLS:
        mcp.add_tool(fn)
