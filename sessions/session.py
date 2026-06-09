"""Session: the isolated runtime for a single meeting.

A Session owns every component needed for one meeting and runs the full
pipeline end to end:

    join (Playwright) -> live capture (tracker + captions + recorder)
        -> leave -> transcribe (Whisper) -> summarize (DeepSeek) -> persist

Each Session is fully self-contained: its own browser context, its own
collectors, its own output directory, its own logger. Nothing is shared with
other sessions, which is what makes running many meetings in parallel safe.
The Session also exposes a live `state` and a `snapshot()` for the dashboard.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from automation.playwright_bot import PlaywrightBot
from captions.caption_listener import CaptionListener
from config import get_settings
from metadata.metadata_collector import MetadataCollector
from recorder.audio_recorder import AudioRecorder
from storage.base import StorageBackend
from summary.summary_service import SummaryService
from tracker.participant_tracker import ParticipantTracker
from transcriber.whisper_service import WhisperService
from utils.logger import session_logger
from utils.models import MeetingSummary, ScheduledMeeting, SessionState, Transcript


class Session:
    """Runs and tracks one Google Meet meeting from join to summary."""

    def __init__(self, meeting: ScheduledMeeting, storage: StorageBackend) -> None:
        self.meeting = meeting
        self.session_id = meeting.id
        self.storage = storage
        self.log = session_logger(__name__, self.session_id)
        self._settings = get_settings()

        self.state: SessionState = SessionState.PENDING
        self.error: Optional[str] = None

        self._dir = self._settings.session_dir(self.session_id)
        self._dir.mkdir(parents=True, exist_ok=True)

        # Components (constructed on demand so a cancelled session is cheap).
        self._bot: Optional[PlaywrightBot] = None
        self._tracker: Optional[ParticipantTracker] = None
        self._captions: Optional[CaptionListener] = None
        self._recorder: Optional[AudioRecorder] = None
        self._metadata = MetadataCollector(
            self.session_id, meeting.title, meeting.meet_url
        )
        self._metadata.scheduled_start = meeting.start_time

        self._stop_requested = asyncio.Event()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    async def run(self) -> None:
        """Execute the complete pipeline. Never raises to the caller."""
        try:
            await self._join_and_capture()
            transcript = await self._transcribe()
            await self._summarize(transcript)
            self._set_state(SessionState.COMPLETED)
        except asyncio.CancelledError:
            self._set_state(SessionState.CANCELLED)
            await self._safe_teardown()
            raise
        except Exception as exc:  # pipeline must fail closed, never crash the manager
            self.error = str(exc)
            self.log.exception("Session failed: %s", exc)
            self._set_state(SessionState.FAILED)
        finally:
            await self._persist_metadata()

    def request_stop(self) -> None:
        """Ask the session to leave the meeting at the next opportunity."""
        self.log.info("Stop requested")
        self._stop_requested.set()

    def snapshot(self) -> dict:
        """Lightweight live status for the dashboard."""
        return {
            "session_id": self.session_id,
            "title": self.meeting.title,
            "state": self.state.value,
            "participants": self._tracker.unique_participants if self._tracker else [],
            "peak_participants": self._tracker.peak_count if self._tracker else 0,
            "captions": len(self._captions.captions) if self._captions else 0,
            "error": self.error,
        }

    # ------------------------------------------------------------------ #
    # Pipeline stages
    # ------------------------------------------------------------------ #
    async def _join_and_capture(self) -> None:
        self._set_state(SessionState.JOINING)
        self._bot = PlaywrightBot(self.session_id, self.meeting.meet_url)
        page = await self._bot.start()
        await self._bot.join()
        await self._bot.turn_on_captions()

        self._metadata.mark_started()
        self._set_state(SessionState.ACTIVE)

        # Spin up the live collectors. Each runs as its own task.
        self._tracker = ParticipantTracker(self.session_id, page)
        self._captions = CaptionListener(self.session_id, page)
        self._recorder = AudioRecorder(self.session_id, self._dir / "audio.wav")

        self._tracker.start()
        self._captions.start()
        await self._recorder.start()

        await self._wait_for_meeting_end()

        # Leave and stop collectors in a safe order.
        self._set_state(SessionState.LEAVING)
        await self._recorder.stop()
        await self._captions.stop()
        await self._tracker.stop()
        await self._bot.leave()
        await self._bot.stop()
        self._metadata.mark_ended()
        self._set_state(SessionState.RECORDING_DONE)

        # Persist the live-captured artifacts immediately.
        await self.storage.save_participants(self.session_id, self._tracker.events)
        await self.storage.save_captions(self.session_id, self._captions.captions)

    async def _wait_for_meeting_end(self) -> None:
        """Block until the meeting ends, max duration elapses, or stop is asked."""
        assert self._bot is not None
        max_seconds = min(
            self.meeting.duration_minutes, self._settings.max_meeting_minutes
        ) * 60
        elapsed = 0
        check_interval = 10
        while elapsed < max_seconds:
            if self._stop_requested.is_set():
                self.log.info("Ending capture: stop requested")
                return
            if not await self._bot.is_still_in_call():
                self.log.info("Ending capture: no longer in call (host ended / removed)")
                return
            try:
                await asyncio.wait_for(self._stop_requested.wait(), timeout=check_interval)
            except asyncio.TimeoutError:
                pass
            elapsed += check_interval
        self.log.info("Ending capture: max duration reached")

    async def _transcribe(self) -> Transcript:
        self._set_state(SessionState.TRANSCRIBING)
        whisper = WhisperService(self.session_id)
        audio_path = self._dir / "audio.wav"
        transcript = await whisper.transcribe(audio_path, language=self.meeting.language)

        # Fall back to live captions if Whisper produced nothing.
        if not transcript.segments and self._captions and self._captions.captions:
            self.log.info("No audio transcript; using live captions as fallback")
            from utils.models import TranscriptSegment

            transcript = Transcript(
                segments=[
                    TranscriptSegment(start=0.0, end=0.0, text=c.text, speaker=c.speaker)
                    for c in self._captions.captions
                ]
            )

        await self.storage.save_transcript(self.session_id, transcript)
        return transcript

    async def _summarize(self, transcript: Transcript) -> MeetingSummary:
        self._set_state(SessionState.SUMMARIZING)
        summary = await SummaryService(self.session_id).summarize(transcript)
        await self.storage.save_summary(self.session_id, summary)
        return summary

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _set_state(self, state: SessionState) -> None:
        self.state = state
        self.log.info("State -> %s", state.value)

    async def _persist_metadata(self) -> None:
        try:
            metadata = self._metadata.build(self._tracker, self.state, self.error)
            await self.storage.save_metadata(self.session_id, metadata)
        except Exception as exc:
            self.log.error("Failed to persist metadata: %s", exc)

    async def _safe_teardown(self) -> None:
        """Best-effort teardown used on cancellation."""
        for closer in (
            self._recorder.stop if self._recorder else None,
            self._captions.stop if self._captions else None,
            self._tracker.stop if self._tracker else None,
            self._bot.stop if self._bot else None,
        ):
            if closer is None:
                continue
            try:
                await closer()
            except Exception:
                pass
