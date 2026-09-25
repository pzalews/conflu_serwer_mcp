# Design: Confluence Server MCP

**Date:** 2026-09-25
**Status:** Approved (design review in chat); awaiting written-spec review

## Goal

A Python MCP server that gives AI assistants (Claude Code, Claude Desktop, …) read **and** write access to a self-hosted **Confluence Server / Data Center** instance (e.g. `https://securitylabs.corp.idemia.com/`), authenticated with a Personal Access Token. It runs remotely as a Docker image over streamable HTTP.

It is a sibling of `jira_server_mcp` and `bitbucket_server_mcp` and **mirrors `bitbucket_server_mcp`** in layout, tooling and conventions.

**Not for Confluence Cloud.** Targets the Confluence Server REST API (`/rest/api/...`), PAT support requires Confluence 7.9+.

## Success criteria

- Claude Code registered with `claude mcp add --transport http confluence http://<host>:8000/mcp/` can search, read, create and update pages and blog posts, and manage comments, labels and attachments.
- Reading a page as Markdown and writing that Markdown back does not lose content (known macros round-trip; unknown macros pass through verbatim).
- An update cannot silently drop macros or overwrite a concurrent edit.
- `CONFLUENCE_READ_ONLY=true` blocks every write tool before any HTTP call.
- Credentials never appear in logs or error messages.
- `make check` (ruff, mypy strict, pytest) passes; tests run offline with respx.

## Non-goals

- Confluence Cloud / REST v2.
- Per-request / per-user auth: one token per container (same as siblings). Anyone who can reach the endpoint acts as that token's user.
- Page restrictions, templates, space administration, whiteboards.
- Perfect Markdown rendering of every macro.

## Architecture

Mirrors `bitbucket_server_mcp`:

```
conflu_serwer_mcp/
├── src/confluence_mcp/
│   ├── __init__.py
│   ├── __main__.py        # main(): MCP_TRANSPORT=stdio|http → mcp.run(...)
│   ├── server.py          # create_server(): FastMCP + lifespan (Settings, ConfluenceClient)
│   ├── config.py          # Settings (pydantic-settings), auth/custom headers, redacted()
│   ├── client.py          # ConfluenceClient: httpx.AsyncClient, retry, error mapping, paginate()
│   ├── exceptions.py      # exception hierarchy
│   ├── logging_setup.py   # structlog setup + log_tool_call (as in bitbucket)
│   ├── converter/
│   │   ├── __init__.py    # exports to_markdown, to_storage, inventory
│   │   ├── to_markdown.py # storage XHTML → Markdown
│   │   ├── to_storage.py  # Markdown → storage XHTML
│   │   └── macros.py      # macro mapping table, passthrough, macro inventory
│   ├── content.py         # shared page/blogpost get/create/update logic + safeguards
│   ├── tools/
│   │   ├── __init__.py    # register_all_tools(mcp)
│   │   ├── _common.py     # require_writable(ctx, tool), resolve_space(ctx, space_key)
│   │   ├── spaces.py
│   │   ├── pages.py
│   │   ├── blogposts.py
│   │   ├── search.py
│   │   ├── comments.py
│   │   ├── labels.py
│   │   ├── attachments.py
│   │   ├── history.py
│   │   └── users.py
│   ├── resources.py       # register_resources(mcp)
│   └── prompts.py         # register_prompts(mcp)
├── tests/
│   ├── conftest.py
│   ├── fixtures/          # realistic storage-format samples
│   ├── test_config.py
│   ├── test_client.py
│   ├── test_converter.py
│   ├── test_content.py
│   ├── test_read_only.py
│   ├── test_server_registration.py
│   └── test_tools_*.py
├── Dockerfile, docker-compose.yml, Makefile, .env.example, .gitignore, .dockerignore
├── mcp_config_http.json, mcp_config_stdio.json, README.md, pyproject.toml, .python-version
└── .github/workflows/docker-image.yml, .github/dependabot.yml
```

### Unit boundaries

