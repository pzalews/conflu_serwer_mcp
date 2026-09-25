# Confluence Server MCP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a FastMCP server (Docker, streamable HTTP) that gives AI assistants read/write access to a self-hosted Confluence Server / Data Center through 31 tools, exchanging page bodies as Markdown without losing macros.

**Architecture:** Mirrors `../bitbucket_server_mcp`: `src/confluence_mcp/` with a lifespan that builds `Settings` + `ConfluenceClient`, module-level async tool functions that read them from `ctx.lifespan_context`, and `register_all_tools`. A pure `converter/` package turns storage XHTML ↔ Markdown by scanning `ac:`/`ri:` elements on the raw text, converting known constructs and passing unknown ones through byte-for-byte as tokens. `content.py` is the single place implementing create/update rules (version bump, `expected_version`, macro-loss check).

**Tech Stack:** Python 3.12, FastMCP (≥3.3.1; resolves to 4.x), httpx, pydantic-settings, tenacity, structlog, markdown, markdownify, beautifulsoup4, lxml (tests); pytest + pytest-asyncio + respx; ruff; mypy --strict; uv; Docker.

**Spec:** `docs/superpowers/specs/2026-09-25-confluence-server-mcp-design.md`

**Note on the code in this plan:** every file below was written and run in a scratch prototype before the plan was written: 136 tests pass, `ruff check` and `mypy --strict` are clean, and the Docker image builds, starts as the non-root user and answers MCP `initialize` on `/mcp`. Copy the code exactly; if a step's result differs from "Expected", stop and investigate instead of improvising.

## Global Constraints

- Python `>=3.12`; Docker base image `python:3.12-slim`; package name `confluence-server-mcp`, import package `confluence_mcp`, console script `confluence-mcp`.
- Layout and conventions follow `../bitbucket_server_mcp` (src layout, lifespan context, `log_tool_call`, `register_all_tools`, Makefile targets).
- Env vars exactly: `CONFLUENCE_URL`, `CONFLUENCE_TOKEN`, `CONFLUENCE_USERNAME`, `CONFLUENCE_PASSWORD`, `CONFLUENCE_DEFAULT_SPACE`, `CONFLUENCE_READ_ONLY`, `CONFLUENCE_CUSTOM_HEADERS`, `CONFLUENCE_LOG_PATH`, `CONFLUENCE_ATTACHMENT_MAX_BYTES` (default `5242880`), `CONFLUENCE_TIMEOUT_SECONDS` (default `30`), `MCP_TRANSPORT` (`stdio`|`http`), `MCP_HTTP_HOST`, `MCP_HTTP_PORT`.
- PAT → `Authorization: Bearer <token>`; PAT wins over basic auth; startup fails without either.
- Credentials never appear in logs or exception messages.
- Every write tool calls `require_writable(ctx, "<tool name>")` as its first statement, before any HTTP call.
- Content tools take `format: Literal["markdown", "storage"] = "markdown"`.
- List tools return `{"results", "start", "limit", "size", "has_more"}`; `limit` is capped at 100.
- Retries: 3 attempts; 429 and connection errors retried for all methods; 5xx and other transport errors only for GET/PUT/DELETE; `Retry-After` honoured (capped at 30 s).
- ruff line-length 100, rules `E,W,F,UP,B,I`; `mypy --strict` clean on `src/`.
- MCP HTTP endpoint is `http://<host>:8000/mcp` (FastMCP answers `/mcp/` with a 307 redirect).
- Every commit message ends with the `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` line shown in the commit steps.

## Review Focus

1. **Real pages with macros that have extra parameters** (code macro with `title`, panel with `title`, `ac:link` to a user or with an anchor): a reader expects them to survive untouched, not to be half-converted and lose their parameters. They must go through as raw XHTML. Pinned by fixture `macros_unknown.xml` in Task 5.
2. **An assistant rewrites a page and drops a raw `<ac:…>` block**: the user expects the page to keep its Jira/TOC macros. The update is rejected with `MacroLossError` and no PUT is sent. Pinned by `test_update_rejects_macro_loss` in Task 6.
3. **Literal `<`, `&`, or `<ac:` text in prose, inline code and code blocks**: this must stay text and never become markup or a spurious macro. Pinned by `test_md_literal_angle_bracket_escaped` (Task 4) and `test_st_raw_macro_in_code_span_is_text` / `test_st_fence_becomes_code_macro` (Task 5).
4. **Adjacent callouts or adjacent raw macro blocks**: Python-Markdown would merge them into one blockquote or one `<p>`, and the user expects two separate panels/macros. Pinned by `test_st_consecutive_callouts_stay_separate` and `test_st_adjacent_raw_blocks_not_wrapped_in_p` (Task 5).
5. **Confluence under a context path** (`https://host/confluence`): API calls and relative attachment download links must keep the path. Pinned by `test_context_path_kept` (Task 2) and `test_download_link_resolved_under_context_path` (Task 9).

## File Map

| File | Responsibility | Task |
|---|---|---|
| `pyproject.toml`, `.python-version`, `.gitignore`, `README.md` (stub) | packaging, tooling config | 1 |
| `src/confluence_mcp/exceptions.py` | exception hierarchy | 1 |
| `src/confluence_mcp/config.py` | `Settings`, auth/custom headers, `redacted()` | 1 |
| `src/confluence_mcp/logging_setup.py` | structlog config, `log_tool_call` | 2 |
| `src/confluence_mcp/client.py` | `ConfluenceClient`: retries, status→exception, `paginate` | 2 |
| `src/confluence_mcp/converter/macros.py` | text-level `ac:`/`ri:` scanner, CDATA helpers, `inventory` | 3 |
| `src/confluence_mcp/converter/to_markdown.py` | storage → Markdown | 4 |
| `src/confluence_mcp/converter/to_storage.py`, `converter/__init__.py` | Markdown → storage; public API | 5 |
| `src/confluence_mcp/content.py` | get/create/update/restore with safeguards | 6 |
| `src/confluence_mcp/tools/_common.py`, `tools/pages.py`, `tools/blogposts.py` | helpers; page and blog post tools | 7 |
| `tools/search.py`, `tools/spaces.py`, `tools/users.py`, `tools/history.py` | search, spaces, users, history tools | 8 |
| `tools/comments.py`, `tools/labels.py`, `tools/attachments.py` | comment, label, attachment tools | 9 |
| `tools/__init__.py`, `server.py`, `__main__.py`, `resources.py`, `prompts.py` | registration, server, entry point | 10 |
| `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `Makefile`, `.env.example`, `mcp_config_*.json`, `.github/*`, `README.md` | deployment and docs | 11 |

---

### Task 1: Project scaffold, exceptions and configuration

**Files:**
- Create: `pyproject.toml`, `.python-version`, `.gitignore`, `README.md` (one-line stub; replaced in Task 11)
- Create: `src/confluence_mcp/__init__.py`, `src/confluence_mcp/exceptions.py`, `src/confluence_mcp/config.py`
- Test: `tests/__init__.py` (empty), `tests/conftest.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Settings` (pydantic-settings) with fields `confluence_url: str`, `confluence_token/username/password/default_space/custom_headers/log_path: str | None`, `confluence_read_only: bool`, `confluence_attachment_max_bytes: int`, `confluence_timeout_seconds: float`, `mcp_transport: Literal["stdio","http"]`, `mcp_http_host: str`, `mcp_http_port: int`; methods `get_auth_headers() -> dict[str,str]`, `get_custom_headers() -> dict[str,str]`, `redacted() -> dict[str, object]`.
  - Exceptions: `ConfluenceMCPError`, `ConfigurationError`, `ReadOnlyModeError(tool_name)`, `MacroLossError(lost: Counter[str])` (has `.lost`), `ConfluenceAPIError(status_code, message)` (has `.status_code`) with subclasses `ValidationError`, `AuthenticationError`, `AuthorizationError`, `NotFoundError`, `VersionConflictError(message, current_version=None)` (status 409, has `.current_version`), `PayloadTooLargeError`, `RateLimitError`.
  - Test helpers in `tests/conftest.py`: `BASE = "https://confluence.test"`, `make_settings(**overrides) -> Settings`, fixture `settings`, autouse fixture that clears `CONFLUENCE_*`/`MCP_*` env vars and chdirs into `tests/`.

- [ ] **Step 1: Create packaging files and the virtualenv**

`pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "confluence-server-mcp"
version = "0.1.0"
description = "FastMCP server for Confluence Server / Confluence Data Center (self-hosted)"
readme = "README.md"
requires-python = ">=3.12"
license = { text = "MIT" }
dependencies = [
    "fastmcp>=3.3.1",
    "httpx>=0.28.1,<1.0",
    "pydantic>=2.11.0,<3.0",
    "pydantic-settings>=2.7.0,<3.0",
    "tenacity>=9.0.0,<10.0",
    "structlog>=25.1.0",
    "markdown>=3.7",
    "markdownify>=1.1",
    "beautifulsoup4>=4.12",
    "lxml>=5.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.25.0",
    "respx>=0.22.0",
    "ruff>=0.9.0",
    "mypy>=1.15.0",
    "types-Markdown",
    "lxml-stubs",
]

[project.scripts]
confluence-mcp = "confluence_mcp.__main__:main"

[tool.hatch.build.targets.wheel]
packages = ["src/confluence_mcp"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
target-version = "py312"
line-length = 100
src = ["src"]

[tool.ruff.lint]
select = ["E", "W", "F", "UP", "B", "I"]
ignore = []

[tool.mypy]
python_version = "3.12"
strict = true
mypy_path = "src"
packages = ["confluence_mcp"]

[[tool.mypy.overrides]]
module = ["tenacity.*", "structlog.*"]
ignore_missing_imports = true
```

`.python-version`:

```
3.12
```

`.gitignore`:

```gitignore
__pycache__/
*.py[cod]
.env
.venv/
venv/
dist/
**/*.egg-info/
.mypy_cache/
.ruff_cache/
.pytest_cache/
.coverage
coverage.xml
htmlcov/
uv.lock
```

`README.md` (stub so `pip install` works; Task 11 replaces it):

```markdown
# Confluence Server MCP
```

`src/confluence_mcp/__init__.py`:

```python
"""MCP server for Confluence Server / Data Center."""
```

Create an empty `tests/__init__.py`, then:

```bash
uv venv -p 3.12 .venv
uv pip install -p .venv/bin/python -e ".[dev]"
```

Expected: installs without errors.

- [ ] **Step 2: Write the failing tests**

`tests/conftest.py`:

```python
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

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
```

`tests/test_config.py`:

```python
from __future__ import annotations

import base64

import pytest
from pydantic import ValidationError

from confluence_mcp.config import Settings
from tests.conftest import BASE, make_settings


def test_url_trailing_slash_and_quotes_stripped() -> None:
    s = make_settings(confluence_url='"https://c.example.com/confluence/"')
    assert s.confluence_url == "https://c.example.com/confluence"


def test_url_must_have_scheme() -> None:
    with pytest.raises(ValidationError, match="must start with http"):
        make_settings(confluence_url="c.example.com")


def test_token_auth_header() -> None:
    assert make_settings().get_auth_headers() == {"Authorization": "Bearer secret-token"}


def test_token_preferred_over_basic() -> None:
    s = make_settings(confluence_username="u", confluence_password="p")
    assert s.get_auth_headers()["Authorization"].startswith("Bearer ")


def test_basic_auth_header() -> None:
    s = Settings(confluence_url=BASE, confluence_username="alice", confluence_password="pw")
    expected = base64.b64encode(b"alice:pw").decode()
    assert s.get_auth_headers() == {"Authorization": f"Basic {expected}"}


def test_missing_auth_fails() -> None:
    with pytest.raises(ValidationError, match="CONFLUENCE_TOKEN"):
        Settings(confluence_url=BASE)


def test_empty_quoted_token_counts_as_missing() -> None:
    with pytest.raises(ValidationError, match="CONFLUENCE_TOKEN"):
        Settings(confluence_url=BASE, confluence_token='""')


def test_env_vars_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONFLUENCE_URL", BASE)
    monkeypatch.setenv("CONFLUENCE_TOKEN", "'quoted'")
    monkeypatch.setenv("CONFLUENCE_READ_ONLY", "true")
    s = Settings()  # type: ignore[call-arg]
    assert s.confluence_token == "quoted"
    assert s.confluence_read_only is True


def test_custom_headers_parsing() -> None:
    s = make_settings(confluence_custom_headers="X-A=1, X-B=a=b,broken,=novalue")
    assert s.get_custom_headers() == {"X-A": "1", "X-B": "a=b"}


def test_redacted_hides_secrets() -> None:
    s = make_settings(confluence_custom_headers="X-Secret=zzz")
    text = repr(s.redacted())
    assert "secret-token" not in text
    assert "zzz" not in text
    assert s.redacted()["auth_method"] == "token"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_config.py -q`
Expected: collection error: `ModuleNotFoundError: No module named 'confluence_mcp.config'`.

- [ ] **Step 4: Implement exceptions and configuration**

`src/confluence_mcp/exceptions.py`:

```python
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
            f"Update would remove macros/elements: {listed}. Keep the raw <ac:…> blocks "
            "from the page body, or pass allow_macro_loss=true if removing them is intended."
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
```

`src/confluence_mcp/config.py`:

```python
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
```

- [ ] **Step 5: Run tests and checks**

Run: `.venv/bin/python -m pytest tests/test_config.py -q && .venv/bin/ruff format src tests && .venv/bin/ruff check src tests && .venv/bin/mypy src`
Expected: `10 passed`; ruff and mypy report no issues.

- [ ] **Step 6: Commit**

```bash
git add .python-version .gitignore pyproject.toml README.md src tests
git commit -m "feat: scaffold project with settings and exceptions

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 2: HTTP client with retries and error mapping

**Files:**
- Create: `src/confluence_mcp/logging_setup.py`, `src/confluence_mcp/client.py`
- Modify: `tests/conftest.py` (add the `client` fixture and `make_ctx`)
- Test: `tests/test_client.py`

**Interfaces:**
- Consumes: `Settings`, exceptions (Task 1).
- Produces:
  - `configure_logging(log_path: str | None = None, json_logs: bool = False) -> None`, `get_logger(name)`, `log_tool_call(tool_name: str, **fields: str | int | None)` (async context manager).
  - `ConfluenceClient(settings, *, retry_wait: float = 0.5)` with `base_url: str` property, `aclose()`, `request(method, path, *, params, json, files, data, headers) -> httpx.Response`, `get(path, params=None) -> Any`, `post(path, json=None, *, params, files, data, headers) -> Any`, `put(path, json=None) -> Any`, `delete(path, params=None) -> None`, `get_bytes(path) -> tuple[bytes, str]`, `paginate(path, params=None, *, max_items=500) -> list[dict]`. Paths are relative to `CONFLUENCE_URL`, so a context path is preserved.
  - Test helpers: fixture `client` (a `ConfluenceClient` with `retry_wait=0`), `make_ctx(client, settings) -> MagicMock` whose `lifespan_context` is `{"client", "settings"}`.

- [ ] **Step 1: Replace `tests/conftest.py` with the full version and write the failing client tests**

`tests/conftest.py`:

```python
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
```

`tests/test_client.py`:

```python
from __future__ import annotations

import httpx
import pytest
import respx

from confluence_mcp.client import ConfluenceClient
from confluence_mcp.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ConfluenceAPIError,
    NotFoundError,
    PayloadTooLargeError,
    RateLimitError,
    ValidationError,
    VersionConflictError,
)
from tests.conftest import BASE, make_settings


@respx.mock
async def test_sends_auth_and_custom_headers() -> None:
    c = ConfluenceClient(make_settings(confluence_custom_headers="X-Proxy=abc"), retry_wait=0)
    route = respx.get(f"{BASE}/rest/api/space").mock(return_value=httpx.Response(200, json={}))
    await c.get("/rest/api/space")
    headers = route.calls.last.request.headers
    assert headers["Authorization"] == "Bearer secret-token"
    assert headers["X-Proxy"] == "abc"
    await c.aclose()


@respx.mock
async def test_context_path_kept() -> None:
    c = ConfluenceClient(make_settings(confluence_url=f"{BASE}/confluence"), retry_wait=0)
    route = respx.get(f"{BASE}/confluence/rest/api/space").mock(
        return_value=httpx.Response(200, json={})
    )
    await c.get("/rest/api/space")
    assert route.called
    await c.aclose()


@pytest.mark.parametrize(
    ("status", "exc"),
    [
        (400, ValidationError),
        (401, AuthenticationError),
        (403, AuthorizationError),
        (404, NotFoundError),
        (409, VersionConflictError),
        (413, PayloadTooLargeError),
        (418, ConfluenceAPIError),
    ],
)
@respx.mock
async def test_status_mapping(client: ConfluenceClient, status: int, exc: type[Exception]) -> None:
    respx.get(f"{BASE}/x").mock(
        return_value=httpx.Response(status, json={"statusCode": status, "message": "boom msg"})
    )
    with pytest.raises(exc) as info:
        await client.get("/x")
    if status != 401:
        assert "boom msg" in str(info.value)


@respx.mock
async def test_error_text_never_contains_token(client: ConfluenceClient) -> None:
    respx.get(f"{BASE}/x").mock(return_value=httpx.Response(401, text="nope"))
    with pytest.raises(AuthenticationError) as info:
        await client.get("/x")
    assert "secret-token" not in str(info.value)


@respx.mock
async def test_retries_get_on_503(client: ConfluenceClient) -> None:
    route = respx.get(f"{BASE}/x").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json={"ok": True})]
    )
    assert await client.get("/x") == {"ok": True}
    assert route.call_count == 2


@respx.mock
async def test_gives_up_after_three_attempts(client: ConfluenceClient) -> None:
    route = respx.get(f"{BASE}/x").mock(return_value=httpx.Response(502))
    with pytest.raises(ConfluenceAPIError):
        await client.get("/x")
    assert route.call_count == 3


@respx.mock
async def test_post_not_retried_on_5xx(client: ConfluenceClient) -> None:
    route = respx.post(f"{BASE}/x").mock(return_value=httpx.Response(500))
    with pytest.raises(ConfluenceAPIError):
        await client.post("/x", json={})
    assert route.call_count == 1


@respx.mock
async def test_post_retried_on_429_honouring_retry_after(client: ConfluenceClient) -> None:
    route = respx.post(f"{BASE}/x").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json={"id": "1"}),
        ]
    )
    assert await client.post("/x", json={}) == {"id": "1"}
    assert route.call_count == 2


@respx.mock
async def test_429_exhausted_raises_rate_limit(client: ConfluenceClient) -> None:
    respx.get(f"{BASE}/x").mock(return_value=httpx.Response(429, headers={"Retry-After": "0"}))
    with pytest.raises(RateLimitError):
        await client.get("/x")


@respx.mock
async def test_connect_error_retried_for_post(client: ConfluenceClient) -> None:
    route = respx.post(f"{BASE}/x").mock(
        side_effect=[httpx.ConnectError("down"), httpx.Response(200, json={})]
    )
    await client.post("/x", json={})
    assert route.call_count == 2


@respx.mock
async def test_paginate_follows_next(client: ConfluenceClient) -> None:
    route = respx.get(f"{BASE}/rest/api/space").mock(
        side_effect=[
            httpx.Response(
                200,
                json={"results": [{"key": "A"}], "start": 0, "_links": {"next": "/n"}},
            ),
            httpx.Response(200, json={"results": [{"key": "B"}], "start": 1, "_links": {}}),
        ]
    )
    assert await client.paginate("/rest/api/space") == [{"key": "A"}, {"key": "B"}]
    assert route.calls[1].request.url.params["start"] == "1"


@respx.mock
async def test_delete_returns_none_on_204(client: ConfluenceClient) -> None:
    respx.delete(f"{BASE}/x").mock(return_value=httpx.Response(204))
    assert await client.delete("/x") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_client.py -q`
