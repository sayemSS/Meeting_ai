"""Re-process an already-recorded meeting from its audio.wav.

Use this after fixing Whisper settings (model size, VAD, language) to
recover a meeting whose first transcription went wrong — no need to hold
the meeting again. It re-runs: transcription -> summary -> report.md ->
report.pdf, overwriting the files in the meeting folder.

Usage:
    python -m tools.retranscribe <session_id> [language]

Examples:
    python -m tools.retranscribe 17e88688ad94 bn
    python -m tools.retranscribe 17e88688ad94        (auto-detect)
"""

from __future__ import annotations

import asyncio
import sys

from config import get_settings
from storage.file_storage import FileStorageBackend
from summary.summary_service import SummaryService
from transcriber.whisper_service import WhisperService
from utils.logger import get_logger

log = get_logger(__name__)


async def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    session_id = sys.argv[1]
    language = sys.argv[2] if len(sys.argv) > 2 else None

    settings = get_settings()
    session_dir = settings.session_dir(session_id)
    audio_path = session_dir / "audio.wav"
    if not audio_path.exists():
        log.error("No audio.wav in %s", session_dir)
        sys.exit(1)

    storage = FileStorageBackend()
    metadata = await storage.load_metadata(session_id)
    if metadata is None:
        log.error("No metadata for session %s", session_id)
        sys.exit(1)

    log.info("Re-transcribing %s (language=%s, model=%s)...",
             audio_path, language or "auto", settings.whisper_model)
    transcript = await WhisperService(session_id).transcribe(audio_path, language=language)
    await storage.save_transcript(session_id, transcript)
    log.info("Transcript: %d segments, language=%s",
             len(transcript.segments), transcript.language)
    preview = transcript.full_text[:300]
    log.info("Preview: %s%s", preview, "..." if len(transcript.full_text) > 300 else "")

    log.info("Re-generating summary...")
    summary = await SummaryService(session_id, language=language).summarize(transcript)
    await storage.save_summary(session_id, summary)

    # report.md (if the builder exists in this project)
    try:
        from summary.report_builder import build_report

        (session_dir / "report.md").write_text(
            build_report(metadata, summary), encoding="utf-8"
        )
        log.info("report.md regenerated")
    except Exception as exc:
        log.warning("report.md skipped: %s", exc)

    # report.pdf
    try:
        from report.report_service import ReportService

        await ReportService().build(metadata, summary, session_dir / "report.pdf")
        log.info("report.pdf regenerated")
    except Exception as exc:
        log.warning("report.pdf skipped: %s", exc)

    log.info("Done. Files updated in %s", session_dir)


if __name__ == "__main__":
    asyncio.run(main())