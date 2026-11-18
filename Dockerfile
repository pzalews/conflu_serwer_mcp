FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928 AS builder

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /usr/local/bin/uv

COPY pyproject.toml README.md ./
COPY src/ src/

RUN uv pip install --system --no-cache .

FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/confluence-mcp /usr/local/bin/confluence-mcp

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -r -s /bin/false mcp && mkdir -p /var/log/confluence-mcp && chown mcp /var/log/confluence-mcp
USER mcp

ENV MCP_TRANSPORT=http
ENV MCP_HTTP_HOST=0.0.0.0
ENV MCP_HTTP_PORT=8000

EXPOSE 8000

ENTRYPOINT ["confluence-mcp"]
