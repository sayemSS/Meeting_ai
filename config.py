"""Central configuration for the Meeting AI Assistant.

All runtime configuration is loaded from environment variables (.env) and
exposed as a single, cached Settings object. Keeping configuration in one
place means the rest of the codebase never calls os.getenv directly, which
makes it trivial to retarget the system at a new environment (local,
staging, production) or a new storage backend (file -> Redis -> Oracle 26ai).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed application settings.

    Every value can be overridden through an environment variable of the
    same (upper-cased) name, or through a key in the .env file.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ----- General -----------------------------------------------------
    app_name: str = "meeting-ai"
    environment: Literal["local", "staging", "production"] = "local"
    log_level: str = "INFO"
    log_json: bool = False

    # ----- Concurrency -------------------------------------------------
    # Maximum number of Google Meet sessions that may run at the same time.
    max_concurrent_sessions: int = 5

    # ----- Storage -----------------------------------------------------
    # Selects the storage backend implementation. Today only "file" is
    # implemented; "redis" and "oracle" are wired as stubs so the rest of
    # the system is already decoupled from the persistence mechanism.
    storage_backend: Literal["file", "redis", "oracle"] = "file"
    storage_root: Path = Path("meetings")

    # Redis (future migration target) ----------------------------------
    redis_url: str = "redis://localhost:6379/0"
    redis_namespace: str = "meeting_ai"

    # Oracle 26ai (future migration target) ----------------------------
    oracle_dsn: str = ""
    oracle_user: str = ""
    oracle_password: str = ""

    # ----- Google / Playwright -----------------------------------------
    google_email: str = ""
    google_password: str = ""
    # Path to a Playwright storage_state.json holding an authenticated
    # Google session. Far safer than typing credentials on every run.
    google_storage_state: Path = Path("auth/storage_state.json")
    headless: bool = True
    browser_channel: str = "chrome"  # use the real Chrome for Meet support

    # How the bot obtains an authenticated browser. Google blocks login on
    # browsers it detects as automated, so prefer "persistent" or "cdp":
    #   persistent -> reuse a real Chrome profile (login once by hand)
    #   cdp        -> attach to your own already-logged-in Chrome (most robust)
    #   launch     -> fresh context + storage_state (often blocked by Google)
    browser_connect_mode: Literal["persistent", "cdp", "launch"] = "persistent"
    # Master Chrome profile directory used for persistent mode. The bot makes
    # a per-session copy of this so parallel sessions don't lock each other.
    chrome_user_data_dir: Path = Path("auth/chrome_profile")
    # Endpoint of an externally launched Chrome started with
    # --remote-debugging-port=9222 (used only in cdp mode).
    cdp_endpoint: str = "http://localhost:9222"
    # A realistic desktop user-agent helps avoid the "unsupported browser" page.
    browser_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    join_timeout_seconds: int = 60
    # How long to stay in the meeting if no explicit end is detected.
    max_meeting_minutes: int = 180

    # ----- Audio recorder ----------------------------------------------
    # ffmpeg input. On Linux with PulseAudio a virtual sink monitor is the
    # typical source, e.g. "meeting_sink.monitor".
    audio_input_format: str = "pulse"
    audio_input_device: str = "default"
    # PyAudio input device index. -1 = use the OS default input device.
    # Use `python -m recorder.list_devices` to find the index of e.g. VB-CABLE.
    audio_input_device_index: int = -1
    audio_sample_rate: int = 16000
    audio_channels: int = 1

    # ----- Whisper transcription ---------------------------------------
    # Engine: "faster-whisper" (recommended) or "openai-whisper".
    whisper_engine: Literal["faster-whisper", "openai-whisper"] = "faster-whisper"
    whisper_model: str = "base"
    whisper_device: str = "auto"  # auto | cpu | cuda
    whisper_compute_type: str = "int8"
    whisper_language: str = ""  # empty = auto-detect

    # ----- DeepSeek LLM ------------------------------------------------
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    deepseek_timeout_seconds: int = 120
    deepseek_max_tokens: int = 2048
    deepseek_temperature: float = 0.3

    # ----- Dashboard API -----------------------------------------------
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    def session_dir(self, session_id: str) -> Path:
        """Return the per-meeting output directory for a session id."""
        return self.storage_root / f"meeting_{session_id}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide cached Settings instance."""
    return Settings()  # type: ignore[call-arg]