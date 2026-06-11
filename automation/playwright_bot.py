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

import asyncio
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
        await page.goto(self.meet_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(8000)

        debug_path = Path(tempfile.gettempdir()) / f"meet_debug_{self.session_id}.png"
        try:
            await page.screenshot(path=str(debug_path), full_page=True)
            self.log.info("Debug screenshot saved to %s", debug_path)
            self.log.info("Page URL: %s", page.url)
            self.log.info("Page title: %s", await page.title())
        except Exception as exc:
            self.log.debug("Debug screenshot failed: %s", exc)

        page_text = await page.inner_text("body")
        page_lower = page_text.lower()
        if "sign in" in page_lower and "join" not in page_lower:
            raise RuntimeError(
                "Google is showing the sign-in screen — persistent profile "
                "login may have expired. Re-run `python -m auth.google_auth`."
            )
        if "meeting not found" in page_lower or "no longer available" in page_lower:
            raise RuntimeError(
                f"Meeting URL is invalid or the meeting has ended: {self.meet_url}"
            )

        # Turn off mic and camera before joining (bot should be silent/invisible).
        await self._ensure_mic_off()
        await self._ensure_camera_off()

        joined = await self._safe_click(
            [
                'button:has-text("Join now")',
                'button:has-text("Ask to join")',
                'button:has-text("Join")',
                'span:has-text("Join now")',
                'span:has-text("Ask to join")',
                '[role="button"]:has-text("Join now")',
                '[role="button"]:has-text("Ask to join")',
                '[role="button"]:has-text("Join")',
                'button[jsname="Qx7uuf"]',
                'button[jsname="r8g1K"]',
                'div[jsname="Qx7uuf"]',
                'div[jsname="r8g1K"]',
            ],
            timeout=self._settings.join_timeout_seconds * 1000,
        )
        if not joined:
            try:
                fail_path = (
                    Path(tempfile.gettempdir())
                    / f"meet_join_failed_{self.session_id}.png"
                )
                await page.screenshot(path=str(fail_path), full_page=True)
                self.log.error(
                    "Join button not found. Failure screenshot: %s", fail_path
                )
            except Exception:
                pass
            raise RuntimeError("Could not find a Join button on the Meet page")
        self.log.info("Join action submitted")

    async def wait_until_admitted(self, timeout_seconds: int = 120) -> None:
        """Wait until the host admits the bot from the lobby.

        After clicking "Ask to join", Meet places the bot in a waiting lobby.
        This method polls until the in-call UI appears (signalled by the
        presence of the "Leave call" hang-up button), or until the timeout
        expires, or until the meeting disappears entirely.

        Once admitted, mic and camera are forcefully turned off again —
        Meet sometimes re-enables them on entry.
        """
        assert self.page is not None, "start() must be called first"
        self.log.info("Waiting to be admitted (timeout=%ds)...", timeout_seconds)

        deadline = asyncio.get_event_loop().time() + timeout_seconds
        poll_interval = 3

        while asyncio.get_event_loop().time() < deadline:
            # Admitted check: "Leave call" button only appears once inside the meeting.
            try:
                el = await self.page.query_selector('[aria-label*="Leave call"]')
                if el is not None:
                    self.log.info("Admitted into the meeting.")
                    # Meet sometimes re-enables cam/mic on admission — force off again.
                    await self._ensure_camera_off()
                    await self._ensure_mic_off()
                    return
            except Exception:
                pass

            # Meeting-ended / URL-changed check while still in lobby.
            try:
                page_text = (await self.page.inner_text("body")).lower()
                if (
                    "meeting not found" in page_text
                    or "no longer available" in page_text
                    or "you have been removed" in page_text
                    or "the meeting has ended" in page_text
                ):
                    raise RuntimeError(
                        "Meeting ended or bot was removed while waiting to be admitted."
                    )

                url = self.page.url or ""
                if "meet.google.com" in url:
                    path = url.split("meet.google.com")[-1].strip("/").split("?")[0]
                    if not path or path.startswith("_") or path.startswith("lookup"):
                        raise RuntimeError(
                            "Redirected away from meeting while waiting to be admitted."
                        )
            except RuntimeError:
                raise
            except Exception:
                pass

            await asyncio.sleep(poll_interval)

        raise RuntimeError(
            f"Timed out after {timeout_seconds}s waiting to be admitted. "
            "The host may not have approved the join request."
        )

    async def _ensure_camera_off(self) -> None:
        """Make sure camera is off. Tries button click, then keyboard shortcut.

        Google Meet's camera toggle has two possible states:
          - Camera is ON  → button says "Turn off camera"  → we click it
          - Camera is OFF → button says "Turn on camera"   → already off, skip

        Falls back to 'e' keyboard shortcut (Meet's built-in camera toggle)
        if the button is not found.
        """
        assert self.page is not None

        # Check if camera is currently ON (button offers to turn it off).
        try:
            el = await self.page.query_selector(
                '[aria-label*="Turn off camera"], [aria-label*="turn off camera"]'
            )
            if el is None:
                # Camera already off — nothing to do.
                self.log.debug("Camera already off")
                return
        except Exception:
            return

        # Camera is on — click the button to turn it off.
        clicked = await self._safe_click(
            [
                '[aria-label*="Turn off camera"]',
                'button[aria-label*="camera"]',
                'div[role="button"][aria-label*="camera"]',
                '[data-tooltip*="camera"]',
            ],
            timeout=5000,
        )

        if not clicked:
            # Fallback: 'e' is Google Meet's keyboard shortcut for camera toggle.
            try:
                await self.page.keyboard.press("e")
                await self.page.wait_for_timeout(800)
                self.log.debug("Camera toggled via keyboard shortcut 'e'")
            except Exception as exc:
                self.log.debug("Camera keyboard shortcut failed: %s", exc)
            return

        # Verify camera is now off.
        await self.page.wait_for_timeout(500)
        try:
            still_on = await self.page.query_selector(
                '[aria-label*="Turn off camera"]'
            )
            if still_on:
                self.log.warning("Camera may still be on after click attempt")
            else:
                self.log.info("Camera confirmed off")
        except Exception:
            pass

    async def _ensure_mic_off(self) -> None:
        """Make sure microphone is off. Tries button click, then keyboard shortcut.

        Same logic as _ensure_camera_off but for the microphone.
        Keyboard fallback is 'd' (Meet's built-in mic toggle).
        """
        assert self.page is not None

        try:
            el = await self.page.query_selector(
                '[aria-label*="Turn off microphone"], [aria-label*="turn off microphone"]'
            )
            if el is None:
                self.log.debug("Microphone already off")
                return
        except Exception:
            return

        clicked = await self._safe_click(
            [
                '[aria-label*="Turn off microphone"]',
                'button[aria-label*="microphone"]',
                'div[role="button"][aria-label*="microphone"]',
                '[data-tooltip*="microphone"]',
            ],
            timeout=5000,
        )

        if not clicked:
            try:
                await self.page.keyboard.press("d")
                await self.page.wait_for_timeout(800)
                self.log.debug("Mic toggled via keyboard shortcut 'd'")
            except Exception as exc:
                self.log.debug("Mic keyboard shortcut failed: %s", exc)
            return

        await self.page.wait_for_timeout(500)
        try:
            still_on = await self.page.query_selector(
                '[aria-label*="Turn off microphone"]'
            )
            if still_on:
                self.log.warning("Microphone may still be on after click attempt")
            else:
                self.log.info("Microphone confirmed off")
        except Exception:
            pass

    async def turn_on_captions(self) -> None:
        """Enable live captions so the caption listener has data to read.

        Strategy: click the captions toggle, then VERIFY it worked (the
        button flips to "Turn off captions"). If clicking failed — Meet
        frequently renames/moves this button — fall back to the keyboard
        shortcut "c", which toggles captions and is far more stable.
        """
        assert self.page is not None
        await self._safe_click(
            [
                'button[aria-label*="Turn on captions"]',
                '[aria-label*="Turn on captions"]',
                'button[aria-label*="captions"]',
            ],
            timeout=8000,
        )
        if await self._captions_enabled():
            self.log.info("Captions enabled (button)")
            return
        try:
            await self.page.keyboard.press("c")
            await self.page.wait_for_timeout(1500)
        except Exception as exc:
            self.log.debug("Caption shortcut press failed: %s", exc)
        if await self._captions_enabled():
            self.log.info("Captions enabled (keyboard shortcut)")
        else:
            self.log.warning(
                "Could not verify captions are ON — caption capture may be empty"
            )

    async def _captions_enabled(self) -> bool:
        """True if the toggle now reads 'Turn off captions' (captions are ON)."""
        if self.page is None:
            return False
        try:
            el = await self.page.query_selector('[aria-label*="Turn off captions"]')
            return el is not None
        except Exception:
            return False

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
            url = self.page.url or ""
            if "meet.google.com" in url:
                path = url.split("meet.google.com")[-1].strip("/").split("?")[0]
                if not path or path.startswith("_") or path.startswith("lookup"):
                    return False

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

            el = await self.page.query_selector('[aria-label*="Leave call"]')
            return el is not None
        except Exception:
            return False

    async def stop(self) -> None:
        """Tear down the context/browser and remove the temp profile copy."""
        try:
            if self._context is not None:
                await self._context.close()
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
        """Try a list of selectors; click the first that appears.

        Two-phase approach to handle Google Meet's delayed React renders:
          Phase 1 — normal Playwright wait-for-visible + click (fast path).
          Phase 2 — retry loop that checks element *existence* (not visibility)
                    and force-clicks. Catches buttons that are in the DOM but
                    still animating, temporarily detached, or behind an overlay
                    that Playwright's visibility heuristic rejects.

        Never raises.
        """
        assert self.page is not None

        per_selector = max(800, timeout // max(1, len(selectors)))
        for selector in selectors:
            try:
                locator = self.page.locator(selector).first
                await locator.wait_for(state="visible", timeout=per_selector)
                await locator.click()
                self.log.debug("Clicked (phase 1): %s", selector)
                return True
            except Exception:
                continue

        self.log.debug(
            "Phase 1 missed all selectors; retrying with force-click (%d ms budget)",
            timeout,
        )
        deadline = asyncio.get_event_loop().time() + (timeout / 1000)
        retry_interval = 1.0

        while asyncio.get_event_loop().time() < deadline:
            for selector in selectors:
                try:
                    locator = self.page.locator(selector)
                    count = await locator.count()
                    if count == 0:
                        continue
                    await locator.first.click(timeout=2000, force=True)
                    self.log.debug("Clicked (phase 2, force): %s", selector)
                    return True
                except Exception:
                    continue
            try:
                await asyncio.sleep(retry_interval)
            except asyncio.CancelledError:
                break

        return False