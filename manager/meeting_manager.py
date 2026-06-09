"""Meeting Manager: the multi-session controller.

Owns the registry of all sessions and runs them concurrently as asyncio
tasks, bounded by a semaphore (max_concurrent_sessions). This is the single
component that knows about "all meetings happening right now"; the dashboard
queries it for live status, and the scheduler asks it to start new meetings.

Design choices:
  * One storage backend instance is shared (it is stateless/thread-safe per
    session_id), but every Session is otherwise fully isolated.
  * Tasks self-clean from the registry on completion to avoid leaks.
  * shutdown() cancels everything gracefully for a clean process exit.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from config import get_settings
from sessions.session import Session
from storage.base import StorageBackend, build_storage_backend
from utils.logger import get_logger
from utils.models import ScheduledMeeting

log = get_logger(__name__)


class MeetingManager:
    """Starts, tracks, and stops independent meeting sessions in parallel."""

    def __init__(self, storage: Optional[StorageBackend] = None) -> None:
        self._settings = get_settings()
        self.storage: StorageBackend = storage or build_storage_backend(
            self._settings.storage_backend
        )
        self._semaphore = asyncio.Semaphore(self._settings.max_concurrent_sessions)
        self._sessions: dict[str, Session] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def start_session(self, meeting: ScheduledMeeting) -> Optional[str]:
        """Start a meeting session. Returns the session id, or None if duplicate."""
        async with self._lock:
            if meeting.id in self._sessions:
                log.warning("Session %s already running; ignoring", meeting.id)
                return None
            session = Session(meeting, self.storage)
            self._sessions[meeting.id] = session
            task = asyncio.create_task(
                self._run_guarded(session), name=f"session-{meeting.id}"
            )
            self._tasks[meeting.id] = task
            task.add_done_callback(lambda t, sid=meeting.id: self._on_done(sid))
        log.info("Started session %s (%s)", meeting.id, meeting.title)
        return meeting.id

    async def _run_guarded(self, session: Session) -> None:
        """Run a session while holding a concurrency slot."""
        async with self._semaphore:
            await session.run()

    def _on_done(self, session_id: str) -> None:
        self._tasks.pop(session_id, None)
        log.info("Session %s finished", session_id)

    async def stop_session(self, session_id: str) -> bool:
        """Ask a running session to leave its meeting gracefully."""
        session = self._sessions.get(session_id)
        if session is None:
            return False
        session.request_stop()
        return True

    def get_session(self, session_id: str) -> Optional[Session]:
        return self._sessions.get(session_id)

    def live_snapshots(self) -> list[dict]:
        """Status of every session the manager currently knows about."""
        return [s.snapshot() for s in self._sessions.values()]

    @property
    def active_count(self) -> int:
        return len(self._tasks)

    async def shutdown(self) -> None:
        """Cancel all running sessions and wait for them to unwind."""
        log.info("Shutting down %d active session(s)", len(self._tasks))
        for session in self._sessions.values():
            session.request_stop()
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
