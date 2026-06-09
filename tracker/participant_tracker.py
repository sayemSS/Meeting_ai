"""Participant tracker.

Polls the Meet UI on an interval, diffs the current participant set against
the previous one, and records join/leave events with timestamps. The result
is a participant timeline plus the set of unique participants and the peak
concurrent count.

The DOM also contains icon ligatures ("more_vert", "frame_person"), tooltips,
and notices ("Others might still see your video") that must NOT be mistaken
for names. The filters below (is_ui_label / is_valid_name) are ported from a
battle-tested denylist and do the heavy lifting of separating real names from
UI noise. They are heuristics — Meet's DOM changes — but catch the vast
majority of junk.
"""

from __future__ import annotations

import asyncio
import re
from typing import Optional

from playwright.async_api import Page

from utils.logger import session_logger
from utils.models import ParticipantAction, ParticipantEvent


# --------------------------------------------------------------------------- #
# Name filtering (ported from the project's hardened bot logic)
# --------------------------------------------------------------------------- #
_UI_NOISE_SUBSTRINGS = (
    "reducing noise", "noise cancellation", "background noise", "others may see",
    "might still see", "may see your", "got it", "dismiss", "learn more",
    "has joined", "has left", "is presenting", "turned on", "turned off",
    "caption", "font size", "font color", "auto detect", "meeting is safe",
    "return to home", "rejoin", "no one can join", "by the host",
    "backgrounds and effects", "more options for", "you can't", "remotely",
)

_UI_EXACT = {
    "you", "search", "back", "home", "menu", "close", "open", "mute", "unmute",
    "more", "pin", "unpin", "options", "present", "raise", "hand", "settings",
    "camera", "microphone", "mic", "stop", "leave", "end", "call", "chat",
    "people", "participants", "everyone", "reactions", "effects", "blur",
    "background", "layout", "grid", "recording", "live", "captions", "subtitles",
    "host", "guest", "waiting", "contributors", "details", "tools", "devices",
    "reframe", "info", "apps", "mood", "videocam", "language", "font", "size",
    "color", "colour", "small", "medium", "large", "style", "text", "auto",
    "detect", "ok", "okay", "cancel", "confirm", "yes", "no", "allow", "block",
}

_UI_REGEX = [
    re.compile(r"^keep_"), re.compile(r"^frame_"), re.compile(r"_outline$"),
    re.compile(r"_off$"), re.compile(r"_on$"), re.compile(r"^pan_"),
    re.compile(r"more_vert"), re.compile(r"present_to"), re.compile(r"screen_share"),
    re.compile(r"^[a-z_]+_[a-z_]+$"), re.compile(r"\(you\)"), re.compile(r"^\d+$"),
    re.compile(r"^[a-z]+[A-Z]"),  # e.g. "frame_personReframe" / camelCase junk
]


def is_ui_label(text: str) -> bool:
    """True if the text is Google Meet UI chrome rather than a person's name."""
    if not text or not isinstance(text, str):
        return True
    original = text.strip()
    low = original.lower()
    if len(low) < 2:
        return True
    if "\n" in original:
        return True
    if original.isupper() and len(original) > 3:
        return True
    if low in _UI_EXACT:
        return True
    if any(s in low for s in _UI_NOISE_SUBSTRINGS):
        return True
    if text.count("_") >= 1 or text.count("-") > 2:
        return True
    for rx in _UI_REGEX:
        if rx.search(low) or rx.search(original):
            return True
    return False


def is_valid_name(name: str) -> bool:
    """True if the text looks like a real participant name."""
    if not name or not isinstance(name, str):
        return False
    name = name.strip()
    if len(name) < 2 or len(name) > 100:
        return False
    if name.isdigit():
        return False
    if sum(1 for c in name if c.isalpha()) < 2:
        return False
    bad = ("extension", "plugin", "addon", "chrome", "firefox", "grammarly")
    if any(b in name.lower() for b in bad):
        return False
    return True


def clean_name(raw: str) -> Optional[str]:
    """Normalise a raw label into a participant name, or None if it is noise."""
    if not raw:
        return None
    # Meet often duplicates the name across lines ("Alice\nAlice").
    candidate = raw.strip().split("\n")[0].strip()
    # Strip common suffixes.
    candidate = re.sub(r"\s*\((you|host|guest)\)\s*$", "", candidate, flags=re.IGNORECASE).strip()
    # Strip aria prefixes.
    candidate = re.sub(r"^(profile (photo |picture )?of |avatar for )", "", candidate, flags=re.IGNORECASE).strip()
    if not candidate or is_ui_label(candidate) or not is_valid_name(candidate):
        return None
    return candidate


