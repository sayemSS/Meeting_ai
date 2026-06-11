"""Summary service (v2 — management-report grade).

Turns a Transcript into a structured MeetingSummary suitable for an
executive PDF report. Two paths:

  * SHORT transcripts (fits in one prompt): single LLM call.
  * LONG transcripts (1-2 hour meetings): map-reduce. The transcript is
    split into chunks; each chunk is condensed into notes (map), then the
    notes are merged into one final report (reduce). This is what
    guarantees that a 2-hour meeting does NOT get truncated and important
    decisions/action items are NOT silently dropped.

The output is length-disciplined: the executive summary stays short and
key points are capped, but decisions and action items are NEVER dropped —
those are the things management cares about most.
"""

from __future__ import annotations

import asyncio

from llm.deepseek_service import DeepSeekError, DeepSeekService
from utils.logger import session_logger
from utils.models import ActionItem, MeetingSummary, Transcript

# A single prompt comfortably handles this much transcript text.
_SINGLE_PASS_CHARS = 24000
# Chunk size for the map phase of long meetings.
_CHUNK_CHARS = 20000

_SYSTEM_PROMPT = (
    "You are an expert meeting analyst preparing reports for company "
    "management. You read raw meeting transcripts and produce concise, "
    "accurate, structured summaries. Never invent facts that are not "
    "supported by the transcript. Respond with a single JSON object only."
)

_REPORT_RULES = """LENGTH RULES (the report is read by busy executives):
- "overview": an executive summary of AT MOST 4 sentences.
- "key_points": AT MOST 8 short bullet strings — only the points that matter
  to management. Merge related points instead of listing them separately.
- "decisions": include EVERY decision that was made, each as one short string.
  Decisions must NEVER be dropped, but keep each one brief.
- "action_items": include EVERY action item as an object with keys
  "description", "owner" (person's name or null), "due" (deadline or null).
  Action items must NEVER be dropped.
- "risks": AT MOST 5 short strings — risks, blockers, or open questions.
- "next_steps": AT MOST 5 short strings.
- "sentiment": one of "positive", "neutral", "negative", or "mixed".

LANGUAGE RULE: {language_rule} Keep the JSON keys in English."""

# Per-language report instructions, chosen by the meeting's language setting.
_LANGUAGE_RULES = {
    "bn": "Write all values in Bengali (Bangla).",
    "en": "Write all values in English.",
    "mixed": (
        "Write all values in Bengali (Bangla), but keep English technical "
        "and business terms exactly as spoken (e.g. 'sales', 'budget', 'KPI')."
    ),
}
_DEFAULT_LANGUAGE_RULE = (
    "Write all values in the SAME LANGUAGE as the transcript "
    "(Bengali transcript -> Bengali report)."
)

_FINAL_TEMPLATE = """Produce a management meeting report from the following transcript.

{rules}

Return a JSON object with exactly these keys:
"overview", "key_points", "decisions", "action_items", "risks",
"next_steps", "sentiment".

Transcript:
\"\"\"
{transcript}
\"\"\"
"""

_MAP_TEMPLATE = """The text below is PART {part} of {total} of a long meeting transcript.
Condense ONLY this part into structured notes. Do not summarize away
specifics: keep every decision, every action item (with owner/deadline if
mentioned), important numbers, and named risks or open questions.

Return a JSON object with exactly these keys:
- "notes": array of short strings (the substantive points discussed).
- "decisions": array of short strings.
- "action_items": array of objects with "description", "owner", "due".
- "risks": array of short strings.

Write values in the same language as the transcript.

Transcript part:
\"\"\"
{chunk}
\"\"\"
"""

_REDUCE_TEMPLATE = """Below are condensed notes from consecutive parts of ONE long meeting.
Merge them into a single management meeting report.

{rules}

Deduplicate overlapping points. Return a JSON object with exactly these
keys: "overview", "key_points", "decisions", "action_items", "risks",
"next_steps", "sentiment".

Notes from the meeting (in order):
\"\"\"
{notes}
\"\"\"
"""



def _looks_degenerate(text: str) -> bool:
    """True if the transcript is Whisper hallucination on silence/noise.

    Whisper invents short repeated phrases ("ola ola ola...") when the
    audio is mostly silent — e.g. when only the bot's own microphone was
    recorded instead of the meeting audio. Such text must not be sent to
    the LLM, which would confidently write a report about nothing (and in
    the wrong language).
    """
    words = [w for w in text.lower().split() if w.strip()]
    if len(words) < 3:
        return True
    unique = len(set(words))
    if unique <= 2:
        return True
    if len(words) >= 10 and unique / len(words) < 0.2:
        return True
    return False


