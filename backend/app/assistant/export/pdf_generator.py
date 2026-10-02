"""Render a chat conversation to a well-formatted, multi-page PDF.

Uses ReportLab's Platypus document model so long conversations flow across
pages automatically with consistent margins, headings, spacing, and footer
page numbers. Lightweight markdown-ish formatting (bullets, numbered lists,
**bold**, *italic*) from assistant turns is preserved where practical.

The only public entry point is `build_conversation_pdf`, which returns the PDF
as raw bytes so the caller decides how to stream/store it.
"""
from __future__ import annotations

import io
import os
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    ListFlowable,
    ListItem,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.assistant.schemas.conversation import Conversation

# Page geometry — generous margins keep text well inside the printable area.
_PAGE_SIZE = A4
_MARGIN = 20 * mm

# India Standard Time is a fixed UTC+5:30 offset (no DST), so a fixed-offset
# timezone is correct and avoids a tzdata dependency on Windows hosts.
_IST = timezone(timedelta(hours=5, minutes=30), name="IST")


def ist_now() -> datetime:
    """Current wall-clock time in India Standard Time."""
    return datetime.now(_IST)


def fmt_ist(dt: datetime) -> str:
    """Format a datetime in IST as e.g. '19 Jun 2026, 11:02 AM IST'."""
    hour12 = dt.hour % 12 or 12  # 0/12/24h → 12-hour clock, no leading zero
    return f"{dt.day:02d} {dt:%b %Y}, {hour12}:{dt:%M %p} IST"

# Roles we render as conversation turns; everything else (tool/system) is hidden
# so the export mirrors what the user actually sees on screen.
_VISIBLE_ROLES = ("user", "assistant")

_BULLET_RE = re.compile(r"^\s*[-*•]\s+(.*)$")
_NUMBERED_RE = re.compile(r"^\s*\d+[.)]\s+(.*)$")

# A markdown table's second line is a separator like `|---|:--:|---|`: only
# pipes, dashes, colons and spaces, and at least one dash.
_TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$")
# Split a row on unescaped pipes so `\|` can appear literally inside a cell.
_PIPE_SPLIT_RE = re.compile(r"(?<!\\)\|")

# Any character in the Devanagari Unicode block (U+0900-U+097F) needs a
# Devanagari-aware font. (Plain str, not raw, so the \u escapes are decoded.)
_DEVANAGARI_RE = re.compile("[ऀ-ॿ]")

# Resolved Devanagari font family name once registered (or None if unavailable).
_DEV_FONT: Optional[str] = None
_DEV_FONTS_TRIED = False

_FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")
# (regular, bold) candidate paths: bundled Noto first (portable, OFL-licensed),
# then common Linux/Windows system locations as a best-effort fallback.
_DEV_FONT_CANDIDATES = [
    (
        os.path.join(_FONT_DIR, "NotoSansDevanagari-Regular.ttf"),
        os.path.join(_FONT_DIR, "NotoSansDevanagari-Bold.ttf"),
    ),
    (
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf",
    ),
]


def _ensure_dev_font() -> Optional[str]:
    """Register a Devanagari-capable TTF once; return its family name or None.

    Registers a regular + bold pair under the 'NotoDevanagari' family so inline
    <b> markup resolves to the bold face. Failures degrade gracefully to None
    (callers then keep Helvetica — English is unaffected either way).
    """
    global _DEV_FONT, _DEV_FONTS_TRIED
    if _DEV_FONTS_TRIED:
        return _DEV_FONT
    _DEV_FONTS_TRIED = True

    for reg_path, bold_path in _DEV_FONT_CANDIDATES:
        if not os.path.exists(reg_path):
            continue
        try:
            pdfmetrics.registerFont(TTFont("NotoDevanagari", reg_path))
            bold_name = "NotoDevanagari"
            if bold_path and os.path.exists(bold_path):
                pdfmetrics.registerFont(TTFont("NotoDevanagari-Bold", bold_path))
                bold_name = "NotoDevanagari-Bold"
            pdfmetrics.registerFontFamily(
                "NotoDevanagari",
                normal="NotoDevanagari",
                bold=bold_name,
                italic="NotoDevanagari",
                boldItalic=bold_name,
            )
            _DEV_FONT = "NotoDevanagari"
            break
        except Exception:
            continue
    return _DEV_FONT


# Maximal run of Devanagari characters (incl. ZWJ/ZWNJ so conjuncts stay intact).
_DEV_RUN_RE = re.compile("[ऀ-ॿ‌‍]+")