class ParticipantTracker:
    """Tracks participant join/leave events for one meeting."""

    POLL_INTERVAL_SECONDS = 5

    def __init__(self, session_id: str, page: Page) -> None:
        self.session_id = session_id
        self.page = page
        self.log = session_logger(__name__, session_id)

        self.events: list[ParticipantEvent] = []
        self._current: set[str] = set()
        self._peak: int = 0
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

    @property
    def unique_participants(self) -> list[str]:
        seen: list[str] = []
        for e in self.events:
            if e.name not in seen:
                seen.append(e.name)
        return seen

    @property
    def peak_count(self) -> int:
        return self._peak

    def add_known_names(self, names: list[str]) -> None:
        """Merge externally-discovered participant names (e.g. caption speakers).

        Used as a fallback: when the DOM-based tracker misses people, the live
        captions still reveal real speaker names. Any name not already seen is
        recorded as a JOIN so it shows up in the participant list and timeline.
        """
        existing = set(self.unique_participants)
        for raw in names:
            if not raw or raw == "Unknown":
                continue
            cleaned = clean_name(raw)
            if cleaned and cleaned not in existing:
                self.events.append(
                    ParticipantEvent(name=cleaned, action=ParticipantAction.JOIN)
                )
                existing.add(cleaned)
        self._peak = max(self._peak, len(existing))

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name=f"tracker-{self.session_id}")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await asyncio.gather(self._task, return_exceptions=True)
        for name in list(self._current):
            self.events.append(ParticipantEvent(name=name, action=ParticipantAction.LEAVE))

    async def _run(self) -> None:
        self.log.info("Participant tracker started")
        # Try to open the People panel once so list items are available.
        await self._open_people_panel()
        while not self._stop.is_set():
            try:
                # Re-open the People panel if it has closed; people who never
                # speak only ever appear in this list, so it must stay open.
                await self._open_people_panel()
                present = await self._read_participants()
                if present:
                    self._diff_and_record(present)
            except Exception as exc:
                self.log.debug("Participant poll failed: %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.POLL_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                pass
        self.log.info("Participant tracker stopped (%d events)", len(self.events))

    def _diff_and_record(self, present: set[str]) -> None:
        joined = present - self._current
        left = self._current - present
        for name in sorted(joined):
            self.events.append(ParticipantEvent(name=name, action=ParticipantAction.JOIN))
        for name in sorted(left):
            self.events.append(ParticipantEvent(name=name, action=ParticipantAction.LEAVE))
        self._current = present
        self._peak = max(self._peak, len(present))

    async def _open_people_panel(self) -> None:
        """Ensure the People panel is open (idempotent, safe to call each poll)."""
        # If the participant list is already on screen, do nothing.
        try:
            if await self.page.query_selector('div[role="list"] div[role="listitem"]'):
                return
        except Exception:
            pass
        selectors = [
            'button[aria-label*="Show everyone"]',
            'button[aria-label*="People"]',
            'button[aria-label*="participant"]',
            'button[aria-label*="Participants"]',
        ]
        for selector in selectors:
            try:
                btn = self.page.locator(selector).first
                await btn.wait_for(state="visible", timeout=2000)
                await btn.click()
                await self.page.wait_for_timeout(800)
                return
            except Exception:
                continue

    async def _read_participants(self) -> set[str]:
        """Read and clean the current set of participant names from the DOM.

        The People panel's list is the authoritative source because it
        includes everyone present, even people who never speak or turn on
        their camera. Video-tile selectors are only a secondary fallback.
        """
        names: set[str] = set()
        selectors = [
            # People panel list items (authoritative — includes silent people).
            'div[role="list"] div[role="listitem"]',
            'div[role="listitem"]',
            # Per-participant data attributes / labels.
            '[aria-label^="Profile photo of"]',
            '[data-participant-id] [data-self-name]',
            '[data-self-name]',
            '[data-participant-id]',
        ]
        for selector in selectors:
            try:
                handles = await self.page.query_selector_all(selector)
                for h in handles:
                    raw = (
                        await h.get_attribute("data-self-name")
                        or await h.get_attribute("aria-label")
                        or await h.inner_text()
                    )
                    cleaned = clean_name(raw or "")
                    if cleaned:
                        names.add(cleaned)
                if names:
                    break
            except Exception:
                continue
        return names