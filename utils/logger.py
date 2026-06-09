"""Logging configuration.

A single setup_logging() call configures the root logger for the whole
process. get_logger() returns module-scoped loggers. Sessions attach a
`session_id` via LoggerAdapter so every line is traceable to one meeting,
which is essential when many meetings run concurrently.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any


class _JsonFormatter(logging.Formatter):
    """Minimal structured JSON formatter for production log shipping."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if hasattr(record, "session_id"):
            payload["session_id"] = record.session_id  # type: ignore[attr-defined]
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


_CONFIGURED = False


def setup_logging(level: str = "INFO", json_output: bool = False) -> None:
    """Configure the root logger once for the entire process."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    handler = logging.StreamHandler(sys.stdout)
    if json_output:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
                datefmt="%H:%M:%S",
            )
        )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Quiet down noisy third-party libraries.
    for noisy in ("httpx", "asyncio", "playwright"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a named logger."""
    return logging.getLogger(name)


def session_logger(name: str, session_id: str) -> logging.LoggerAdapter:
    """Return a logger whose every record carries the session_id."""
    return logging.LoggerAdapter(get_logger(name), {"session_id": session_id})
