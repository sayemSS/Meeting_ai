"""Dashboard API.

A FastAPI application that exposes the system over HTTP:

  * live status of currently running meetings (from the manager),
  * scheduling and ad-hoc triggering of meetings,
  * retrieval of stored artifacts (metadata, transcript, summary) for any
    completed meeting (from the storage backend).

Built as a factory, create_app(manager, scheduler), so the same wiring is
reusable in tests and in main.py. All persistence goes through the storage
backend, so these endpoints keep working unchanged after a Redis/Oracle
migration.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from manager.meeting_manager import MeetingManager
from scheduler.meeting_scheduler import MeetingScheduler
from utils.helpers import new_session_id
from utils.models import ScheduledMeeting


class CreateMeetingRequest(BaseModel):
    title: str
    meet_url: str
    start_time: datetime | None = None  # None / past => start immediately
    duration_minutes: int = 60
    language: str | None = None


def create_app(manager: MeetingManager, scheduler: MeetingScheduler) -> FastAPI:
    app = FastAPI(title="Meeting AI Assistant", version="1.0.0")

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "active_sessions": manager.active_count}

    @app.get("/sessions/live")
    async def live_sessions() -> dict:
        return {"sessions": manager.live_snapshots()}

    @app.post("/meetings")
    async def create_meeting(req: CreateMeetingRequest) -> dict:
        meeting = ScheduledMeeting(
            id=new_session_id(),
            title=req.title,
            meet_url=req.meet_url,
            start_time=req.start_time or datetime.now(timezone.utc),
            duration_minutes=req.duration_minutes,
            language=req.language,
        )
        start = meeting.start_time
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if start <= datetime.now(timezone.utc):
            await manager.start_session(meeting)
            mode = "started"
        else:
            scheduler.add_meeting(meeting)
            mode = "scheduled"
        return {"session_id": meeting.id, "mode": mode}

    @app.post("/sessions/{session_id}/stop")
    async def stop_session(session_id: str) -> dict:
        ok = await manager.stop_session(session_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Session not running")
        return {"session_id": session_id, "stopping": True}

    @app.get("/meetings/upcoming")
    async def upcoming() -> dict:
        return {"meetings": [m.model_dump() for m in scheduler.upcoming]}

    @app.get("/meetings")
    async def list_meetings() -> dict:
        return {"sessions": await manager.storage.list_sessions()}

    @app.get("/meetings/{session_id}/metadata")
    async def get_metadata(session_id: str) -> dict:
        data = await manager.storage.load_metadata(session_id)
        if data is None:
            raise HTTPException(status_code=404, detail="Metadata not found")
        return data.model_dump()

    @app.get("/meetings/{session_id}/transcript")
    async def get_transcript(session_id: str) -> dict:
        data = await manager.storage.load_transcript(session_id)
        if data is None:
            raise HTTPException(status_code=404, detail="Transcript not found")
        return data.model_dump()

    @app.get("/meetings/{session_id}/summary")
    async def get_summary(session_id: str) -> dict:
        data = await manager.storage.load_summary(session_id)
        if data is None:
            raise HTTPException(status_code=404, detail="Summary not found")
        return data.model_dump()

    return app
