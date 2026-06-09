"""Whisper transcription service.

Transcribes audio.wav into a time-aligned Transcript. Supports two engines:

  * faster-whisper (default, recommended): CTranslate2 backend, much faster
    and lighter, great for running several transcriptions in parallel.
  * openai-whisper: the reference implementation.

Transcription is CPU/GPU-bound and blocking, so it is executed in a thread
via run_blocking() to avoid stalling the event loop and the other live
sessions. The model is loaded lazily and cached per process.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from config import get_settings
from utils.helpers import run_blocking
from utils.logger import session_logger
from utils.models import Transcript, TranscriptSegment


class WhisperService:
    """Loads a Whisper model once and transcribes audio files."""

    _model = None  # process-wide cached model
    _model_key: Optional[tuple] = None

    def __init__(self, session_id: str = "global") -> None:
        self.session_id = session_id
        self.log = session_logger(__name__, session_id)
        self._settings = get_settings()

    def _resolve_device(self) -> str:
        device = self._settings.whisper_device
        if device != "auto":
            return device
        try:
            import torch  # type: ignore

            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            return "cpu"

    def _load_model(self):
        s = self._settings
        device = self._resolve_device()
        key = (s.whisper_engine, s.whisper_model, device, s.whisper_compute_type)
        if WhisperService._model is not None and WhisperService._model_key == key:
            return WhisperService._model

        self.log.info(
            "Loading Whisper model (engine=%s model=%s device=%s)",
            s.whisper_engine, s.whisper_model, device,
        )
        if s.whisper_engine == "faster-whisper":
            from faster_whisper import WhisperModel  # type: ignore

            model = WhisperModel(
                s.whisper_model, device=device, compute_type=s.whisper_compute_type
            )
        else:
            import whisper  # type: ignore

            model = whisper.load_model(s.whisper_model, device=device)

        WhisperService._model = model
        WhisperService._model_key = key
        return model

    async def transcribe(self, audio_path: Path, language: Optional[str] = None) -> Transcript:
        """Transcribe an audio file into a Transcript (runs off the event loop)."""
        if not audio_path.exists():
            self.log.warning("Audio file missing; returning empty transcript")
            return Transcript()
        lang = language or (self._settings.whisper_language or None)
        return await run_blocking(self._transcribe_sync, audio_path, lang)

    def _transcribe_sync(self, audio_path: Path, language: Optional[str]) -> Transcript:
        model = self._load_model()
        if self._settings.whisper_engine == "faster-whisper":
            return self._transcribe_faster(model, audio_path, language)
        return self._transcribe_openai(model, audio_path, language)

    def _transcribe_faster(self, model, audio_path: Path, language: Optional[str]) -> Transcript:
        segments_iter, info = model.transcribe(
            str(audio_path), language=language, vad_filter=True
        )
        segments = [
            TranscriptSegment(start=float(s.start), end=float(s.end), text=s.text.strip())
            for s in segments_iter
        ]
        transcript = Transcript(
            language=getattr(info, "language", language),
            duration=float(getattr(info, "duration", 0.0)),
            segments=segments,
        )
        self.log.info("Transcription complete (%d segments)", len(segments))
        return transcript

    def _transcribe_openai(self, model, audio_path: Path, language: Optional[str]) -> Transcript:
        result = model.transcribe(str(audio_path), language=language)
        segments = [
            TranscriptSegment(
                start=float(s["start"]), end=float(s["end"]), text=str(s["text"]).strip()
            )
            for s in result.get("segments", [])
        ]
        transcript = Transcript(
            language=result.get("language", language),
            duration=segments[-1].end if segments else 0.0,
            segments=segments,
        )
        self.log.info("Transcription complete (%d segments)", len(segments))
        return transcript
