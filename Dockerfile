FROM python:3.14-slim AS builder

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml README.md ./
COPY src/ src/

RUN uv pip install --system --no-cache .

FROM python:3.14-slim

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
