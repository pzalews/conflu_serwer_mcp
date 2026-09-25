"""Typed exceptions for Confluence Server MCP."""

from __future__ import annotations

from collections import Counter


class ConfluenceMCPError(Exception):
    """Base for all domain exceptions."""


class ConfigurationError(ConfluenceMCPError):
    """Raised for invalid or missing configuration."""


class ReadOnlyModeError(ConfluenceMCPError):
    """Raised when a write tool is called with CONFLUENCE_READ_ONLY=true."""

    def __init__(self, tool_name: str) -> None:
        super().__init__(
            f"Tool '{tool_name}' is a write operation blocked by read-only mode "
            f"(CONFLUENCE_READ_ONLY=true)."
        )


class MacroLossError(ConfluenceMCPError):
    """Raised when an update would remove macros from existing content."""

    def __init__(self, lost: Counter[str]) -> None:
        self.lost = lost
        listed = ", ".join(f"{name}×{count}" for name, count in sorted(lost.items()))
        super().__init__(
            f"The Markdown conversion or the edit would remove these macros/elements: {listed}. "
            "Re-read the page and keep its raw <ac:…> blocks unchanged in the new body, or "
            'edit it with format="storage". Pass allow_macro_loss=true only if removing '
            "them is intended."
        )


class ConfluenceAPIError(ConfluenceMCPError):
    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}: {message}")


class ValidationError(ConfluenceAPIError):
    """400 — request rejected by Confluence."""


class AuthenticationError(ConfluenceAPIError):
    """401 — authentication failed."""


class AuthorizationError(ConfluenceAPIError):
    """403 — insufficient permissions."""


class NotFoundError(ConfluenceAPIError):
    """404 — resource not found."""


class VersionConflictError(ConfluenceAPIError):
    """409 — content was modified concurrently, or expected_version did not match."""

    def __init__(self, message: str, current_version: int | None = None) -> None:
        self.current_version = current_version
        super().__init__(409, message)


class PayloadTooLargeError(ConfluenceAPIError):
    """413 — payload too large (also used for local size-limit refusals)."""


class RateLimitError(ConfluenceAPIError):
    """429 — rate limited (after retries)."""
