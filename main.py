"""Application entry point.

Wires the whole system together and runs it as one process:

  * builds the storage backend (from config),
  * constructs the MeetingManager (multi-session controller),
  * constructs the MeetingScheduler and seeds it from meetings.json (if any),
  * builds the FastAPI dashboard,
  * starts the scheduler inside the FastAPI lifespan and stops everything
    cleanly on shutdown.

Run with:   python main.py
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn

from config import get_settings
from dashboard.dashboard_api import create_app
from manager.meeting_manager import MeetingManager
from scheduler.meeting_scheduler import MeetingScheduler
from utils.logger import get_logger, setup_logging
from utils.models import ScheduledMeeting

SEED_FILE = Path("meetings.json")


def _load_seed_meetings() -> list[ScheduledMeeting]:
    """Optionally load scheduled meetings from a meetings.json file."""
    if not SEED_FILE.exists():
        return []
    raw = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    return [ScheduledMeeting(**item) for item in raw]


def build_application():
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_json)
    log = get_logger("main")

    manager = MeetingManager()
    scheduler = MeetingScheduler(manager)
    scheduler.add_meetings(_load_seed_meetings())

    @asynccontextmanager
    async def lifespan(app):
        log.info(
            "Starting Meeting AI (env=%s, storage=%s, max_sessions=%d)",
            settings.environment, settings.storage_backend,
            settings.max_concurrent_sessions,
        )
        scheduler.start()
        try:
            yield
        finally:
            log.info("Stopping Meeting AI...")
            await scheduler.stop()
            await manager.shutdown()

    app = create_app(manager, scheduler)
    app.router.lifespan_context = lifespan
    return app, settings


app, _settings = build_application()


def main() -> None:
    uvicorn.run(
        app,
        host=_settings.api_host,
        port=_settings.api_port,
        log_level=_settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
