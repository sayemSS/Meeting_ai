"""Summary service.

Turns a Transcript into a structured MeetingSummary (overview, key points,
decisions, action items, sentiment) by prompting the DeepSeek LLM and parsing
its JSON response. The prompt is constrained and the output validated against
the MeetingSummary model, so the dashboard always receives a predictable
shape. Long transcripts are truncated to a safe character budget.
"""

from __future__ import annotations

from llm.deepseek_service import DeepSeekError, DeepSeekService
from utils.logger import session_logger
from utils.models import ActionItem, MeetingSummary, Transcript

_MAX_TRANSCRIPT_CHARS = 24000

_SYSTEM_PROMPT = (
    "You are an expert meeting analyst. You read raw meeting transcripts and "
    "produce concise, accurate, structured summaries. Never invent facts that "
    "are not supported by the transcript. Respond with a single JSON object only."
)

_USER_TEMPLATE = """Summarize the following meeting transcript.

Return a JSON object with exactly these keys:
- "overview": a 2-4 sentence summary of the meeting.
- "key_points": array of short strings (the main discussion points).
- "decisions": array of short strings (decisions that were made).
- "action_items": array of objects with keys "description", "owner" (or null),
  and "due" (or null).
- "sentiment": one of "positive", "neutral", "negative", or "mixed".

Transcript:
\"\"\"
{transcript}
\"\"\"
"""


class SummaryService:
    """Generates structured summaries from transcripts using DeepSeek."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.log = session_logger(__name__, session_id)
        self._llm = DeepSeekService()

    async def summarize(self, transcript: Transcript) -> MeetingSummary:
        text = transcript.full_text.strip()
        if not text:
            self.log.warning("Empty transcript; returning empty summary")
            return MeetingSummary(session_id=self.session_id, overview="No speech was captured.")

        if len(text) > _MAX_TRANSCRIPT_CHARS:
            self.log.info("Truncating transcript from %d chars", len(text))
            text = text[:_MAX_TRANSCRIPT_CHARS]

        user = _USER_TEMPLATE.format(transcript=text)
        try:
            data = await self._llm.chat_json(_SYSTEM_PROMPT, user)
        except DeepSeekError as exc:
            self.log.error("Summary generation failed: %s", exc)
            return MeetingSummary(
                session_id=self.session_id, overview=f"Summary unavailable: {exc}"
            )

        summary = self._parse(data)
        self.log.info(
            "Summary generated (%d key points, %d action items)",
            len(summary.key_points), len(summary.action_items),
        )
        return summary

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

        return MeetingSummary(
            session_id=self.session_id,
            overview=str(data.get("overview", "")).strip(),
            key_points=[str(x).strip() for x in (data.get("key_points") or []) if str(x).strip()],
            decisions=[str(x).strip() for x in (data.get("decisions") or []) if str(x).strip()],
            action_items=[a for a in action_items if a.description],
            sentiment=data.get("sentiment"),
        )