def _wrap_devanagari(text: str) -> str:
    """Tag Devanagari runs with the Unicode font, leaving Latin in the base font.

    Noto Sans Devanagari has no Latin glyphs, so swapping a whole mixed-script
    paragraph to it would box the English. Instead each Devanagari run is wrapped
    in <font name="NotoDevanagari">…</font>; inline <b>/<i> still resolve to the
    bold/italic face via the registered font family. No-ops if no font registered.
    """
    if not _DEV_FONT or not _DEVANAGARI_RE.search(text):
        return text
    return _DEV_RUN_RE.sub(rf'<font name="{_DEV_FONT}">\g<0></font>', text)


def _para(text: str, style: ParagraphStyle) -> Paragraph:
    """Build a Paragraph (Devanagari runs are already font-tagged by `_escape`)."""
    return Paragraph(text, style)


def _styles():
    """Build the paragraph styles used across the document (once per render)."""
    base = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle(
            "ChatTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            spaceAfter=4,
            textColor=colors.HexColor("#1e1b4b"),
        ),
        "subtitle": ParagraphStyle(
            "ChatSubtitle",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#6b7280"),
            spaceAfter=2,
        ),
        "role_user": ParagraphStyle(
            "RoleUser",
            parent=base["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=colors.HexColor("#4338ca"),
            spaceBefore=12,
            spaceAfter=3,
        ),
        "role_assistant": ParagraphStyle(
            "RoleAssistant",
            parent=base["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=colors.HexColor("#047857"),
            spaceBefore=12,
            spaceAfter=3,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10.5,
            leading=15,
            alignment=TA_LEFT,
            textColor=colors.HexColor("#111827"),
            spaceAfter=4,
        ),
    }
    return styles


def _escape(text: str) -> str:
    """Escape XML special chars, then re-apply a tiny markdown→ReportLab subset."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # **bold** and __bold__
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)
    # *italic* and _italic_ (avoid matching the bold markers already consumed)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"<i>\1</i>", text)
    # `code`
    text = re.sub(r"`(.+?)`", r'<font face="Courier">\1</font>', text)
    # Route Devanagari runs through the Unicode font (keeps Latin in Helvetica).
    text = _wrap_devanagari(text)
    return text


def _split_table_row(line: str) -> List[str]:
    """Split a markdown table row into trimmed cell strings.

    Handles optional leading/trailing pipes and escaped `\\|` inside cells.
    """
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.replace("\\|", "|").strip() for c in _PIPE_SPLIT_RE.split(s)]


def _is_table_start(lines: List[str], i: int) -> bool:
    """True if a markdown table begins at line `i` (header row + separator)."""
    n = len(lines)
    if i + 1 >= n:
        return False
    header = lines[i]
    sep = lines[i + 1]
    if "|" not in header or _TABLE_SEP_RE.match(header):
        return False
    return bool(_TABLE_SEP_RE.match(sep)) and "-" in sep


def _build_table(header: List[str], rows: List[List[str]], doc_width: float):
    """Render a markdown table as a real, page-fitting ReportLab Table.

    Column widths sum to `doc_width` so the table never overflows the page; the
    font shrinks as columns grow so wide tables stay legible; cells use wrapping
    Paragraphs; and the header row repeats on every page the table spans.
    """
    ncols = max(1, len(header))
    # Scale font down as the table widens so columns don't get cramped.
    font_size = 9 if ncols <= 4 else 8 if ncols <= 6 else 7
    leading = font_size + 2
    pad = 5 if ncols <= 6 else 3

    cell_style = ParagraphStyle(
        "TableCell",
        fontName="Helvetica",
        fontSize=font_size,
        leading=leading,
        textColor=colors.HexColor("#111827"),
    )
    head_style = ParagraphStyle(
        "TableHead",
        fontName="Helvetica-Bold",
        fontSize=font_size,
        leading=leading,
        textColor=colors.white,
    )

    def _row(cells: List[str], style) -> list:
        # Pad/truncate every row to the header's column count so the grid is square.
        padded = (cells + [""] * ncols)[:ncols]
        return [_para(_escape(c or ""), style) for c in padded]

    data = [_row(header, head_style)]
    data.extend(_row(r, cell_style) for r in rows)

    col_width = doc_width / ncols
    table = Table(data, colWidths=[col_width] * ncols, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4338ca")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                 [colors.white, colors.HexColor("#f3f4f6")]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), pad),
                ("RIGHTPADDING", (0, 0), (-1, -1), pad),
                ("TOPPADDING", (0, 0), (-1, -1), pad),
                ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
            ]
        )
    )
    return table


def _content_flowables(content: str, styles, doc_width: float) -> list:
    """Convert one message body into a list of flowables.

    Splits on blank lines into blocks; markdown tables become real ReportLab
    tables, consecutive bullet/numbered lines become a single proper list, and
    plain lines collapse into wrapped paragraphs. `doc_width` bounds table width.
    """
    flowables: list = []
    if not content or not content.strip():
        flowables.append(Paragraph("<i>(no content)</i>", styles["body"]))
        return flowables

    lines = content.replace("\r\n", "\n").split("\n")
    i = 0
    n = len(lines)

    def flush_paragraph(buf: List[str]):
        if buf:
            flowables.append(_para(_escape(" ".join(buf)), styles["body"]))
            buf.clear()

    para_buf: List[str] = []
    while i < n:
        line = lines[i]

        # Markdown table → real PDF table (checked first so pipes never leak as text).
        if _is_table_start(lines, i):
            flush_paragraph(para_buf)
            header = _split_table_row(lines[i])
            i += 2  # skip header + separator
            rows: List[List[str]] = []
            while i < n and "|" in lines[i] and lines[i].strip():
                rows.append(_split_table_row(lines[i]))
                i += 1
            flowables.append(Spacer(1, 2))
            flowables.append(_build_table(header, rows, doc_width))
            flowables.append(Spacer(1, 2))
            continue

        bullet = _BULLET_RE.match(line)
        numbered = _NUMBERED_RE.match(line)

        if bullet or numbered:
            flush_paragraph(para_buf)
            ordered = bool(numbered)
            items: List[ListItem] = []
            while i < n:
                bm = _BULLET_RE.match(lines[i])
                nm = _NUMBERED_RE.match(lines[i])
                if ordered and nm:
                    items.append(ListItem(_para(_escape(nm.group(1)), styles["body"])))
                elif (not ordered) and bm:
                    items.append(ListItem(_para(_escape(bm.group(1)), styles["body"])))
                else:
                    break
                i += 1
            flowables.append(
                ListFlowable(
                    items,
                    bulletType="1" if ordered else "bullet",
                    bulletColor=colors.HexColor("#6b7280"),
                    leftIndent=14,
                    bulletFontSize=9,
                )
            )
            continue

        if not line.strip():
            flush_paragraph(para_buf)
        else:
            para_buf.append(line.strip())
        i += 1

    flush_paragraph(para_buf)
    return flowables


def _footer(canvas, doc):
    """Draw 'Page N' centered in the bottom margin of every page."""
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#9ca3af"))
    width, _ = _PAGE_SIZE
    canvas.drawCentredString(width / 2.0, 12 * mm, f"Page {doc.page}")
    canvas.restoreState()


def build_conversation_pdf(conversation: Conversation) -> bytes:
    """Render `conversation` to PDF bytes (A4, multi-page, page-numbered)."""
    buffer = io.BytesIO()
    _ensure_dev_font()  # register the Devanagari font once before building paragraphs
    styles = _styles()

    doc = BaseDocTemplate(
        buffer,
        pagesize=_PAGE_SIZE,
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
        topMargin=_MARGIN,
        bottomMargin=_MARGIN,
        title="Chat Conversation",
        author="Sparsh Assistant",
    )
    frame = Frame(
        doc.leftMargin,
        doc.bottomMargin,
        doc.width,
        doc.height,
        id="body",
    )
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=_footer)])

    story: list = []

    # ── Header ────────────────────────────────────────────────────────────
    title = (conversation.title or "Chat Conversation").strip() or "Chat Conversation"
    story.append(_para(_escape(title), styles["title"]))
    story.append(Paragraph("Chat Conversation", styles["subtitle"]))
    # Generated at the moment of export, in India Standard Time.
    story.append(
        Paragraph(f"Generated on {fmt_ist(ist_now())}", styles["subtitle"])
    )
    story.append(Spacer(1, 6))

    # ── Turns ─────────────────────────────────────────────────────────────
    visible = [m for m in conversation.messages if m.role in _VISIBLE_ROLES]
    if not visible:
        story.append(Spacer(1, 10))
        story.append(Paragraph("<i>This conversation has no messages yet.</i>", styles["body"]))
    for msg in visible:
        if msg.role == "user":
            story.append(Paragraph("User", styles["role_user"]))
        else:
            story.append(Paragraph("Assistant", styles["role_assistant"]))
        story.extend(_content_flowables(msg.content or "", styles, doc.width))
        story.append(Spacer(1, 6))

    doc.build(story)
    pdf = buffer.getvalue()
    buffer.close()
    return pdf
