"""Configuration for Confluence Server MCP.

Reads from environment variables (CONFLUENCE_* and MCP_*) or a .env file.
"""

from __future__ import annotations

import base64
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _unquote(v: str) -> str:
    """Strip surrounding quotes that Docker Compose passes through literally."""
    return v.strip().strip('"').strip("'")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,  # never echo CONFLUENCE_PASSWORD/TOKEN at startup
    )

    # Confluence connection
    confluence_url: str
    confluence_token: str | None = None
    confluence_username: str | None = None
    confluence_password: str | None = None

    # Behaviour options
    confluence_default_space: str | None = None
    confluence_read_only: bool = False
    confluence_custom_headers: str | None = None  # "Header=Val,Other=Val=WithEquals"
    confluence_log_path: str | None = None
    confluence_attachment_max_bytes: int = Field(default=5 * 1024 * 1024, gt=0)
    confluence_timeout_seconds: float = Field(default=30.0, gt=0)

    # Transport
    mcp_transport: Literal["stdio", "http"] = "stdio"
    mcp_http_host: str = "127.0.0.1"
    mcp_http_port: int = Field(default=8000, gt=0, le=65535)

    @field_validator("confluence_url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = _unquote(v).rstrip("/")
        if not v.startswith(("http://", "https://")):
            raise ValueError(f"CONFLUENCE_URL must start with http:// or https://, got: {v!r}")
        return v

    @field_validator(
        "confluence_token",
        "confluence_username",
        "confluence_password",
        "confluence_default_space",
        "confluence_custom_headers",
        mode="before",
    )
    @classmethod
    def unquote_optional(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = _unquote(v)
        return v or None

    @model_validator(mode="after")
    def require_auth(self) -> Settings:
        has_basic = bool(self.confluence_username) and bool(self.confluence_password)
        if not self.confluence_token and not has_basic:
            raise ValueError(
                "Set CONFLUENCE_TOKEN or both CONFLUENCE_USERNAME and CONFLUENCE_PASSWORD"
            )
        return self

    def get_auth_headers(self) -> dict[str, str]:
        if self.confluence_token:
            return {"Authorization": f"Bearer {self.confluence_token}"}
        creds = base64.b64encode(
            f"{self.confluence_username}:{self.confluence_password}".encode()
        ).decode()
        return {"Authorization": f"Basic {creds}"}

    def get_custom_headers(self) -> dict[str, str]:
        """Parse comma-separated Header=Value pairs; values may contain '='."""
        if not self.confluence_custom_headers:
            return {}
        result: dict[str, str] = {}
        for pair in self.confluence_custom_headers.split(","):
            key, sep, value = pair.strip().partition("=")
            key = key.strip()
            if key and sep:  # skip pairs without a '=' separator
                result[key] = value.strip()
        return result

    def redacted(self) -> dict[str, object]:
        return {
            "confluence_url": self.confluence_url,
            "auth_method": "token" if self.confluence_token else "basic",
            "default_space": self.confluence_default_space,
            "read_only": self.confluence_read_only,
            "transport": self.mcp_transport,
            "http_host": self.mcp_http_host,
            "http_port": self.mcp_http_port,
            "attachment_max_bytes": self.confluence_attachment_max_bytes,
            "custom_headers_count": len(self.get_custom_headers()),
        }
