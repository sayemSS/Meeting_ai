"""Playwright-driven Google Meet automation.

Each session owns its own isolated browser context. That per-session
isolation is what makes parallel meetings safe: no shared DOM, no cross-talk.

AUTHENTICATION / "browser may not be secure":
Google blocks sign-in on browsers it detects as automated. To avoid that,
this bot supports three connect modes (config.browser_connect_mode):

  * "persistent" (default): reuse a real Chrome profile that was logged in
    by hand once. For parallel safety each session runs on its own *copy* of
    the master profile (a profile dir can only be opened by one Chrome at a
    time). This is the easy, reliable path.
  * "cdp": attach to a Chrome you launched yourself with
    --remote-debugging-port and logged into normally. Most robust, because
    Google sees a 100% real browser.
  * "launch": fresh context + storage_state.json. Simplest, but Google often
    shows the "this browser may not be secure" page, so it is last resort.

NOTE ON SELECTORS: Google Meet's DOM and aria-labels change frequently and
can differ by locale. Selectors here are defensive (multiple fallbacks) but
should be treated as config that needs occasional maintenance.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Optional

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from auth.google_auth import has_valid_storage_state, storage_state_path
from config import get_settings
from utils.logger import session_logger

# Removes the most common automation fingerprints before any page script runs.
_STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
window.chrome = window.chrome || { runtime: {} };
"""

_LAUNCH_ARGS = [
    "--use-fake-ui-for-media-stream",  # auto-accept mic/cam prompts
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--start-maximized",
]


