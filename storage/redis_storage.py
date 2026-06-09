"""Redis storage backend (migration stub).

Wired into the factory so switching STORAGE_BACKEND=redis is a config-only
change. Implement the methods with redis.asyncio (recommended: store each
artifact as a JSON string under a namespaced key, e.g.
"{namespace}:{session_id}:metadata", and maintain a sorted set of session
ids for listing). Left intentionally unimplemented to keep the dependency
optional until the migration is scheduled.
"""

from __future__ import annotations

from typing import Optional

from storage.base import StorageBackend
from utils.models import (
    CaptionEntry,
    MeetingMetadata,
    MeetingSummary,
    ParticipantEvent,
    Transcript,
)

_NOT_IMPLEMENTED = (
    "RedisStorageBackend is a migration stub. Implement with redis.asyncio "
    "before setting STORAGE_BACKEND=redis."
)


class RedisStorageBackend(StorageBackend):
    async def save_metadata(self, session_id: str, metadata: MeetingMetadata) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    async def save_participants(self, session_id: str, events: list[ParticipantEvent]) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    async def save_captions(self, session_id: str, captions: list[CaptionEntry]) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    async def save_transcript(self, session_id: str, transcript: Transcript) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    async def save_summary(self, session_id: str, summary: MeetingSummary) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    async def list_sessions(self) -> list[str]:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    async def load_metadata(self, session_id: str) -> Optional[MeetingMetadata]:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    async def load_transcript(self, session_id: str) -> Optional[Transcript]:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    async def load_summary(self, session_id: str) -> Optional[MeetingSummary]:
        raise NotImplementedError(_NOT_IMPLEMENTED)
