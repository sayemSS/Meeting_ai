"""Live caption listener.

Google Meet renders live captions into a dedicated region. Captions update
in place (the latest line keeps growing until the speaker pauses), so naive
scraping produces massive duplication. This listener keeps the last seen
text per speaker and only commits a CaptionEntry when the line stops changing
(a debounce), giving clean, de-duplicated caption records.

Captions are a useful real-time/fallback transcript; the authoritative
transcript still comes from Whisper running on the recorded audio.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from playwright.async_api import Page

from utils.logger import session_logger
from utils.models import CaptionEntry


class CaptionListener:
    """Captures and de-duplicates Meet live captions for one meeting."""

    POLL_INTERVAL_SECONDS = 1.0
    COMMIT_AFTER_SECONDS = 2.5  # commit a line once it has been stable this long

    def __init__(self, session_id: str, page: Page) -> None:
        self.session_id = session_id
        self.page = page
        self.log = session_logger(__name__, session_id)

        self.captions: list[CaptionEntry] = []
        self._pending: dict[str, tuple[str, float]] = {}  # speaker -> (text, last_change)
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name=f"captions-{self.session_id}")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await asyncio.gather(self._task, return_exceptions=True)
        # Flush any still-pending lines.
        for speaker, (text, _) in self._pending.items():
            self._commit(speaker, text)
        self.log.info("Caption listener stopped (%d captions)", len(self.captions))

    async def _run(self) -> None:
        self.log.info("Caption listener started")
        loop = asyncio.get_running_loop()
        while not self._stop.is_set():
            try:
                lines = await self._read_caption_lines()
                now = loop.time()
                self._update_pending(lines, now)
                self._flush_stable(now)
            except Exception as exc:
                self.log.debug("Caption poll failed: %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.POLL_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                pass

    def _update_pending(self, lines: list[tuple[str, str]], now: float) -> None:
        for speaker, text in lines:
            prev = self._pending.get(speaker)
            if prev is None or prev[0] != text:
                self._pending[speaker] = (text, now)

    def _flush_stable(self, now: float) -> None:
        for speaker in list(self._pending.keys()):
            text, last_change = self._pending[speaker]
            if now - last_change >= self.COMMIT_AFTER_SECONDS:
                self._commit(speaker, text)
                del self._pending[speaker]

    def _commit(self, speaker: str, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if self.captions and self.captions[-1].text == text:
            return
        self.captions.append(CaptionEntry(speaker=speaker or "Unknown", text=text))

    async def _read_caption_lines(self) -> list[tuple[str, str]]:
        """Return [(speaker, text), ...] currently visible in the caption area."""
        results: list[tuple[str, str]] = []
        selectors = [
            'div[aria-label*="Captions"] div',
            'div[jsname][class*="caption"]',
            'div[role="region"][aria-label*="aption"] span',
        ]
        for selector in selectors:
            try:
                handles = await self.page.query_selector_all(selector)
                for h in handles:
                    text = (await h.inner_text()).strip()
                    if text:
                        # Meet sometimes prefixes "Speaker name\nspoken text".
                        if "\n" in text:
                            speaker, _, spoken = text.partition("\n")
                            results.append((speaker.strip(), spoken.strip()))
                        else:
                            results.append(("Unknown", text))
                if results:
                    break
            except Exception:
                continue
        return results
