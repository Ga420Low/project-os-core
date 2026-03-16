from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any


def render_operator_reply_pdf(
    destination: Path,
    *,
    display_title: str,
    metadata: dict[str, Any],
    overview: str,
    highlights: list[str],
    questions: list[str],
    full_response: str,
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        _render_with_reportlab(
            destination,
            display_title=display_title,
            metadata=metadata,
            overview=overview,
            highlights=highlights,
            questions=questions,
            full_response=full_response,
        )
    except Exception:
        _render_fallback(
            destination,
            display_title=display_title,
            metadata=metadata,
            overview=overview,
            highlights=highlights,
            questions=questions,
            full_response=full_response,
        )
    return destination


def _render_with_reportlab(
    destination: Path,
    *,
    display_title: str,
    metadata: dict[str, Any],
    overview: str,
    highlights: list[str],
    questions: list[str],
    full_response: str,
) -> None:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="ReplyTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=21,
            leading=25,
            textColor=colors.HexColor("#143642"),
            alignment=TA_LEFT,
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ReplyHeading",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=17,
            textColor=colors.HexColor("#0D3B66"),
            spaceBefore=8,
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ReplyMuted",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#52606D"),
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ReplyBody",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#1F2933"),
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ReplyBullet",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#1F2933"),
            leftIndent=12,
            firstLineIndent=0,
            bulletIndent=0,
            spaceAfter=3,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ReplySubheading",
            parent=styles["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=colors.HexColor("#143642"),
            spaceBefore=6,
            spaceAfter=2,
        )
    )

    doc = SimpleDocTemplate(
        str(destination),
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=display_title,
        author="Project OS",
    )
    generated_at = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")
    story: list[Any] = [
        Paragraph(display_title, styles["ReplyTitle"]),
        Paragraph(
            _escape("Version longue jointe depuis Discord pour une lecture propre et complete."),
            styles["ReplyBody"],
        ),
        Paragraph(_escape(f"Genere le {generated_at}"), styles["ReplyMuted"]),
        Spacer(1, 4),
    ]
    meta_rows = [
        [_kv("Canal", str(metadata.get("channel") or "-"), styles), _kv("Modele", str(metadata.get("model") or "-"), styles)],
        [_kv("Provider", str(metadata.get("provider") or "-"), styles), _kv("Message", str(metadata.get("message_id") or "-"), styles)],
    ]
    meta_table = Table(meta_rows, colWidths=[82 * mm, 82 * mm])
    meta_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F5F7FA")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#BCCCDC")),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D9E2EC")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.extend([meta_table, Spacer(1, 8)])

    if str(overview or "").strip():
        story.append(Paragraph("En bref", styles["ReplyHeading"]))
        story.append(Paragraph(_escape(str(overview).strip()), styles["ReplyBody"]))
    if highlights:
        story.append(Paragraph("Ce que tu trouveras dans ce document", styles["ReplyHeading"]))
        _append_bullets(story, styles["ReplyBody"], highlights)
    if questions:
        story.append(Paragraph("Question ouverte", styles["ReplyHeading"]))
        _append_bullets(story, styles["ReplyBody"], questions)

    story.append(Paragraph("Version complete", styles["ReplyHeading"]))
    _append_full_response(story, styles, str(full_response or ""))

    def _decorate(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#52606D"))
        canvas.drawString(16 * mm, 8 * mm, f"Project OS - {display_title}")
        canvas.drawRightString(A4[0] - 16 * mm, 8 * mm, f"Page {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_decorate, onLaterPages=_decorate)


def _render_fallback(
    destination: Path,
    *,
    display_title: str,
    metadata: dict[str, Any],
    overview: str,
    highlights: list[str],
    questions: list[str],
    full_response: str,
) -> None:
    lines = [
        display_title,
        "",
        f"Canal: {metadata.get('channel') or '-'}",
        f"Provider: {metadata.get('provider') or '-'}",
        f"Modele: {metadata.get('model') or '-'}",
        f"Message id: {metadata.get('message_id') or '-'}",
    ]
    if str(overview or "").strip():
        lines.extend(["", "En bref", str(overview).strip()])
    if highlights:
        lines.extend(["", "Ce que tu trouveras dans ce document", *[f"- {item}" for item in highlights]])
    if questions:
        lines.extend(["", "Question ouverte", *[f"- {item}" for item in questions]])
    lines.extend(["", "Version complete", "", str(full_response or "").strip()])
    _write_minimal_pdf(destination, lines)


def _append_bullets(story: list[Any], body_style: Any, payload: list[str]) -> None:
    from reportlab.platypus import Paragraph

    for line in payload:
        cleaned = str(line or "").strip()
        if not cleaned:
            continue
        story.append(Paragraph(f"- {_rich_text(cleaned)}", body_style))


def _append_full_response(story: list[Any], styles: Any, full_response: str) -> None:
    from reportlab.platypus import Paragraph, Spacer

    blocks = [block.strip() for block in re.split(r"\n\s*\n", str(full_response or "").strip()) if block.strip()]
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        if len(lines) == 1:
            line = lines[0]
            if _looks_like_heading(line):
                story.append(Paragraph(_rich_text(_normalize_heading(line)), styles["ReplySubheading"]))
            elif _looks_like_list_item(line):
                _append_list_item(story, styles, line)
            else:
                story.append(Paragraph(_rich_text(line), styles["ReplyBody"]))
            continue

        first = lines[0]
        rest = lines[1:]
        if _looks_like_heading(first):
            story.append(Paragraph(_rich_text(_normalize_heading(first)), styles["ReplySubheading"]))
            for line in rest:
                if _looks_like_list_item(line):
                    _append_list_item(story, styles, line)
                else:
                    story.append(Paragraph(_rich_text(line), styles["ReplyBody"]))
        else:
            for line in lines:
                if _looks_like_list_item(line):
                    _append_list_item(story, styles, line)
                else:
                    story.append(Paragraph(_rich_text(line), styles["ReplyBody"]))
        story.append(Spacer(1, 2))


def _append_list_item(story: list[Any], styles: Any, line: str) -> None:
    from reportlab.platypus import Paragraph

    bullet_match = re.match(r"^[-*]\s+(.*)$", line)
    number_match = re.match(r"^(\d+)\.\s+(.*)$", line)
    if bullet_match:
        story.append(Paragraph(f"- {_rich_text(bullet_match.group(1).strip())}", styles["ReplyBullet"]))
        return
    if number_match:
        number = number_match.group(1)
        body = number_match.group(2).strip()
        story.append(Paragraph(f"{number}. {_rich_text(body)}", styles["ReplyBullet"]))
        return
    story.append(Paragraph(_rich_text(line.strip()), styles["ReplyBullet"]))


def _looks_like_heading(line: str) -> bool:
    cleaned = line.strip()
    if not cleaned:
        return False
    if cleaned.startswith(("# ", "## ", "### ")):
        return True
    if re.match(r"^\d+\.\s+\*\*.+\*\*:?\s*$", cleaned):
        return True
    if re.match(r"^\*\*.+\*\*:?\s*$", cleaned):
        return True
    return cleaned.endswith(":") and len(cleaned) <= 90


def _looks_like_list_item(line: str) -> bool:
    cleaned = line.strip()
    return bool(re.match(r"^[-*]\s+", cleaned) or re.match(r"^\d+\.\s+", cleaned))


def _normalize_heading(line: str) -> str:
    cleaned = line.strip()
    cleaned = re.sub(r"^#{1,3}\s*", "", cleaned)
    cleaned = re.sub(r"^\d+\.\s+", "", cleaned)
    if cleaned.endswith(":"):
        cleaned = cleaned[:-1].rstrip()
    return cleaned


def _escape(value: str) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )


def _rich_text(value: str) -> str:
    text = _escape(value)
    text = re.sub(r"`([^`]+)`", lambda match: f"<font face='Courier'>{match.group(1)}</font>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", lambda match: f"<b>{match.group(1)}</b>", text)
    return text


def _kv(label: str, value: str, styles: Any):
    from reportlab.platypus import Paragraph

    return Paragraph(f"<b>{_escape(label)}</b><br/>{_escape(value)}", styles["ReplyBody"])


def _write_minimal_pdf(destination: Path, lines: list[str]) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    pdf = canvas.Canvas(str(destination), pagesize=A4)
    width, height = A4
    y = height - 18 * mm
    pdf.setFont("Helvetica", 10)
    for raw_line in lines:
        line = str(raw_line or "")
        if y < 18 * mm:
            pdf.showPage()
            pdf.setFont("Helvetica", 10)
            y = height - 18 * mm
        pdf.drawString(16 * mm, y, line[:110])
        y -= 6 * mm
    pdf.save()
