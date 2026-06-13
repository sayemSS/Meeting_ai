"""Storage backend abstraction.

The whole pipeline persists its artifacts (audio path, transcript, metadata,
participant timeline, summary) through this interface only. Today the
default implementation writes JSON files exactly as described in the project
layout. Tomorrow a RedisBackend or Oracle26aiBackend can be dropped in with
zero changes to sessions, the manager, or the dashboard.

This is the single most important seam for the Oracle 26ai + Redis migration.
"""

from __future__ import annotations

import abc
from typing import Optional

from utils.models import (
    CaptionEntry,
    MeetingMetadata,
    MeetingSummary,
    ParticipantEvent,
    Transcript,
)


class StorageBackend(abc.ABC):
    """Contract every persistence implementation must satisfy."""

    @abc.abstractmethod
    async def save_metadata(self, session_id: str, metadata: MeetingMetadata) -> None: ...

    @abc.abstractmethod
    async def save_participants(
        self, session_id: str, events: list[ParticipantEvent]
    ) -> None: ...

    @abc.abstractmethod
    async def save_captions(self, session_id: str, captions: list[CaptionEntry]) -> None: ...

    @abc.abstractmethod
    async def save_transcript(self, session_id: str, transcript: Transcript) -> None: ...

    @abc.abstractmethod
    async def save_summary(self, session_id: str, summary: MeetingSummary) -> None: ...

    @abc.abstractmethod
    async def list_sessions(self) -> list[str]: ...

    @abc.abstractmethod
    async def load_metadata(self, session_id: str) -> Optional[MeetingMetadata]: ...

    @abc.abstractmethod
    async def load_transcript(self, session_id: str) -> Optional[Transcript]: ...

    @abc.abstractmethod
    async def load_summary(self, session_id: str) -> Optional[MeetingSummary]: ...

    @abc.abstractmethod
    async def load_captions(self, session_id: str) -> list[CaptionEntry]: ...


def build_storage_backend(backend: str) -> StorageBackend:
    """Factory that returns the configured storage backend implementation."""
    if backend == "file":
        from storage.file_storage import FileStorageBackend

        return FileStorageBackend()
    if backend == "redis":
        from storage.redis_storage import RedisStorageBackend

        return RedisStorageBackend()
    if backend == "oracle":
        from storage.oracle_storage import Oracle26aiStorageBackend

        return Oracle26aiStorageBackend()
    raise ValueError(f"Unknown storage backend: {backend!r}")