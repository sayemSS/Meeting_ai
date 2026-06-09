"""Google authentication for the Meet bot.

Google blocks sign-in on browsers it detects as automated ("This browser or
app may not be secure"). The reliable fix is to log in ONCE inside a real,
persistent Chrome profile and then have the bot reuse that profile. We avoid
Playwright's fresh Chromium for the login itself.

Two supported flows (see config.browser_connect_mode):

  persistent (recommended) -- run this module to open a real Chrome on a
      dedicated profile dir, log in by hand once; the cookies persist in the
      profile and the bot reuses copies of it.

  cdp -- you launch your own Chrome and log in normally, then point the bot
      at it. No login step here; see print_cdp_instructions().

Run:  python -m auth.google_auth
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import BrowserContext, async_playwright

from config import get_settings
from utils.logger import get_logger

log = get_logger(__name__)


def storage_state_path() -> Path:
    return get_settings().google_storage_state


def has_valid_storage_state() -> bool:
    """True if a non-empty storage state file already exists."""
    path = storage_state_path()
    return path.exists() and path.stat().st_size > 0


def has_chrome_profile() -> bool:
    """True if the persistent Chrome profile directory looks initialised."""
    profile = get_settings().chrome_user_data_dir
    return profile.exists() and any(profile.iterdir())


async def apply_auth(context: BrowserContext) -> None:
    """Reserved hook for future token-refresh / header injection."""
    return None


async def interactive_login() -> None:
    """Open a real Chrome on the persistent profile and wait for manual login.

    Because this uses launch_persistent_context with the real Chrome channel
    and a normal user profile, Google treats it like an ordinary browser and
    allows sign-in. The session is saved both in the profile (for persistent
    mode) and as storage_state.json (for launch mode).
    """
    settings = get_settings()
    profile_dir = settings.chrome_user_data_dir
    profile_dir.mkdir(parents=True, exist_ok=True)
    storage_state_path().parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            channel=settings.browser_channel,
            headless=False,  # must be visible so a human can log in
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
            user_agent=settings.browser_user_agent,
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://accounts.google.com/")
        log.info("A Chrome window opened. Sign in to the bot's Google account.")
        log.info("If you still hit a block, sign in to Gmail first, then return here.")
        log.info("When you can see you are signed in, press ENTER in this terminal.")
        await asyncio.get_running_loop().run_in_executor(None, input)

        try:
            await context.storage_state(path=str(storage_state_path()))
            log.info("Saved storage state to %s", storage_state_path())
        except Exception as exc:
            log.warning("Could not export storage_state: %s", exc)

        log.info("Persistent profile saved at %s", profile_dir)
        await context.close()


def print_cdp_instructions() -> None:
    """Print how to run CDP mode (attach to your own logged-in Chrome)."""
    settings = get_settings()
    port = settings.cdp_endpoint.rsplit(":", 1)[-1]
    print(
        "\nCDP mode setup (most reliable against Google's bot check):\n"
        "  1. Fully close Chrome.\n"
        f"  2. Launch Chrome with remote debugging, e.g.:\n"
        f"       chrome --remote-debugging-port={port} "
        f"--user-data-dir=\"$HOME/meet-bot-chrome\"\n"
        "  3. In that window, sign in to the bot's Google account normally.\n"
        "  4. Set BROWSER_CONNECT_MODE=cdp in .env and run `python main.py`.\n"
    )


if __name__ == "__main__":
    asyncio.run(interactive_login())
    print_cdp_instructions()