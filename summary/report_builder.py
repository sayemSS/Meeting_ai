"""Markdown report builder.

Turns a MeetingMetadata + MeetingSummary into a human-readable
markdown management report (report.md).  The PDF is built separately
by report.report_service using this same data.
"""

from __future__ import annotations

from datetime import timezone

from utils.models import MeetingMetadata, MeetingSummary


def _fmt_duration(seconds: float) -> str:
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m}m" if h else f"{m}m {s}s"


def _fmt_dt(dt) -> str:
    if not dt:
        return "—"
    return dt.astimezone(timezone.utc).strftime("%d %b %Y, %H:%M UTC")


def build_report(metadata: MeetingMetadata, summary: MeetingSummary) -> str:
    """Return a markdown string for the meeting report."""
    lines: list[str] = []

    # ── Header ──────────────────────────────────────────────────────────
    lines.append(f"# Meeting Report: {metadata.title}\n")
    lines.append(f"**Date:** {_fmt_dt(metadata.actual_start)}")
    lines.append(f"**Duration:** {_fmt_duration(metadata.duration_seconds)}")
    lines.append(
        f"**Participants:** {', '.join(metadata.unique_participants) or '—'}"
    )
    lines.append(
        f"**Overall tone:** {(summary.sentiment or '—').capitalize()}"
    )
    lines.append("\n---\n")

    # ── Executive Summary ────────────────────────────────────────────────
    lines.append("## Executive Summary")
    lines.append(summary.overview or "—")

    # ── Key Discussion Points ────────────────────────────────────────────
    if summary.key_points:
        lines.append("\n## Key Discussion Points")
        for p in summary.key_points:
            lines.append(f"- {p}")

    # ── Decisions ───────────────────────────────────────────────────────
    if summary.decisions:
        lines.append("\n## Decisions Made")
        for d in summary.decisions:
            lines.append(f"- {d}")

    # ── Action Items ─────────────────────────────────────────────────────
    if summary.action_items:
        lines.append("\n## Action Items")
        lines.append("| # | Action | Owner | Due |")
        lines.append("|---|--------|-------|-----|")
        for i, a in enumerate(summary.action_items, start=1):
            lines.append(
                f"| {i} | {a.description} | {a.owner or '—'} | {a.due or '—'} |"
            )

    # ── Risks & Open Questions ───────────────────────────────────────────
    if summary.risks:
        lines.append("\n## Risks & Open Questions")
        for r in summary.risks:
            lines.append(f"- {r}")

    # ── Next Steps ───────────────────────────────────────────────────────
    if summary.next_steps:
        lines.append("\n## Next Steps")
        for n in summary.next_steps:
            lines.append(f"- {n}")

    # ── Footer ───────────────────────────────────────────────────────────
    lines.append(
        f"\n---\n*Generated automatically by Meeting AI Assistant · "
        f"session `{metadata.session_id}`*"
    )

    return "\n".join(lines)