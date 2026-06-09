"""Oracle 26ai storage backend (migration stub).

Wired into the factory so switching STORAGE_BACKEND=oracle is a config-only
change. The recommended schema stores each artifact as a JSON document in
Oracle's native JSON / 23ai+ vector-enabled tables (one table per artifact
type keyed by session_id), which also positions transcripts for AI Vector
Search. Implement with python-oracledb (async) before enabling.
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
    "Oracle26aiStorageBackend is a migration stub. Implement with "
    "python-oracledb before setting STORAGE_BACKEND=oracle."
)


class Oracle26aiStorageBackend(StorageBackend):
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
