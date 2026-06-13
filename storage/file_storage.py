"""Default file-based storage backend.

Writes one directory per meeting under <storage_root>/meeting_<session_id>/
containing exactly the artifacts described in the project layout:

    audio.wav
    transcript.txt
    transcript.json
    metadata.json
    participant_timeline.json
    summary.json
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from config import get_settings
from storage.base import StorageBackend
from utils.helpers import read_json, run_blocking, write_json, write_text
from utils.models import (
    CaptionEntry,
    MeetingMetadata,
    MeetingSummary,
    ParticipantEvent,
    Transcript,
)


class FileStorageBackend(StorageBackend):
    """Persists artifacts as JSON/TXT files on the local filesystem."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._root: Path = self._settings.storage_root
        self._root.mkdir(parents=True, exist_ok=True)

    def _dir(self, session_id: str) -> Path:
        return self._settings.session_dir(session_id)

    async def save_metadata(self, session_id: str, metadata: MeetingMetadata) -> None:
        await run_blocking(write_json, self._dir(session_id) / "metadata.json", metadata)

    async def save_participants(
        self, session_id: str, events: list[ParticipantEvent]
    ) -> None:
        await run_blocking(
            write_json,
            self._dir(session_id) / "participant_timeline.json",
            [e.model_dump() for e in events],
        )

    async def save_captions(self, session_id: str, captions: list[CaptionEntry]) -> None:
        await run_blocking(
            write_json,
            self._dir(session_id) / "captions.json",
            [c.model_dump() for c in captions],
        )

    async def save_transcript(self, session_id: str, transcript: Transcript) -> None:
        d = self._dir(session_id)
        await run_blocking(write_json, d / "transcript.json", transcript)
        await run_blocking(write_text, d / "transcript.txt", transcript.full_text)

    async def save_summary(self, session_id: str, summary: MeetingSummary) -> None:
        await run_blocking(write_json, self._dir(session_id) / "summary.json", summary)

    async def list_sessions(self) -> list[str]:
        if not self._root.exists():
            return []
        ids = [
            p.name.removeprefix("meeting_")
            for p in self._root.iterdir()
            if p.is_dir() and p.name.startswith("meeting_")
        ]
        return sorted(ids)

    async def load_metadata(self, session_id: str) -> Optional[MeetingMetadata]:
        path = self._dir(session_id) / "metadata.json"
        if not path.exists():
            return None
        return MeetingMetadata(**read_json(path))

    async def load_transcript(self, session_id: str) -> Optional[Transcript]:
        path = self._dir(session_id) / "transcript.json"
        if not path.exists():
            return None
        return Transcript(**read_json(path))

    async def load_summary(self, session_id: str) -> Optional[MeetingSummary]:
        path = self._dir(session_id) / "summary.json"
        if not path.exists():
            return None
        return MeetingSummary(**read_json(path))

    async def load_captions(self, session_id: str) -> list[CaptionEntry]:
        path = self._dir(session_id) / "captions.json"
        if not path.exists():
            return []
        return [CaptionEntry(**c) for c in read_json(path)]