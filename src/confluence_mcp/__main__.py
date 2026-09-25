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
