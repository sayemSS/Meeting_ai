"""Small, dependency-free helper utilities used across the project."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


def new_session_id() -> str:
    """Generate a short, filesystem-safe unique session id."""
    return uuid.uuid4().hex[:12]


def slugify(value: str, max_len: int = 60) -> str:
    """Convert an arbitrary string into a safe slug."""
    value = re.sub(r"[^\w\s-]", "", value).strip().lower()
    value = re.sub(r"[\s_-]+", "-", value)
    return value[:max_len] or "untitled"


def _json_default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, "model_dump"):  # pydantic v2 models
        return obj.model_dump()
    raise TypeError(f"Object of type {type(obj)!r} is not JSON serializable")


def to_json(data: Any, indent: int = 2) -> str:
    """Serialize any project object (incl. pydantic models) to JSON text."""
    return json.dumps(data, default=_json_default, ensure_ascii=False, indent=indent)


def write_json(path: Path, data: Any, indent: int = 2) -> None:
    """Atomically write JSON to disk (write to temp, then rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(to_json(data, indent=indent), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> Any:
    """Read and parse a JSON file."""
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, text: str) -> None:
    """Atomically write plain text to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


async def run_blocking(func, *args, **kwargs):
    """Run a blocking callable in the default thread pool.

    Used to keep CPU-bound work (Whisper) and blocking IO off the event
    loop so concurrent sessions are never starved.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))