Expected: collection error: `ModuleNotFoundError: No module named 'confluence_mcp.client'`.

- [ ] **Step 3: Implement logging and the client**

`src/confluence_mcp/logging_setup.py`:

```python
"""Structured logging setup using structlog."""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog


def configure_logging(log_path: str | None = None, json_logs: bool = False) -> None:
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    renderer: Any
    if json_logs or log_path:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    structlog.configure(
        processors=shared + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_path:
        handlers.append(logging.FileHandler(log_path))

    root = logging.getLogger()
    for handler in handlers:
        handler.setFormatter(formatter)
        root.addHandler(handler)
    root.setLevel(logging.INFO)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]


@asynccontextmanager
async def log_tool_call(tool_name: str, **fields: str | int | None) -> AsyncIterator[None]:
    """Bind tool name (and non-empty identifying fields) to the log context; log duration."""
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        tool=tool_name, **{k: v for k, v in fields.items() if v is not None}
    )
    log = get_logger(tool_name)
    start = time.monotonic()
    log.debug("tool.start")
    try:
        yield
        log.info("tool.success", duration_ms=round((time.monotonic() - start) * 1000))
    except Exception as exc:
        log.warning(
            "tool.error",
            duration_ms=round((time.monotonic() - start) * 1000),
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise
```

`src/confluence_mcp/client.py`:

```python
"""HTTP client for the Confluence Server REST API.

Knows auth, retries, status→exception mapping and pagination; nothing about
page content formats.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from tenacity import AsyncRetrying, RetryCallState, retry_if_exception, stop_after_attempt

from .config import Settings
from .exceptions import (
    AuthenticationError,
    AuthorizationError,
    ConfluenceAPIError,
    NotFoundError,
    PayloadTooLargeError,
    RateLimitError,
    ValidationError,
    VersionConflictError,
)
from .logging_setup import get_logger

log = get_logger(__name__)

_IDEMPOTENT = {"GET", "PUT", "DELETE"}
_MAX_RETRY_AFTER = 30.0


class _RetryableRateLimit(RateLimitError):
    def __init__(self, message: str, retry_after: float | None) -> None:
        super().__init__(429, message)
        self.retry_after = retry_after


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:500] or response.reason_phrase
    if isinstance(body, dict) and body.get("message"):
        return str(body["message"])
    return response.text[:500]


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    try:
        return min(float(value), _MAX_RETRY_AFTER) if value else None
    except ValueError:
        return None


def _raise_for_status(response: httpx.Response) -> None:
    status = response.status_code
    if status < 400:
        return
    message = _error_message(response)
    if status == 400:
        raise ValidationError(400, message)
    if status == 401:
        raise AuthenticationError(401, "Authentication failed — check CONFLUENCE_TOKEN")
    if status == 403:
        raise AuthorizationError(403, message or "Insufficient permissions")
    if status == 404:
        raise NotFoundError(404, message or "Not found")
    if status == 409:
        raise VersionConflictError(message or "Conflict — content was modified concurrently")
    if status == 413:
        raise PayloadTooLargeError(413, message or "Payload too large")
    if status == 429:
        raise _RetryableRateLimit(message or "Rate limited", _retry_after(response))
    raise ConfluenceAPIError(status, message)


class ConfluenceClient:
    def __init__(self, settings: Settings, *, retry_wait: float = 0.5) -> None:
        self._settings = settings
        self._retry_wait = retry_wait
        headers = {
            "Accept": "application/json",
            **settings.get_auth_headers(),
            **settings.get_custom_headers(),
        }
        self._http = httpx.AsyncClient(
            base_url=settings.confluence_url,
            headers=headers,
            timeout=httpx.Timeout(settings.confluence_timeout_seconds, connect=10.0),
            follow_redirects=True,
        )

    @property
    def base_url(self) -> str:
        return self._settings.confluence_url

    async def aclose(self) -> None:
        await self._http.aclose()

    def _should_retry(self, method: str) -> Any:
        def check(exc: BaseException) -> bool:
            if isinstance(exc, RateLimitError):
                return True
            if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
                return True  # request never reached the server
            if method not in _IDEMPOTENT:
                return False
            if isinstance(exc, httpx.TransportError):
                return True
            return isinstance(exc, ConfluenceAPIError) and exc.status_code >= 500

        return check

    def _wait(self, state: RetryCallState) -> float:
        exc = state.outcome.exception() if state.outcome else None
        retry_after = getattr(exc, "retry_after", None)
        if retry_after is not None:
            return float(retry_after)
        return float(min(self._retry_wait * 2 ** (state.attempt_number - 1), 4.0))

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        files: dict[str, Any] | None = None,
        data: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Send a request with retries; raise a typed exception for HTTP errors."""
        retrying = AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=self._wait,
            retry=retry_if_exception(self._should_retry(method)),
            reraise=True,
        )
        response: httpx.Response | None = None
        async for attempt in retrying:
            with attempt:
                start = time.monotonic()
                response = await self._http.request(
                    method,
                    path,
                    params=params,
                    json=json,
                    files=files,
                    data=data,
                    headers=headers,
                )
                log.info(
                    "confluence.request",
                    method=method,
                    path=path,
                    status=response.status_code,
                    duration_ms=round((time.monotonic() - start) * 1000),
                )
                _raise_for_status(response)
        assert response is not None
        return response

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = await self.request("GET", path, params=params)
        return response.json() if response.content else None

    async def post(
        self,
        path: str,
        json: Any = None,
        *,
        params: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        data: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        response = await self.request(
            "POST", path, params=params, json=json, files=files, data=data, headers=headers
        )
        return response.json() if response.content else None

    async def put(self, path: str, json: Any = None) -> Any:
        response = await self.request("PUT", path, json=json)
        return response.json() if response.content else None

    async def delete(self, path: str, params: dict[str, Any] | None = None) -> None:
        await self.request("DELETE", path, params=params)

    async def get_bytes(self, path: str) -> tuple[bytes, str]:
        """Download a binary resource (path may be relative to the base URL)."""
        response = await self.request("GET", path)
        return response.content, response.headers.get("Content-Type", "")

    async def paginate(
        self, path: str, params: dict[str, Any] | None = None, *, max_items: int = 500
    ) -> list[dict[str, Any]]:
        """Collect ``results`` across pages by following ``_links.next``."""
        page_params: dict[str, Any] = {**(params or {}), "start": 0, "limit": 100}
        results: list[dict[str, Any]] = []
        while len(results) < max_items:
            data = await self.get(path, params=page_params)
            batch: list[dict[str, Any]] = data.get("results", [])
            results.extend(batch)
            if not batch or "next" not in data.get("_links", {}):
                break
            page_params["start"] = data.get("start", page_params["start"]) + len(batch)
        return results[:max_items]
```

- [ ] **Step 4: Run tests and checks**

Run: `.venv/bin/python -m pytest tests -q && .venv/bin/ruff format src tests && .venv/bin/ruff check src tests && .venv/bin/mypy src`
Expected: all tests pass (`28 passed`); ruff and mypy clean.

- [ ] **Step 5: Commit**

```bash
git add src tests
git commit -m "feat: add Confluence HTTP client with retries and error mapping

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 3: Converter scanner and macro inventory

The converter never parses storage as a DOM for macros. `find_elements` scans the raw text for `ac:`/`ri:` tags, skipping CDATA and comments (and, in Markdown mode, fenced code and code spans). It returns the outermost elements with exact offsets. This lets unknown elements be copied byte-for-byte.

**Files:**
- Create: `src/confluence_mcp/converter/macros.py` (create the `converter/` directory without an `__init__.py` for now — Task 5 adds it; Python treats it as a namespace package meanwhile)
- Test: `tests/test_macros.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `PANEL_MACROS = ("info", "note", "warning", "tip")`.
  - `@dataclass Element(name, attrs: dict[str,str], start, end, inner_start, inner_end, source)` with properties `text`, `inner` and method `children() -> list[Element]` (offsets absolute in `source`).
  - `find_elements(text: str, *, markdown: bool = False) -> list[Element]`.
  - `cdata_text(inner: str) -> str` (joins all CDATA sections), `cdata(text: str) -> str` (splits `]]>`).
  - `inventory(storage: str) -> Counter[str]` counting macros by `ac:name` plus `ac:image`, `ac:task-list`, `ac:link` (ignores CDATA/comments; `ac:link-body` is not an `ac:link`).

- [ ] **Step 1: Write the failing tests**

`tests/test_macros.py`:

````python
from __future__ import annotations

from collections import Counter

from confluence_mcp.converter.macros import cdata, cdata_text, find_elements, inventory


def test_find_outermost_elements_only() -> None:
    text = (
        '<p>a</p><ac:structured-macro ac:name="info"><ac:rich-text-body>'
        '<ac:structured-macro ac:name="jira"/></ac:rich-text-body></ac:structured-macro>'
        '<ri:page ri:content-title="T"/>'
    )
    els = find_elements(text)
    assert [e.name for e in els] == ["ac:structured-macro", "ri:page"]
    assert els[0].attrs == {"ac:name": "info"}
    assert els[0].text.endswith("</ac:structured-macro>")
    assert els[1].attrs == {"ri:content-title": "T"}


def test_nested_same_name_matched_correctly() -> None:
    text = (
        '<ac:structured-macro ac:name="expand"><ac:rich-text-body>'
        '<ac:structured-macro ac:name="expand"><ac:rich-text-body>x</ac:rich-text-body>'
        "</ac:structured-macro></ac:rich-text-body></ac:structured-macro>tail"
    )
    [el] = find_elements(text)
    assert text[el.end :] == "tail"


def test_children_have_absolute_offsets() -> None:
    text = '<ac:link><ri:page ri:content-title="T"/><ac:link-body>x</ac:link-body></ac:link>'
    [el] = find_elements(text)
    kids = el.children()
    assert [k.name for k in kids] == ["ri:page", "ac:link-body"]
    assert kids[1].inner == "x"


def test_cdata_content_is_not_scanned() -> None:
    text = "<ac:plain-text-body><![CDATA[<ac:fake>]]></ac:plain-text-body>"
    [el] = find_elements(text)
    assert el.children() == []


def test_markdown_mode_skips_code() -> None:
    md = "`<ac:a/>` and\n\n```\n<ac:b/>\n```\n\n<ac:c/>"
    assert [e.text for e in find_elements(md, markdown=True)] == ["<ac:c/>"]


def test_unclosed_element_runs_to_end() -> None:
    [el] = find_elements('<p>x</p><ac:structured-macro ac:name="toc"><p>y</p>')
    assert el.text == '<ac:structured-macro ac:name="toc"><p>y</p>'


def test_cdata_roundtrip_with_terminator() -> None:
    wrapped = cdata("a ]]> b")
    assert wrapped == "<![CDATA[a ]]]]><![CDATA[> b]]>"
    assert cdata_text(wrapped) == "a ]]> b"


def test_inventory_counts_macros_and_structures() -> None:
    storage = (
        '<ac:structured-macro ac:name="jira"/><ac:structured-macro ac:name="jira">'
        '</ac:structured-macro><ac:macro ac:name="toc"/><ac:link><ri:page/></ac:link>'
        '<ac:image><ri:url ri:value="u"/></ac:image><ac:task-list></ac:task-list>'
        '<ac:plain-text-body><![CDATA[<ac:structured-macro ac:name="fake"/>]]>'
        "</ac:plain-text-body>"
    )
    assert inventory(storage) == Counter(
        {"jira": 2, "toc": 1, "ac:link": 1, "ac:image": 1, "ac:task-list": 1}
    )
