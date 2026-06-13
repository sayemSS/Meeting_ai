"""Shared domain models and enums.

These pydantic models are the contract between every component in the
pipeline (tracker, captions, transcriber, summary, storage, dashboard).
Centralising them keeps serialization consistent and makes the eventual
Redis/Oracle migration a matter of reading/writing these same shapes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    """Timezone-aware UTC now (avoids naive-datetime bugs)."""
    return datetime.now(timezone.utc)


class SessionState(str, Enum):
    """Lifecycle states for a single meeting session."""

    PENDING = "pending"
    JOINING = "joining"
    ACTIVE = "active"
    LEAVING = "leaving"
    RECORDING_DONE = "recording_done"
    TRANSCRIBING = "transcribing"
    SUMMARIZING = "summarizing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ParticipantAction(str, Enum):
    JOIN = "join"
    LEAVE = "leave"


class ScheduledMeeting(BaseModel):
    """A meeting the scheduler is expected to run."""

    id: str
    title: str
    meet_url: str
    start_time: datetime
    duration_minutes: int = 60
    language: Optional[str] = None
    enabled: bool = True


class ParticipantEvent(BaseModel):
    """A single join/leave event in the participant timeline."""

    name: str
    action: ParticipantAction
    timestamp: datetime = Field(default_factory=utcnow)


class CaptionEntry(BaseModel):
    """A finalised live-caption line captured from the Meet UI."""

    speaker: str = "Unknown"
    text: str
    timestamp: datetime = Field(default_factory=utcnow)


class TranscriptSegment(BaseModel):
    """A time-aligned segment produced by Whisper."""

    start: float
    end: float
    text: str
    speaker: Optional[str] = None


class Transcript(BaseModel):
    """Full transcription result for one meeting."""

    language: Optional[str] = None
    duration: float = 0.0
    segments: list[TranscriptSegment] = Field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n".join(seg.text.strip() for seg in self.segments if seg.text.strip())


class MeetingMetadata(BaseModel):
    """Descriptive metadata about a single meeting run."""

    session_id: str
    title: str
    meet_url: str
    # Language Whisper detected for the meeting audio (ISO 639-1 code, e.g.
    # "en"/"bn"), or None if detection was unavailable. Drives report language.
    language: Optional[str] = None
    scheduled_start: Optional[datetime] = None
    actual_start: Optional[datetime] = None
    actual_end: Optional[datetime] = None
    duration_seconds: float = 0.0
    unique_participants: list[str] = Field(default_factory=list)
    peak_participant_count: int = 0
    state: SessionState = SessionState.PENDING
    error: Optional[str] = None


class ActionItem(BaseModel):
    description: str
    owner: Optional[str] = None
    due: Optional[str] = None


class MeetingSummary(BaseModel):
    """LLM-generated summary of a meeting."""

    session_id: str
    overview: str = ""
    key_points: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)        # ← ADDED
    next_steps: list[str] = Field(default_factory=list)   # ← ADDED
    sentiment: Optional[str] = None
    generated_at: datetime = Field(default_factory=utcnow)