# Meeting AI Assistant

An enterprise-grade, multi-session meeting assistant (Fireflies.ai-style) for
Google Meet. It joins meetings, records audio, tracks participants, captures
live captions, transcribes with Whisper, summarizes with DeepSeek, and serves
everything through a dashboard API. Multiple meetings run fully in parallel,
each in its own isolated runtime.

## Pipeline

```
Scheduler -> Manager (multi-session) -> Session (isolated runtime)
   -> Playwright Meet bot
   -> Participant Tracker + Caption Listener + Metadata Collector + Audio Recorder
   -> Whisper transcription -> transcript.json / transcript.txt
   -> DeepSeek LLM -> Summary
   -> Storage backend (JSON files per meeting)
   -> Dashboard API
```

## Architecture principles

- **Per-session isolation.** Every `Session` owns its own browser context,
  collectors, output directory, and logger. Nothing is shared, so meetings
  cannot interfere with each other.
- **Bounded concurrency.** `MeetingManager` runs sessions as asyncio tasks
  gated by a semaphore (`MAX_CONCURRENT_SESSIONS`).
- **Storage abstraction.** The whole pipeline persists through the
  `StorageBackend` interface. `file` is implemented today; `redis` and
  `oracle` (Oracle 26ai) are wired stubs so migration is a config change.
- **Non-blocking by design.** CPU-bound Whisper work runs in a thread pool;
  network/LLM calls are async. One slow meeting never blocks the others.

## Setup

```bash
pip install -r requirements.txt
playwright install chrome

# One-time: log in to Google and save the browser session
python -m auth.google_auth

# Configure the system
cp .env .env.local   # then edit values (DeepSeek key, audio device, etc.)
```

For headless server recording you also need: `ffmpeg`, `Xvfb` (virtual
display), and a PulseAudio virtual sink routed from Chrome.

## Run

```bash
python main.py
```

The dashboard is then available at `http://localhost:8000`.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET  | `/health` | liveness + active session count |
| GET  | `/sessions/live` | live status of running meetings |
| POST | `/meetings` | start now or schedule a meeting |
| POST | `/sessions/{id}/stop` | gracefully leave a running meeting |
| GET  | `/meetings/upcoming` | scheduled (not yet started) meetings |
| GET  | `/meetings` | list completed session ids |
| GET  | `/meetings/{id}/metadata` | meeting metadata |
| GET  | `/meetings/{id}/transcript` | full transcript |
| GET  | `/meetings/{id}/summary` | structured summary |

Start a meeting immediately:

```bash
curl -X POST http://localhost:8000/meetings \
  -H "Content-Type: application/json" \
  -d '{"title":"Standup","meet_url":"https://meet.google.com/abc-defg-hij"}'
```

## Output layout

```
meetings/meeting_<session_id>/
    audio.wav
    transcript.txt
    transcript.json
    metadata.json
    participant_timeline.json
    captions.json
    summary.json
```

## Migration notes

- **Redis:** implement `storage/redis_storage.py` (store each artifact as a
  JSON string under `{namespace}:{session_id}:{artifact}`), then set
  `STORAGE_BACKEND=redis`.
- **Oracle 26ai:** implement `storage/oracle_storage.py` with `python-oracledb`
  using native JSON columns (transcripts are well-suited to AI Vector Search),
  then set `STORAGE_BACKEND=oracle`.

The selectors in `automation/`, `tracker/`, and `captions/` depend on Google
Meet's DOM and may need periodic maintenance.
