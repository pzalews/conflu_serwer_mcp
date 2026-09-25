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
