"""PDF report generator (v2 — HTML + Chrome print).

WHY HTML->CHROME AND NOT REPORTLAB: Bengali script needs complex text
shaping (conjuncts like ন্ত, pre-base vowels like ে). reportlab cannot
shape Indic text, so Bangla comes out mangled and the Bengali-only Noto
font has no Latin letters, so English words vanish. Chrome shapes Bengali
perfectly — and the bot already ships with Playwright + Chrome, so this
adds zero new dependencies.

Pipeline: render the report as a styled HTML page, then print it to PDF
with headless Chrome via Playwright. If Chrome is unavailable for any
reason, a plain reportlab fallback still produces an English-safe PDF so
the session never fails.

FONTS: the page uses (in order) the project's fonts/NotoSansBengali.ttf
if present, the system "Noto Sans Bengali", and Windows' built-in
"Nirmala UI" (which includes Bengali). On a normal Windows machine Bangla
renders correctly even without the project font.
"""

from __future__ import annotations

import html as _html
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from utils.logger import get_logger
from utils.models import MeetingMetadata, MeetingSummary

log = get_logger(__name__)

_FONT_PATH = Path("fonts/NotoSansBengali.ttf")


def _fmt_duration(seconds: float) -> str:
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m}m" if h else f"{m}m {s}s"


def _fmt_dt(dt: Optional[datetime]) -> str:
    if not dt:
        return "—"
    return dt.astimezone(timezone.utc).strftime("%d %b %Y, %H:%M UTC")


def _esc(text: str) -> str:
    return _html.escape(str(text), quote=False)