````

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_macros.py -q`
Expected: collection error: `ModuleNotFoundError: No module named 'confluence_mcp.converter'`.

- [ ] **Step 3: Implement the scanner**

`src/confluence_mcp/converter/macros.py`:

```python
"""Text-level scanning of Confluence storage elements (ac:*/ri:*) and macro inventory.

Scanning works on the raw text so unknown elements can be passed through byte-for-byte.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

PANEL_MACROS = ("info", "note", "warning", "tip")

_TAG_RE = re.compile(
    r"<(/?)((?:ac|ri):[\w-]+)((?:\s+[\w:-]+\s*=\s*(?:\"[^\"]*\"|'[^']*'))*)\s*(/?)>"
)
_ATTR_RE = re.compile(r"([\w:-]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)')")
_CDATA_RE = re.compile(r"<!\[CDATA\[.*?\]\]>", re.DOTALL)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_FENCE_RE = re.compile(
    r"^(?P<fence>`{3,}|~{3,})[^\n]*\n.*?(?:^(?P=fence)[ \t]*$|\Z)", re.DOTALL | re.MULTILINE
)
_CODE_SPAN_RE = re.compile(r"(`+)(?!`).+?(?<!`)\1(?!`)", re.DOTALL)
_MACRO_NAME_RE = re.compile(r"<ac:(?:structured-)?macro\b[^>]*?\bac:name\s*=\s*[\"']([^\"']+)[\"']")
_STRUCTURE_RE = re.compile(r"<(ac:image|ac:task-list|ac:link)(?=[\s/>])")


@dataclass
class Element:
    """One ac:/ri: element located in a text."""

    name: str
    attrs: dict[str, str]
    start: int
    end: int
    inner_start: int
    inner_end: int
    source: str = field(repr=False)

    @property
    def text(self) -> str:
        return self.source[self.start : self.end]

    @property
    def inner(self) -> str:
        return self.source[self.inner_start : self.inner_end]

    def children(self) -> list[Element]:
        return [
            Element(
                c.name,
                c.attrs,
                c.start + self.inner_start,
                c.end + self.inner_start,
                c.inner_start + self.inner_start,
                c.inner_end + self.inner_start,
                self.source,
            )
            for c in find_elements(self.inner)
        ]


def _protected_ranges(text: str, markdown: bool) -> list[tuple[int, int]]:
    patterns = [_CDATA_RE, _COMMENT_RE]
    if markdown:
        patterns += [_FENCE_RE, _CODE_SPAN_RE]
    ranges = [(m.start(), m.end()) for p in patterns for m in p.finditer(text)]
    return sorted(ranges)


def _in_ranges(pos: int, ranges: list[tuple[int, int]]) -> bool:
    return any(a <= pos < b for a, b in ranges)


def find_elements(text: str, *, markdown: bool = False) -> list[Element]:
    """Return the outermost ac:/ri: elements in ``text`` in document order.

    CDATA sections and comments are skipped; with ``markdown=True`` fenced code
    blocks and inline code spans are skipped too. An element whose closing tag is
    missing extends to the end of the text.
    """
    ranges = _protected_ranges(text, markdown)
    tags = [m for m in _TAG_RE.finditer(text) if not _in_ranges(m.start(), ranges)]
    result: list[Element] = []
    i = 0
    while i < len(tags):
        m = tags[i]
        closing, name, attr_text, self_closing = m.group(1), m.group(2), m.group(3), m.group(4)
        if closing:  # stray closing tag: ignore
            i += 1
            continue
        attrs = {
            a.group(1): a.group(2) if a.group(2) is not None else a.group(3) or ""
            for a in _ATTR_RE.finditer(attr_text)
        }
        if self_closing:
            result.append(Element(name, attrs, m.start(), m.end(), m.end(), m.end(), text))
            i += 1
            continue
        depth = 1
        j = i + 1
        while j < len(tags) and depth:
            t = tags[j]
            if t.group(2) == name and not t.group(4):
                depth += -1 if t.group(1) else 1
            j += 1
        if depth:  # unclosed: take the rest of the text
            result.append(Element(name, attrs, m.start(), len(text), m.end(), len(text), text))
            break
        close = tags[j - 1]
        result.append(Element(name, attrs, m.start(), close.end(), m.end(), close.start(), text))
        i = j
    return result


def cdata_text(inner: str) -> str:
    """Concatenate the contents of all CDATA sections in ``inner``."""
    return "".join(m.group(0)[9:-3] for m in _CDATA_RE.finditer(inner))


def cdata(text: str) -> str:
    """Wrap ``text`` in CDATA, splitting any ``]]>`` it contains."""
    return "<![CDATA[" + text.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def inventory(storage: str) -> Counter[str]:
    """Count macros (by name) and structural elements in storage XHTML."""
    stripped = _COMMENT_RE.sub("", _CDATA_RE.sub("", storage))
    counts: Counter[str] = Counter(m.group(1) for m in _MACRO_NAME_RE.finditer(stripped))
    counts.update(m.group(1) for m in _STRUCTURE_RE.finditer(stripped))
    return counts
```

- [ ] **Step 4: Run tests and checks**

Run: `.venv/bin/python -m pytest tests/test_macros.py -q && .venv/bin/ruff format src tests && .venv/bin/ruff check src tests && .venv/bin/mypy src`
Expected: `8 passed`; ruff and mypy clean.

- [ ] **Step 5: Commit**

```bash
git add src/confluence_mcp/converter/macros.py tests/test_macros.py
git commit -m "feat: add storage element scanner and macro inventory

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 4: Storage → Markdown

`_prepare` replaces each outermost `ac:`/`ri:` element with plain HTML when it's a known construct with no extra parameters. Otherwise it replaces the element with a token `XCFRAW0000X`, and the original text is stored. Known bodies are prepared recursively. markdownify then converts the HTML. Tokens that end up at top level get their own paragraph. At the end the tokens are replaced by the original XHTML. Complex tables (spans, block content in cells, nested tables) are emitted as raw HTML. Literal `<` and entity-like `&` in text are escaped so they are not read back as markup.

**Files:**
- Create: `src/confluence_mcp/converter/to_markdown.py`
- Test: `tests/test_converter.py` (this task creates it with the storage → Markdown tests; Task 5 replaces it with the full suite)

**Interfaces:**
- Consumes: `find_elements`, `Element`, `cdata_text`, `PANEL_MACROS` (Task 3).
- Produces: `to_markdown(storage: str) -> str` (always ends with a single `\n`; `""` → `"\n"`). Mapping: code macro (only `language` param) → fenced block; `info/note/warning/tip` without params → `> [!INFO]` + `>` + body; `ac:link` + `ri:page` (no anchor) → `[text](confluence:SPACE/Title%20Encoded)` or `confluence:Title` (titles containing `/` without a space key stay raw); `ac:image` (only `ac:alt`) + `ri:attachment`/`ri:url` → `![alt](attachment:file%20name)` / `![alt](url)`; `ac:task-list` → `- [x]`/`- [ ]`; everything else raw.

- [ ] **Step 1: Write the failing tests**

`tests/test_converter.py`:

````python
from __future__ import annotations

from confluence_mcp.converter.to_markdown import to_markdown


# ── storage → Markdown ────────────────────────────────────────────────────────


def test_md_headings_and_inline() -> None:
    md = to_markdown("<h2>T</h2><p><strong>b</strong> <em>i</em> <code>c</code></p>")
    assert md == "## T\n\n**b** *i* `c`\n"


def test_md_code_macro_becomes_fence() -> None:
    storage = (
        '<ac:structured-macro ac:name="code"><ac:parameter ac:name="language">sql'
        "</ac:parameter><ac:plain-text-body><![CDATA[SELECT 1 < 2]]></ac:plain-text-body>"
        "</ac:structured-macro>"
    )
    assert to_markdown(storage) == "```sql\nSELECT 1 < 2\n```\n"


def test_md_panel_becomes_callout() -> None:
    storage = (
        '<ac:structured-macro ac:name="tip"><ac:rich-text-body><p>Hi</p>'
        "</ac:rich-text-body></ac:structured-macro>"
    )
    assert to_markdown(storage) == "> [!TIP]\n>\n> Hi\n"


def test_md_page_links() -> None:
    storage = (
        '<p><ac:link><ri:page ri:content-title="A B" ri:space-key="S"/></ac:link> '
        '<ac:link><ri:page ri:content-title="C"/><ac:plain-text-link-body><![CDATA[see]]>'
        "</ac:plain-text-link-body></ac:link></p>"
    )
    assert to_markdown(storage) == "[A B](confluence:S/A%20B) [see](confluence:C)\n"


def test_md_attachment_image() -> None:
    storage = '<p><ac:image ac:alt="x"><ri:attachment ri:filename="a b.png"/></ac:image></p>'
    assert to_markdown(storage) == "![x](attachment:a%20b.png)\n"


def test_md_tasks() -> None:
    storage = (
        "<ac:task-list><ac:task><ac:task-id>1</ac:task-id><ac:task-status>complete"
        "</ac:task-status><ac:task-body>a</ac:task-body></ac:task></ac:task-list>"
    )
    assert to_markdown(storage) == "- [x] a\n"


def test_md_unknown_block_macro_on_own_paragraph() -> None:
    storage = '<p>a</p><ac:structured-macro ac:name="toc"/><p>b</p>'
    assert to_markdown(storage) == 'a\n\n<ac:structured-macro ac:name="toc"/>\n\nb\n'


def test_md_unknown_inline_macro_stays_inline() -> None:
    storage = '<p>x <ac:structured-macro ac:name="status"/> y</p>'
    assert to_markdown(storage) == 'x <ac:structured-macro ac:name="status"/> y\n'


def test_md_literal_angle_bracket_escaped() -> None:
    assert to_markdown("<p>a &lt;tag&gt; &amp;lt;</p>") == "a &lt;tag> &amp;lt;\n"


def test_md_empty() -> None:
    assert to_markdown("") == "\n"
````

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_converter.py -q`
Expected: collection error: `ModuleNotFoundError: No module named 'confluence_mcp.converter.to_markdown'`.

- [ ] **Step 3: Implement storage → Markdown**

`src/confluence_mcp/converter/to_markdown.py`:

```python
"""Confluence storage XHTML → Markdown."""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import quote

from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString
from markdownify import MarkdownConverter

from .macros import PANEL_MACROS, Element, cdata_text, find_elements

RAW_TOKEN = "XCFRAW{:04d}X"
_RAW_TOKEN_RE = re.compile(r"XCFRAW(\d{4})X")
_IGNORED_MACRO_ATTRS = {"ac:name", "ac:schema-version", "ac:macro-id"}
_BLOCK_IN_CELL = (
    "ul",
    "ol",
    "pre",
    "blockquote",
    "table",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
)


def _macro_known_attrs(el: Element) -> bool:
    return set(el.attrs) <= _IGNORED_MACRO_ATTRS


def _code_macro(el: Element) -> str | None:
    if not _macro_known_attrs(el):
        return None
    language = ""
    body: str | None = None
    for child in el.children():
        if child.name == "ac:parameter" and child.attrs.get("ac:name") == "language":
            language = child.inner.strip()
        elif child.name == "ac:plain-text-body" and body is None:
            body = cdata_text(child.inner)
        else:
            return None
    cls = f' class="language-{html.escape(language)}"' if language else ""
    return f"<pre><code{cls}>{html.escape(body or '')}</code></pre>"


def _panel_macro(el: Element, raws: list[str]) -> str | None:
    children = el.children()
    if not _macro_known_attrs(el) or len(children) != 1 or children[0].name != "ac:rich-text-body":
        return None
    kind = el.attrs["ac:name"].upper()
    return f"<blockquote><p>[!{kind}]</p>{_prepare(children[0].inner, raws)}</blockquote>"


def _link(el: Element, raws: list[str]) -> str | None:
    if el.attrs:
        return None
    page: Element | None = None
    text: str | None = None
    for child in el.children():
        if child.name == "ri:page" and page is None:
            page = child
        elif child.name == "ac:plain-text-link-body" and text is None:
            text = html.escape(cdata_text(child.inner))
        elif child.name == "ac:link-body" and text is None:
            text = _prepare(child.inner, raws)
        else:
            return None
    if page is None or not set(page.attrs) <= {"ri:content-title", "ri:space-key"}:
        return None
    title = html.unescape(page.attrs.get("ri:content-title", ""))
    space = page.attrs.get("ri:space-key")
    if not title or (space is None and "/" in title):
        return None
    target = f"{space}/{title}" if space else title
    href = (
        "confluence:" + quote(target, safe="/") if space else "confluence:" + quote(title, safe="")
    )
    return f'<a href="{html.escape(href)}">{text if text is not None else html.escape(title)}</a>'


def _image(el: Element) -> str | None:
    if not set(el.attrs) <= {"ac:alt"}:
        return None
    children = el.children()
    if len(children) != 1:
        return None
    ref = children[0]
    if ref.name == "ri:attachment" and set(ref.attrs) == {"ri:filename"}:
        src = "attachment:" + quote(html.unescape(ref.attrs["ri:filename"]), safe="")
    elif ref.name == "ri:url" and set(ref.attrs) == {"ri:value"}:
        src = html.unescape(ref.attrs["ri:value"])
    else:
        return None
    alt = html.unescape(el.attrs.get("ac:alt", ""))
    return f'<img src="{html.escape(src)}" alt="{html.escape(alt)}"/>'


def _task_list(el: Element, raws: list[str]) -> str | None:
    if el.attrs:
        return None
    items: list[str] = []
    for task in el.children():
        if task.name != "ac:task":
            return None
        status, body = None, None
        for part in task.children():
            if part.name == "ac:task-status":
                status = part.inner.strip()
            elif part.name == "ac:task-body":
                body = _prepare(part.inner, raws)
            elif part.name != "ac:task-id":
                return None
        if status not in ("complete", "incomplete") or body is None:
            return None
        items.append(f"<li>[{'x' if status == 'complete' else ' '}] {body}</li>")
    return "<ul>" + "".join(items) + "</ul>"


def _convert_known(el: Element, raws: list[str]) -> str | None:
    if el.name == "ac:structured-macro":
        name = el.attrs.get("ac:name", "")
        if name == "code":
            return _code_macro(el)
        if name in PANEL_MACROS:
            return _panel_macro(el, raws)
        return None
    if el.name == "ac:link":
        return _link(el, raws)
    if el.name == "ac:image":
        return _image(el)
    if el.name == "ac:task-list":
        return _task_list(el, raws)
    return None


def _prepare(storage: str, raws: list[str]) -> str:
    """Replace ac:/ri: elements with plain HTML (known) or raw tokens (unknown)."""
    out: list[str] = []
    pos = 0
    for el in find_elements(storage):
        out.append(storage[pos : el.start])
        converted = _convert_known(el, raws)
        if converted is None:
            raws.append(el.text)
            converted = RAW_TOKEN.format(len(raws) - 1)
        out.append(converted)
        pos = el.end
    out.append(storage[pos:])
    return "".join(out)


def _is_complex_table(table: Tag) -> bool:
    if table.find("table"):
        return True
    for cell in table.find_all(["td", "th"]):
        if cell.get("rowspan", "1") != "1" or cell.get("colspan", "1") != "1":
            return True
        if cell.find(_BLOCK_IN_CELL) or len(cell.find_all("p")) > 1:
            return True
    return False


_ENTITY_LIKE_RE = re.compile(r"&(?=#?\w+;)")


# The markdownify type stub does not declare escape/convert_table.
_MarkdownConverterBase: Any = MarkdownConverter


class _Converter(_MarkdownConverterBase):  # type: ignore[misc]
    def escape(self, text: str, parent_tags: set[str]) -> str:
        # Literal '<' and entity-like '&' would otherwise be read back as HTML.
        text = str(super().escape(text, parent_tags))
        return _ENTITY_LIKE_RE.sub("&amp;", text).replace("<", "&lt;")

    def convert_table(self, el: Tag, text: str, parent_tags: set[str]) -> str:
        if _is_complex_table(el):
            return "\n\n" + str(el) + "\n\n"
        return str(super().convert_table(el, text, parent_tags))


def _code_language(el: Tag) -> str:
    code = el.find("code")
    for cls in (code.get("class") or []) if isinstance(code, Tag) else []:
        if cls.startswith("language-"):
            return str(cls[len("language-") :])
    return ""


_OPTIONS: dict[str, Any] = {
    "heading_style": "ATX",
    "bullets": "-",
    "code_language_callback": _code_language,
    "escape_misc": False,
}


def _split_top_level(soup: BeautifulSoup, node: NavigableString) -> None:
    """Give each top-level raw token (and any stray text) its own paragraph."""
    for part in re.split(r"(XCFRAW\d{4}X)", str(node)):
        if part.strip():
            p = soup.new_tag("p")
            p.string = part.strip()
            node.insert_before(p)
    node.extract()


def to_markdown(storage: str) -> str:
    """Convert Confluence storage XHTML to Markdown.

    Known constructs become Markdown; any other ac:/ri: element is kept as raw
    XHTML (on its own line when block-level) so that ``to_storage`` restores it.
    """
    raws: list[str] = []
    prepared = _prepare(storage, raws)
    soup = BeautifulSoup(prepared, "html.parser")
    for node in list(soup.find_all(string=_RAW_TOKEN_RE)):
        if node.parent is soup and isinstance(node, NavigableString):
            _split_top_level(soup, node)
    markdown = _Converter(**_OPTIONS).convert_soup(soup)
    markdown = _RAW_TOKEN_RE.sub(lambda m: raws[int(m.group(1))], markdown)
    return re.sub(r"\n{3,}", "\n\n", markdown).strip() + "\n"
```

- [ ] **Step 4: Run tests and checks**

Run: `.venv/bin/python -m pytest tests/test_converter.py -q && .venv/bin/ruff format src tests && .venv/bin/ruff check src tests && .venv/bin/mypy src`
Expected: `10 passed`; ruff and mypy clean.

- [ ] **Step 5: Commit**

```bash
git add src/confluence_mcp/converter/to_markdown.py tests/test_converter.py
git commit -m "feat: convert Confluence storage format to Markdown

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 5: Markdown → storage, round-trip fixtures

`to_storage` first swaps raw `ac:`/`ri:` elements outside code for tokens. It then inserts a separator paragraph between adjacent blockquotes, because Python-Markdown would merge them. It renders with `markdown` (`tables`, `fenced_code`, `sane_lists`) and post-processes the HTML with BeautifulSoup:
- `<pre><code>` → code macro
- tables → a single `<tbody>`
- `confluence:` links → `ac:link`
- images → `ac:image`
- `[ ]`/`[x]` lists → `ac:task-list` (task ids numbered 1..N across the document)
- `[!TYPE]` blockquotes → panels

Finally the tokens are restored. Paragraphs that contain only raw tokens are unwrapped.

**Files:**
- Create: `src/confluence_mcp/converter/to_storage.py`, `src/confluence_mcp/converter/__init__.py`
- Create: `tests/xml_utils.py` (XML normaliser for comparisons), fixtures `tests/fixtures/lossy/cell_paragraphs.expected.xml`, `tests/fixtures/lossy/cell_paragraphs.xml`, `tests/fixtures/roundtrip/basic_text.xml`, `tests/fixtures/roundtrip/macros_known.xml`, `tests/fixtures/roundtrip/macros_unknown.xml`
- Modify: `tests/test_converter.py` (replace with the full suite below)

**Interfaces:**
- Consumes: Task 3 helpers; `to_markdown` (Task 4).
- Produces: `to_storage(md: str) -> str`; package API `from confluence_mcp.converter import inventory, to_markdown, to_storage`; test helper `tests.xml_utils.normalize(storage) -> str` (sorted attributes, `ac:macro-id`/`ac:schema-version` dropped, whitespace collapsed, CDATA kept).
- Guarantees (tested): for every fixture in `tests/fixtures/roundtrip/`, `normalize(to_storage(to_markdown(s))) == normalize(s)` and `to_markdown(to_storage(md)) == md`. Each `tests/fixtures/lossy/X.xml` round-trips to `X.expected.xml`. The macro inventory never shrinks for any fixture.

- [ ] **Step 1: Add the fixtures, the normaliser and the full converter test suite**

`tests/fixtures/lossy/cell_paragraphs.expected.xml`:

```xml
<table><tbody><tr><th>H</th><th>V</th></tr><tr><td>a</td><td>1</td></tr></tbody></table>
<ac:structured-macro ac:name="code"><ac:plain-text-body><![CDATA[plain pre]]></ac:plain-text-body></ac:structured-macro>
<p>Link body <ac:link><ri:page ri:content-title="P"/><ac:plain-text-link-body><![CDATA[plain]]></ac:plain-text-link-body></ac:link></p>
```

`tests/fixtures/lossy/cell_paragraphs.xml`:

```xml
<table class="wrapped"><colgroup><col/><col/></colgroup><tbody><tr><th><p>H</p></th><th><p>V</p></th></tr><tr><td><p>a</p></td><td><p>1</p></td></tr></tbody></table>
<pre>plain pre</pre>
<p>Link body <ac:link><ri:page ri:content-title="P"/><ac:link-body>plain</ac:link-body></ac:link></p>
```

`tests/fixtures/roundtrip/basic_text.xml`:

```xml
<h1>Release notes</h1>
<p>Plain <strong>bold</strong>, <em>italic</em>, <code>inline_code</code> and a <a href="https://example.com/a?b=1&amp;c=2">link</a>.</p>
<p>Symbols: snake_case, 2 * 3, a &lt; b, AT&amp;T, &amp;lt; stays literal.</p>
<h2>Lists</h2>
<ul><li>one</li><li>two</li></ul>
<ol><li>first</li><li>second</li></ol>
<hr/>
<blockquote><p>Quoted text</p></blockquote>
```

`tests/fixtures/roundtrip/macros_known.xml`:

```xml
<ac:structured-macro ac:name="code" ac:schema-version="1" ac:macro-id="0a1b"><ac:parameter ac:name="language">python</ac:parameter><ac:plain-text-body><![CDATA[def f(a, b):
    return a < b  # ]]]]><![CDATA[> tricky]]></ac:plain-text-body></ac:structured-macro>
<ac:structured-macro ac:name="info" ac:schema-version="1"><ac:rich-text-body><p>Read this first.</p></ac:rich-text-body></ac:structured-macro>
<ac:structured-macro ac:name="warning" ac:schema-version="1"><ac:rich-text-body><p>Danger</p><ul><li>item</li></ul></ac:rich-text-body></ac:structured-macro>
<p>See <ac:link><ri:page ri:content-title="Other Page" ri:space-key="DOC"/><ac:plain-text-link-body><![CDATA[the docs]]></ac:plain-text-link-body></ac:link> and <ac:link><ri:page ri:content-title="Same (space) page"/></ac:link>.</p>
<p><ac:image ac:alt="diagram"><ri:attachment ri:filename="arch diagram.png"/></ac:image></p>
<p><ac:image><ri:url ri:value="https://example.com/x.png"/></ac:image></p>
<ac:task-list><ac:task><ac:task-id>1</ac:task-id><ac:task-status>complete</ac:task-status><ac:task-body>done it</ac:task-body></ac:task><ac:task><ac:task-id>2</ac:task-id><ac:task-status>incomplete</ac:task-status><ac:task-body>todo <strong>soon</strong></ac:task-body></ac:task></ac:task-list>
<table><tbody><tr><th>Name</th><th>Value</th></tr><tr><td>a</td><td>1</td></tr></tbody></table>
```

`tests/fixtures/roundtrip/macros_unknown.xml`:

```xml
<ac:structured-macro ac:name="toc" ac:schema-version="1" ac:macro-id="t1"/>
<p>Status: <ac:structured-macro ac:name="status" ac:schema-version="1"><ac:parameter ac:name="colour">Green</ac:parameter><ac:parameter ac:name="title">DONE</ac:parameter></ac:structured-macro> today.</p>
<ac:structured-macro ac:name="jira" ac:schema-version="1"><ac:parameter ac:name="server">JIRA</ac:parameter><ac:parameter ac:name="jqlQuery">project = SEC AND status = Open</ac:parameter></ac:structured-macro>
<ac:structured-macro ac:name="info" ac:schema-version="1"><ac:rich-text-body><p>Tracked in <ac:structured-macro ac:name="jira" ac:schema-version="1"><ac:parameter ac:name="key">SEC-1</ac:parameter></ac:structured-macro></p></ac:rich-text-body></ac:structured-macro>
<ac:structured-macro ac:name="expand" ac:schema-version="1"><ac:parameter ac:name="title">Details</ac:parameter><ac:rich-text-body><p>Hidden &nbsp;text</p><ac:structured-macro ac:name="expand"><ac:rich-text-body><p>nested same-name</p></ac:rich-text-body></ac:structured-macro></ac:rich-text-body></ac:structured-macro>
<ac:structured-macro ac:name="code" ac:schema-version="1"><ac:parameter ac:name="title">With title</ac:parameter><ac:plain-text-body><![CDATA[x = 1]]></ac:plain-text-body></ac:structured-macro>
<ac:structured-macro ac:name="note" ac:schema-version="1"><ac:parameter ac:name="title">Titled panel</ac:parameter><ac:rich-text-body><p>body</p></ac:rich-text-body></ac:structured-macro>
<p>Ping <ac:link><ri:user ri:userkey="8a7f"/></ac:link> about <ac:link><ri:page ri:content-title="A/B"/></ac:link>.</p>
<table><tbody><tr><th colspan="2">Merged</th></tr><tr><td>1</td><td><ul><li>list in cell</li></ul></td></tr></tbody></table>
```

`tests/xml_utils.py`:

```python
"""Normalise storage XHTML for equality checks in tests."""

from __future__ import annotations

import html.entities
import re

from lxml import etree

_WRAP = (
    '<root xmlns:ac="http://atlassian.com/content" '
    'xmlns:ri="http://atlassian.com/resource/identifier">{}</root>'
)
_XML_ENTITIES = {"amp", "lt", "gt", "quot", "apos"}
_DROP_ATTRS = {
    "{http://atlassian.com/content}macro-id",
    "{http://atlassian.com/content}schema-version",
}


def _numeric_entities(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        name = m.group(1)
        if name in _XML_ENTITIES or name not in html.entities.name2codepoint:
            return m.group(0)
        return f"&#{html.entities.name2codepoint[name]};"

    return re.sub(r"&(\w+);", repl, text)


def normalize(storage: str) -> str:
    """Canonical form: attributes sorted, macro-id/schema-version dropped, whitespace
    between elements removed, runs of whitespace in text collapsed (CDATA kept)."""
    parser = etree.XMLParser(strip_cdata=False, remove_blank_text=True)
    root = etree.fromstring(_WRAP.format(_numeric_entities(storage)), parser)
    for el in root.iter():
        for attr in _DROP_ATTRS & set(el.attrib):
            del el.attrib[attr]
        attrs = sorted(el.attrib.items())
        el.attrib.clear()
        el.attrib.update(attrs)
        in_cdata = el.tag == "{http://atlassian.com/content}plain-text-body"
        if not in_cdata:
            if el.text is not None:
                el.text = re.sub(r"\s+", " ", el.text).strip() or None
        if el.tail is not None:
            el.tail = re.sub(r"\s+", " ", el.tail).strip() or None
    return etree.tostring(root, encoding="unicode")
```

`tests/test_converter.py`:

````python
from __future__ import annotations

from pathlib import Path

import pytest

from confluence_mcp.converter import inventory, to_markdown, to_storage
from tests.xml_utils import normalize

FIXTURES = Path(__file__).parent / "fixtures"
ROUNDTRIP = sorted((FIXTURES / "roundtrip").glob("*.xml"))
LOSSY = sorted(p for p in (FIXTURES / "lossy").glob("*.xml") if ".expected" not in p.name)


@pytest.mark.parametrize("path", ROUNDTRIP, ids=lambda p: p.stem)
def test_roundtrip_fixture(path: Path) -> None:
    storage = path.read_text()
    assert normalize(to_storage(to_markdown(storage))) == normalize(storage)


@pytest.mark.parametrize("path", LOSSY, ids=lambda p: p.stem)
def test_lossy_fixture(path: Path) -> None:
    expected = path.with_name(path.stem + ".expected.xml").read_text()
    assert normalize(to_storage(to_markdown(path.read_text()))) == normalize(expected)


@pytest.mark.parametrize("path", ROUNDTRIP + LOSSY, ids=lambda p: p.stem)
def test_roundtrip_never_loses_macros(path: Path) -> None:
    storage = path.read_text()
    assert not inventory(storage) - inventory(to_storage(to_markdown(storage)))


@pytest.mark.parametrize("path", ROUNDTRIP, ids=lambda p: p.stem)
def test_markdown_is_stable(path: Path) -> None:
    md = to_markdown(path.read_text())
    assert to_markdown(to_storage(md)) == md


# ── storage → Markdown ────────────────────────────────────────────────────────


def test_md_headings_and_inline() -> None:
    md = to_markdown("<h2>T</h2><p><strong>b</strong> <em>i</em> <code>c</code></p>")
    assert md == "## T\n\n**b** *i* `c`\n"


def test_md_code_macro_becomes_fence() -> None:
    storage = (
        '<ac:structured-macro ac:name="code"><ac:parameter ac:name="language">sql'
        "</ac:parameter><ac:plain-text-body><![CDATA[SELECT 1 < 2]]></ac:plain-text-body>"
        "</ac:structured-macro>"
    )
    assert to_markdown(storage) == "```sql\nSELECT 1 < 2\n```\n"


def test_md_panel_becomes_callout() -> None:
    storage = (
        '<ac:structured-macro ac:name="tip"><ac:rich-text-body><p>Hi</p>'
        "</ac:rich-text-body></ac:structured-macro>"
    )
    assert to_markdown(storage) == "> [!TIP]\n>\n> Hi\n"


def test_md_page_links() -> None:
    storage = (
        '<p><ac:link><ri:page ri:content-title="A B" ri:space-key="S"/></ac:link> '
        '<ac:link><ri:page ri:content-title="C"/><ac:plain-text-link-body><![CDATA[see]]>'
        "</ac:plain-text-link-body></ac:link></p>"
    )
    assert to_markdown(storage) == "[A B](confluence:S/A%20B) [see](confluence:C)\n"


def test_md_attachment_image() -> None:
    storage = '<p><ac:image ac:alt="x"><ri:attachment ri:filename="a b.png"/></ac:image></p>'
    assert to_markdown(storage) == "![x](attachment:a%20b.png)\n"


def test_md_tasks() -> None:
    storage = (
        "<ac:task-list><ac:task><ac:task-id>1</ac:task-id><ac:task-status>complete"
        "</ac:task-status><ac:task-body>a</ac:task-body></ac:task></ac:task-list>"
    )
    assert to_markdown(storage) == "- [x] a\n"


def test_md_unknown_block_macro_on_own_paragraph() -> None:
    storage = '<p>a</p><ac:structured-macro ac:name="toc"/><p>b</p>'
    assert to_markdown(storage) == 'a\n\n<ac:structured-macro ac:name="toc"/>\n\nb\n'


def test_md_unknown_inline_macro_stays_inline() -> None:
    storage = '<p>x <ac:structured-macro ac:name="status"/> y</p>'
    assert to_markdown(storage) == 'x <ac:structured-macro ac:name="status"/> y\n'


def test_md_literal_angle_bracket_escaped() -> None:
    assert to_markdown("<p>a &lt;tag&gt; &amp;lt;</p>") == "a &lt;tag> &amp;lt;\n"


def test_md_empty() -> None:
    assert to_markdown("") == "\n"


# ── Markdown → storage ────────────────────────────────────────────────────────


def test_st_fence_becomes_code_macro() -> None:
    assert normalize(to_storage("```js\nlet a = '<ac:x/>';\n```\n")) == normalize(
        '<ac:structured-macro ac:name="code"><ac:parameter ac:name="language">js'
        "</ac:parameter><ac:plain-text-body><![CDATA[let a = '<ac:x/>';]]>"
        "</ac:plain-text-body></ac:structured-macro>"
    )


def test_st_callout_same_line_body() -> None:
    assert normalize(to_storage("> [!warning] Careful\n> now\n")) == normalize(
        '<ac:structured-macro ac:name="warning"><ac:rich-text-body><p>Careful now</p>'
        "</ac:rich-text-body></ac:structured-macro>"
    )


def test_st_plain_blockquote_stays_blockquote() -> None:
    assert normalize(to_storage("> just a quote\n")) == normalize(
        "<blockquote><p>just a quote</p></blockquote>"
    )


def test_st_task_list_ids_sequential_across_lists() -> None:
    out = to_storage("- [ ] a\n- [X] b\n\ntext\n\n- [ ] c\n")
    assert out.count("<ac:task-id>") == 3
    assert "<ac:task-id>3</ac:task-id>" in out
    assert "<ac:task-status>complete</ac:task-status><ac:task-body>b" in out


def test_st_regular_list_not_task_list() -> None:
    assert "<ac:task-list>" not in to_storage("- a\n- [ ] b\n")


def test_st_gfm_table_has_single_tbody() -> None:
    out = normalize(to_storage("| h |\n|---|\n| v |\n"))
    assert out == normalize("<table><tbody><tr><th>h</th></tr><tr><td>v</td></tr></tbody></table>")


def test_st_links_and_images() -> None:
    out = to_storage("[Doc](confluence:S/A%20B) [x](https://e.com) ![i](attachment:f.png)\n")
    assert normalize(out) == normalize(
        '<p><ac:link><ri:page ri:content-title="A B" ri:space-key="S"/>'
        "<ac:plain-text-link-body><![CDATA[Doc]]></ac:plain-text-link-body></ac:link> "
        '<a href="https://e.com">x</a> '
        '<ac:image ac:alt="i"><ri:attachment ri:filename="f.png"/></ac:image></p>'
    )


def test_st_raw_macro_in_code_span_is_text() -> None:
    assert to_storage("use `<ac:link>` here\n") == "<p>use <code>&lt;ac:link&gt;</code> here</p>"


def test_st_consecutive_callouts_stay_separate() -> None:
    out = to_storage("> [!INFO]\n>\n> a\n\n> [!NOTE]\n>\n> b\n")
    assert out.count("<ac:structured-macro") == 2
    assert "[!NOTE]" not in out


def test_st_adjacent_raw_blocks_not_wrapped_in_p() -> None:
    md = '<ac:structured-macro ac:name="toc"/>\n<ac:structured-macro ac:name="jira"/>\n'
    assert to_storage(md) == (
        '<ac:structured-macro ac:name="toc"/>\n<ac:structured-macro ac:name="jira"/>'
    )
````

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_converter.py -q`
Expected: collection error: `ImportError: cannot import name 'inventory' from 'confluence_mcp.converter'` (or `ModuleNotFoundError` for `to_storage`).

- [ ] **Step 3: Implement Markdown → storage and the package API**

`src/confluence_mcp/converter/to_storage.py`:

```python
"""Markdown → Confluence storage XHTML."""

from __future__ import annotations

import html
import re
from urllib.parse import unquote

import markdown
from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString

from .macros import PANEL_MACROS, cdata, find_elements

_RAW_TOKEN = "XCFRAW{:04d}X"
_RAW_TOKEN_RE = re.compile(r"XCFRAW(\d{4})X")
_GEN_TOKEN = "XCFGEN{:04d}X"
_GEN_TOKEN_RE = re.compile(r"XCFGEN(\d{4})X")
_CALLOUT_RE = re.compile(r"^\s*\[!(" + "|".join(PANEL_MACROS) + r")\]\s*", re.IGNORECASE)
_TASK_RE = re.compile(r"^\[([ xX])\]\s+")
_EXTENSIONS = ["tables", "fenced_code", "sane_lists"]
_SEPARATOR = "XCFSEPX"
_QUOTE_GAP_RE = re.compile(r"(^>[^\n]*\n)(?:[ \t]*\n)+(?=>)", re.MULTILINE)


def _protect_raw(md: str) -> tuple[str, list[str]]:
    """Swap raw ac:/ri: elements (outside code) for tokens before Markdown runs."""
    raws: list[str] = []
    out: list[str] = []
    pos = 0
    for el in find_elements(md, markdown=True):
        out.append(md[pos : el.start])
        raws.append(el.text)
        out.append(_RAW_TOKEN.format(len(raws) - 1))
        pos = el.end
    out.append(md[pos:])
    return "".join(out), raws


def _inner_html(tag: Tag) -> str:
    return "".join(str(c) for c in tag.contents)


def _macro(name: str, body: str, params: dict[str, str] | None = None) -> str:
    ps = "".join(
        f'<ac:parameter ac:name="{k}">{html.escape(v, quote=False)}</ac:parameter>'
        for k, v in (params or {}).items()
    )
    return (
        f'<ac:structured-macro ac:name="{name}" ac:schema-version="1">'
        f"{ps}{body}</ac:structured-macro>"
    )


class _Builder:
    def __init__(self, soup: BeautifulSoup) -> None:
        self.soup = soup
        self.generated: list[str] = []

    def replace(self, tag: Tag, storage: str) -> None:
        self.generated.append(storage)
        tag.replace_with(NavigableString(_GEN_TOKEN.format(len(self.generated) - 1)))

    def code_blocks(self) -> None:
        for pre in self.soup.find_all("pre"):
            code = pre.find("code")
            if not isinstance(code, Tag):
                continue
            lang = next((c[9:] for c in code.get("class") or [] if c.startswith("language-")), "")
            text = code.get_text()
            text = text[:-1] if text.endswith("\n") else text
            body = f"<ac:plain-text-body>{cdata(text)}</ac:plain-text-body>"
            self.replace(pre, _macro("code", body, {"language": lang} if lang else None))

    def links(self) -> None:
        for a in self.soup.find_all("a", href=re.compile(r"^confluence:")):
            target = str(a["href"])[len("confluence:") :]
            space, sep, title = target.partition("/") if "/" in target else ("", "", target)
            title = unquote(title)
            space_attr = f' ri:space-key="{html.escape(unquote(space))}"' if sep else ""
            page = f'<ri:page ri:content-title="{html.escape(title)}"{space_attr}/>'
            text = a.get_text()
            if text == title and not a.find(True):
                body = ""
            elif a.find(True):
                body = f"<ac:link-body>{_inner_html(a)}</ac:link-body>"
            else:
                body = f"<ac:plain-text-link-body>{cdata(text)}</ac:plain-text-link-body>"
            self.replace(a, f"<ac:link>{page}{body}</ac:link>")

    def images(self) -> None:
        for img in self.soup.find_all("img"):
            src = str(img.get("src", ""))
            if src.startswith("attachment:"):
                ref = f'<ri:attachment ri:filename="{html.escape(unquote(src[11:]))}"/>'
            else:
                ref = f'<ri:url ri:value="{html.escape(src)}"/>'
            alt = str(img.get("alt", ""))
            alt_attr = f' ac:alt="{html.escape(alt)}"' if alt else ""
            self.replace(img, f"<ac:image{alt_attr}>{ref}</ac:image>")

    def task_lists(self) -> None:
        task_id = 0
        for ul in self.soup.find_all("ul"):
            items = ul.find_all("li", recursive=False)
            if not items or not all(_TASK_RE.match(li.get_text()) for li in items):
                continue
            tasks: list[str] = []
            for li in items:
                paragraph = li.find("p") if isinstance(li.contents[0], Tag) else None
                holder = paragraph if isinstance(paragraph, Tag) else li
                first = holder.contents[0] if holder.contents else None
                if not isinstance(first, NavigableString):
                    break
                m = _TASK_RE.match(str(first))
                if not m:
                    break
                first.replace_with(str(first)[m.end() :])
                task_id += 1
                status = "incomplete" if m.group(1) == " " else "complete"
                tasks.append(
                    f"<ac:task><ac:task-id>{task_id}</ac:task-id>"
                    f"<ac:task-status>{status}</ac:task-status>"
                    f"<ac:task-body>{_inner_html(holder).strip()}</ac:task-body></ac:task>"
                )
            else:
                self.replace(ul, "<ac:task-list>" + "".join(tasks) + "</ac:task-list>")

    def callouts(self) -> None:
        for bq in reversed(self.soup.find_all("blockquote")):
            first = bq.find(True)
            if not isinstance(first, Tag) or first.name != "p" or not first.contents:
                continue
            lead = first.contents[0]
            m = _CALLOUT_RE.match(str(lead)) if isinstance(lead, NavigableString) else None
            if not m:
                continue
            lead.replace_with(str(lead)[m.end() :])
            if not first.get_text(strip=True) and not first.find(True):
                first.decompose()
            body = f"<ac:rich-text-body>{_inner_html(bq).strip()}</ac:rich-text-body>"
            self.replace(bq, _macro(m.group(1).lower(), body))

    def tables(self) -> None:
        for table in self.soup.find_all("table"):
            rows = table.find_all("tr")
            for section in table.find_all(["thead", "tbody"]):
                section.unwrap()
            tbody = self.soup.new_tag("tbody")
            for row in rows:
                tbody.append(row.extract())
            table.clear()
            table.append(tbody)


def _restore(text: str, generated: list[str], raws: list[str]) -> str:
    while _GEN_TOKEN_RE.search(text):
        text = _GEN_TOKEN_RE.sub(lambda m: generated[int(m.group(1))], text)
    text = re.sub(r"<p>((?:\s*XCFRAW\d{4}X)+)\s*</p>", lambda m: m.group(1).strip(), text)
    return _RAW_TOKEN_RE.sub(lambda m: raws[int(m.group(1))], text)


def to_storage(md: str) -> str:
    """Convert Markdown (as produced by ``to_markdown``) to Confluence storage XHTML."""
    protected, raws = _protect_raw(md)
    # Python-Markdown joins '> a' + blank line + '> b' into one blockquote; CommonMark
    # (and our callouts) treat them as two, so put a separator paragraph between them.
    protected = _QUOTE_GAP_RE.sub(r"\1\n" + _SEPARATOR + "\n\n", protected)
    rendered = markdown.markdown(protected, extensions=_EXTENSIONS, output_format="xhtml")
    soup = BeautifulSoup(rendered, "html.parser")
    builder = _Builder(soup)
    builder.code_blocks()
    builder.tables()
    builder.links()
    builder.images()
    builder.task_lists()
    builder.callouts()
    text = re.sub(r"<p>" + _SEPARATOR + r"</p>\n?", "", str(soup))
    return _restore(text, builder.generated, raws).strip()
```

`src/confluence_mcp/converter/__init__.py`:

```python
"""Conversion between Confluence storage XHTML and Markdown."""

from .macros import inventory
from .to_markdown import to_markdown
from .to_storage import to_storage

__all__ = ["inventory", "to_markdown", "to_storage"]
```

- [ ] **Step 4: Run tests and checks**

Run: `.venv/bin/python -m pytest tests -q && .venv/bin/ruff format src tests && .venv/bin/ruff check src tests && .venv/bin/mypy src`
Expected: all tests pass (`39` across `test_converter.py` and `test_macros.py`); ruff and mypy clean.

- [ ] **Step 5: Commit**

```bash
git add src/confluence_mcp/converter tests
git commit -m "feat: convert Markdown to Confluence storage format with round-trip fixtures

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 6: Content read/create/update with safeguards

**Files:**
- Create: `src/confluence_mcp/content.py`
- Test: `tests/test_content.py` (also defines the `page(version=3, storage="<p>old</p>", **extra)` JSON builder reused by later tool tests)

**Interfaces:**
- Consumes: `ConfluenceClient` (Task 2), `inventory/to_markdown/to_storage` (Task 5), exceptions (Task 1).
- Produces:
  - `Format = Literal["markdown", "storage"]`, `ContentType = Literal["page", "blogpost", "comment"]`, `EXPAND_READ`.
  - `to_storage_body(body, fmt) -> str`, `render_body(storage, fmt) -> str`, `web_url(client, content) -> str | None`.
  - `compact(client, content, fmt=None) -> dict` → keys `id, type, title, space{key,name}, version{number,when,by,message}, url`, plus `labels` / `ancestors` when present, plus `format`/`body` when `fmt` is given.
  - `async get_content(client, content_id, fmt, *, version=None)`, `async find_by_title(client, space_key, title, fmt, type_="page")` (raises `NotFoundError`), `async create_content(client, type_, space_key, title, body, fmt, parent_id=None)`.
  - `async update_content(client, content_id, *, body=None, fmt="markdown", title=None, expected_version=None, allow_macro_loss=False, version_comment=None)`: GET → `expected_version` check (`VersionConflictError` with `.current_version`) → convert → macro-loss check (`MacroLossError`) → PUT with version+1 (no `ancestors`).
  - `async restore_version(client, content_id, version)`: historical GET, then `update_content(..., fmt="storage", allow_macro_loss=True, version_comment="Restored version N")`.

- [ ] **Step 1: Write the failing tests**

`tests/test_content.py`:

```python
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from confluence_mcp.client import ConfluenceClient
from confluence_mcp.content import (
    compact,
    create_content,
    find_by_title,
    get_content,
    restore_version,
    update_content,
)
from confluence_mcp.exceptions import MacroLossError, NotFoundError, VersionConflictError
from tests.conftest import BASE

TOC = '<ac:structured-macro ac:name="toc"/>'


def page(version: int = 3, storage: str = "<p>old</p>", **extra: Any) -> dict[str, Any]:
    return {
        "id": "42",
        "type": "page",
        "title": "Home",
        "space": {"key": "DOC", "name": "Docs"},
        "version": {"number": version, "when": "2026-01-01", "by": {"displayName": "Ann"}},
        "body": {"storage": {"value": storage}},
        "_links": {"webui": "/display/DOC/Home"},
        **extra,
    }


def test_compact_shape(client: ConfluenceClient) -> None:
    data = page(
        ancestors=[{"id": "1", "title": "Root"}],
        metadata={"labels": {"results": [{"name": "a"}]}},
    )
    out = compact(client, data, "markdown")
    assert out == {
        "id": "42",
        "type": "page",
        "title": "Home",
        "space": {"key": "DOC", "name": "Docs"},
        "version": {"number": 3, "when": "2026-01-01", "by": "Ann", "message": None},
        "url": f"{BASE}/display/DOC/Home",
        "labels": ["a"],
        "ancestors": [{"id": "1", "title": "Root"}],
        "format": "markdown",
        "body": "old\n",
    }


@respx.mock
async def test_get_content_storage_format(client: ConfluenceClient) -> None:
    route = respx.get(f"{BASE}/rest/api/content/42").mock(
        return_value=httpx.Response(200, json=page())
    )
    out = await get_content(client, "42", "storage")
    assert out["body"] == "<p>old</p>"
    assert "body.storage" in route.calls.last.request.url.params["expand"]


@respx.mock
async def test_get_content_historical(client: ConfluenceClient) -> None:
    route = respx.get(f"{BASE}/rest/api/content/42").mock(
        return_value=httpx.Response(200, json=page(version=1))
    )
    await get_content(client, "42", "markdown", version=1)
    params = route.calls.last.request.url.params
    assert params["status"] == "historical"
    assert params["version"] == "1"


@respx.mock
async def test_find_by_title_not_found(client: ConfluenceClient) -> None:
    respx.get(f"{BASE}/rest/api/content").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    with pytest.raises(NotFoundError, match="Missing"):
        await find_by_title(client, "DOC", "Missing", "markdown")


@respx.mock
async def test_create_converts_markdown_and_sets_parent(client: ConfluenceClient) -> None:
    route = respx.post(f"{BASE}/rest/api/content").mock(
        return_value=httpx.Response(200, json=page(version=1))
    )
    out = await create_content(client, "page", "DOC", "Home", "# Hi", "markdown", parent_id="7")
    sent = json.loads(route.calls.last.request.content)
    assert sent["body"]["storage"] == {"value": "<h1>Hi</h1>", "representation": "storage"}
    assert sent["ancestors"] == [{"id": "7"}]
    assert sent["space"] == {"key": "DOC"}
    assert "body" not in out


@respx.mock
async def test_update_bumps_version(client: ConfluenceClient) -> None:
    respx.get(f"{BASE}/rest/api/content/42").mock(return_value=httpx.Response(200, json=page()))
    put = respx.put(f"{BASE}/rest/api/content/42").mock(
        return_value=httpx.Response(200, json=page(version=4))
    )
    out = await update_content(client, "42", body="new", version_comment="why")
    sent = json.loads(put.calls.last.request.content)
    assert sent["version"] == {"number": 4, "message": "why"}
    assert sent["title"] == "Home"
    assert sent["type"] == "page"
    assert sent["body"]["storage"]["value"] == "<p>new</p>"
    assert "ancestors" not in sent
    assert out["version"]["number"] == 4


@respx.mock
async def test_update_expected_version_mismatch(client: ConfluenceClient) -> None:
    respx.get(f"{BASE}/rest/api/content/42").mock(return_value=httpx.Response(200, json=page()))
    put = respx.put(f"{BASE}/rest/api/content/42")
    with pytest.raises(VersionConflictError) as info:
        await update_content(client, "42", body="x", expected_version=2)
    assert info.value.current_version == 3
    assert not put.called


@respx.mock
async def test_update_409_from_put(client: ConfluenceClient) -> None:
    respx.get(f"{BASE}/rest/api/content/42").mock(return_value=httpx.Response(200, json=page()))
    respx.put(f"{BASE}/rest/api/content/42").mock(
        return_value=httpx.Response(409, json={"message": "Version must be incremented"})
    )
    with pytest.raises(VersionConflictError):
        await update_content(client, "42", body="x", expected_version=3)


@respx.mock
async def test_update_rejects_macro_loss(client: ConfluenceClient) -> None:
    respx.get(f"{BASE}/rest/api/content/42").mock(
        return_value=httpx.Response(200, json=page(storage=f"<p>a</p>{TOC}"))
    )
    put = respx.put(f"{BASE}/rest/api/content/42")
    with pytest.raises(MacroLossError, match="toc×1"):
        await update_content(client, "42", body="only text")
    with pytest.raises(MacroLossError):
        await update_content(client, "42", body="<p>x</p>", fmt="storage")
    assert not put.called


@respx.mock
async def test_update_macro_loss_override(client: ConfluenceClient) -> None:
    respx.get(f"{BASE}/rest/api/content/42").mock(
        return_value=httpx.Response(200, json=page(storage=TOC))
    )
    put = respx.put(f"{BASE}/rest/api/content/42").mock(
        return_value=httpx.Response(200, json=page(version=4))
    )
    await update_content(client, "42", body="gone", allow_macro_loss=True)
    assert put.called


@respx.mock
async def test_update_keeping_raw_macro_passes(client: ConfluenceClient) -> None:
    respx.get(f"{BASE}/rest/api/content/42").mock(
        return_value=httpx.Response(200, json=page(storage=f"<p>a</p>{TOC}"))
    )
    put = respx.put(f"{BASE}/rest/api/content/42").mock(
        return_value=httpx.Response(200, json=page(version=4))
    )
    await update_content(client, "42", body=f"b\n\n{TOC}\n")
    assert TOC in json.loads(put.calls.last.request.content)["body"]["storage"]["value"]


@respx.mock
async def test_title_only_update_keeps_body(client: ConfluenceClient) -> None:
    respx.get(f"{BASE}/rest/api/content/42").mock(
        return_value=httpx.Response(200, json=page(storage=TOC))
    )
    put = respx.put(f"{BASE}/rest/api/content/42").mock(
        return_value=httpx.Response(200, json=page(version=4))
    )
    await update_content(client, "42", title="Renamed")
    sent = json.loads(put.calls.last.request.content)
    assert sent["title"] == "Renamed"
    assert sent["body"]["storage"]["value"] == TOC


@respx.mock
async def test_restore_version(client: ConfluenceClient) -> None:
    def get_side_effect(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("status") == "historical":
            return httpx.Response(200, json=page(version=1, storage="<p>v1</p>"))
        return httpx.Response(200, json=page(version=3, storage=f"<p>v3</p>{TOC}"))

    respx.get(f"{BASE}/rest/api/content/42").mock(side_effect=get_side_effect)
    put = respx.put(f"{BASE}/rest/api/content/42").mock(
        return_value=httpx.Response(200, json=page(version=4))
    )
    await restore_version(client, "42", 1)
    sent = json.loads(put.calls.last.request.content)
    assert sent["body"]["storage"]["value"] == "<p>v1</p>"
    assert sent["version"] == {"number": 4, "message": "Restored version 1"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_content.py -q`
Expected: collection error: `ModuleNotFoundError: No module named 'confluence_mcp.content'`.

- [ ] **Step 3: Implement content logic**

`src/confluence_mcp/content.py`:

```python
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
```

- [ ] **Step 4: Run tests and checks**

Run: `.venv/bin/python -m pytest tests -q && .venv/bin/ruff format src tests && .venv/bin/ruff check src tests && .venv/bin/mypy src`
Expected: all tests pass (`13` new in `test_content.py`); ruff and mypy clean.

- [ ] **Step 5: Commit**

```bash
git add src/confluence_mcp/content.py tests/test_content.py
git commit -m "feat: add content read/create/update with version and macro safeguards

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 7: Tool helpers, page and blog post tools

Tools are module-level `async def name(ctx: Context, ...)` functions, as in bitbucket. FastMCP hides `ctx` from the schema. Docstrings are what the model reads, so keep them as written.

**Files:**
- Create: `src/confluence_mcp/tools/_common.py`, `src/confluence_mcp/tools/pages.py`, `src/confluence_mcp/tools/blogposts.py` (no `tools/__init__.py` yet — Task 10 adds it)
- Test: `tests/test_tools_pages.py`

**Interfaces:**
- Consumes: `content.py` (Task 6), `ConfluenceClient`, `Settings`, `ReadOnlyModeError`, `log_tool_call`.
- Produces:
  - `_common`: `MAX_LIMIT = 100`, `get_client(ctx)`, `get_settings(ctx)`, `require_writable(ctx, tool_name)`, `resolve_space(ctx, space_key) -> str` (falls back to `CONFLUENCE_DEFAULT_SPACE`, else `ValueError`), `page_params(limit, start) -> {"limit","start"}` (clamped), `list_result(data, items) -> {"results","start","limit","size","has_more"}`.
  - Tools: `get_page`, `get_page_children`, `get_page_ancestors`, `create_page`, `update_page`, `delete_page`, `move_page`, `list_blog_posts`, `get_blog_post`, `create_blog_post`, `update_blog_post` (signatures as in the code).

- [ ] **Step 1: Write the failing tests**

`tests/test_tools_pages.py`:

```python
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from confluence_mcp.client import ConfluenceClient
from confluence_mcp.config import Settings
from confluence_mcp.tools.blogposts import create_blog_post, list_blog_posts
from confluence_mcp.tools.pages import (
    create_page,
    delete_page,
    get_page,
    get_page_ancestors,
    get_page_children,
    move_page,
    update_page,
)
from tests.conftest import BASE, make_ctx, make_settings
from tests.test_content import page


@pytest.fixture
def ctx(client: ConfluenceClient, settings: Settings) -> Any:
    return make_ctx(client, settings)


@respx.mock
async def test_get_page_by_id(ctx: Any) -> None:
    respx.get(f"{BASE}/rest/api/content/42").mock(return_value=httpx.Response(200, json=page()))
    out = await get_page(ctx, page_id="42")
    assert out["body"] == "old\n"
    assert out["format"] == "markdown"


@respx.mock
async def test_get_page_by_title_uses_default_space(client: ConfluenceClient) -> None:
    settings = make_settings(confluence_default_space="DOC")
    route = respx.get(f"{BASE}/rest/api/content").mock(
        return_value=httpx.Response(200, json={"results": [page()]})
    )
    await get_page(make_ctx(client, settings), title="Home")
    params = route.calls.last.request.url.params
    assert (params["spaceKey"], params["title"], params["type"]) == ("DOC", "Home", "page")


async def test_get_page_requires_id_or_title(ctx: Any) -> None:
    with pytest.raises(ValueError, match="page_id"):
        await get_page(ctx)


async def test_title_lookup_without_space_fails(ctx: Any) -> None:
    with pytest.raises(ValueError, match="space_key is required"):
        await get_page(ctx, title="Home")


@respx.mock
async def test_children_list_shape(ctx: Any) -> None:
    route = respx.get(f"{BASE}/rest/api/content/42/child/page").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [{"id": "7", "title": "Kid", "_links": {"webui": "/x"}}],
                "start": 0,
                "limit": 25,
                "size": 1,
                "_links": {"next": "/more"},
            },
        )
    )
    out = await get_page_children(ctx, "42", limit=500)
    assert out == {
        "results": [{"id": "7", "title": "Kid", "url": f"{BASE}/x"}],
        "start": 0,
        "limit": 25,
        "size": 1,
        "has_more": True,
    }
    assert route.calls.last.request.url.params["limit"] == "100"


@respx.mock
async def test_ancestors(ctx: Any) -> None:
    respx.get(f"{BASE}/rest/api/content/42").mock(
        return_value=httpx.Response(200, json={"ancestors": [{"id": "1", "title": "Root"}]})
    )
    assert await get_page_ancestors(ctx, "42") == [{"id": "1", "title": "Root"}]


@respx.mock
async def test_create_page(ctx: Any) -> None:
    route = respx.post(f"{BASE}/rest/api/content").mock(
        return_value=httpx.Response(200, json=page(version=1))
    )
    await create_page(ctx, title="T", body="<p>x</p>", space_key="DOC", format="storage")
    sent = json.loads(route.calls.last.request.content)
    assert sent["type"] == "page"
    assert sent["body"]["storage"]["value"] == "<p>x</p>"


@respx.mock
async def test_update_page_passes_safeguards(ctx: Any) -> None:
    respx.get(f"{BASE}/rest/api/content/42").mock(return_value=httpx.Response(200, json=page()))
    route = respx.put(f"{BASE}/rest/api/content/42").mock(
        return_value=httpx.Response(200, json=page(version=4))
    )
    await update_page(ctx, "42", body="new", expected_version=3)
    assert json.loads(route.calls.last.request.content)["version"]["number"] == 4


@respx.mock
async def test_delete_and_move(ctx: Any) -> None:
    respx.delete(f"{BASE}/rest/api/content/42").mock(return_value=httpx.Response(204))
    move = respx.put(f"{BASE}/rest/api/content/42/move/append/9").mock(
        return_value=httpx.Response(200, json={"pageId": 42})
    )
    assert (await delete_page(ctx, "42"))["status"] == "trashed"
    assert (await move_page(ctx, "42", "9"))["parent_id"] == "9"
    assert move.called


@respx.mock
async def test_blog_posts(ctx: Any) -> None:
    search = respx.get(f"{BASE}/rest/api/content/search").mock(
        return_value=httpx.Response(200, json={"results": [page(type="blogpost")], "size": 1})
    )
    create = respx.post(f"{BASE}/rest/api/content").mock(
        return_value=httpx.Response(200, json=page(type="blogpost"))
    )
    listed = await list_blog_posts(ctx, space_key="DOC")
    assert listed["results"][0]["type"] == "blogpost"
    assert search.calls.last.request.url.params["cql"] == (
        'type = blogpost AND space = "DOC" ORDER BY created DESC'
    )
    await create_blog_post(ctx, title="News", body="hi", space_key="DOC")
    assert json.loads(create.calls.last.request.content)["type"] == "blogpost"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_tools_pages.py -q`
Expected: collection error: `ModuleNotFoundError: No module named 'confluence_mcp.tools'`.

- [ ] **Step 3: Implement helpers and tools**

`src/confluence_mcp/tools/_common.py`:

```python
"""Helpers shared by all tool modules."""

from __future__ import annotations

from typing import Any

from fastmcp import Context

from ..client import ConfluenceClient
from ..config import Settings
from ..exceptions import ReadOnlyModeError

MAX_LIMIT = 100


def get_client(ctx: Context) -> ConfluenceClient:
    client: ConfluenceClient = ctx.lifespan_context["client"]
    return client


def get_settings(ctx: Context) -> Settings:
    settings: Settings = ctx.lifespan_context["settings"]
    return settings


def require_writable(ctx: Context, tool_name: str) -> None:
    """Every write tool calls this first, before any HTTP request."""
    if get_settings(ctx).confluence_read_only:
        raise ReadOnlyModeError(tool_name)


def resolve_space(ctx: Context, space_key: str | None) -> str:
    resolved = space_key or get_settings(ctx).confluence_default_space
    if not resolved:
        raise ValueError("space_key is required when CONFLUENCE_DEFAULT_SPACE is not set")
    return resolved


def page_params(limit: int, start: int) -> dict[str, int]:
    return {"limit": max(1, min(limit, MAX_LIMIT)), "start": max(0, start)}


def list_result(data: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    """Uniform shape for paged list results."""
    start = int(data.get("start", 0))
    size = int(data.get("size", len(items)))
    total = data.get("totalSize")
    has_more = "next" in data.get("_links", {}) or (total is not None and start + size < int(total))
    return {
        "results": items,
        "start": start,
        "limit": data.get("limit"),
        "size": size,
        "has_more": has_more,
    }
```

`src/confluence_mcp/tools/pages.py`:

````python
from __future__ import annotations

from typing import Any

from fastmcp import Context

from ..content import Format, create_content, find_by_title, get_content, update_content
from ..logging_setup import log_tool_call
from ._common import get_client, list_result, page_params, require_writable, resolve_space


async def get_page(
    ctx: Context,
    page_id: str | None = None,
    title: str | None = None,
    space_key: str | None = None,
    format: Format = "markdown",
) -> dict[str, Any]:
    """Get a page by id, or by title within a space.

    The body is Markdown by default. Raw <ac:…>/<ri:…> blocks in it are Confluence
    macros that have no Markdown form: keep them unchanged when editing unless you
    intend to change them. Use format="storage" for the exact Confluence XHTML.
    The returned version.number can be passed to update_page as expected_version.
    """
    client = get_client(ctx)
    if page_id:
        async with log_tool_call("get_page", page_id=page_id):
            return await get_content(client, page_id, format)
    if not title:
        raise ValueError("Pass page_id, or title (with space_key or CONFLUENCE_DEFAULT_SPACE)")
    key = resolve_space(ctx, space_key)
    async with log_tool_call("get_page", space=key):
        return await find_by_title(client, key, title, format)


async def get_page_children(
    ctx: Context, page_id: str, limit: int = 25, start: int = 0
) -> dict[str, Any]:
    """List the direct child pages of a page."""
    async with log_tool_call("get_page_children", page_id=page_id):
        client = get_client(ctx)
        data = await client.get(
            f"/rest/api/content/{page_id}/child/page", params=page_params(limit, start)
        )
        items = [
            {
                "id": c.get("id"),
                "title": c.get("title"),
                "url": f"{client.base_url}{c.get('_links', {}).get('webui', '')}",
            }
            for c in data.get("results", [])
        ]
        return list_result(data, items)


async def get_page_ancestors(ctx: Context, page_id: str) -> list[dict[str, Any]]:
    """List a page's ancestors from the space root down to its parent."""
    async with log_tool_call("get_page_ancestors", page_id=page_id):
        data = await get_client(ctx).get(
            f"/rest/api/content/{page_id}", params={"expand": "ancestors"}
        )
        return [{"id": a.get("id"), "title": a.get("title")} for a in data.get("ancestors", [])]


