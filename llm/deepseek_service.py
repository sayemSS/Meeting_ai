"""DeepSeek LLM service.

A thin async client around DeepSeek's OpenAI-compatible chat completions API
(via httpx). Exposes two helpers used by the summary service:

  * chat(): free-form completion.
  * chat_json(): forces a JSON object response and parses it.

Keeping all LLM access behind this one class means we can swap providers,
add retries, or add streaming in a single place.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import httpx

from config import get_settings
from utils.logger import get_logger

log = get_logger(__name__)


class DeepSeekError(RuntimeError):
    """Raised when the DeepSeek API call fails."""


class DeepSeekService:
    """Async wrapper over the DeepSeek chat completions endpoint."""

    def __init__(self) -> None:
        self._settings = get_settings()

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._settings.deepseek_api_key}",
            "Content-Type": "application/json",
        }

    async def chat(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool = False,
        temperature: Optional[float] = None,
    ) -> str:
        """Send a chat completion request and return the assistant text."""
        if not self._settings.deepseek_api_key:
            raise DeepSeekError("DEEPSEEK_API_KEY is not configured")

        payload: dict[str, Any] = {
            "model": self._settings.deepseek_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": self._settings.deepseek_max_tokens,
            "temperature": (
                temperature if temperature is not None else self._settings.deepseek_temperature
            ),
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        url = f"{self._settings.deepseek_base_url.rstrip('/')}/v1/chat/completions"
        timeout = self._settings.deepseek_timeout_seconds
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, headers=self._headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            raise DeepSeekError(
                f"DeepSeek returned {exc.response.status_code}: {exc.response.text[:300]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise DeepSeekError(f"DeepSeek request failed: {exc}") from exc

        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise DeepSeekError(f"Unexpected DeepSeek response shape: {data}") from exc

    async def chat_json(self, system: str, user: str) -> dict[str, Any]:
        """Chat completion that returns a parsed JSON object."""
        raw = await self.chat(system, user, json_mode=True)
        cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise DeepSeekError(f"Could not parse JSON from LLM: {raw[:300]}") from exc
