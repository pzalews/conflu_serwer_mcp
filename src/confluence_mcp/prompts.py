from __future__ import annotations

from fastmcp import FastMCP
from fastmcp.prompts import Message


def register_prompts(mcp: FastMCP) -> None:

    @mcp.prompt
    def summarize_page(page_id: str, audience: str = "engineers") -> list[Message]:
        """Summarize a Confluence page for a given audience."""
        return [
            Message(
                f"Call `get_page` with page_id='{page_id}'. Summarize it for {audience}: "
                "a 2-3 sentence overview, then key points as bullets, then any open "
                "questions or action items. End with the page URL."
            )
        ]

    @mcp.prompt
    def draft_page_from_notes(space_key: str, parent_id: str, notes: str) -> list[Message]:
        """Turn rough notes into a structured page, created after confirmation."""
        return [
            Message(
                "Turn these notes into a well-structured Confluence page in Markdown "
                "(headings, bullet lists, tables where useful, `> [!INFO]` callouts for "
                "important notes):\n\n"
                f"{notes}\n\n"
                "Show me the title and Markdown first. Only after I confirm, call "
                f"`create_page` with space_key='{space_key}' and parent_id='{parent_id}'."
            )
        ]

    @mcp.prompt
    def find_and_answer(question: str, space_key: str = "") -> list[Message]:
        """Answer a question from Confluence content, citing page URLs."""
        scope = f" with space_key='{space_key}'" if space_key else ""
        return [
            Message(
                f"Question: {question}\n\n"
                f"1. Call `search_text`{scope} with the key terms of the question.\n"
                "2. Read the 2-4 most relevant results with `get_page`.\n"
                "3. Answer using only what those pages say, citing each page URL. "
                "If the pages do not answer it, say so."
            )
        ]