async def create_page(
    ctx: Context,
    title: str,
    body: str,
    space_key: str | None = None,
    parent_id: str | None = None,
    format: Format = "markdown",
) -> dict[str, Any]:
    """Create a page. body is Markdown by default (or storage XHTML with format="storage").

    Markdown extras: ```lang fences → code macro; "> [!INFO]" / [!NOTE] / [!WARNING] /
    [!TIP] callouts → panels; [text](confluence:SPACE/Page%20Title) → page link;
    ![alt](attachment:file.png) → attached image; "- [ ] task" → task list.
    """
    require_writable(ctx, "create_page")
    key = resolve_space(ctx, space_key)
    async with log_tool_call("create_page", space=key):
        return await create_content(get_client(ctx), "page", key, title, body, format, parent_id)


async def update_page(
    ctx: Context,
    page_id: str,
    body: str | None = None,
    title: str | None = None,
    format: Format = "markdown",
    expected_version: int | None = None,
    allow_macro_loss: bool = False,
    version_comment: str | None = None,
) -> dict[str, Any]:
    """Replace a page's body and/or title; the version number is bumped automatically.

    Read the page first and edit its full body — body replaces the whole page.
    Pass expected_version (from get_page) to fail instead of overwriting someone
    else's concurrent edit. The update is rejected if it would drop macros present
    in the current page (keep the raw <ac:…> blocks); set allow_macro_loss=true only
    when removing them is intended. Omit body to only rename.
    """
    require_writable(ctx, "update_page")
    async with log_tool_call("update_page", page_id=page_id):
        return await update_content(
            get_client(ctx),
            page_id,
            body=body,
            fmt=format,
            title=title,
            expected_version=expected_version,
            allow_macro_loss=allow_macro_loss,
            version_comment=version_comment,
        )