- **`converter/`**: pure functions (`str → str`, `str → Counter[str]`), no HTTP, no settings. Testable in isolation.
- **`content.py`**: the only place implementing content create/update rules (format conversion, version bump, `expected_version` check, macro-loss check). Works for `type="page"` and `type="blogpost"`. `pages.py`, `blogposts.py` and `history.py` are thin wrappers.
- **`client.py`**: knows HTTP, auth, retry, status→exception mapping and pagination; no Markdown or macro knowledge. Exposes thin typed methods per endpoint (as `BitbucketClient` does) plus `get/post/put/delete/paginate`.
- **Tools**: module-level async functions taking `ctx: Context` first, reading `client`/`settings` from `ctx.lifespan_context`, wrapped in `log_tool_call(...)`; collected in `register_all_tools` (same pattern as bitbucket). Write tools call `require_writable(ctx, "<tool>")` first. Unlike bitbucket, this helper lives once in `tools/_common.py` instead of being duplicated per module.

## Configuration

Env vars or `.env` (pydantic-settings, `extra="ignore"`). Values are stripped of surrounding quotes (Docker Compose passes them literally).

| Variable | Required | Default | Description |
|---|---|---|---|
| `CONFLUENCE_URL` | yes | — | Base URL, trailing slash stripped, must start with `http(s)://`. Include context path if any (e.g. `https://host/confluence`). |
| `CONFLUENCE_TOKEN` | one of | — | PAT → `Authorization: Bearer <token>` (preferred) |
| `CONFLUENCE_USERNAME` / `CONFLUENCE_PASSWORD` | one of | — | Basic auth fallback |
| `CONFLUENCE_DEFAULT_SPACE` | no | — | Used when a tool's `space_key` is omitted |
| `CONFLUENCE_READ_ONLY` | no | `false` | Block write tools |
| `CONFLUENCE_CUSTOM_HEADERS` | no | — | `Header=Value,Other=Val=WithEquals` (proxy / Zero Trust) |
| `CONFLUENCE_LOG_PATH` | no | — | JSON log file; stderr always logged |
| `CONFLUENCE_ATTACHMENT_MAX_BYTES` | no | `5242880` | Max size for `download_attachment` / `upload_attachment` |
| `CONFLUENCE_TIMEOUT_SECONDS` | no | `30` | httpx timeout |
| `MCP_TRANSPORT` | no | `stdio` (`http` in Docker) | `stdio` or `http` (streamable-http) |
| `MCP_HTTP_HOST` | no | `127.0.0.1` (`0.0.0.0` in Docker) | |
| `MCP_HTTP_PORT` | no | `8000` | |

Validation fails at startup unless a token or both username and password are set. `redacted()` returns loggable settings (auth method only, header count only).

## Content format and converter

Page content is exchanged as **Markdown by default**; every content read/write tool takes `format: Literal["markdown", "storage"] = "markdown"`. `storage` returns/accepts raw Confluence storage XHTML unchanged.

Libraries: `markdownify` (read direction, with custom converters) and `markdown` (write direction, extensions `tables`, `fenced_code`, `sane_lists` plus our own small extensions for callouts, task lists and `confluence:`/`attachment:` links). Storage is parsed with `beautifulsoup4` + `lxml` (XML mode, since `ac:`/`ri:` are namespaced elements; a fragment is wrapped in a root element declaring the `ac`/`ri` namespaces before parsing).

### Mapping

