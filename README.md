# Meeting AI Assistant

An enterprise-grade, fully automated meeting assistant for **Google Meet** — inspired by Fireflies.ai. It autonomously joins scheduled or ad-hoc meetings, records audio, tracks participants, captures live captions, transcribes speech with Whisper, generates structured summaries via DeepSeek LLM, and exposes everything through a REST dashboard API. Multiple meetings run in parallel, each in its own fully isolated runtime.

---

## Table of Contents

- [How It Works](#how-it-works)
- [Architecture Overview](#architecture-overview)
- [Project Structure](#project-structure)
- [Pipeline Stages (in detail)](#pipeline-stages-in-detail)
- [Configuration Reference](#configuration-reference)
- [Setup & Installation](#setup--installation)
- [Running the Application](#running-the-application)
- [Dashboard API Reference](#dashboard-api-reference)
- [Output Artifacts](#output-artifacts)
- [Storage Backends & Migration](#storage-backends--migration)
- [Known Limitations & Maintenance](#known-limitations--maintenance)

---

## How It Works

1. **Schedule or trigger** a meeting via the REST API or the `meetings.json` seed file.
2. At the scheduled time, the **Scheduler** hands the meeting to the **Manager**.
3. The Manager spawns an isolated **Session** (bounded by a concurrency semaphore).
4. A **Playwright bot** opens an authenticated Chrome instance, navigates to the Google Meet URL, mutes mic/camera, and clicks "Join now".
5. Once inside, three concurrent collectors start:
   - **Participant Tracker** — polls the People panel for join/leave events.
   - **Caption Listener** — scrapes and de-duplicates live captions from the Meet UI.
   - **Audio Recorder** — captures the system audio input to a WAV file via PyAudio.
6. When the meeting ends (host ends it, bot is removed, max duration reached, or manual stop), the bot leaves gracefully and collectors shut down.
7. **Whisper** transcribes the recorded audio into a time-aligned transcript (runs off the event loop in a thread pool so it never blocks other sessions).
8. **DeepSeek LLM** generates a structured summary: overview, key points, decisions, action items, and sentiment.
9. All artifacts (audio, transcript, metadata, participant timeline, captions, summary) are persisted through a pluggable **Storage Backend**.
10. Everything is queryable through the **FastAPI Dashboard API**.

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                          main.py (entry point)                       │
│  Wires: Settings → Manager → Scheduler → FastAPI app → Uvicorn      │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
              ┌────────────────┴────────────────┐
              │                                 │
   ┌──────────▼──────────┐          ┌───────────▼───────────┐
   │  MeetingScheduler   │  fires   │   MeetingManager      │
   │  (async time-based  │─────────▶│  (multi-session       │
   │   queue, 5s ticks)  │          │   controller)         │
   └─────────────────────┘          └───────────┬───────────┘
                                                │
                              ┌─────────────────┼─────────────────┐
                              │                 │                 │
                       ┌──────▼──────┐  ┌──────▼──────┐  ┌──────▼──────┐
                       │  Session A  │  │  Session B  │  │  Session C  │
                       │ (isolated)  │  │ (isolated)  │  │ (isolated)  │
                       └──────┬──────┘  └─────────────┘  └─────────────┘
                              │
         ┌────────────────────┼────────────────────────┐
         │                    │                        │
  ┌──────▼──────┐  ┌─────────▼─────────┐  ┌──────────▼──────────┐
  │ PlaywrightBot│  │ AudioRecorder     │  │ ParticipantTracker  │
  │ (join/leave) │  │ (PyAudio → WAV)   │  │ + CaptionListener   │
  └──────────────┘  └─────────┬─────────┘  └──────────┬──────────┘
                              │                        │
                   ┌──────────▼──────────┐  ┌──────────▼──────────┐
                   │ WhisperService      │  │ SummaryService      │
                   │ (faster-whisper /   │─▶│ (DeepSeek LLM)      │
                   │  openai-whisper)    │  │                     │
                   └─────────────────────┘  └──────────┬──────────┘
                                                       │
                                            ┌──────────▼──────────┐
                                            │ StorageBackend      │
                                            │ (file / redis /     │
                                            │  oracle)            │
                                            └──────────┬──────────┘
                                                       │
                                            ┌──────────▼──────────┐
                                            │ Dashboard API       │
                                            │ (FastAPI + Uvicorn) │
                                            └─────────────────────┘
```

### Core Design Principles

- **Per-session isolation** — Every `Session` owns its own browser context, audio recorder, collectors, output directory, and logger. Nothing is shared between sessions, so parallel meetings cannot interfere with each other.
- **Bounded concurrency** — `MeetingManager` runs sessions as asyncio tasks gated by an `asyncio.Semaphore` (`MAX_CONCURRENT_SESSIONS`, default 5). New sessions queue until a slot opens.
- **Non-blocking by design** — CPU-bound Whisper transcription runs in a thread pool via `run_blocking()`. All network I/O (DeepSeek API, Playwright) is fully async. One slow meeting never starves the others.
- **Storage abstraction** — The entire pipeline persists through the `StorageBackend` interface. Swapping from file to Redis to Oracle 26ai is a single config change — zero modifications to sessions, manager, or dashboard.
- **Fail-closed sessions** — A session catches all exceptions internally and transitions to `FAILED` state. One broken meeting never crashes the manager or affects other running sessions.

---

## Project Structure

```
Meeting_ai/
├── main.py                          # Application entry point
├── config.py                        # Centralized Settings (pydantic-settings)
├── meetings.json                    # Seed file for pre-scheduled meetings
├── requirements.txt                 # Python dependencies
├── .env                             # Runtime environment overrides
│
├── auth/
│   ├── google_auth.py               # One-time interactive Google login
│   └── chrome_profile/              # Persistent Chrome profile (created by google_auth)
│
├── automation/
│   └── playwright_bot.py            # Playwright-driven Google Meet join/leave/stealth
│
├── captions/
│   └── caption_listener.py          # Live caption scraper with debounce de-duplication
│
├── dashboard/
│   └── dashboard_api.py             # FastAPI REST API factory
│
├── llm/
│   └── deepseek_service.py          # Async DeepSeek chat completions client
│
├── manager/
│   └── meeting_manager.py           # Multi-session controller (semaphore-gated)
│
├── metadata/
│   └── metadata_collector.py        # Aggregates timing, participants, state into metadata
│
├── recorder/
│   └── audio_recorder.py            # PyAudio-based WAV recorder (background thread)
│
├── scheduler/
│   └── meeting_scheduler.py         # Async time-based meeting queue (5s tick loop)
│
├── sessions/
│   └── session.py                   # Isolated per-meeting pipeline orchestrator
│
├── storage/
│   ├── base.py                      # StorageBackend ABC + factory
│   ├── file_storage.py              # Default: JSON files per meeting
│   ├── redis_storage.py             # Migration stub (redis.asyncio)
│   └── oracle_storage.py            # Migration stub (python-oracledb)
│
├── summary/
│   └── summary_service.py           # LLM-powered structured meeting summaries
│
├── tracker/
│   └── participant_tracker.py       # DOM-based join/leave tracking with name filtering
│
├── transcriber/
│   └── whisper_service.py           # Whisper transcription (faster-whisper / openai-whisper)
│
└── utils/
    ├── helpers.py                   # JSON I/O, session ID generation, run_blocking()
    ├── logger.py                    # Logging setup (plain + JSON structured output)
    └── models.py                    # Shared Pydantic domain models and enums
```

---

## Pipeline Stages (in detail)

### 1. Scheduling (`scheduler/meeting_scheduler.py`)

The `MeetingScheduler` maintains an in-memory dictionary of `ScheduledMeeting` objects. An async loop runs every 5 seconds, checks the current UTC time against each meeting's `start_time`, and fires due meetings into the `MeetingManager`. Meetings can also be added on the fly via the API or loaded from `meetings.json` at startup.

Meetings with `enabled: false` are skipped. Once fired, a meeting is moved to a `_fired` set and will not be re-triggered.

### 2. Session Management (`manager/meeting_manager.py`)

The `MeetingManager` is the single source of truth for all running meetings. It:
- Creates a `Session` object for each meeting.
- Runs each session as an `asyncio.Task` gated by a semaphore.
- Tracks active sessions in a registry (dict).
- Supports graceful stop (`request_stop()`) and full shutdown (`shutdown()` cancels all tasks).
- Tasks self-clean from the registry on completion via a done callback.

### 3. Session Lifecycle (`sessions/session.py`)

Each `Session` runs the full pipeline end-to-end and never raises to the caller:

| State           | Description                                                        |
|-----------------|--------------------------------------------------------------------|
| `PENDING`       | Session created, not yet started                                   |
| `JOINING`       | Playwright bot is launching browser and navigating to Meet         |
| `ACTIVE`        | Bot is in the call; tracker, captions, and recorder are running    |
| `LEAVING`       | Meeting ended; collectors stopping, bot leaving                    |
| `RECORDING_DONE`| All live artifacts captured and persisted                          |
| `TRANSCRIBING`  | Whisper is processing audio.wav                                    |
| `SUMMARIZING`   | DeepSeek LLM is generating the structured summary                 |
| `COMPLETED`     | Pipeline finished successfully                                     |
| `FAILED`        | An exception occurred (error message stored)                       |
| `CANCELLED`     | Session was cancelled externally (e.g., shutdown)                  |

**Meeting end detection** combines three signals (checked every 10 seconds):
1. A manual stop was requested via the API.
2. The bot is no longer in the call (URL changed, post-call UI detected, or "Leave call" button gone).
3. Maximum meeting duration elapsed (`min(duration_minutes, MAX_MEETING_MINUTES)` × 60 seconds).

### 4. Browser Automation (`automation/playwright_bot.py`)

The `PlaywrightBot` handles all Google Meet interaction. It supports three **browser connect modes** to bypass Google's automated-browser detection:

| Mode         | How It Works                                                                 | Reliability         |
|--------------|------------------------------------------------------------------------------|---------------------|
| `persistent` | Copies a real Chrome profile (logged in once by hand) per session. Default.  | High (recommended)  |
| `cdp`        | Attaches to an externally launched Chrome via `--remote-debugging-port`.      | Highest (most robust)|
| `launch`     | Fresh browser context + `storage_state.json`. Simplest but often blocked.     | Low (last resort)   |

**Stealth measures** applied to every session:
- `navigator.webdriver` is set to `undefined`.
- Automation-controlled Blink features are disabled.
- A realistic desktop user-agent is injected.
- Media stream prompts are auto-accepted (`--use-fake-ui-for-media-stream`).

**Join flow**: Navigate to Meet URL → wait 8 s for React render → detect login/invalid-meeting errors early → mute mic → mute camera → click "Join now" or "Ask to join" (13 fallback selectors covering text, `role="button"`, and `jsname` variants). A debug screenshot is saved to `%TEMP%` on every run for post-mortem visibility.

**Click strategy** (`_safe_click`): Two-phase approach — Phase 1 uses Playwright's standard `wait_for(state="visible")` + click (fast path). Phase 2 is a retry loop that checks element *existence* (not visibility) and force-clicks, catching buttons stuck behind animations, React re-renders, or overlays that Playwright's visibility heuristic rejects.

**Leave flow**: Click the hang-up button (`aria-label*="Leave call"`).

### 5. Google Authentication (`auth/google_auth.py`)

Google blocks sign-in on browsers it detects as automated. The solution is a one-time manual login:

```bash
python -m auth.google_auth
```

This opens a **real, visible Chrome window** on a dedicated profile directory (`auth/chrome_profile/`). You sign in to Google by hand, press Enter, and the session is saved both in the profile (for persistent mode) and as `storage_state.json` (for launch mode). The bot then reuses copies of this profile for all future sessions.

### 6. Participant Tracking (`tracker/participant_tracker.py`)

Polls the Meet **People panel** every 5 seconds and diffs the current participant set against the previous snapshot. Records `JOIN` and `LEAVE` events with timestamps.

**Panel detection** uses the sidebar's `role="complementary"` wrapper (checked with `.is_visible()`) rather than generic `div[role="listitem"]` selectors, which previously caused false positives — the function would think the panel was already open when it was actually closed, causing the scraper to return stale or empty data and silently miss late joiners.

**DOM reading** tries all selectors (People panel list items, `aria-label`, `data-self-name`, `data-participant-id`) and **merges** their results rather than stopping at the first match. This prevents a broad selector returning partial/noisy data and blocking the more specific ones. If every selector returns empty, a **video-tile fallback** (`_read_from_video_tiles()`) is tried as a last resort.

**Diagnostic logging** is built into every poll cycle: the previous snapshot, current snapshot, joined set, and left set are all logged at `INFO` level. Empty `_read_participants` results emit a `WARNING`. This makes it immediately obvious whether a late-joiner miss is a scraping problem (name never appears in `CURRENT`) or a diff-logic problem (name appears in `CURRENT` but not in `JOINED`).

**Name filtering** is the hardest part — the Meet DOM is full of UI labels, icon ligatures, tooltips, and notices that look like names. The tracker uses a battle-tested denylist of:
- Exact UI words (`"mute"`, `"camera"`, `"settings"`, etc.)
- Substring patterns (`"reducing noise"`, `"others may see"`, etc.)
- Regex patterns (Material icon ligatures like `keep_*`, `frame_*`, `*_outline`, camelCase junk)

Additional validation rejects strings that are too short, purely numeric, lack enough alpha characters, or match browser extension names.

The tracker also opens the People panel automatically (and re-opens it if closed), because silent participants only appear in that list.

**Fallback enrichment**: The `add_known_names()` method accepts names discovered from live caption speakers, catching participants the DOM tracker might have missed.

### 7. Live Caption Capture (`captions/caption_listener.py`)

Google Meet renders live captions that update in place (the latest line keeps growing until the speaker pauses). Naive scraping would produce massive duplication.

The `CaptionListener` solves this with a **debounce mechanism**:
- Polls the caption DOM every 1 second.
- Tracks the last seen text per speaker.
- Only commits a `CaptionEntry` when a line has been **stable for 2.5 seconds** (stopped changing).
- On shutdown, flushes any still-pending lines.

Multiple fallback selectors target different Meet DOM versions. Speaker names are extracted from newline-delimited caption text when available.

Captions serve as a **fallback transcript**: if Whisper produces no output (e.g., audio recording failed), the session falls back to assembling a transcript from the captured captions.

### 8. Audio Recording (`recorder/audio_recorder.py`)

Records meeting audio to `<session_dir>/audio.wav` using **PyAudio** (16-bit PCM, 16kHz, mono by default).

Recording runs on a **dedicated background thread** (PyAudio is blocking). The async session starts and stops it through thread-safe wrappers.

**Input device**: By default, captures the OS default input device (`AUDIO_INPUT_DEVICE_INDEX=-1`). To capture what other participants say (not just your own mic), route the meeting's audio output into a virtual input:
- **Windows**: Install [VB-CABLE](https://vb-audio.com/Cable/), route Meet audio to it, set `AUDIO_INPUT_DEVICE_INDEX` to the CABLE Output index.
- **Linux**: Use a PulseAudio virtual sink monitor.
- **macOS**: Use a virtual audio device like BlackHole.

### 9. Transcription (`transcriber/whisper_service.py`)

Transcribes `audio.wav` into a time-aligned `Transcript` (list of `TranscriptSegment` with `start`, `end`, `text`).

| Engine            | Backend       | Speed     | Parallelism        |
|-------------------|---------------|-----------|--------------------|
| `faster-whisper`  | CTranslate2   | Fast      | Excellent (default)|
| `openai-whisper`  | PyTorch       | Slower    | Good (GPU helps)   |

The model is **loaded lazily and cached** process-wide (keyed by engine + model name + device + compute type). Transcription runs via `run_blocking()` in a thread pool executor, so the CPU/GPU-bound work never stalls the asyncio event loop or other live sessions.

**VAD filtering** is enabled for `faster-whisper` to skip silence. Language can be auto-detected or forced per-meeting via the `language` field in `ScheduledMeeting`.

### 10. AI Summarization (`summary/summary_service.py` + `llm/deepseek_service.py`)

The `SummaryService` sends the transcript to **DeepSeek** (OpenAI-compatible chat completions API) with a constrained prompt requesting a structured JSON response:

```json
{
  "overview": "2-4 sentence meeting summary",
  "key_points": ["main discussion points"],
  "decisions": ["decisions that were made"],
  "action_items": [{"description": "...", "owner": "...", "due": "..."}],
  "sentiment": "positive | neutral | negative | mixed"
}
```

**Safety measures**:
- Transcripts longer than 24,000 characters are truncated.
- The LLM response is forced into JSON mode (`response_format: json_object`).
- Markdown code fences are stripped before parsing.
- If the API call fails, the session returns a `MeetingSummary` with an error message in the overview (never crashes).
- All action items are validated: empty descriptions are dropped, string-only items are wrapped into `ActionItem` objects.

The `DeepSeekService` is a thin async httpx client. All LLM access goes through it, making it trivial to swap providers, add retries, or add streaming in one place.

### 11. Metadata Collection (`metadata/metadata_collector.py`)

A thin assembler that builds the `MeetingMetadata` document from the session clock and the participant tracker:
- Session ID, title, Meet URL
- Scheduled start time, actual start/end times, duration in seconds
- Unique participant list and peak concurrent count
- Final lifecycle state and error message (if any)

---

## Configuration Reference

All configuration lives in `.env` (or environment variables). The `Settings` class in `config.py` is a pydantic-settings model — every field can be overridden by an env var of the same name (case-insensitive).

### General

| Variable                  | Default    | Description                                           |
|---------------------------|------------|-------------------------------------------------------|
| `APP_NAME`                | meeting-ai | Application name (used in logs)                       |
| `ENVIRONMENT`             | local      | `local`, `staging`, or `production`                   |
| `LOG_LEVEL`               | INFO       | Standard Python log level                             |
| `LOG_JSON`                | false      | Use structured JSON logging (for production shipping) |
| `MAX_CONCURRENT_SESSIONS` | 5          | Max parallel meetings (semaphore limit)               |

### Storage

| Variable        | Default  | Description                                |
|-----------------|----------|--------------------------------------------|
| `STORAGE_BACKEND`| file    | `file`, `redis`, or `oracle`               |
| `STORAGE_ROOT`  | meetings | Root directory for file storage             |
| `REDIS_URL`     | —        | Redis connection string (future)            |
| `REDIS_NAMESPACE`| meeting_ai | Redis key namespace (future)            |
| `ORACLE_DSN`    | —        | Oracle connection string (future)           |
| `ORACLE_USER`   | —        | Oracle username (future)                    |
| `ORACLE_PASSWORD`| —       | Oracle password (future)                    |

### Google / Playwright

| Variable               | Default                | Description                                                  |
|------------------------|------------------------|--------------------------------------------------------------|
| `GOOGLE_EMAIL`         | —                      | Google account email (for reference)                         |
| `GOOGLE_PASSWORD`      | —                      | Google account password (for reference)                      |
| `GOOGLE_STORAGE_STATE` | auth/storage_state.json| Path to Playwright storage state file                        |
| `HEADLESS`             | true                   | Run browser headless                                         |
| `BROWSER_CHANNEL`      | chrome                 | Browser channel (use real Chrome for Meet support)           |
| `BROWSER_CONNECT_MODE` | persistent             | `persistent` (recommended), `cdp` (most robust), or `launch` |
| `CHROME_USER_DATA_DIR` | auth/chrome_profile    | Master Chrome profile directory (persistent mode)            |
| `CDP_ENDPOINT`          | http://localhost:9222  | Chrome DevTools Protocol endpoint (cdp mode)                |
| `BROWSER_USER_AGENT`   | Chrome 124 on Win10   | Custom user-agent string                                     |
| `JOIN_TIMEOUT_SECONDS` | 60                     | Max time to wait for the Join button                         |
| `MAX_MEETING_MINUTES`  | 180                    | Max meeting duration before auto-leave                       |

### Audio Recorder

| Variable                 | Default | Description                                           |
|--------------------------|---------|-------------------------------------------------------|
| `AUDIO_INPUT_DEVICE_INDEX`| -1     | PyAudio device index (-1 = OS default input)          |
| `AUDIO_SAMPLE_RATE`      | 16000   | Sample rate in Hz (16kHz is optimal for Whisper)      |
| `AUDIO_CHANNELS`         | 1       | Number of audio channels (mono recommended)           |
| `AUDIO_INPUT_FORMAT`     | pulse   | ffmpeg input format (Linux/PulseAudio)                |
| `AUDIO_INPUT_DEVICE`     | default | ffmpeg device name (advanced/non-Windows)             |

### Whisper Transcription

| Variable              | Default        | Description                                         |
|-----------------------|----------------|-----------------------------------------------------|
| `WHISPER_ENGINE`      | faster-whisper | `faster-whisper` (recommended) or `openai-whisper`  |
| `WHISPER_MODEL`       | base           | Model size: `tiny`, `base`, `small`, `medium`, `large` |
| `WHISPER_DEVICE`      | auto           | `auto`, `cpu`, or `cuda`                            |
| `WHISPER_COMPUTE_TYPE`| int8           | Quantization: `int8`, `float16`, `float32`          |
| `WHISPER_LANGUAGE`    | *(empty=auto)* | Force a language code (e.g., `en`, `fr`, `es`)      |

### DeepSeek LLM

| Variable                | Default                  | Description                          |
|-------------------------|--------------------------|--------------------------------------|
| `DEEPSEEK_API_KEY`      | —                        | DeepSeek API key (required)          |
| `DEEPSEEK_BASE_URL`     | https://api.deepseek.com | API base URL                         |
| `DEEPSEEK_MODEL`        | deepseek-chat            | Model name                           |
| `DEEPSEEK_TIMEOUT_SECONDS`| 120                    | Request timeout                      |
| `DEEPSEEK_MAX_TOKENS`   | 2048                     | Max response tokens                  |
| `DEEPSEEK_TEMPERATURE`  | 0.3                      | Sampling temperature (low = focused) |

### Dashboard API

| Variable   | Default   | Description                |
|------------|-----------|----------------------------|
| `API_HOST` | 0.0.0.0   | Bind address               |
| `API_PORT` | 8000      | Bind port                  |

---

## Setup & Installation

### Prerequisites

- **Python 3.11+**
- **Google Chrome** installed (the bot uses the real Chrome channel, not Playwright's bundled Chromium)
- **Audio input device** (microphone, VB-CABLE, Stereo Mix, or PulseAudio virtual sink)

### Install Dependencies

```bash
pip install -r requirements.txt
playwright install chrome
```

### One-Time Google Authentication

Google blocks sign-in on automated browsers. You must log in once inside a real Chrome profile:

```bash
python -m auth.google_auth
```

This opens a visible Chrome window. Sign in to the Google account the bot should use, then press **Enter** in the terminal. The session is saved to `auth/chrome_profile/` and reused by all future sessions.

**Alternative (CDP mode)**: Launch Chrome yourself with `--remote-debugging-port=9222`, log in normally, then set `BROWSER_CONNECT_MODE=cdp` in `.env`.

### Configure Environment

Edit `.env` to set at minimum:
- `DEEPSEEK_API_KEY` — your DeepSeek API key
- `AUDIO_INPUT_DEVICE_INDEX` — if using a virtual audio device (VB-CABLE, etc.)
- `WHISPER_MODEL` — `small` or `medium` for better accuracy (default `base` is fast but less accurate)

### Optional: Headless Server Setup

For running on a headless Linux server, you additionally need:
- **ffmpeg** — audio processing
- **Xvfb** — virtual display (`xvfb-run python main.py`)
- **PulseAudio** — virtual sink to route Chrome audio to a recordable input

---

## Running the Application

```bash
python main.py
```

The application:
1. Loads configuration from `.env`.
2. Sets up logging (plain text or structured JSON).
3. Creates the `MeetingManager` and `MeetingScheduler`.
4. Seeds the scheduler with any meetings from `meetings.json`.
5. Builds the FastAPI dashboard app.
6. Starts the scheduler (async background loop).
7. Serves the API on `http://localhost:8000` via Uvicorn.

On shutdown (Ctrl+C), the scheduler stops, all running sessions are cancelled gracefully, and the process exits cleanly.

### Seed File (`meetings.json`)

Pre-schedule meetings by placing them in `meetings.json`:

```json
[
  {
    "id": "demo001",
    "title": "Weekly Engineering Sync",
    "meet_url": "https://meet.google.com/abc-defg-hij",
    "start_time": "2026-06-09T15:00:00+00:00",
    "duration_minutes": 60,
    "language": null,
    "enabled": true
  }
]
```

---

## Dashboard API Reference

The API is available at `http://localhost:8000` (configurable via `API_HOST` / `API_PORT`).

### Endpoints

| Method | Path                            | Description                                         |
|--------|---------------------------------|-----------------------------------------------------|
| GET    | `/health`                       | Liveness check + active session count               |
| GET    | `/sessions/live`                | Live status of all running meetings                 |
| POST   | `/meetings`                     | Start a meeting now or schedule for later           |
| POST   | `/sessions/{id}/stop`           | Gracefully leave a running meeting                  |
| GET    | `/meetings/upcoming`            | List scheduled (not yet started) meetings           |
| GET    | `/meetings`                     | List all completed session IDs                      |
| GET    | `/meetings/{id}/metadata`       | Meeting metadata (timing, participants, state)      |
| GET    | `/meetings/{id}/transcript`     | Full time-aligned transcript                        |
| GET    | `/meetings/{id}/summary`        | Structured AI summary                               |

### Start a Meeting Immediately

```bash
curl -X POST http://localhost:8000/meetings \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Standup",
    "meet_url": "https://meet.google.com/abc-defg-hij",
    "duration_minutes": 30
  }'
```

Response:
```json
{"session_id": "a1b2c3d4e5f6", "mode": "started"}
```

If `start_time` is provided and is in the future, the meeting is scheduled instead:
```json
{"session_id": "a1b2c3d4e5f6", "mode": "scheduled"}
```

### Stop a Running Meeting

```bash
curl -X POST http://localhost:8000/sessions/a1b2c3d4e5f6/stop
```

### Check Live Status

```bash
curl http://localhost:8000/sessions/live
```

Returns:
```json
{
  "sessions": [
    {
      "session_id": "demo001",
      "title": "Weekly Engineering Sync",
      "state": "active",
      "participants": ["Alice", "Bob", "Charlie"],
      "peak_participants": 5,
      "captions": 42,
      "error": null
    }
  ]
}
```

---

## Output Artifacts

Each meeting produces a directory under `<STORAGE_ROOT>/meeting_<session_id>/`:

```
meetings/meeting_<session_id>/
├── audio.wav                    # Raw recorded audio (16kHz mono WAV)
├── transcript.txt               # Plain text transcript
├── transcript.json              # Time-aligned transcript with segments
├── metadata.json                # Meeting metadata (timing, participants, state)
├── participant_timeline.json    # Join/leave events with timestamps
├── captions.json                # De-duplicated live captions
└── summary.json                 # AI-generated structured summary
```

### Example `summary.json`

```json
{
  "session_id": "demo001",
  "overview": "The team discussed the Q3 roadmap and prioritized the authentication migration...",
  "key_points": [
    "Authentication migration to OAuth 2.1 is the top priority",
    "Performance benchmarks show a 40% improvement after the database index changes"
  ],
  "decisions": [
    "Postpone the dashboard redesign to Q4",
    "Adopt faster-whisper as the default transcription engine"
  ],
  "action_items": [
    {"description": "Draft the OAuth migration plan", "owner": "Alice", "due": "2026-06-15"},
    {"description": "Set up load testing environment", "owner": "Bob", "due": null}
  ],
  "sentiment": "positive",
  "generated_at": "2026-06-10T15:32:00+00:00"
}
```

---

## Storage Backends & Migration

### Current: File Storage (`storage/file_storage.py`)

Writes JSON files per meeting. Atomic writes (write to `.tmp`, then rename) prevent corruption. Fully implemented and production-ready.

### Future: Redis (`storage/redis_storage.py`)

Currently a **stub** (raises `NotImplementedError`). Implementation plan:
- Store each artifact as a JSON string under `{namespace}:{session_id}:{artifact}`.
- Maintain a sorted set of session IDs for listing.
- Use `redis.asyncio` for non-blocking I/O.
- Enable with: `STORAGE_BACKEND=redis` + `pip install redis>=5.0`.

### Future: Oracle 26ai (`storage/oracle_storage.py`)

Currently a **stub** (raises `NotImplementedError`). Implementation plan:
- Use `python-oracledb` (async) with native JSON columns.
- One table per artifact type, keyed by `session_id`.
- Transcripts are well-suited to Oracle's **AI Vector Search** for semantic queries.
- Enable with: `STORAGE_BACKEND=oracle` + `pip install oracledb>=2.0`.

Switching backends requires **zero code changes** — only the `.env` configuration and implementing the `StorageBackend` ABC methods.

---

## Known Limitations & Maintenance

- **Google Meet DOM selectors** — The selectors in `automation/`, `tracker/`, and `captions/` depend on Google Meet's DOM structure and `aria-label` attributes, which change frequently and can differ by locale. Treat them as configuration that needs periodic maintenance. The join flow includes `jsname` fallbacks (`Qx7uuf`, `r8g1K`) which also rotate with Meet updates; if joining breaks, inspect the failure screenshot at `%TEMP%\meet_join_failed_<session_id>.png` to identify the new DOM structure.
- **Audio capture** — PyAudio captures the default input device. To record what other participants say, you must set up a virtual audio device (VB-CABLE, PulseAudio sink, etc.) to route Meet's output into a recordable input.
- **Google bot detection** — Google actively detects and blocks automated browsers. The `persistent` and `cdp` connect modes are the most reliable workarounds. The `launch` mode (fresh context) is frequently blocked.
- **Whisper accuracy** — The `base` model is fast but less accurate for multi-speaker or noisy audio. Use `small` or `medium` for production. GPU acceleration (`WHISPER_DEVICE=cuda`) significantly speeds up larger models.
- **Transcript truncation** — Summaries are generated from at most 24,000 characters of transcript text. Very long meetings may lose content in the summary (the full transcript is always preserved).
- **No speaker diarization** — Whisper produces time-aligned segments but does not identify speakers. The `speaker` field on `TranscriptSegment` is currently unused. Speaker identification would require an additional diarization step (e.g., pyannote.audio).