async def delete_page(ctx: Context, page_id: str) -> dict[str, Any]:
    """Move a page to the space trash (it can be restored from the trash in Confluence)."""
    require_writable(ctx, "delete_page")
    async with log_tool_call("delete_page", page_id=page_id):
        await get_client(ctx).delete(f"/rest/api/content/{page_id}")
        return {"id": page_id, "status": "trashed"}


async def move_page(ctx: Context, page_id: str, target_parent_id: str) -> dict[str, Any]:
    """Move a page (with its children) under another page in the same space."""
    require_writable(ctx, "move_page")
    async with log_tool_call("move_page", page_id=page_id):
        await get_client(ctx).put(f"/rest/api/content/{page_id}/move/append/{target_parent_id}")
        return {"id": page_id, "parent_id": target_parent_id, "status": "moved"}
````

`src/confluence_mcp/tools/blogposts.py`:

```python
from __future__ import annotations

from typing import Any

from fastmcp import Context

from ..content import Format, compact, create_content, get_content, update_content
from ..logging_setup import log_tool_call
from ._common import get_client, list_result, page_params, require_writable, resolve_space


async def list_blog_posts(
    ctx: Context, space_key: str | None = None, limit: int = 25, start: int = 0
) -> dict[str, Any]:
    """List blog posts in a space, newest first."""
    key = resolve_space(ctx, space_key)
    async with log_tool_call("list_blog_posts", space=key):
        client = get_client(ctx)
        cql = f'type = blogpost AND space = "{key}" ORDER BY created DESC'
        data = await client.get(
            "/rest/api/content/search",
            params={"cql": cql, "expand": "space,version", **page_params(limit, start)},
        )
        return list_result(data, [compact(client, c) for c in data.get("results", [])])


async def get_blog_post(
    ctx: Context, blog_post_id: str, format: Format = "markdown"
) -> dict[str, Any]:
    """Get a blog post. Body format and macro rules are the same as get_page."""
    async with log_tool_call("get_blog_post", page_id=blog_post_id):
        return await get_content(get_client(ctx), blog_post_id, format)


async def create_blog_post(
    ctx: Context,
    title: str,
    body: str,
    space_key: str | None = None,
    format: Format = "markdown",
) -> dict[str, Any]:
    """Create a blog post. body follows the same Markdown rules as create_page."""
    require_writable(ctx, "create_blog_post")
    key = resolve_space(ctx, space_key)
    async with log_tool_call("create_blog_post", space=key):
        return await create_content(get_client(ctx), "blogpost", key, title, body, format)


async def update_blog_post(
    ctx: Context,
    blog_post_id: str,
    body: str | None = None,
    title: str | None = None,
    format: Format = "markdown",
    expected_version: int | None = None,
    allow_macro_loss: bool = False,
    version_comment: str | None = None,
) -> dict[str, Any]:
    """Update a blog post. Same version and macro safeguards as update_page."""
    require_writable(ctx, "update_blog_post")
    async with log_tool_call("update_blog_post", page_id=blog_post_id):
        return await update_content(
            get_client(ctx),
            blog_post_id,
            body=body,
            fmt=format,
            title=title,
            expected_version=expected_version,
            allow_macro_loss=allow_macro_loss,
            version_comment=version_comment,
        )
```