class PlaywrightBot:
    """Owns one isolated browser context dedicated to one meeting."""

    def __init__(self, session_id: str, meet_url: str) -> None:
        self.session_id = session_id
        self.meet_url = meet_url
        self.log = session_logger(__name__, session_id)
        self._settings = get_settings()

        self._pw: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._temp_profile: Optional[Path] = None

    async def start(self) -> Page:
        """Open an authenticated, isolated context and return the page."""
        self._pw = await async_playwright().start()
        mode = self._settings.browser_connect_mode
        self.log.info("Starting browser (mode=%s)", mode)

        if mode == "cdp":
            await self._start_cdp()
        elif mode == "persistent":
            await self._start_persistent()
        else:
            await self._start_launch()

        await self._context.add_init_script(_STEALTH_SCRIPT)
        self.page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        return self.page

    async def _start_cdp(self) -> None:
        """Attach to an externally launched, already-logged-in Chrome."""
        endpoint = self._settings.cdp_endpoint
        self._browser = await self._pw.chromium.connect_over_cdp(endpoint)
        # Use the existing (logged-in) default context.
        if self._browser.contexts:
            self._context = self._browser.contexts[0]
        else:
            self._context = await self._browser.new_context()
        self.log.info("Attached to external Chrome at %s", endpoint)

    async def _start_persistent(self) -> None:
        """Launch a real Chrome on a per-session copy of the master profile."""
        master = self._settings.chrome_user_data_dir
        if not master.exists():
            raise RuntimeError(
                f"Chrome profile not found at {master}. Run "
                f"`python -m auth.google_auth` once to create and log it in."
            )
        # A profile dir can only be opened by one Chrome at a time, so copy it.
        self._temp_profile = Path(
            tempfile.mkdtemp(prefix=f"meet_{self.session_id}_")
        )
        shutil.copytree(master, self._temp_profile, dirs_exist_ok=True)

        self._context = await self._pw.chromium.launch_persistent_context(
            user_data_dir=str(self._temp_profile),
            channel=self._settings.browser_channel,
            headless=self._settings.headless,
            args=_LAUNCH_ARGS,
            permissions=["microphone", "camera"],
            user_agent=self._settings.browser_user_agent,
            viewport={"width": 1280, "height": 800},
        )
        self.log.info("Launched persistent Chrome profile copy")

    async def _start_launch(self) -> None:
        """Fresh context + storage_state (least reliable against Google)."""
        self._browser = await self._pw.chromium.launch(
            headless=self._settings.headless,
            channel=self._settings.browser_channel,
            args=_LAUNCH_ARGS,
        )
        state = str(storage_state_path()) if has_valid_storage_state() else None
        self._context = await self._browser.new_context(
            storage_state=state,
            permissions=["microphone", "camera"],
            user_agent=self._settings.browser_user_agent,
            viewport={"width": 1280, "height": 800},
        )

    async def join(self) -> None:
        """Navigate to the meeting and click through the join flow."""
        assert self.page is not None, "start() must be called before join()"
        page = self.page
        self.log.info("Navigating to meeting URL")
        # Google Meet keeps polling the network forever, so "networkidle" never
        # fires and times out. Wait for the DOM instead, then let the join UI settle.
        await page.goto(self.meet_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)

        # Turn off mic and camera before joining (bot should be silent).
        await self._safe_click(
            [
                '[aria-label*="Turn off microphone"]',
                'div[role="button"][aria-label*="microphone"]',
            ],
            timeout=4000,
        )
        await self._safe_click(
            [
                '[aria-label*="Turn off camera"]',
                'div[role="button"][aria-label*="camera"]',
            ],
            timeout=4000,
        )

        # Click "Join now" / "Ask to join".
        joined = await self._safe_click(
            [
                'button:has-text("Join now")',
                'button:has-text("Ask to join")',
                'span:has-text("Join now")',
                'span:has-text("Ask to join")',
            ],
            timeout=self._settings.join_timeout_seconds * 1000,
        )
        if not joined:
            raise RuntimeError("Could not find a Join button on the Meet page")
        self.log.info("Join action submitted")

    async def turn_on_captions(self) -> None:
        """Enable live captions so the caption listener has data to read."""
        assert self.page is not None
        await self._safe_click(
            [
                '[aria-label*="Turn on captions"]',
                'button[aria-label*="captions"]',
            ],
            timeout=8000,
        )

    async def leave(self) -> None:
        """Click the hang-up button to leave the call gracefully."""
        if self.page is None:
            return
        await self._safe_click(
            [
                '[aria-label*="Leave call"]',
                'button[aria-label*="Leave call"]',
            ],
            timeout=5000,
        )
        self.log.info("Left the meeting")

    async def is_still_in_call(self) -> bool:
        """Are we still in the call?

        Returns False when the meeting has ended (host ended it, we were
        removed, or we left). Detection combines several signals because the
        "Leave call" button alone is unreliable on the post-call screen:
          1. The URL leaves the active meeting path (becomes home/lookup/_meet).
          2. A "Return to home screen" / "Rejoin" button appears.
          3. The "Leave call" hang-up control is gone.
        """
        if self.page is None:
            return False
        try:
            # 1. URL no longer points at an active meeting (e.g. xxx-yyyy-zzz).
            url = self.page.url or ""
            if "meet.google.com" in url:
                path = url.split("meet.google.com")[-1].strip("/").split("?")[0]
                if not path or path.startswith("_") or path.startswith("lookup"):
                    return False

            # 2. Post-call UI present -> meeting ended.
            ended = await self.page.evaluate(
                """
                () => {
                    const txt = (document.body.innerText || '').toLowerCase();
                    if (txt.includes('return to home screen') ||
                        txt.includes('you left the meeting') ||
                        txt.includes('the meeting has ended') ||
                        txt.includes('you have been removed')) return true;
                    const rejoin = document.querySelector(
                        '[aria-label*="Rejoin"], button[jsname*="rejoin"]'
                    );
                    return !!(rejoin && rejoin.offsetParent !== null);
                }
                """
            )
            if ended:
                return False

            # 3. Hang-up control still present -> still in the call.
            el = await self.page.query_selector('[aria-label*="Leave call"]')
            return el is not None
        except Exception:
            # On any DOM/navigation error, assume the call is over so the
            # session can finish and save its transcript rather than hang.
            return False

    async def stop(self) -> None:
        """Tear down the context/browser and remove the temp profile copy."""
        try:
            if self._context is not None:
                await self._context.close()
            # In CDP mode the browser is owned externally; don't kill it.
            if self._browser is not None and self._settings.browser_connect_mode != "cdp":
                await self._browser.close()
            if self._pw is not None:
                await self._pw.stop()
        finally:
            if self._temp_profile and self._temp_profile.exists():
                shutil.rmtree(self._temp_profile, ignore_errors=True)
            self.page = None
            self.log.info("Browser context stopped")

    async def _safe_click(self, selectors: list[str], timeout: int) -> bool:
        """Try a list of selectors; click the first that appears. Never raises."""
        assert self.page is not None
        per_selector = max(500, timeout // max(1, len(selectors)))
        for selector in selectors:
            try:
                locator = self.page.locator(selector).first
                await locator.wait_for(state="visible", timeout=per_selector)
                await locator.click()
                return True
            except Exception:
                continue
        return False