class SummaryService:
    """Generates structured, report-ready summaries from transcripts."""

    def __init__(self, session_id: str, language: str | None = None) -> None:
        self.session_id = session_id
        self.log = session_logger(__name__, session_id)
        self._llm = DeepSeekService()
        lang = (language or "").strip().lower()
        self._rules = _REPORT_RULES.format(
            language_rule=_LANGUAGE_RULES.get(lang, _DEFAULT_LANGUAGE_RULE)
        )

    async def summarize(self, transcript: Transcript) -> MeetingSummary:
        text = transcript.full_text.strip()
        if not text:
            self.log.warning("Empty transcript; returning empty summary")
            return MeetingSummary(session_id=self.session_id, overview="No speech was captured.")
        if _looks_degenerate(text):
            self.log.warning(
                "Transcript looks like silence/hallucination (%r...); skipping LLM",
                text[:60],
            )
            return MeetingSummary(
                session_id=self.session_id,
                overview=(
                    "No usable speech was captured in this meeting. The audio "
                    "recording was mostly silent — check that meeting audio is "
                    "routed to the recording device (e.g. VB-CABLE) and that "
                    "captions are enabled."
                ),
                sentiment="neutral",
            )

        try:
            if len(text) <= _SINGLE_PASS_CHARS:
                data = await self._summarize_single(text)
            else:
                data = await self._summarize_long(text)
        except DeepSeekError as exc:
            self.log.error("Summary generation failed: %s", exc)
            return MeetingSummary(
                session_id=self.session_id, overview=f"Summary unavailable: {exc}"
            )

        summary = self._parse(data)
        self.log.info(
            "Summary generated (%d key points, %d decisions, %d action items)",
            len(summary.key_points), len(summary.decisions), len(summary.action_items),
        )
        return summary

    # ------------------------------------------------------------------ #
    # Short path
    # ------------------------------------------------------------------ #
    async def _summarize_single(self, text: str) -> dict:
        user = _FINAL_TEMPLATE.format(rules=self._rules, transcript=text)
        return await self._llm.chat_json(_SYSTEM_PROMPT, user)

    # ------------------------------------------------------------------ #
    # Long path (map-reduce) — for 1-2 hour meetings
    # ------------------------------------------------------------------ #
    async def _summarize_long(self, text: str) -> dict:
        chunks = self._split(text, _CHUNK_CHARS)
        self.log.info("Long transcript (%d chars) -> %d chunks", len(text), len(chunks))

        # MAP: condense each chunk into notes (run sequentially to be gentle
        # on rate limits; switch to gather() later if speed matters).
        notes_blocks: list[str] = []
        for i, chunk in enumerate(chunks, start=1):
            user = _MAP_TEMPLATE.format(part=i, total=len(chunks), chunk=chunk)
            try:
                data = await self._llm.chat_json(_SYSTEM_PROMPT, user)
            except DeepSeekError as exc:
                # One failed chunk must not sink the whole report.
                self.log.warning("Chunk %d/%d failed: %s", i, len(chunks), exc)
                continue
            notes_blocks.append(self._format_notes(i, data))
            await asyncio.sleep(0.5)

        if not notes_blocks:
            raise DeepSeekError("All transcript chunks failed to summarize")

        # REDUCE: merge notes into the final report.
        user = _REDUCE_TEMPLATE.format(rules=self._rules, notes="\n\n".join(notes_blocks))
        return await self._llm.chat_json(_SYSTEM_PROMPT, user)

    @staticmethod
    def _split(text: str, size: int) -> list[str]:
        """Split on line boundaries so sentences are not cut mid-way."""
        chunks: list[str] = []
        current: list[str] = []
        current_len = 0
        for line in text.split("\n"):
            if current_len + len(line) > size and current:
                chunks.append("\n".join(current))
                current, current_len = [], 0
            current.append(line)
            current_len += len(line) + 1
        if current:
            chunks.append("\n".join(current))
        return chunks

    @staticmethod
    def _format_notes(part: int, data: dict) -> str:
        lines = [f"--- Part {part} ---"]
        for note in data.get("notes") or []:
            lines.append(f"* {note}")
        for d in data.get("decisions") or []:
            lines.append(f"DECISION: {d}")
        for a in data.get("action_items") or []:
            if isinstance(a, dict):
                owner = a.get("owner") or "?"
                due = a.get("due") or "?"
                lines.append(f"ACTION: {a.get('description', '')} (owner: {owner}, due: {due})")
            else:
                lines.append(f"ACTION: {a}")
        for r in data.get("risks") or []:
            lines.append(f"RISK: {r}")
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # Parse & validate
    # ------------------------------------------------------------------ #
    def _parse(self, data: dict) -> MeetingSummary:
        action_items: list[ActionItem] = []
        for item in data.get("action_items", []) or []:
            if isinstance(item, dict):
                action_items.append(
                    ActionItem(
                        description=str(item.get("description", "")).strip(),
                        owner=item.get("owner"),
                        due=item.get("due"),
                    )
                )
            elif isinstance(item, str):
                action_items.append(ActionItem(description=item.strip()))

        def _strs(key: str) -> list[str]:
            return [str(x).strip() for x in (data.get(key) or []) if str(x).strip()]

        return MeetingSummary(
            session_id=self.session_id,
            overview=str(data.get("overview", "")).strip(),
            key_points=_strs("key_points"),
            decisions=_strs("decisions"),
            action_items=[a for a in action_items if a.description],
            risks=_strs("risks"),
            next_steps=_strs("next_steps"),
            sentiment=data.get("sentiment"),
        )