- [ ] **Step 4: Run tests and checks**

Run: `.venv/bin/python -m pytest tests -q && .venv/bin/ruff format src tests && .venv/bin/ruff check src tests && .venv/bin/mypy src`
Expected: all tests pass (`10` new); ruff and mypy clean.

- [ ] **Step 5: Commit**

```bash
git add src/confluence_mcp/tools tests/test_tools_pages.py
git commit -m "feat: add page and blog post tools

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 8: Search, space, user and history tools

**Files:**
- Create: `src/confluence_mcp/tools/search.py`, `src/confluence_mcp/tools/spaces.py`, `src/confluence_mcp/tools/users.py`, `src/confluence_mcp/tools/history.py`
- Test: `tests/test_tools_search.py`, `tests/test_tools_misc.py`

**Interfaces:**
- Consumes: `_common` (Task 7), `content.get_content` / `restore_version` (Task 6).
- Produces tools: `search(cql, limit, start)`, `search_text(text, space_key, type, limit)` (CQL-escapes `\` and `"`), `list_spaces(type, limit, start)`, `get_space(space_key)`, `get_current_user()`, `get_user(username | user_key)`, `get_page_history(page_id, limit)` (tries `/rest/experimental/content/{id}/version`, then `/rest/api/content/{id}/version`), `get_page_version(page_id, version, format)`, `restore_page_version(page_id, version)`.
- Search hits: `{id, type, title, space, excerpt, url, last_modified}` from a single `GET /rest/api/search` with `expand=content.space`.

- [ ] **Step 1: Write the failing tests**

`tests/test_tools_search.py`:

```python
from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from confluence_mcp.client import ConfluenceClient
from confluence_mcp.config import Settings
from confluence_mcp.tools.search import search, search_text
from tests.conftest import BASE, make_ctx

HIT = {
    "content": {"id": "42", "type": "page", "title": "Deploy", "space": {"key": "OPS"}},
    "title": "Deploy",
    "excerpt": "how to @@@hl@@@deploy@@@endhl@@@",
    "url": "/display/OPS/Deploy",
    "lastModified": "2026-09-01T10:00:00.000Z",
    "resultGlobalContainer": {"title": "Operations"},
}


@pytest.fixture
def ctx(client: ConfluenceClient, settings: Settings) -> Any:
    return make_ctx(client, settings)


@respx.mock
async def test_search_compact_hits(ctx: Any) -> None:
    respx.get(f"{BASE}/rest/api/search").mock(
        return_value=httpx.Response(
            200, json={"results": [HIT], "start": 0, "limit": 25, "size": 1, "totalSize": 3}
        )
    )
    out = await search(ctx, cql="type = page")
    assert out["results"] == [
        {
            "id": "42",
            "type": "page",
            "title": "Deploy",
            "space": "OPS",
            "excerpt": "how to @@@hl@@@deploy@@@endhl@@@",
            "url": f"{BASE}/display/OPS/Deploy",
            "last_modified": "2026-09-01T10:00:00.000Z",
        }
    ]
    assert out["has_more"] is True


@respx.mock
async def test_search_text_escapes_quotes(ctx: Any) -> None:
    route = respx.get(f"{BASE}/rest/api/search").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    await search_text(ctx, text='say "hi" \\ bye', space_key="OPS", type="page")
    assert route.calls.last.request.url.params["cql"] == (
        'text ~ "say \\"hi\\" \\\\ bye" AND space = "OPS" AND type = page '
        "ORDER BY lastmodified DESC"
    )
```

`tests/test_tools_misc.py`:

```python
from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from confluence_mcp.client import ConfluenceClient
from confluence_mcp.config import Settings
from confluence_mcp.exceptions import NotFoundError
from confluence_mcp.tools.history import get_page_history, get_page_version
from confluence_mcp.tools.spaces import get_space, list_spaces
from confluence_mcp.tools.users import get_current_user, get_user
from tests.conftest import BASE, make_ctx
from tests.test_content import page

SPACE = {
    "key": "DOC",
    "name": "Docs",
    "type": "global",
    "description": {"plain": {"value": "All docs"}},
    "homepage": {"id": "1"},
    "_links": {"webui": "/display/DOC"},
}


@pytest.fixture
def ctx(client: ConfluenceClient, settings: Settings) -> Any:
    return make_ctx(client, settings)


@respx.mock
async def test_spaces(ctx: Any) -> None:
    route = respx.get(f"{BASE}/rest/api/space").mock(
        return_value=httpx.Response(200, json={"results": [SPACE], "size": 1})
    )
    respx.get(f"{BASE}/rest/api/space/DOC").mock(return_value=httpx.Response(200, json=SPACE))
    listed = await list_spaces(ctx, type="global")
    assert route.calls.last.request.url.params["type"] == "global"
    expected = {
        "key": "DOC",
        "name": "Docs",
        "type": "global",
        "description": "All docs",
        "homepage_id": "1",
        "url": f"{BASE}/display/DOC",
    }
    assert listed["results"] == [expected]
    assert await get_space(ctx, "DOC") == expected


@respx.mock
async def test_users(ctx: Any) -> None:
    user = {"username": "ann", "userKey": "k1", "displayName": "Ann", "type": "known"}
    respx.get(f"{BASE}/rest/api/user/current").mock(return_value=httpx.Response(200, json=user))
    by_key = respx.get(f"{BASE}/rest/api/user").mock(return_value=httpx.Response(200, json=user))
    assert (await get_current_user(ctx))["user_key"] == "k1"
    await get_user(ctx, user_key="k1")
    assert by_key.calls.last.request.url.params["key"] == "k1"
    with pytest.raises(ValueError):
        await get_user(ctx)


@respx.mock
async def test_history_falls_back_to_second_endpoint(ctx: Any) -> None:
    respx.get(f"{BASE}/rest/experimental/content/42/version").mock(return_value=httpx.Response(404))
    respx.get(f"{BASE}/rest/api/content/42/version").mock(
        return_value=httpx.Response(
            200,
            json={"results": [{"number": 2, "when": "t", "by": {"displayName": "Ann"}}]},
        )
    )
    assert await get_page_history(ctx, "42") == [
        {"number": 2, "when": "t", "by": "Ann", "message": None}
    ]


@respx.mock
async def test_history_unavailable(ctx: Any) -> None:
    respx.get(f"{BASE}/rest/experimental/content/42/version").mock(return_value=httpx.Response(404))
    respx.get(f"{BASE}/rest/api/content/42/version").mock(return_value=httpx.Response(404))
    with pytest.raises(NotFoundError, match="history"):
        await get_page_history(ctx, "42")


@respx.mock
async def test_get_page_version(ctx: Any) -> None:
    route = respx.get(f"{BASE}/rest/api/content/42").mock(
        return_value=httpx.Response(200, json=page(version=1, storage="<p>v1</p>"))
    )
    out = await get_page_version(ctx, "42", 1)
    assert out["body"] == "v1\n"
    assert route.calls.last.request.url.params["version"] == "1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_tools_search.py tests/test_tools_misc.py -q`
Expected: collection errors: `ModuleNotFoundError: No module named 'confluence_mcp.tools.search'` (and `.history`).

- [ ] **Step 3: Implement the tools**

`src/confluence_mcp/tools/search.py`:

```python
from __future__ import annotations

from typing import Any, Literal

from fastmcp import Context

from ..logging_setup import log_tool_call
from ._common import get_client, list_result, page_params


def _cql_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


async def _run_search(ctx: Context, cql: str, limit: int, start: int) -> dict[str, Any]:
    client = get_client(ctx)
    data = await client.get(
        "/rest/api/search",
        params={"cql": cql, "expand": "content.space", **page_params(limit, start)},
    )
    hits = []
    for item in data.get("results", []):
        content = item.get("content") or {}
        container = item.get("resultGlobalContainer") or {}
        hits.append(
            {
                "id": content.get("id"),
                "type": content.get("type") or item.get("entityType"),
                "title": content.get("title") or item.get("title"),
                "space": (content.get("space") or {}).get("key") or container.get("title"),
                "excerpt": item.get("excerpt"),
                "url": f"{client.base_url}{item['url']}" if item.get("url") else None,
                "last_modified": item.get("lastModified"),
            }
        )
    return list_result(data, hits)


async def search(ctx: Context, cql: str, limit: int = 25, start: int = 0) -> dict[str, Any]:
    """Search with a CQL query, e.g. 'space = DOC AND type = page AND title ~ "deploy"'."""
    async with log_tool_call("search"):
        return await _run_search(ctx, cql, limit, start)


async def search_text(
    ctx: Context,
    text: str,
    space_key: str | None = None,
    type: Literal["page", "blogpost"] | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Full-text search, newest first. Optionally restrict to a space and content type."""
    clauses = [f"text ~ {_cql_string(text)}"]
    if space_key:
        clauses.append(f"space = {_cql_string(space_key)}")
    if type:
        clauses.append(f"type = {type}")
    cql = " AND ".join(clauses) + " ORDER BY lastmodified DESC"
    async with log_tool_call("search_text", space=space_key):
        return await _run_search(ctx, cql, limit, 0)
```

`src/confluence_mcp/tools/spaces.py`:

```python
from __future__ import annotations

from typing import Any, Literal

from fastmcp import Context

from ..logging_setup import log_tool_call
from ._common import get_client, list_result, page_params, resolve_space

_EXPAND = "description.plain,homepage"


def _space(ctx: Context, data: dict[str, Any]) -> dict[str, Any]:
    webui = data.get("_links", {}).get("webui")
    return {
        "key": data.get("key"),
        "name": data.get("name"),
        "type": data.get("type"),
        "description": data.get("description", {}).get("plain", {}).get("value") or None,
        "homepage_id": (data.get("homepage") or {}).get("id"),
        "url": f"{get_client(ctx).base_url}{webui}" if webui else None,
    }


async def list_spaces(
    ctx: Context,
    type: Literal["global", "personal"] | None = None,
    limit: int = 25,
    start: int = 0,
) -> dict[str, Any]:
    """List Confluence spaces visible to the token's user. Start here to discover space keys."""
    async with log_tool_call("list_spaces"):
        params: dict[str, Any] = {**page_params(limit, start), "expand": _EXPAND}
        if type:
            params["type"] = type
        data = await get_client(ctx).get("/rest/api/space", params=params)
        return list_result(data, [_space(ctx, s) for s in data.get("results", [])])


async def get_space(ctx: Context, space_key: str | None = None) -> dict[str, Any]:
    """Get a space's details, including the id of its home page."""
    key = resolve_space(ctx, space_key)
    async with log_tool_call("get_space", space=key):
        data = await get_client(ctx).get(f"/rest/api/space/{key}", params={"expand": _EXPAND})
        return _space(ctx, data)
```

`src/confluence_mcp/tools/users.py`:

```python
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
```

`src/confluence_mcp/tools/history.py`:

```python
from __future__ import annotations

from typing import Any

from fastmcp import Context

from ..content import Format, get_content, restore_version
from ..exceptions import NotFoundError
from ..logging_setup import log_tool_call
from ._common import get_client, page_params, require_writable

_VERSION_PATHS = ("/rest/experimental/content/{id}/version", "/rest/api/content/{id}/version")


async def get_page_history(ctx: Context, page_id: str, limit: int = 25) -> list[dict[str, Any]]:
    """List a page's versions, newest first."""
    async with log_tool_call("get_page_history", page_id=page_id):
        client = get_client(ctx)
        for template in _VERSION_PATHS:
            try:
                data = await client.get(template.format(id=page_id), params=page_params(limit, 0))
            except NotFoundError:
                continue
            return [
                {
                    "number": v.get("number"),
                    "when": v.get("when"),
                    "by": (v.get("by") or {}).get("displayName"),
                    "message": v.get("message") or None,
                }
                for v in data.get("results", [])
            ]
        raise NotFoundError(404, f"Version history not available for content {page_id}")


async def get_page_version(
    ctx: Context, page_id: str, version: int, format: Format = "markdown"
) -> dict[str, Any]:
    """Get the content of a specific historical version of a page."""
    async with log_tool_call("get_page_version", page_id=page_id):
        return await get_content(get_client(ctx), page_id, format, version=version)


async def restore_page_version(ctx: Context, page_id: str, version: int) -> dict[str, Any]:
    """Restore an old version by saving its content as a new version."""
    require_writable(ctx, "restore_page_version")
    async with log_tool_call("restore_page_version", page_id=page_id):
        return await restore_version(get_client(ctx), page_id, version)
```

- [ ] **Step 4: Run tests and checks**

Run: `.venv/bin/python -m pytest tests -q && .venv/bin/ruff format src tests && .venv/bin/ruff check src tests && .venv/bin/mypy src`
Expected: all tests pass (`7` new); ruff and mypy clean.

- [ ] **Step 5: Commit**

```bash
git add src/confluence_mcp/tools tests/test_tools_search.py tests/test_tools_misc.py
git commit -m "feat: add search, space, user and history tools

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 9: Comment, label and attachment tools

**Files:**
- Create: `src/confluence_mcp/tools/comments.py`, `src/confluence_mcp/tools/labels.py`, `src/confluence_mcp/tools/attachments.py`
- Test: `tests/test_tools_comments_labels.py`, `tests/test_tools_attachments.py`

**Interfaces:**
- Consumes: `_common` (Task 7), `content.render_body` / `to_storage_body` / `update_content` (Task 6), `PayloadTooLargeError`, `NotFoundError`.
- Produces tools:
  - Comments: `list_comments(content_id, format, limit, start)` (items `{id, author, when, version, parent_comment_id, body}`), `add_comment(content_id, body, format, parent_comment_id)` (looks up the container type first), `update_comment(comment_id, body, format)` (via `update_content`, `allow_macro_loss=True`), `delete_comment(comment_id)`.
  - Labels: `get_labels(content_id) -> list[str]`, `add_labels(content_id, labels) -> list[str]`, `remove_label(content_id, label)`.
  - Attachments: `list_attachments`, `download_attachment(content_id, filename | attachment_id)` (size checked against `confluence_attachment_max_bytes` before and after download; text for `text/*`, JSON, XML, `+xml`/`+json`, and undecodable text falls back to base64), `upload_attachment(content_id, filename, content_base64 | text, comment, media_type)` (multipart with `X-Atlassian-Token: no-check`; an existing filename is uploaded to `.../child/attachment/{id}/data` as a new version), `delete_attachment(attachment_id)`.

- [ ] **Step 1: Write the failing tests**

`tests/test_tools_comments_labels.py`:

```python
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
```

`tests/test_tools_attachments.py`:

```python
from __future__ import annotations

import base64
from typing import Any

import httpx
import pytest
import respx

from confluence_mcp.client import ConfluenceClient
from confluence_mcp.config import Settings
from confluence_mcp.exceptions import NotFoundError, PayloadTooLargeError
from confluence_mcp.tools.attachments import (
    delete_attachment,
    download_attachment,
    list_attachments,
    upload_attachment,
)
from tests.conftest import BASE, make_ctx, make_settings

DL = "/download/attachments/42/notes.txt?version=1&api=v2"


def att(size: int = 5, media: str = "text/plain", name: str = "notes.txt") -> dict[str, Any]:
    return {
        "id": "att9",
        "title": name,
        "extensions": {"mediaType": media, "fileSize": size},
        "version": {"number": 1},
        "_links": {"download": DL},
    }


@pytest.fixture
def ctx(client: ConfluenceClient, settings: Settings) -> Any:
    return make_ctx(client, settings)


@respx.mock
async def test_list_attachments(ctx: Any) -> None:
    respx.get(f"{BASE}/rest/api/content/42/child/attachment").mock(
        return_value=httpx.Response(200, json={"results": [att()]})
    )
    out = await list_attachments(ctx, "42")
    assert out["results"][0] == {
        "id": "att9",
        "filename": "notes.txt",
        "media_type": "text/plain",
        "size": 5,
        "version": 1,
        "download_url": f"{BASE}{DL}",
    }


@respx.mock
async def test_download_text_by_filename(ctx: Any) -> None:
    respx.get(f"{BASE}/rest/api/content/42/child/attachment").mock(
        return_value=httpx.Response(200, json={"results": [att()]})
    )
    respx.get(f"{BASE}/download/attachments/42/notes.txt").mock(
        return_value=httpx.Response(200, content=b"hello")
    )
    out = await download_attachment(ctx, "42", filename="notes.txt")
    assert out == {
        "filename": "notes.txt",
        "media_type": "text/plain",
        "size": 5,
        "encoding": "text",
        "content": "hello",
    }


@respx.mock
async def test_download_binary_by_id_is_base64(ctx: Any) -> None:
    respx.get(f"{BASE}/rest/api/content/att9").mock(
        return_value=httpx.Response(200, json=att(media="image/png", name="a.png"))
    )
    respx.get(f"{BASE}/download/attachments/42/notes.txt").mock(
        return_value=httpx.Response(200, content=b"\x89PNG")
    )
    out = await download_attachment(ctx, "42", attachment_id="att9")
    assert out["encoding"] == "base64"
    assert base64.b64decode(out["content"]) == b"\x89PNG"


@respx.mock
async def test_download_refuses_large_file_before_fetching(client: ConfluenceClient) -> None:
    settings = make_settings(confluence_attachment_max_bytes=4)
    respx.get(f"{BASE}/rest/api/content/42/child/attachment").mock(
        return_value=httpx.Response(200, json={"results": [att(size=5)]})
    )
    body = respx.get(f"{BASE}/download/attachments/42/notes.txt")
    with pytest.raises(PayloadTooLargeError):
        await download_attachment(make_ctx(client, settings), "42", filename="notes.txt")
    assert not body.called


@respx.mock
async def test_download_missing_filename(ctx: Any) -> None:
    respx.get(f"{BASE}/rest/api/content/42/child/attachment").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    with pytest.raises(NotFoundError):
        await download_attachment(ctx, "42", filename="nope.txt")


async def test_download_needs_exactly_one_selector(ctx: Any) -> None:
    with pytest.raises(ValueError):
        await download_attachment(ctx, "42")


@respx.mock
async def test_upload_new_attachment(ctx: Any) -> None:
    respx.get(f"{BASE}/rest/api/content/42/child/attachment").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    route = respx.post(f"{BASE}/rest/api/content/42/child/attachment").mock(
        return_value=httpx.Response(200, json={"results": [att()]})
    )
    out = await upload_attachment(ctx, "42", "notes.txt", text="hello", comment="v1")
    request = route.calls.last.request
    assert request.headers["X-Atlassian-Token"] == "no-check"
    assert b'filename="notes.txt"' in request.content
    assert b"hello" in request.content
    assert out["id"] == "att9"


@respx.mock
async def test_upload_existing_creates_new_version(ctx: Any) -> None:
    respx.get(f"{BASE}/rest/api/content/42/child/attachment").mock(
        return_value=httpx.Response(200, json={"results": [att()]})
    )
    route = respx.post(f"{BASE}/rest/api/content/42/child/attachment/att9/data").mock(
        return_value=httpx.Response(200, json=att())
    )
    await upload_attachment(ctx, "42", "notes.txt", content_base64=base64.b64encode(b"x").decode())
    assert route.called


async def test_upload_validation(ctx: Any) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        await upload_attachment(ctx, "42", "a.txt")
    with pytest.raises(ValueError, match="base64"):
        await upload_attachment(ctx, "42", "a.bin", content_base64="%%%")


async def test_upload_too_large(client: ConfluenceClient) -> None:
    settings = make_settings(confluence_attachment_max_bytes=2)
    with pytest.raises(PayloadTooLargeError):
        await upload_attachment(make_ctx(client, settings), "42", "a.txt", text="abc")


@respx.mock
async def test_delete_attachment(ctx: Any) -> None:
    respx.delete(f"{BASE}/rest/api/content/att9").mock(return_value=httpx.Response(204))
    assert (await delete_attachment(ctx, "att9"))["status"] == "deleted"


@respx.mock
async def test_download_link_resolved_under_context_path() -> None:
    settings = make_settings(confluence_url=f"{BASE}/confluence")
    client = ConfluenceClient(settings, retry_wait=0)
    respx.get(f"{BASE}/confluence/rest/api/content/42/child/attachment").mock(
        return_value=httpx.Response(200, json={"results": [att()]})
    )
    body = respx.get(f"{BASE}/confluence/download/attachments/42/notes.txt").mock(
        return_value=httpx.Response(200, content=b"hello")
    )
    out = await download_attachment(make_ctx(client, settings), "42", filename="notes.txt")
    assert body.called
    assert out["content"] == "hello"
    await client.aclose()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_tools_comments_labels.py tests/test_tools_attachments.py -q`
Expected: collection errors: `ModuleNotFoundError` for `confluence_mcp.tools.comments` and `.attachments`.

- [ ] **Step 3: Implement the tools**

`src/confluence_mcp/tools/comments.py`:

```python
from __future__ import annotations

from typing import Any

from fastmcp import Context

from ..content import Format, render_body, to_storage_body, update_content
from ..logging_setup import log_tool_call
from ._common import get_client, list_result, page_params, require_writable


def _comment(data: dict[str, Any], fmt: Format) -> dict[str, Any]:
    version = data.get("version") or {}
    ancestors = data.get("ancestors") or []
    storage = data.get("body", {}).get("storage", {}).get("value", "")
    return {
        "id": data.get("id"),
        "author": (version.get("by") or {}).get("displayName"),
        "when": version.get("when"),
        "version": version.get("number"),
        "parent_comment_id": ancestors[-1].get("id") if ancestors else None,
        "body": render_body(storage, fmt),
    }


async def list_comments(
    ctx: Context, content_id: str, format: Format = "markdown", limit: int = 25, start: int = 0
) -> dict[str, Any]:
    """List comments (including replies) on a page or blog post."""
    async with log_tool_call("list_comments", page_id=content_id):
        data = await get_client(ctx).get(
            f"/rest/api/content/{content_id}/child/comment",
            params={
                "expand": "body.storage,version,ancestors",
                "depth": "all",
                **page_params(limit, start),
            },
        )
        return list_result(data, [_comment(c, format) for c in data.get("results", [])])


async def add_comment(
    ctx: Context,
    content_id: str,
    body: str,
    format: Format = "markdown",
    parent_comment_id: str | None = None,
) -> dict[str, Any]:
    """Add a comment to a page or blog post, or reply to a comment (parent_comment_id)."""
    require_writable(ctx, "add_comment")
    async with log_tool_call("add_comment", page_id=content_id):
        client = get_client(ctx)
        container = await client.get(f"/rest/api/content/{content_id}")
        payload: dict[str, Any] = {
            "type": "comment",
            "container": {"id": content_id, "type": container.get("type", "page")},
            "body": {
                "storage": {"value": to_storage_body(body, format), "representation": "storage"}
            },
        }
        if parent_comment_id:
            payload["ancestors"] = [{"id": parent_comment_id}]
        data = await client.post("/rest/api/content", json=payload)
        return {"id": data.get("id"), "status": "created"}


async def update_comment(
    ctx: Context, comment_id: str, body: str, format: Format = "markdown"
) -> dict[str, Any]:
    """Replace the text of a comment (version bumped automatically)."""
    require_writable(ctx, "update_comment")
    async with log_tool_call("update_comment", page_id=comment_id):
        return await update_content(
            get_client(ctx), comment_id, body=body, fmt=format, allow_macro_loss=True
        )


async def delete_comment(ctx: Context, comment_id: str) -> dict[str, Any]:
    """Delete a comment."""
    require_writable(ctx, "delete_comment")
    async with log_tool_call("delete_comment", page_id=comment_id):
        await get_client(ctx).delete(f"/rest/api/content/{comment_id}")
        return {"id": comment_id, "status": "deleted"}
```

`src/confluence_mcp/tools/labels.py`:

```python
from __future__ import annotations

from typing import Any

from fastmcp import Context

from ..logging_setup import log_tool_call
from ._common import get_client, require_writable


def _names(data: dict[str, Any]) -> list[str]:
    return [str(label.get("name")) for label in data.get("results", [])]


async def get_labels(ctx: Context, content_id: str) -> list[str]:
    """List the labels on a page or blog post."""
    async with log_tool_call("get_labels", page_id=content_id):
        return _names(await get_client(ctx).get(f"/rest/api/content/{content_id}/label"))


async def add_labels(ctx: Context, content_id: str, labels: list[str]) -> list[str]:
    """Add labels (lowercase, no spaces) to a page or blog post; returns all labels."""
    require_writable(ctx, "add_labels")
    async with log_tool_call("add_labels", page_id=content_id):
        payload = [{"prefix": "global", "name": name} for name in labels]
        data = await get_client(ctx).post(f"/rest/api/content/{content_id}/label", json=payload)
        return _names(data)


async def remove_label(ctx: Context, content_id: str, label: str) -> dict[str, Any]:
    """Remove one label from a page or blog post."""
    require_writable(ctx, "remove_label")
    async with log_tool_call("remove_label", page_id=content_id):
        await get_client(ctx).delete(
            f"/rest/api/content/{content_id}/label", params={"name": label}
        )
        return {"id": content_id, "removed": label}
```

`src/confluence_mcp/tools/attachments.py`:

```python
from __future__ import annotations

import base64
import binascii
import mimetypes
from typing import Any

from fastmcp import Context

from ..client import ConfluenceClient
from ..exceptions import NotFoundError, PayloadTooLargeError
from ..logging_setup import log_tool_call
from ._common import get_client, get_settings, list_result, page_params, require_writable

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
    async with log_tool_call("delete_attachment", page_id=attachment_id):
        await get_client(ctx).delete(f"/rest/api/content/{attachment_id}")
        return {"id": attachment_id, "status": "deleted"}
```

- [ ] **Step 4: Run tests and checks**

Run: `.venv/bin/python -m pytest tests -q && .venv/bin/ruff format src tests && .venv/bin/ruff check src tests && .venv/bin/mypy src`
Expected: all tests pass (`16` new); ruff and mypy clean.

- [ ] **Step 5: Commit**

```bash
git add src/confluence_mcp/tools tests/test_tools_comments_labels.py tests/test_tools_attachments.py
git commit -m "feat: add comment, label and attachment tools

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 10: Server, registration, resources, prompts and read-only coverage

**Files:**
- Create: `src/confluence_mcp/tools/__init__.py`, `src/confluence_mcp/server.py`, `src/confluence_mcp/__main__.py`, `src/confluence_mcp/resources.py`, `src/confluence_mcp/prompts.py`
- Test: `tests/test_server_registration.py`, `tests/test_read_only.py`, `tests/test_resources.py`

**Interfaces:**
- Consumes: every tool module (Tasks 7–9), `Settings`, `ConfluenceClient`, `configure_logging`, `get_content`.
- Produces:
  - `tools.ALL_TOOLS: list[Callable]` (the 31 tools) and `register_all_tools(mcp)`.
  - `server.create_server() -> FastMCP`, module-level `server.mcp`, lifespan yielding `{"client", "settings"}`.
  - `__main__.main()`: `MCP_TRANSPORT=http` → `mcp.run(transport="streamable-http", host, port)`, else stdio.
  - Resources `confluence://spaces`, `confluence://space/{space_key}`, `confluence://page/{page_id}` (Markdown); prompts `summarize_page`, `draft_page_from_notes`, `find_and_answer`.
- `test_read_only.py` finds the write tools by looking for `require_writable(` in each tool's source. It builds dummy arguments from the type hints and asserts `ReadOnlyModeError` with zero HTTP calls, so new write tools are covered automatically.

- [ ] **Step 1: Write the failing tests**

`tests/test_server_registration.py`:

```python
from __future__ import annotations

import asyncio

from confluence_mcp.server import create_server

EXPECTED_TOOLS = {
    "list_spaces", "get_space",
    "get_page", "get_page_children", "get_page_ancestors", "create_page", "update_page",
    "delete_page", "move_page",
    "list_blog_posts", "get_blog_post", "create_blog_post", "update_blog_post",
    "search", "search_text",
    "list_comments", "add_comment", "update_comment", "delete_comment",
    "get_labels", "add_labels", "remove_label",
    "list_attachments", "download_attachment", "upload_attachment", "delete_attachment",
    "get_page_history", "get_page_version", "restore_page_version",
    "get_current_user", "get_user",
}  # fmt: skip


def test_all_tools_registered() -> None:
    tools = asyncio.run(create_server().list_tools())
    assert {t.name for t in tools} == EXPECTED_TOOLS
    assert len(EXPECTED_TOOLS) == 31


def test_ctx_not_exposed_in_tool_schema() -> None:
    tools = asyncio.run(create_server().list_tools())
    for tool in tools:
        assert "ctx" not in tool.parameters.get("properties", {}), tool.name


def test_format_parameter_is_enum() -> None:
    tools = {t.name: t for t in asyncio.run(create_server().list_tools())}
    fmt = tools["get_page"].parameters["properties"]["format"]
    assert fmt["enum"] == ["markdown", "storage"]


def test_resources_registered() -> None:
    mcp = create_server()
    resources = asyncio.run(mcp.list_resources())
    templates = asyncio.run(mcp.list_resource_templates())
    uris = {str(r.uri) for r in resources} | {t.uri_template for t in templates}
    assert uris == {
        "confluence://spaces",
        "confluence://space/{space_key}",
        "confluence://page/{page_id}",
    }


def test_prompts_registered() -> None:
    prompts = asyncio.run(create_server().list_prompts())
    assert {p.name for p in prompts} == {
        "summarize_page",
        "draft_page_from_notes",
        "find_and_answer",
    }
```

`tests/test_read_only.py`:

```python
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
```

`tests/test_resources.py`:

```python
from __future__ import annotations

import json

import httpx
import pytest
import respx
from fastmcp import Client

from confluence_mcp.server import create_server
from tests.conftest import BASE
from tests.test_content import page


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONFLUENCE_URL", BASE)
    monkeypatch.setenv("CONFLUENCE_TOKEN", "secret-token")


@respx.mock
async def test_page_resource_is_markdown() -> None:
    respx.get(f"{BASE}/rest/api/content/42").mock(return_value=httpx.Response(200, json=page()))
    async with Client(create_server()) as client:
        [contents] = await client.read_resource("confluence://page/42")
    assert contents.text.startswith("# Home\n\n_Space DOC · version 3 · ")
    assert contents.text.endswith("old\n")


@respx.mock
async def test_spaces_resource() -> None:
    respx.get(f"{BASE}/rest/api/space").mock(
        return_value=httpx.Response(200, json={"results": [{"key": "DOC", "name": "Docs"}]})
    )
    async with Client(create_server()) as client:
        [contents] = await client.read_resource("confluence://spaces")
    assert json.loads(contents.text) == [{"key": "DOC", "name": "Docs"}]


@respx.mock
async def test_tool_error_reaches_client_without_token() -> None:
    respx.get(f"{BASE}/rest/api/content/42").mock(return_value=httpx.Response(401))
    async with Client(create_server()) as client:
        result = await client.call_tool("get_page", {"page_id": "42"}, raise_on_error=False)
    assert result.is_error
    text = result.content[0].text
    assert "Authentication failed" in text
    assert "secret-token" not in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_server_registration.py tests/test_read_only.py tests/test_resources.py -q`
Expected: collection errors: `ModuleNotFoundError: No module named 'confluence_mcp.server'` / `ImportError: cannot import name 'ALL_TOOLS'`.

- [ ] **Step 3: Implement registration, server, entry point, resources and prompts**

`src/confluence_mcp/tools/__init__.py`:

```python
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
```

`src/confluence_mcp/server.py`:

```python
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastmcp import FastMCP

from .client import ConfluenceClient
from .config import Settings
from .logging_setup import configure_logging, get_logger
from .prompts import register_prompts
from .resources import register_resources
from .tools import register_all_tools

log = get_logger(__name__)


@asynccontextmanager
async def _lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        log_path=settings.confluence_log_path,
        json_logs=bool(settings.confluence_log_path),
    )
    client = ConfluenceClient(settings)
    log.info("confluence_mcp.startup", **settings.redacted())
    try:
        yield {"client": client, "settings": settings}
    finally:
        await client.aclose()
        log.info("confluence_mcp.shutdown")


def create_server() -> FastMCP:
    mcp = FastMCP(
        name="Confluence Server MCP",
        instructions=(
            "Tools for a self-hosted Confluence Server / Data Center. "
            "Find content with search_text or search (CQL), or browse with list_spaces → "
            "get_space → get_page_children. Page bodies are Markdown by default; raw "
            "<ac:…> blocks inside them are Confluence macros and must be kept unchanged "
            "unless you mean to change them. To edit: get_page → modify the full body → "
            "update_page with expected_version set to the version you read."
        ),
        lifespan=_lifespan,
    )
    register_all_tools(mcp)
    register_resources(mcp)
    register_prompts(mcp)
    return mcp


mcp = create_server()
```

`src/confluence_mcp/__main__.py`:

```python
from __future__ import annotations

from .config import Settings
from .server import mcp


def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    if settings.mcp_transport == "http":
        mcp.run(
            transport="streamable-http",
            host=settings.mcp_http_host,
            port=settings.mcp_http_port,
        )
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
```

`src/confluence_mcp/resources.py`:

```python
from __future__ import annotations

import json
from typing import Any

from fastmcp import Context, FastMCP

from .content import get_content
from .tools._common import get_client


def register_resources(mcp: FastMCP) -> None:

    @mcp.resource("confluence://spaces")
    async def spaces_resource(ctx: Context) -> str:
        """All spaces visible to the server's user (key and name)."""
        spaces: list[dict[str, Any]] = await get_client(ctx).paginate("/rest/api/space")
        return json.dumps([{"key": s.get("key"), "name": s.get("name")} for s in spaces], indent=2)

    @mcp.resource("confluence://space/{space_key}")
    async def space_resource(space_key: str, ctx: Context) -> str:
        """A space's details and its top-level pages."""
        client = get_client(ctx)
        space = await client.get(
            f"/rest/api/space/{space_key}", params={"expand": "description.plain,homepage"}
        )
        pages = await client.get(
            f"/rest/api/space/{space_key}/content/page", params={"depth": "root", "limit": 100}
        )
        summary = {
            "key": space.get("key"),
            "name": space.get("name"),
            "description": space.get("description", {}).get("plain", {}).get("value"),
            "homepage_id": (space.get("homepage") or {}).get("id"),
            "root_pages": [
                {"id": p.get("id"), "title": p.get("title")} for p in pages.get("results", [])
            ],
        }
        return json.dumps(summary, indent=2)

    @mcp.resource("confluence://page/{page_id}", mime_type="text/markdown")
    async def page_resource(page_id: str, ctx: Context) -> str:
        """A page as Markdown with a short metadata header."""
        page = await get_content(get_client(ctx), page_id, "markdown")
        version = (page.get("version") or {}).get("number")
        space = (page.get("space") or {}).get("key")
        header = f"# {page['title']}\n\n_Space {space} · version {version} · {page['url']}_\n\n"
        return header + str(page["body"])
```

`src/confluence_mcp/prompts.py`:

```python
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
```

- [ ] **Step 4: Run the full suite and checks**

Run: `.venv/bin/python -m pytest tests -q && .venv/bin/ruff format src tests && .venv/bin/ruff check src tests && .venv/bin/mypy src`
Expected: `136 passed`; ruff and mypy clean.

- [ ] **Step 5: Smoke-test the HTTP transport locally**

```bash
CONFLUENCE_URL=https://confluence.invalid CONFLUENCE_TOKEN=x MCP_TRANSPORT=http MCP_HTTP_PORT=18765 .venv/bin/confluence-mcp &
sleep 3
curl -s -X POST http://127.0.0.1:18765/mcp -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}' | head -c 200
kill %1
```

Expected: an `event: message` / `data: {"jsonrpc":"2.0","id":1,"result":{...` response.

- [ ] **Step 6: Commit**

```bash
git add src tests
git commit -m "feat: wire up server, resources, prompts and read-only coverage

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 11: Docker, compose, Makefile, CI and README

**Files:**
- Create: `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `Makefile`, `.env.example`, `mcp_config_http.json`, `mcp_config_stdio.json`, `.github/workflows/docker-image.yml`, `.github/dependabot.yml`
- Modify: `README.md` (replace the stub)

**Interfaces:**
- Consumes: console script `confluence-mcp` (Task 10).
- Produces: image `confluence-server-mcp` that runs as non-root `mcp`, defaults to `MCP_TRANSPORT=http` on `0.0.0.0:8000`, and has endpoint `/mcp`. The compose healthcheck is a TCP connect, because a plain GET on `/mcp` is not a valid MCP request. CI pushes `ghcr.io/<owner>/confluence-server-mcp`.

- [ ] **Step 1: Write the deployment files**

`Dockerfile`:

```
FROM python:3.12-slim AS builder

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml README.md ./
COPY src/ src/

RUN uv pip install --system --no-cache .

FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/confluence-mcp /usr/local/bin/confluence-mcp

RUN useradd -r -s /bin/false mcp && mkdir -p /var/log/confluence-mcp && chown mcp /var/log/confluence-mcp
USER mcp

ENV MCP_TRANSPORT=http
ENV MCP_HTTP_HOST=0.0.0.0
ENV MCP_HTTP_PORT=8000

EXPOSE 8000

ENTRYPOINT ["confluence-mcp"]
```

`.dockerignore`:

```
.git
.github
.venv
venv
.env
**/__pycache__
.mypy_cache
.ruff_cache
.pytest_cache
tests
docs
```

`docker-compose.yml`:

```yaml
services:
  confluence-mcp:
    build: .
    image: confluence-server-mcp:latest
    ports:
      - "8000:8000"
    environment:
      - CONFLUENCE_URL=${CONFLUENCE_URL}
      - CONFLUENCE_TOKEN=${CONFLUENCE_TOKEN:-}
      - CONFLUENCE_USERNAME=${CONFLUENCE_USERNAME:-}
      - CONFLUENCE_PASSWORD=${CONFLUENCE_PASSWORD:-}
      - CONFLUENCE_DEFAULT_SPACE=${CONFLUENCE_DEFAULT_SPACE:-}
      - CONFLUENCE_READ_ONLY=${CONFLUENCE_READ_ONLY:-false}
      - CONFLUENCE_CUSTOM_HEADERS=${CONFLUENCE_CUSTOM_HEADERS:-}
      - CONFLUENCE_ATTACHMENT_MAX_BYTES=${CONFLUENCE_ATTACHMENT_MAX_BYTES:-5242880}
      - CONFLUENCE_LOG_PATH=/var/log/confluence-mcp/server.log
      - MCP_TRANSPORT=http
      - MCP_HTTP_HOST=0.0.0.0
      - MCP_HTTP_PORT=8000
    volumes:
      - mcp_logs:/var/log/confluence-mcp
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import socket; socket.create_connection(('localhost', 8000), 5)"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  mcp_logs:
```

`Makefile`:

```
.PHONY: install test lint typecheck format check run-stdio run-http docker-build docker-run clean

