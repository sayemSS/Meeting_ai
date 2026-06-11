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
import difflib
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
        self._region_found_logged = False

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
        last_enable_attempt = 0.0
        while not self._stop.is_set():
            try:
                # Self-healing: if nothing has been captured yet and captions
                # appear to be OFF, retry enabling them every 30 s — the
                # attempt at join time can fail while Meet's UI is settling.
                now = loop.time()
                if not self.captions and now - last_enable_attempt > 30:
                    last_enable_attempt = now
                    await self._ensure_captions_on()
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

    async def _ensure_captions_on(self) -> None:
        """Turn captions on if they are off; safe to call repeatedly."""
        try:
            if await self.page.query_selector('[aria-label*="Turn off captions"]'):
                return  # already on
            btn = await self.page.query_selector(
                'button[aria-label*="Turn on captions"], [aria-label*="Turn on captions"]'
            )
            if btn:
                await btn.click(timeout=2000)
            else:
                await self.page.keyboard.press("c")
            await self.page.wait_for_timeout(1000)
            if await self.page.query_selector('[aria-label*="Turn off captions"]'):
                self.log.info("Captions enabled by listener retry")
        except Exception as exc:
            self.log.debug("Caption re-enable attempt failed: %s", exc)

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

    @staticmethod
    def _norm(text: str) -> str:
        """Lowercase alphanumeric-only form, for growth comparison."""
        return "".join(ch.lower() for ch in text if ch.isalnum())

    @classmethod
    def _is_grown_version(cls, old: str, new: str) -> bool:
        """True if `new` looks like `old` with more words appended.

        Meet edits punctuation/casing mid-line as it refines a caption
        ("increased." -> "increased by 12 percent"), so an exact prefix test
        fails. Compare normalized text, and tolerate small revisions with a
        similarity ratio over the overlapping span.
        """
        o, n = cls._norm(old), cls._norm(new)
        if not o or not n:
            return False
        if n.startswith(o) or o.startswith(n):
            return True
        shorter, longer = (o, n) if len(o) <= len(n) else (n, o)
        ratio = difflib.SequenceMatcher(None, shorter, longer[: len(shorter)]).ratio()
        return ratio >= 0.85

    def _commit(self, speaker: str, text: str) -> None:
        text = text.strip()
        if not text:
            return
        speaker = speaker or "Unknown"
        if self.captions:
            # Meet grows the SAME caption line in place, so commits from one
            # speaker are cumulative snapshots. Check the last few entries
            # (not just the immediate last) because another speaker's line
            # may be interleaved between two snapshots of the same row.
            for idx in range(len(self.captions) - 1, max(len(self.captions) - 4, -1), -1):
                prev = self.captions[idx]
                if prev.speaker != speaker:
                    continue
                if self._is_grown_version(prev.text, text):
                    if len(text) > len(prev.text):
                        self.captions[idx] = CaptionEntry(speaker=speaker, text=text)
                    return
                break  # only merge into the speaker's most recent line
            if self.captions[-1].text == text:
                return
        self.captions.append(CaptionEntry(speaker=speaker, text=text))

    async def _read_caption_lines(self) -> list[tuple[str, str]]:
        """Return [(speaker, text), ...] currently visible in the caption area.

        Primary strategy (robust to Meet's class-name churn): find the
        captions REGION via stable hooks (role="region" whose aria-label
        contains "aption", or the long-lived jsname container), then split it
        into per-speaker rows anchored on the avatar <img> each row contains.
        Row innerText is "Speaker Name\\nspoken text...". The old flat CSS
        selectors are kept only as a last-resort fallback.
        """
        results: list[tuple[str, str]] = []
        try:
            rows = await self.page.evaluate(
                """
                () => {
                    const region = document.querySelector(
                        'div[role="region"][aria-label*="aption"], ' +
                        'div[jsname="dsyhDe"], .a4cQT'
                    );
                    if (!region) return [];
                    const out = [];
                    // Each caption row contains the speaker's avatar <img>.
                    // Climb from each img to the row that is a direct child
                    // of the region, then parse "name\\ntext" from its text.
                    const seen = new Set();
                    region.querySelectorAll('img').forEach((img) => {
                        let row = img;
                        while (row.parentElement && row.parentElement !== region) {
                            row = row.parentElement;
                        }
                        if (seen.has(row)) return;
                        seen.add(row);
                        const lines = (row.innerText || '')
                            .split('\\n').map(s => s.trim()).filter(Boolean);
                        if (lines.length >= 2) {
                            out.push([lines[0], lines.slice(1).join(' ')]);
                        } else if (lines.length === 1) {
                            out.push(['Unknown', lines[0]]);
                        }
                    });
                    // Region exists but no avatar rows found: fall back to
                    // parsing the whole region text once.
                    if (out.length === 0) {
                        const lines = (region.innerText || '')
                            .split('\\n').map(s => s.trim()).filter(Boolean);
                        if (lines.length >= 2) {
                            out.push([lines[0], lines.slice(1).join(' ')]);
                        } else if (lines.length === 1) {
                            out.push(['Unknown', lines[0]]);
                        }
                    }
                    return out;
                }
                """
            )
            for row in rows or []:
                if isinstance(row, (list, tuple)) and len(row) == 2:
                    speaker, text = str(row[0]).strip(), str(row[1]).strip()
                    if text:
                        results.append((speaker or "Unknown", text))
            if results:
                if not self._region_found_logged:
                    self._region_found_logged = True
                    self.log.info("Captions region located; capturing captions")
                return results
        except Exception as exc:
            self.log.debug("Structured caption read failed: %s", exc)

        # ----- legacy flat-selector fallback ----------------------------
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