class ReportService:
    """Builds the meeting report PDF (async — uses Playwright)."""

    async def build(
        self,
        metadata: MeetingMetadata,
        summary: MeetingSummary,
        output_path: Path,
    ) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        page_html = self._render_html(metadata, summary)
        try:
            await self._print_with_chrome(page_html, output_path)
        except Exception as exc:
            log.warning("Chrome PDF failed (%s); using reportlab fallback", exc)
            self._build_with_reportlab(metadata, summary, output_path)
        log.info("Report PDF written to %s", output_path)
        return output_path

    # ------------------------------------------------------------------ #
    # HTML rendering
    # ------------------------------------------------------------------ #
    def _render_html(self, meta: MeetingMetadata, s: MeetingSummary) -> str:
        font_face = ""
        if _FONT_PATH.exists():
            font_face = (
                "@font-face { font-family: 'ProjectBengali'; "
                f"src: url('{_FONT_PATH.resolve().as_uri()}'); }}"
            )

        def bullets(items: list[str]) -> str:
            return "".join(f"<li>{_esc(i)}</li>" for i in items)

        def section(title: str, items: list[str]) -> str:
            if not items:
                return ""
            return f"<h2>{title}</h2><ul>{bullets(items)}</ul>"

        actions = ""
        if s.action_items:
            rows = "".join(
                f"<tr><td>{i}</td><td>{_esc(a.description)}</td>"
                f"<td>{_esc(a.owner or '—')}</td><td>{_esc(a.due or '—')}</td></tr>"
                for i, a in enumerate(s.action_items, start=1)
            )
            actions = (
                "<h2>Action Items</h2>"
                "<table><thead><tr><th>#</th><th>Action</th>"
                "<th>Owner</th><th>Due</th></tr></thead>"
                f"<tbody>{rows}</tbody></table>"
            )

        participants = ", ".join(meta.unique_participants) or "—"
        tone = (s.sentiment or "—").capitalize()
        generated = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")

        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  {font_face}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: 'ProjectBengali', 'Noto Sans Bengali', 'Nirmala UI',
                 'Helvetica Neue', Arial, sans-serif;
    font-size: 10.5pt; line-height: 1.5; color: #1c1c1c; margin: 0;
  }}
  h1 {{ font-size: 17pt; text-align: center; margin: 0 0 10px; }}
  h2 {{ font-size: 12pt; color: #1a3a5c; margin: 16px 0 5px;
       border-bottom: 1px solid #dde4ec; padding-bottom: 2px; }}
  .meta p {{ margin: 1px 0; font-size: 9.5pt; color: #444; }}
  .rule {{ border: none; border-top: 2px solid #1a3a5c; margin: 8px 0 4px; }}
  ul {{ margin: 4px 0 4px 18px; padding: 0; }}
  li {{ margin: 2px 0; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 10pt; }}
  th, td {{ border: 1px solid #b9c4d0; padding: 4px 7px; text-align: left;
            vertical-align: top; }}
  th {{ background: #eef2f7; }}
  .footer {{ margin-top: 18px; border-top: 1px solid #ccc; padding-top: 5px;
             font-size: 8pt; color: #888; }}
  code {{ font-family: Consolas, monospace; }}
</style></head><body>
  <h1>Meeting Report: {_esc(meta.title)}</h1>
  <div class="meta">
    <p><b>Date:</b> {_fmt_dt(meta.actual_start)}</p>
    <p><b>Duration:</b> {_fmt_duration(meta.duration_seconds)}</p>
    <p><b>Participants:</b> {_esc(participants)}</p>
    <p><b>Overall tone:</b> {_esc(tone)}</p>
  </div>
  <hr class="rule">
  <h2>Executive Summary</h2>
  <p>{_esc(s.overview or '—')}</p>
  {section("Key Discussion Points", s.key_points)}
  {section("Decisions Made", s.decisions)}
  {actions}
  {section("Risks &amp; Open Questions", s.risks)}
  {section("Next Steps", s.next_steps)}
  <div class="footer">
    Generated automatically by Meeting AI Assistant ·
    session <code>{_esc(meta.session_id)}</code> · {generated}
  </div>
</body></html>"""

    # ------------------------------------------------------------------ #
    # Chrome print-to-PDF
    # ------------------------------------------------------------------ #
    async def _print_with_chrome(self, page_html: str, output_path: Path) -> None:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = None
            # Bundled Chromium first, then the installed Chrome channel.
            for kwargs in ({}, {"channel": "chrome"}):
                try:
                    browser = await pw.chromium.launch(headless=True, **kwargs)
                    break
                except Exception:
                    continue
            if browser is None:
                raise RuntimeError("No Chromium/Chrome available for PDF print")
            try:
                page = await browser.new_page()
                await page.set_content(page_html, wait_until="load")
                await page.pdf(
                    path=str(output_path),
                    format="A4",
                    margin={"top": "14mm", "bottom": "14mm",
                            "left": "16mm", "right": "16mm"},
                    print_background=True,
                )
            finally:
                await browser.close()

    # ------------------------------------------------------------------ #
    # reportlab fallback (English-safe; Bengali shaping NOT supported)
    # ------------------------------------------------------------------ #
    def _build_with_reportlab(
        self, meta: MeetingMetadata, s: MeetingSummary, output_path: Path
    ) -> None:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
        )

        styles = getSampleStyleSheet()
        body = ParagraphStyle("Body", parent=styles["Normal"], fontSize=10, leading=14)
        h1 = ParagraphStyle("H1", parent=styles["Title"], fontSize=17, leading=21)
        h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=12,
                            spaceBefore=12, spaceAfter=4,
                            textColor=colors.HexColor("#1a3a5c"))
        meta_style = ParagraphStyle("Meta", parent=body, fontSize=9.5,
                                    textColor=colors.HexColor("#444444"))
        footer = ParagraphStyle("Footer", parent=body, fontSize=8,
                                textColor=colors.HexColor("#888888"))

        story: list = [Paragraph(f"Meeting Report: {meta.title}", h1)]
        participants = ", ".join(meta.unique_participants) or "—"
        story += [
            Paragraph(f"<b>Date:</b> {_fmt_dt(meta.actual_start)}", meta_style),
            Paragraph(f"<b>Duration:</b> {_fmt_duration(meta.duration_seconds)}", meta_style),
            Paragraph(f"<b>Participants:</b> {participants}", meta_style),
            Paragraph(f"<b>Overall tone:</b> {(s.sentiment or '—').capitalize()}", meta_style),
            Spacer(1, 4),
            HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#1a3a5c")),
            Paragraph("Executive Summary", h2),
            Paragraph(s.overview or "—", body),
        ]

        def add(title: str, items: list[str]) -> None:
            if not items:
                return
            story.append(Paragraph(title, h2))
            for item in items:
                story.append(Paragraph(f"•&nbsp;&nbsp;{item}", body))

        add("Key Discussion Points", s.key_points)
        add("Decisions Made", s.decisions)
        if s.action_items:
            story.append(Paragraph("Action Items", h2))
            rows = [[Paragraph("<b>#</b>", body), Paragraph("<b>Action</b>", body),
                     Paragraph("<b>Owner</b>", body), Paragraph("<b>Due</b>", body)]]
            for i, a in enumerate(s.action_items, start=1):
                rows.append([Paragraph(str(i), body), Paragraph(a.description, body),
                             Paragraph(a.owner or "—", body), Paragraph(a.due or "—", body)])
            t = Table(rows, colWidths=[10 * mm, 95 * mm, 35 * mm, 30 * mm])
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f7")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b9c4d0")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            story.append(t)
        add("Risks & Open Questions", s.risks)
        add("Next Steps", s.next_steps)
        story += [
            Spacer(1, 10),
            HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc")),
            Paragraph(
                f"Generated automatically by Meeting AI Assistant · session "
                f"<font face='Courier'>{meta.session_id}</font> · "
                f"{datetime.now(timezone.utc).strftime('%d %b %Y %H:%M UTC')}",
                footer,
            ),
        ]
        SimpleDocTemplate(
            str(output_path), pagesize=A4,
            leftMargin=18 * mm, rightMargin=18 * mm,
            topMargin=16 * mm, bottomMargin=16 * mm,
            title=f"Meeting Report: {meta.title}",
        ).build(story)