install:
	uv pip install -e ".[dev]"

test:
	python -m pytest tests/ -v

lint:
	ruff check src/ tests/

format:
	ruff format src/ tests/

typecheck:
	mypy src/

check: lint typecheck test

run-stdio:
	python -m confluence_mcp

run-http:
	MCP_TRANSPORT=http MCP_HTTP_HOST=127.0.0.1 MCP_HTTP_PORT=8000 python -m confluence_mcp

docker-build:
	docker build -t confluence-server-mcp .

docker-run:
	docker compose up

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	rm -rf .pytest_cache .mypy_cache .ruff_cache dist
```

`.env.example`:

```
# Required — include the context path if Confluence is not at the root (e.g. https://host/confluence)
CONFLUENCE_URL=https://confluence.yourcompany.com

# Auth — choose one method:
# Option A: Personal Access Token (preferred; Confluence 7.9+)
CONFLUENCE_TOKEN=your-token-here

# Option B: Basic auth
# CONFLUENCE_USERNAME=your-username
# CONFLUENCE_PASSWORD=your-password

# Optional behaviour
# CONFLUENCE_DEFAULT_SPACE=DOC
CONFLUENCE_READ_ONLY=false
# CONFLUENCE_ATTACHMENT_MAX_BYTES=5242880
# CONFLUENCE_TIMEOUT_SECONDS=30
# CONFLUENCE_LOG_PATH=/var/log/confluence-mcp/server.log

# Custom headers for Zero Trust / reverse proxy (Header=Value,OtherHeader=OtherValue)
# CONFLUENCE_CUSTOM_HEADERS=X-Custom-Token=abc=def

# Transport (stdio is default; use http for remote access)
MCP_TRANSPORT=stdio
MCP_HTTP_HOST=127.0.0.1
MCP_HTTP_PORT=8000
```

`mcp_config_http.json`:

```json
{
  "mcpServers": {
    "confluence": {
      "type": "http",
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

`mcp_config_stdio.json`:

```json
{
  "mcpServers": {
    "confluence": {
      "command": "confluence-mcp",
      "env": {
        "CONFLUENCE_URL": "https://confluence.yourcompany.com",
        "CONFLUENCE_TOKEN": "your-token-here"
      }
    }
  }
}
```

`.github/workflows/docker-image.yml`:

```yaml
name: Docker Image CI

on:
  pull_request:
    branches: [ "main" ]
  push:
    branches: [ "main" ]
    tags:
      - "v*.*.*"

permissions:
  contents: read
  packages: write

jobs:
  docker:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to GHCR
        if: github.event_name != 'pull_request'
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Extract Docker metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ghcr.io/${{ github.repository_owner }}/confluence-server-mcp
          tags: |
            type=raw,value=latest,enable=${{ github.ref == format('refs/heads/{0}', github.event.repository.default_branch) }}
            type=sha,enable=${{ github.ref == format('refs/heads/{0}', github.event.repository.default_branch) }}
            type=semver,pattern={{version}},enable=${{ startsWith(github.ref, 'refs/tags/v') }}
            type=semver,pattern={{major}}.{{minor}},enable=${{ startsWith(github.ref, 'refs/tags/v') }}
            type=semver,pattern={{major}},enable=${{ startsWith(github.ref, 'refs/tags/v') }}

      - name: Build and push
        uses: docker/build-push-action@v7
        with:
          context: .
          file: ./Dockerfile
          push: ${{ github.event_name != 'pull_request' }}
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
```

`.github/dependabot.yml`:

```yaml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
  - package-ecosystem: "docker"
    directory: "/"
    schedule:
      interval: "weekly"
```

- [ ] **Step 2: Replace the README**

`README.md`:

````markdown
# Confluence Server MCP

A [Model Context Protocol](https://modelcontextprotocol.io) server for **Confluence Server and Confluence Data Center** (self-hosted), built with [FastMCP](https://github.com/jlowin/fastmcp). It gives AI assistants such as Claude Code read and write access to spaces, pages, blog posts, comments, labels, attachments and page history.

> **Not for Confluence Cloud.** Targets the Confluence Server REST API (`/rest/api/...`). Personal Access Tokens need Confluence 7.9+.

## Features

- 31 tools: spaces, pages, blog posts, CQL and text search, comments, labels, attachments, history, users
- Page bodies as **Markdown** (default) or raw storage XHTML
- Macros with no Markdown form are kept verbatim as raw `<ac:…>` blocks, so a read → edit → write round trip does not lose them
- Update safeguards: `expected_version` optimistic locking, and rejection of updates that would drop macros (`allow_macro_loss=true` to override)
- Read-only mode, retries with backoff, typed errors, structured logs that never contain credentials
- Docker image (non-root) serving streamable HTTP on port 8000
- 3 resources (`confluence://spaces`, `confluence://space/{key}`, `confluence://page/{id}`) and 3 prompts

## Configuration

Environment variables (or a `.env` file — copy `.env.example`):

| Variable | Required | Default | Description |
|---|---|---|---|
| `CONFLUENCE_URL` | yes | — | Base URL, including any context path (e.g. `https://host/confluence`) |
| `CONFLUENCE_TOKEN` | one of | — | Personal Access Token, sent as `Authorization: Bearer` (preferred) |
| `CONFLUENCE_USERNAME` / `CONFLUENCE_PASSWORD` | one of | — | Basic auth fallback |
| `CONFLUENCE_DEFAULT_SPACE` | no | — | Space used when a tool's `space_key` is omitted |
| `CONFLUENCE_READ_ONLY` | no | `false` | Block all write tools |
| `CONFLUENCE_CUSTOM_HEADERS` | no | — | `Header=Value,Other=Value` for proxies / Zero Trust |
| `CONFLUENCE_ATTACHMENT_MAX_BYTES` | no | `5242880` | Size limit for attachment download/upload |
| `CONFLUENCE_TIMEOUT_SECONDS` | no | `30` | HTTP timeout |
| `CONFLUENCE_LOG_PATH` | no | — | Also write JSON logs to this file |
| `MCP_TRANSPORT` | no | `stdio` (`http` in Docker) | `stdio` or `http` (streamable HTTP) |
| `MCP_HTTP_HOST` / `MCP_HTTP_PORT` | no | `127.0.0.1` / `8000` | HTTP bind address |

### Creating a Personal Access Token

In Confluence: avatar → **Settings** → **Personal Access Tokens** → **Create token**. The server acts as that user: everyone who can reach the MCP endpoint gets that user's permissions, so run one container per token and restrict network access to it.

## Running

### Docker (remote HTTP)

```bash
docker build -t confluence-server-mcp .
docker run -d -p 8000:8000 \
  -e CONFLUENCE_URL=https://confluence.yourcompany.com \
  -e CONFLUENCE_TOKEN=your-token \
  confluence-server-mcp
# or: cp .env.example .env && docker compose up -d
```

Register it in Claude Code:

```bash
claude mcp add --transport http confluence http://localhost:8000/mcp
```

(or use `mcp_config_http.json`).

### Local stdio

```bash
uv pip install -e ".[dev]"
CONFLUENCE_URL=https://confluence.yourcompany.com CONFLUENCE_TOKEN=xxx confluence-mcp
```

## Markdown conversion

| Confluence | Markdown |
|---|---|
| headings, paragraphs, bold/italic, lists, links, simple tables | standard Markdown / GFM tables |
| code macro | fenced block with language |
| info / note / warning / tip panels | `> [!INFO]` / `> [!NOTE]` / `> [!WARNING]` / `> [!TIP]` |
| link to a page | `[text](confluence:SPACE/Page%20Title)` |
| attached image | `![alt](attachment:file.png)` |
| task list | `- [ ]` / `- [x]` |
| anything else (Jira, TOC, status, expand, complex tables, …) | raw XHTML, kept verbatim |

Keep the raw `<ac:…>` blocks unchanged when editing. `update_page` refuses an update that would drop macros unless `allow_macro_loss=true`. Use `format="storage"` for exact XHTML.

## Read-only mode

`CONFLUENCE_READ_ONLY=true` blocks: `create_page`, `update_page`, `delete_page`, `move_page`, `create_blog_post`, `update_blog_post`, `add_comment`, `update_comment`, `delete_comment`, `add_labels`, `remove_label`, `upload_attachment`, `delete_attachment`, `restore_page_version`.

## Development

```bash
make install   # editable install with dev deps
make check     # ruff + mypy --strict + pytest
```
````

- [ ] **Step 3: Build and smoke-test the image**

```bash
docker build -t confluence-server-mcp .
docker run -d --rm --name cfmcp-test -p 18765:8000 \
  -e CONFLUENCE_URL=https://confluence.invalid -e CONFLUENCE_TOKEN=supersecretvalue \
  confluence-server-mcp
sleep 4
docker exec cfmcp-test whoami
curl -s -X POST http://127.0.0.1:18765/mcp -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}' | head -c 200; echo
docker logs cfmcp-test 2>&1 | grep -c supersecretvalue
docker stop cfmcp-test
```

Expected: `whoami` prints `mcp`; curl prints `event: message` / `data: {"jsonrpc":"2.0","id":1,"result":...`; the grep count prints `0`.

- [ ] **Step 4: Run the full check**

Run: `make check`
Expected: ruff clean, mypy clean, `136 passed`. (`make` uses the active Python, so activate `.venv` first or run the three commands with the `.venv/bin/` prefix.)

- [ ] **Step 5: Commit**

```bash
git add Dockerfile .dockerignore docker-compose.yml Makefile .env.example mcp_config_http.json mcp_config_stdio.json .github README.md
git commit -m "feat: add Docker image, compose, CI and README

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

