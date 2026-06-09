"""Audio recorder (PyAudio backend).

Records one meeting's audio to <session_dir>/audio.wav using PyAudio. This
backend captures the operating system's default input device directly, so on
Windows it "just works" without naming a device or matching exact ffmpeg
device strings (which is what made the ffmpeg/dshow path fragile).

Recording runs on a background thread (PyAudio is blocking) and is started /
stopped from the async session via run_blocking-friendly wrappers. Each
session writes to its own file, so parallel recordings never collide.

LIMITATION: This captures the default *input* (microphone), i.e. what THIS
machine's mic hears. To capture what other participants say, route the
meeting's output into a virtual input device (e.g. VB-CABLE on Windows,
"Stereo Mix" if available, or a PulseAudio monitor on Linux) and select that
device via AUDIO_INPUT_DEVICE_INDEX.
"""

from __future__ import annotations

import asyncio
import threading
import wave
from pathlib import Path
from typing import Optional

from config import get_settings
from utils.logger import session_logger

try:
    import pyaudio
except ImportError:  # pragma: no cover - dependency is optional at import time
    pyaudio = None


class AudioRecorder:
    """Records one meeting's audio to a WAV file via PyAudio."""

    _FORMAT_WIDTH = 2  # 16-bit PCM
    _CHUNK = 1024

    def __init__(self, session_id: str, output_path: Path) -> None:
        self.session_id = session_id
        self.output_path = output_path
        self.log = session_logger(__name__, session_id)
        self._settings = get_settings()

        self._stop_flag = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._started_ok = False

    async def start(self) -> None:
        """Begin recording on a background thread."""
        if pyaudio is None:
            self.log.error(
                "PyAudio not installed; audio will NOT be recorded. "
                "Install it with: pip install pyaudio"
            )
            return

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._stop_flag.clear()
        self._thread = threading.Thread(
            target=self._record_loop, name=f"audio-{self.session_id}", daemon=True
        )
        self._thread.start()
        # Give the thread a moment to open the stream and report success.
        await asyncio.sleep(1.0)
        if self._started_ok:
            self.log.info("Audio recording is running -> %s", self.output_path.name)
        else:
            self.log.warning("Audio recording may not have started; see logs above")

    def _record_loop(self) -> None:
        """Blocking record loop (runs on its own thread)."""
        channels = max(1, self._settings.audio_channels)
        rate = self._settings.audio_sample_rate
        device_index = self._device_index()

        audio = pyaudio.PyAudio()
        stream = None
        frames: list[bytes] = []
        try:
            stream = audio.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=rate,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=self._CHUNK,
            )
            self._started_ok = True
            while not self._stop_flag.is_set():
                try:
                    data = stream.read(self._CHUNK, exception_on_overflow=False)
                    frames.append(data)
                except Exception as exc:
                    self.log.debug("Audio read hiccup: %s", exc)
                    continue
        except Exception as exc:
            self.log.error("Could not open audio input device: %s", exc)
        finally:
            try:
                if stream is not None:
                    stream.stop_stream()
                    stream.close()
            except Exception:
                pass
            audio.terminate()
            if frames:
                self._write_wav(frames, channels, rate)

    def _write_wav(self, frames: list[bytes], channels: int, rate: int) -> None:
        try:
            with wave.open(str(self.output_path), "wb") as wf:
                wf.setnchannels(channels)
                wf.setsampwidth(self._FORMAT_WIDTH)
                wf.setframerate(rate)
                wf.writeframes(b"".join(frames))
        except Exception as exc:
            self.log.error("Failed to write WAV: %s", exc)

    def _device_index(self) -> Optional[int]:
        """Optional explicit input device index from config (None = default)."""
        idx = getattr(self._settings, "audio_input_device_index", -1)
        return None if idx is None or idx < 0 else int(idx)

    async def stop(self) -> None:
        """Signal the loop to stop and wait for the WAV to be written."""
        if self._thread is None:
            return
        self.log.info("Stopping audio recording")
        self._stop_flag.set()
        await asyncio.get_running_loop().run_in_executor(None, self._thread.join, 10)
        self._thread = None
        if self.has_audio:
            self.log.info(
                "Saved audio.wav (%.1f KB)", self.output_path.stat().st_size / 1024
            )
        else:
            self.log.warning("audio.wav is missing or empty")

    @property
    def has_audio(self) -> bool:
        return self.output_path.exists() and self.output_path.stat().st_size > 1024