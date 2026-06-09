"""Meeting Scheduler.

Holds the queue of upcoming meetings and hands each one to the MeetingManager
at its scheduled start time. A simple, dependency-light async loop checks the
queue every few seconds and fires due meetings; this is easy to reason about
and trivially future-proof (swap the in-memory queue for a Redis sorted set
or an Oracle table without touching the manager or sessions).

Meetings can also be added on the fly via add_meeting(), and the dashboard
can trigger an immediate (ad-hoc) meeting through the manager directly.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from manager.meeting_manager import MeetingManager
from utils.logger import get_logger
from utils.models import ScheduledMeeting

log = get_logger(__name__)


class MeetingScheduler:
    """Fires scheduled meetings at their start time into the manager."""

    CHECK_INTERVAL_SECONDS = 5

    def __init__(self, manager: MeetingManager) -> None:
        self.manager = manager
        self._queue: dict[str, ScheduledMeeting] = {}
        self._fired: set[str] = set()
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

    def add_meeting(self, meeting: ScheduledMeeting) -> None:
        """Register an upcoming meeting."""
        self._queue[meeting.id] = meeting
        log.info(
            "Scheduled meeting %s (%s) at %s",
            meeting.id, meeting.title, meeting.start_time.isoformat(),
        )

    def add_meetings(self, meetings: list[ScheduledMeeting]) -> None:
        for m in meetings:
            self.add_meeting(m)

    def cancel_meeting(self, meeting_id: str) -> bool:
        return self._queue.pop(meeting_id, None) is not None

    @property
    def upcoming(self) -> list[ScheduledMeeting]:
        return [m for m in self._queue.values() if m.id not in self._fired]

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="scheduler")
        log.info("Scheduler started")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await asyncio.gather(self._task, return_exceptions=True)
        log.info("Scheduler stopped")

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self._fire_due_meetings()
            except Exception as exc:
                log.error("Scheduler tick failed: %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.CHECK_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                pass

    async def _fire_due_meetings(self) -> None:
        now = datetime.now(timezone.utc)
        for meeting in list(self._queue.values()):
            if meeting.id in self._fired or not meeting.enabled:
                continue
            start = meeting.start_time
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            if start <= now:
                self._fired.add(meeting.id)
                log.info("Firing scheduled meeting %s", meeting.id)
                await self.manager.start_session(meeting)