| Storage | Markdown |
|---|---|
| `h1`–`h6`, `p`, `strong`/`b`, `em`/`i`, `code`, `ul`/`ol`/`li`, `a href`, `hr`, `blockquote`, `br` | standard Markdown |
| simple `table` (no `rowspan`/`colspan`, cells contain only inline content) | GFM table |
| complex `table` | raw HTML block (passthrough) |
| `ac:structured-macro ac:name="code"` with `language` param and `ac:plain-text-body` CDATA | fenced block ```` ```lang ```` |
| `ac:structured-macro ac:name="info"`/`note`/`warning`/`tip` with `ac:rich-text-body` | `> [!INFO]` / `> [!NOTE]` / `> [!WARNING]` / `> [!TIP]` followed by the body as quoted lines |
| `ac:link` + `ri:page ri:content-title="T"` (optional `ri:space-key="S"`) with link body | `[text](confluence:S/T)` or `[text](confluence:T)`; URL-encode spaces as `%20` in the target |
| `ac:image` + `ri:attachment ri:filename="f"` | `![alt](attachment:f)` |
| `ac:image` + `ri:url ri:value="u"` | `![alt](u)` |
| `ac:task-list` / `ac:task` with `ac:task-status` complete/incomplete | `- [x]` / `- [ ]` |
| any other `ac:structured-macro`, `ac:*` or `ri:*` element (jira, toc, include, status, expand, excerpt, anchor, …) | the element's original XHTML emitted verbatim as a raw HTML block, separated by blank lines |

**Passthrough rule:** block-level raw HTML is left untouched by `markdown`, so `to_storage` restores unknown macros byte-for-byte. For inline occurrences (e.g. a `status` macro inside a paragraph), the raw XHTML is emitted inline; `markdown` also preserves inline raw HTML. Tool docstrings tell the model: *"Raw `<ac:…>`/`<ri:…>` blocks in the Markdown are Confluence macros; keep them unchanged unless you intend to modify them."*

### Macro inventory

`inventory(storage: str) -> Counter[str]` counts `ac:structured-macro` elements by `ac:name` (plus pseudo-names `ac:image`, `ac:task-list`, `ac:link` for non-macro structures). Used by the macro-loss safeguard.

### Converter correctness criteria

- For every fixture in `tests/fixtures/*.xml`: `normalize(to_storage(to_markdown(s))) == normalize(s)` where `normalize` parses XML, sorts attributes and collapses insignificant whitespace. Fixtures that intentionally lose formatting (e.g. unsupported inline styles) are listed with an expected-output file instead.
- `inventory(to_storage(to_markdown(s))) == inventory(s)` for **all** fixtures (macros are never lost by a round-trip).
- Hand-written Markdown → storage cases for each mapping row.

## Content read/write flow (`content.py`)

### Read: `get_content(client, content_id, fmt)`

1. `GET /rest/api/content/{id}?expand=body.storage,version,space,ancestors,metadata.labels`
2. Body = `to_markdown(storage)` if `fmt == "markdown"` else storage.
3. Return compact dict:
   `{"id", "type", "title", "space": {"key", "name"}, "version": {"number", "when", "by"}, "url", "labels": [...], "ancestors": [{"id", "title"}], "format", "body"}`
   (`url` = `CONFLUENCE_URL` + `_links.webui`.)

Lookup by title: `GET /rest/api/content?spaceKey=S&title=T&type=page&expand=...`; `NotFoundError` if none.

### Create: `create_content(client, type, space_key, title, body, fmt, parent_id=None)`

1. Convert Markdown → storage if needed.
2. `POST /rest/api/content` with `{"type", "title", "space": {"key"}, "ancestors": [{"id": parent_id}]?, "body": {"storage": {"value", "representation": "storage"}}}`.
3. Return compact dict (metadata only, no body).

### Update: `update_content(client, content_id, body=None, fmt, title=None, expected_version=None, allow_macro_loss=False, version_comment=None)`

1. `GET` current content (`expand=body.storage,version,ancestors`).
2. If `expected_version is not None and expected_version != current.version` → `VersionConflictError(current_version=...)`.
3. New storage: `to_storage(body)` if Markdown, `body` if storage, or the current storage if `body is None` (title-only update).
4. **Macro safeguard** (for both formats): `lost = inventory(old) - inventory(new)`; if `lost` and not `allow_macro_loss` → `MacroLossError(lost)` whose message lists `name×count` and explains the `allow_macro_loss=true` override.
5. `PUT /rest/api/content/{id}` with `{"id", "type", "title": title or current.title, "version": {"number": current+1, "message": version_comment?}, "body": {"storage": ...}}`. Keep the existing parent: do not send `ancestors` on update.
6. HTTP 409 from the PUT (edited between GET and PUT) → `VersionConflictError`.
7. Return compact dict with new version.

### Restore: `restore_page_version(page_id, version)`

`GET /rest/api/content/{id}?status=historical&version=N&expand=body.storage` → `update_content(..., body=old_storage, fmt="storage", allow_macro_loss=True, version_comment=f"Restored version {N}")`. Uses the same conflict/version-bump path.

## Tools (31)

`W` = write tool (calls `require_writable`). `space_key: str | None = None` falls back to `CONFLUENCE_DEFAULT_SPACE`, else `ValueError`. List tools take `limit: int = 25` (capped at 100) and `start: int = 0` and return `{"results": [...], "start", "limit", "size", "has_more"}` with compact items. Enum-like parameters use `Literal` types.

### Spaces
- `list_spaces(type: Literal["global", "personal"] | None, limit, start)`
- `get_space(space_key)` — key, name, type, description (plain), homepage id, url

### Pages
- `get_page(page_id: str | None, space_key: str | None, title: str | None, format)` — `page_id` or `title` (+ space) required
- `get_page_children(page_id, limit, start)` — child pages (id, title, url)
- `get_page_ancestors(page_id)` — root → parent list
- W `create_page(title, body, space_key, parent_id: str | None, format)`
- W `update_page(page_id, body: str | None, title: str | None, format, expected_version: int | None, allow_macro_loss: bool = False, version_comment: str | None)`
- W `delete_page(page_id)` — moves to trash (`DELETE /rest/api/content/{id}`)
- W `move_page(page_id, target_parent_id)` — `PUT /rest/api/content/{id}/move/append/{target_parent_id}`; target must be in the same space (Confluence Server limitation, surfaced as `ValidationError`)

### Blog posts
- `list_blog_posts(space_key, limit, start)` — `GET /rest/api/content?type=blogpost&spaceKey=...` (newest first)
- `get_blog_post(blog_post_id, format)`
- W `create_blog_post(title, body, space_key, format)`
- W `update_blog_post(blog_post_id, body, title, format, expected_version, allow_macro_loss, version_comment)`

### Search
- `search(cql, limit, start)` — single call to `GET /rest/api/search?cql=...&expand=content.space` (returns content plus excerpt); hits `{id, type, title, space, excerpt, url, last_modified}`
- `search_text(text, space_key: str | None, type: Literal["page", "blogpost"] | None, limit)` — builds `text ~ "<escaped>"` [`AND space = "S"`] [`AND type = T`] `ORDER BY lastmodified DESC`; escapes `\` and `"` in text

### Comments
- `list_comments(content_id, format, limit, start)` — `GET /rest/api/content/{id}/child/comment?expand=body.storage,version,ancestors&depth=all`; items include `parent_comment_id`
- W `add_comment(content_id, body, format, parent_comment_id: str | None)` — `POST /rest/api/content` with `type=comment`, `container={"id", "type"}` (type taken from the content itself), `ancestors=[{"id": parent_comment_id}]` for replies
- W `update_comment(comment_id, body, format)` — version bump like content (no macro safeguard)
- W `delete_comment(comment_id)`

### Labels
- `get_labels(content_id)`
- W `add_labels(content_id, labels: list[str])` — `POST /rest/api/content/{id}/label` with `[{"prefix": "global", "name"}]`
- W `remove_label(content_id, label)` — `DELETE /rest/api/content/{id}/label?name=...`

### Attachments
- `list_attachments(content_id, limit, start)` — id, title, media type, size, version, download url
- `download_attachment(content_id, filename: str | None, attachment_id: str | None)` — size checked against `CONFLUENCE_ATTACHMENT_MAX_BYTES` before download (from metadata); returns `{"filename", "media_type", "size", "encoding": "text"|"base64", "content"}`; text for `text/*`, `application/json`, `application/xml`, `*+xml`, `*+json`
- W `upload_attachment(content_id, filename, content_base64: str | None, text: str | None, comment: str | None, media_type: str | None)` — exactly one of `content_base64`/`text`; multipart `POST /rest/api/content/{id}/child/attachment` with `X-Atlassian-Token: no-check`; if the filename already exists, `POST .../child/attachment/{attId}/data` (new version)
- W `delete_attachment(attachment_id)`

### History
- `get_page_history(page_id, limit)` — `GET /rest/experimental/content/{id}/version` (fallback: `/rest/api/content/{id}/version` then `/history`); items `{number, when, by, message}`
- `get_page_version(page_id, version, format)` — historical body, converted like `get_page`
- W `restore_page_version(page_id, version)` — see Restore above

### Users
- `get_current_user()` — `GET /rest/api/user/current`
- `get_user(username: str | None, user_key: str | None)` — exactly one required

## Resources

- `confluence://spaces` — list of spaces (key, name)
- `confluence://space/{space_key}` — space info + top-level pages
- `confluence://page/{page_id}` — page as Markdown with a short metadata header

## Prompts

- `summarize_page(page_id)` — read page, summarize for a given audience
- `draft_page_from_notes(space_key, parent_id, notes)` — turn notes into a structured page and create it after confirmation
- `find_and_answer(question, space_key)` — search then answer citing page URLs

## Errors

`exceptions.py` (mirrors bitbucket's shape):

```
ConfluenceMCPError
├── ConfigurationError
├── ReadOnlyModeError(tool_name)
├── MacroLossError(lost: Counter[str])
└── ConfluenceAPIError(status_code, message)
    ├── ValidationError           400
    ├── AuthenticationError       401
    ├── AuthorizationError        403
    ├── NotFoundError             404
    ├── VersionConflictError      409 (or expected_version mismatch; carries current_version)
    ├── PayloadTooLargeError      413 (and local size-limit refusals)
    └── RateLimitError            429 after retries
```

- `client.py` extracts Confluence's `message` field from error JSON when present.
- 429 and 5xx (and connection errors) retried by tenacity: 3 attempts, exponential backoff (0.5s → 4s), honouring `Retry-After`. Only idempotent methods (GET, PUT, DELETE) are retried on 5xx; POST is retried only on 429 and connection errors raised before the request is sent.
- Tools let exceptions propagate; FastMCP presents the message to the model. Messages never include auth headers or the token.
- Logs: method, path (no query string for search, CQL logged at debug level only), status, duration; never headers or bodies.

## Deployment

- **Dockerfile:** multi-stage like bitbucket. The builder uses `uv pip install --system .`; runtime is `python:3.12-slim` with a non-root `mcp` user, `/var/log/confluence-mcp` owned by `mcp`, `ENV MCP_TRANSPORT=http MCP_HTTP_HOST=0.0.0.0 MCP_HTTP_PORT=8000`, `EXPOSE 8000`, `ENTRYPOINT ["confluence-mcp"]`.
- **docker-compose.yml:** single `confluence-mcp` service, port 8000, env from `.env`, log volume, restart `unless-stopped`, healthcheck on `http://localhost:8000/mcp/`.
- **CI:** `.github/workflows/docker-image.yml` copied from bitbucket (build on PR; push to `ghcr.io/<owner>/confluence-server-mcp` on main and `v*.*.*` tags). `.github/dependabot.yml` for pip, github-actions, docker.
- **Makefile:** `install`, `test`, `lint`, `format`, `typecheck`, `check`, `run-stdio`, `run-http`, `docker-build`, `docker-run`, `clean`.
- **README:** features, config table, creating a PAT (Profile → Settings → Personal Access Tokens), read-only mode, Markdown conversion + macro safeguards, Docker usage, `claude mcp add --transport http confluence http://host:8000/mcp/`, and example `mcp_config_http.json`.

## Dependencies

Runtime: `fastmcp>=3.3.1`, `httpx>=0.28.1,<1.0`, `pydantic>=2.11,<3.0`, `pydantic-settings>=2.7,<3.0`, `tenacity>=9.0,<10.0`, `structlog>=25.1,<26.0`, `markdown>=3.7`, `markdownify>=0.14`, `beautifulsoup4>=4.12`, `lxml>=5.0`.
Dev: `pytest`, `pytest-asyncio`, `respx`, `ruff`, `mypy`, `types-Markdown`, `types-beautifulsoup4`/`lxml-stubs` as needed.
Python `>=3.12`; ruff line-length 100, rules `E,W,F,UP,B,I`; mypy strict.

## Testing

- `test_config.py`: URL validation, auth header selection (PAT over basic), missing auth fails, custom header parsing, quote stripping, redaction.
- `test_client.py` (respx): status → exception mapping, Confluence `message` extraction, retry on 429/503 with `Retry-After`, no POST retry on 5xx, pagination via `_links.next`, custom headers sent, token never in exception text.
- `test_converter.py`: fixture round-trips, inventory preservation, per-mapping-row Markdown → storage cases, unknown macro passthrough (block and inline), complex table passthrough.
- `test_content.py` (respx): version bump, `expected_version` mismatch, 409 on PUT, macro-loss rejection and override, title-only update, storage-format path, restore.
- `test_read_only.py`: every write tool raises `ReadOnlyModeError` with no HTTP call (respx asserts no routes called); the list of write tools is derived from registration so new tools are covered automatically.
- `test_server_registration.py`: all 31 tools, 3 resources, 3 prompts registered with expected names.
- `test_tools_*.py`: request shape per tool (path, params, payload) and compact response shape.
