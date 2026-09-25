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
| `CONFLUENCE_CA_BUNDLE` | no | — | PEM file of CA certificates to trust instead of the public ones (corporate root CA) |
| `CONFLUENCE_LOG_PATH` | no | — | Also write JSON logs to this file |
| `MCP_TRANSPORT` | no | `stdio` (`http` in Docker) | `stdio` or `http` (streamable HTTP) |
| `MCP_HTTP_HOST` / `MCP_HTTP_PORT` | no | `127.0.0.1` / `8000` | HTTP bind address |

### Creating a Personal Access Token

In Confluence: avatar → **Settings** → **Personal Access Tokens** → **Create token**. The server acts as that user: everyone who can reach the MCP endpoint gets that user's permissions, so run one container per token and restrict network access to it.

### Corporate (self-signed) certificates

If calls fail with `CERTIFICATE_VERIFY_FAILED ... self-signed certificate in certificate chain`, Confluence uses an internal CA. Mount a PEM bundle that contains it and point `CONFLUENCE_CA_BUNDLE` at it. On a Linux host that already trusts the CA, the system bundle works:

```bash
docker run ... \
  -v /etc/ssl/certs/ca-certificates.crt:/certs/ca.pem:ro \
  -e CONFLUENCE_CA_BUNDLE=/certs/ca.pem \
  confluence-server-mcp
```

The bundle replaces the built-in public CAs for Confluence connections, so it must contain the whole chain's root. The server refuses to start if the file does not exist.

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
| headings, paragraphs, bold/italic, strikethrough, nested lists, links, tables with a header row | standard Markdown / GFM tables |
| superscript / subscript | inline `<sup>` / `<sub>` |
| code macro | fenced block with language |
| info / note / warning / tip panels | `> [!INFO]` / `> [!NOTE]` / `> [!WARNING]` / `> [!TIP]` |
| link to a page | `[text](confluence:SPACE/Page%20Title)` |
| attached image | `![alt](attachment:file.png)` |
| link to an attachment | `[text](attachment:file.pdf)` |
| task list | `- [ ]` / `- [x]` |
| anything else (Jira, TOC, status, expand, dates (`<time>`), complex or header-less tables, …) | raw XHTML, kept verbatim |

Keep the raw `<ac:…>` blocks unchanged when editing. `update_page` refuses an update that would drop macros unless `allow_macro_loss=true`. Use `format="storage"` for exact XHTML.

### Lossy conversion

Markdown cannot express everything Confluence stores. Reading a page as Markdown and writing it back drops: underline, text colours and highlights, paragraph/cell alignment and indentation, `<br>` line breaks inside table cells, and table/column widths. Macros, other unknown `<ac:…>`/`<ri:…>` elements and `<time>` dates are not lost — they pass through as raw XHTML. For heavily formatted pages, read and write with `format="storage"`.

## Read-only mode

`CONFLUENCE_READ_ONLY=true` blocks: `create_page`, `update_page`, `delete_page`, `move_page`, `create_blog_post`, `update_blog_post`, `add_comment`, `update_comment`, `delete_comment`, `add_labels`, `remove_label`, `upload_attachment`, `delete_attachment`, `restore_page_version`.

## Development

```bash
make install   # editable install with dev deps
make check     # ruff + mypy --strict + pytest
```
