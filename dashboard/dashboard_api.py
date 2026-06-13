"""Dashboard API (v2 — single-user / CEO workflow).

FastAPI application exposing the complete workflow the CEO needs:

  CREATE   POST /meetings                     one meeting (link + name)
           POST /meetings/bulk                several meetings at once
  MONITOR  GET  /sessions/live                what is running right now
           POST /sessions/{id}/stop           leave a meeting early
  BROWSE   GET  /meetings                     list with title/date/state
           GET  /meetings/search              by name and/or date range
  READ     GET  /meetings/{id}                everything about one meeting
           GET  /meetings/{id}/metadata
           GET  /meetings/{id}/transcript
           GET  /meetings/{id}/summary
           GET  /meetings/{id}/report.pdf     management PDF (auto-built)

All persistence goes through the storage backend, so every endpoint keeps
working unchanged after the Oracle 26ai migration — only the backend class
changes.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from config import get_settings
from manager.meeting_manager import MeetingManager
from scheduler.meeting_scheduler import MeetingScheduler
from utils.helpers import new_session_id, read_json, run_blocking, write_json
from utils.language import resolve_report_language
from utils.models import (
    MeetingMetadata,
    MeetingSummary,
    ScheduledMeeting,
    Transcript,
    TranscriptSegment,
)


from typing import Literal

# Language choices for a meeting. "auto" (default) lets Whisper detect the
# language and the report follows the transcript's language. The UI dropdown
# should be built from GET /config/languages so it never goes out of sync.
MeetingLanguage = Literal["auto", "bn", "en", "mixed"]

_LANGUAGE_OPTIONS = [
    {"code": "auto", "label": "Auto-detect", "label_bn": "স্বয়ংক্রিয়"},
    {"code": "bn", "label": "Bangla", "label_bn": "বাংলা"},
    {"code": "en", "label": "English", "label_bn": "ইংরেজি"},
    {"code": "mixed", "label": "Bangla-English Mixed", "label_bn": "বাংলা-ইংরেজি মিশ্র"},
]


class CreateMeetingRequest(BaseModel):
    title: str
    meet_url: str
    start_time: datetime | None = None  # None / past => start immediately
    duration_minutes: int = 60
    # "auto" = detect; "bn"/"en" force Whisper; "mixed" = detect + Bangla
    # report with English terms kept. None is treated as "auto".
    language: MeetingLanguage | None = "auto"


class BulkCreateRequest(BaseModel):
    meetings: list[CreateMeetingRequest]


def _meeting_row(meta: MeetingMetadata) -> dict:
    """Compact row for list/search responses (what a meeting list UI needs)."""
    return {
        "session_id": meta.session_id,
        "title": meta.title,
        "meet_url": meta.meet_url,
        "date": meta.actual_start or meta.scheduled_start,
        "duration_seconds": meta.duration_seconds,
        "participants": meta.unique_participants,
        "state": meta.state.value,
        "error": meta.error,
    }


def create_app(manager: MeetingManager, scheduler: MeetingScheduler) -> FastAPI:
    app = FastAPI(title="Meeting AI Assistant", version="2.0.0")
    settings = get_settings()

    # Allow the separate dashboard frontend (e.g. http://localhost:3000) to
    # call this API from the browser. Without this, the browser's preflight
    # OPTIONS request is rejected with 405 and every fetch fails with
    # "Failed to fetch". allow_origins="*" is fine for a local/single-user
    # setup; tighten it to the real dashboard origin in production.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    async def _load_all_metadata() -> list[MeetingMetadata]:
        session_ids = await manager.storage.list_sessions()
        metas = await asyncio.gather(
            *(manager.storage.load_metadata(sid) for sid in session_ids)
        )
        return [m for m in metas if m is not None]

    async def _schedule_or_start(req: CreateMeetingRequest) -> dict:
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
        return {"session_id": meeting.id, "title": meeting.title, "mode": mode}

    # ------------------------------------------------------------------ #
    # Health / live
    # ------------------------------------------------------------------ #
    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "active_sessions": manager.active_count}

    @app.get("/config/languages")
    async def language_options() -> dict:
        """Options for the UI's language dropdown (default first)."""
        return {"languages": _LANGUAGE_OPTIONS, "default": "auto"}

    @app.get("/sessions/live")
    async def live_sessions() -> dict:
        return {"sessions": manager.live_snapshots()}

    @app.post("/sessions/{session_id}/stop")
    async def stop_session(session_id: str) -> dict:
        ok = await manager.stop_session(session_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Session not running")
        return {"session_id": session_id, "stopping": True}

    # ------------------------------------------------------------------ #
    # Create
    # ------------------------------------------------------------------ #
    @app.post("/meetings")
    async def create_meeting(req: CreateMeetingRequest) -> dict:
        return await _schedule_or_start(req)

    @app.post("/meetings/bulk")
    async def create_meetings_bulk(req: BulkCreateRequest) -> dict:
        """Start/schedule several meetings in one request.

        The manager's MAX_CONCURRENT_SESSIONS guard still applies; extra
        meetings simply wait their turn.
        """
        results = [await _schedule_or_start(m) for m in req.meetings]
        return {"created": results, "count": len(results)}

    @app.get("/meetings/upcoming")
    async def upcoming() -> dict:
        return {"meetings": [m.model_dump() for m in scheduler.upcoming]}

    # ------------------------------------------------------------------ #
    # Browse / search
    # ------------------------------------------------------------------ #
    @app.get("/meetings")
    async def list_meetings() -> dict:
        """All meetings, newest first, with the fields a list UI needs."""
        metas = await _load_all_metadata()
        metas.sort(
            key=lambda m: (m.actual_start or m.scheduled_start or datetime.min.replace(tzinfo=timezone.utc)),
            reverse=True,
        )
        return {"meetings": [_meeting_row(m) for m in metas], "count": len(metas)}

    @app.get("/meetings/search")
    async def search_meetings(
        name: str | None = Query(default=None, description="Match in meeting title (case-insensitive)"),
        date_from: datetime | None = Query(default=None, description="Meetings on/after this date"),
        date_to: datetime | None = Query(default=None, description="Meetings on/before this date"),
    ) -> dict:
        """Search by meeting name and/or date range. All filters combine."""
        metas = await _load_all_metadata()
        results: list[MeetingMetadata] = []
        for m in metas:
            if name and name.lower() not in (m.title or "").lower():
                continue
            when = m.actual_start or m.scheduled_start
            if date_from is not None:
                df = date_from if date_from.tzinfo else date_from.replace(tzinfo=timezone.utc)
                if when is None or when < df:
                    continue
            if date_to is not None:
                dt_ = date_to if date_to.tzinfo else date_to.replace(tzinfo=timezone.utc)
                if when is None or when > dt_:
                    continue
            results.append(m)
        results.sort(
            key=lambda m: (m.actual_start or m.scheduled_start or datetime.min.replace(tzinfo=timezone.utc)),
            reverse=True,
        )
        return {"meetings": [_meeting_row(m) for m in results], "count": len(results)}

    # ------------------------------------------------------------------ #
    # Read one meeting
    # ------------------------------------------------------------------ #
    @app.get("/meetings/{session_id}")
    async def get_meeting(session_id: str) -> dict:
        """Everything about one meeting in a single call (for a detail page).

        metadata.json is only written once the meeting ends, so while a meeting
        is still running we synthesise a metadata view from the live session.
        This lets the detail page (and its live-captions tab) open mid-meeting.
        """
        meta = await manager.storage.load_metadata(session_id)
        if meta is None:
            live = manager.get_session(session_id)
            if live is not None:
                snap = live.snapshot()
                return {
                    "metadata": {
                        "session_id": session_id,
                        "title": snap["title"],
                        "meet_url": live.meeting.meet_url,
                        "language": None,
                        "scheduled_start": None,
                        "actual_start": None,
                        "actual_end": None,
                        "duration_seconds": 0.0,
                        "unique_participants": snap["participants"],
                        "peak_participant_count": snap["peak_participants"],
                        "state": snap["state"],
                        "error": snap["error"],
                    },
                    "summary": None,
                    "live": True,
                }
            raise HTTPException(status_code=404, detail="Meeting not found")
        summary = await manager.storage.load_summary(session_id)
        return {
            "metadata": meta.model_dump(),
            "summary": summary.model_dump() if summary else None,
            "live": False,
        }

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

    @app.get("/meetings/{session_id}/captions")
    async def get_captions(session_id: str) -> dict:
        """Live captions while the meeting is running (read from the active
        session in memory), or the saved captions.json once it has ended.

        `live` is True while the meeting is still in progress, so the UI knows
        to keep polling; the Whisper transcript replaces these afterwards.
        """
        live = manager.get_session(session_id)
        if live is not None:
            caps = live.caption_entries()
            return {"captions": [c.model_dump() for c in caps], "live": True}
        saved = await manager.storage.load_captions(session_id)
        return {"captions": [c.model_dump() for c in saved], "live": False}

    @app.get("/meetings/{session_id}/summary")
    async def get_summary(session_id: str) -> dict:
        data = await manager.storage.load_summary(session_id)
        if data is None:
            raise HTTPException(status_code=404, detail="Summary not found")
        return data.model_dump()

    @app.post("/meetings/{session_id}/quick-summary")
    async def make_quick_summary(session_id: str) -> dict:
        """Generate an on-demand summary from the captions captured so far.

        This is the fast "urgent" preview: it uses the live (or saved) Meet
        captions instead of waiting for the full Whisper transcript. The result
        is saved separately as quick_summary.json so it never overwrites the
        final transcript-based summary.json.
        """
        live = manager.get_session(session_id)
        if live is not None:
            caps = live.caption_entries()
            requested_lang = live.meeting.language
        else:
            caps = await manager.storage.load_captions(session_id)
            requested_lang = None
        caps = [c for c in caps if c.text and c.text.strip()]
        if not caps:
            raise HTTPException(
                status_code=404,
                detail="No captions captured yet (are Meet captions ON?)",
            )

        transcript = Transcript(
            segments=[
                TranscriptSegment(start=0.0, end=0.0, text=c.text, speaker=c.speaker)
                for c in caps
            ]
        )
        report_language = resolve_report_language(requested_lang, transcript.language)
        from summary.summary_service import SummaryService

        summary = await SummaryService(
            session_id, language=report_language
        ).summarize(transcript)
        await run_blocking(
            write_json,
            settings.session_dir(session_id) / "quick_summary.json",
            summary,
        )
        return {
            "summary": summary.model_dump(),
            "source": "captions",
            "caption_lines": len(caps),
        }

    @app.get("/meetings/{session_id}/quick-summary")
    async def get_quick_summary(session_id: str) -> dict:
        """Return the previously generated caption-based quick summary, if any."""
        path = settings.session_dir(session_id) / "quick_summary.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail="No quick summary yet")
        return MeetingSummary(**read_json(path)).model_dump()

    @app.get("/meetings/{session_id}/report.pdf")
    async def get_report_pdf(session_id: str) -> FileResponse:
        """Download the management PDF report; built on demand if missing."""
        pdf_path = settings.session_dir(session_id) / "report.pdf"
        if not pdf_path.exists():
            meta = await manager.storage.load_metadata(session_id)
            summary = await manager.storage.load_summary(session_id)
            if meta is None or summary is None:
                raise HTTPException(
                    status_code=404,
                    detail="Report not ready (metadata or summary missing)",
                )
            from report.report_service import ReportService

            await ReportService().build(meta, summary, pdf_path)
        safe_title = "meeting-report"
        return FileResponse(
            path=str(pdf_path),
            media_type="application/pdf",
            filename=f"{safe_title}-{session_id}.pdf",
        )

    return app