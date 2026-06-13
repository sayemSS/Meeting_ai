"""Metadata collector.

Aggregates descriptive facts about a meeting run into a single
MeetingMetadata object: timing, duration, participant roster, peak count,
final lifecycle state, and any error. The collector reads from the tracker
and the session clock rather than holding its own state, so it stays a thin,
testable assembler.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from tracker.participant_tracker import ParticipantTracker
from utils.models import MeetingMetadata, SessionState, utcnow


class MetadataCollector:
    """Builds the MeetingMetadata document for one session."""

    def __init__(self, session_id: str, title: str, meet_url: str) -> None:
        self.session_id = session_id
        self.title = title
        self.meet_url = meet_url
        self.scheduled_start: Optional[datetime] = None
        self.actual_start: Optional[datetime] = None
        self.actual_end: Optional[datetime] = None
        # Set by the session once Whisper has detected the meeting language.
        self.detected_language: Optional[str] = None

    def mark_started(self) -> None:
        self.actual_start = utcnow()

    def mark_ended(self) -> None:
        self.actual_end = utcnow()

    def build(
        self,
        tracker: Optional[ParticipantTracker],
        state: SessionState,
        error: Optional[str] = None,
    ) -> MeetingMetadata:
        duration = 0.0
        if self.actual_start and self.actual_end:
            duration = (self.actual_end - self.actual_start).total_seconds()

        return MeetingMetadata(
            session_id=self.session_id,
            title=self.title,
            meet_url=self.meet_url,
            language=self.detected_language,
            scheduled_start=self.scheduled_start,
            actual_start=self.actual_start,
            actual_end=self.actual_end,
            duration_seconds=duration,
            unique_participants=tracker.unique_participants if tracker else [],
            peak_participant_count=tracker.peak_count if tracker else 0,
            state=state,
            error=error,
        )