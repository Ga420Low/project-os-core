from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
import textwrap
import unicodedata
from typing import Any


def build_seo_slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").strip())
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")
    return slug or "deep-research"


def build_archive_stem(*, title: str, kind: str, created_at: str | None = None) -> str:
    raw_date = str(created_at or "").strip()[:10] or datetime.now(timezone.utc).date().isoformat()
    suffix = "system-dossier" if str(kind or "").strip().lower() == "system" else "deep-research-audit"
    return f"{raw_date}-{build_seo_slug(title)}-{suffix}"


def render_deep_research_pdf(
    destination: Path,
    *,
    display_title: str,
    request: dict[str, Any],
    structured: dict[str, Any],
    repo_context: dict[str, Any],
    dossier_relative_path: str | None,
    archive_relative_path: str | None,
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        _render_with_reportlab(
            destination,
            display_title=display_title,
            request=request,
            structured=structured,
            repo_context=repo_context,
            dossier_relative_path=dossier_relative_path,
            archive_relative_path=archive_relative_path,
        )
    except Exception:
        _render_fallback_pdf(
            destination,
            display_title=display_title,
            request=request,
            structured=structured,
            repo_context=repo_context,
            dossier_relative_path=dossier_relative_path,
            archive_relative_path=archive_relative_path,
        )
    return destination


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
        _render_operator_reply_with_reportlab(
            destination,
            display_title=display_title,
            metadata=metadata,
            overview=overview,
            highlights=highlights,
            questions=questions,
            full_response=full_response,
        )
    except Exception:
        _render_operator_reply_fallback(
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
    request: dict[str, Any],
    structured: dict[str, Any],
    repo_context: dict[str, Any],
    dossier_relative_path: str | None,
    archive_relative_path: str | None,
) -> None:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
        PageBreak,
    )

    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="ResearchTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=26,
            textColor=colors.HexColor("#143642"),
            alignment=TA_LEFT,
            spaceAfter=12,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ResearchHeading",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=18,
            textColor=colors.HexColor("#0D3B66"),
            spaceBefore=10,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ResearchBody",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=13,
            textColor=colors.HexColor("#1F2933"),
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ResearchMuted",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#52606D"),
            spaceAfter=3,
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

    story: list[Any] = []
    question = str(request.get("question") or "").strip()
    kind = str(request.get("kind") or "audit").strip().lower()
    research_profile = str(structured.get("research_profile") or request.get("research_profile") or "domain_audit").strip().lower()
    research_intensity = str(structured.get("research_intensity") or request.get("research_intensity") or "simple").strip().lower()
    generated_at = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")
    recommendation_rows = [
        item for item in structured.get("recommendations", []) if isinstance(item, dict)
    ]
    bucket_counts = {
        "A faire": sum(1 for item in recommendation_rows if str(item.get("bucket") or "").strip().lower() == "a_faire"),
        "A etudier": sum(1 for item in recommendation_rows if str(item.get("bucket") or "").strip().lower() == "a_etudier"),
        "A rejeter": sum(1 for item in recommendation_rows if str(item.get("bucket") or "").strip().lower() == "a_rejeter"),
    }

    story.append(Paragraph(display_title, styles["ResearchTitle"]))
    story.append(
        Paragraph(
            f"Rapport Project OS recherche approfondie - type {kind} - genere le {generated_at}",
            styles["ResearchMuted"],
        )
    )
    if question:
        story.append(Paragraph(_escape(question), styles["ResearchBody"]))
    story.append(Spacer(1, 4))

    meta_table = Table(
        [
            [
                _kv("Repo dossier", dossier_relative_path or "-", styles),
                _kv("Archive cold", archive_relative_path or "-", styles),
            ],
            [
                _kv("Branche", str(repo_context.get("current_branch") or "-"), styles),
                _kv("Modele", str(structured.get("metadata", {}).get("model") or "-"), styles),
            ],
            [
                _kv("Buckets", " | ".join(f"{key}: {value}" for key, value in bucket_counts.items()), styles),
                _kv("Tool", str(structured.get("metadata", {}).get("tool_type") or "-"), styles),
            ],
            [
                _kv("Profil", research_profile, styles),
                _kv("Intensite", research_intensity, styles),
            ],
        ],
        colWidths=[82 * mm, 82 * mm],
    )
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
    story.append(meta_table)
    story.append(Spacer(1, 8))

    story.append(Paragraph("Synthese executive", styles["ResearchHeading"]))
    for line in _coerce_lines(structured.get("summary")):
        story.append(Paragraph(_escape(line), styles["ResearchBody"]))

    if research_profile == "project_audit":
        block = structured.get("project_audit_block") or {}
        story.append(Paragraph("Cap nord", styles["ResearchHeading"]))
        _append_bullets(story, styles, block.get("north_star"))
        story.append(Paragraph("These systeme", styles["ResearchHeading"]))
        _append_bullets(story, styles, block.get("system_thesis"))
        story.append(Paragraph("Couches plateforme", styles["ResearchHeading"]))
        _append_bullets(story, styles, block.get("platform_layers"))
        _append_labeled_table(
            story,
            styles,
            title="Priorite / Pourquoi / Ce que ca debloque",
            headers=("Priorite", "Pourquoi", "Ce que ca debloque"),
            rows=[
                (
                    "Foundational now",
                    _join_lines((block.get("priority_ladder") or {}).get("foundational_now")),
                    _join_lines((recommendation_rows[0].get("goal_link") if recommendation_rows else [])),
                ),
                (
                    "System next",
                    _join_lines((block.get("priority_ladder") or {}).get("system_next")),
                    _join_lines((recommendation_rows[1].get("goal_link") if len(recommendation_rows) > 1 else [])),
                ),
                (
                    "Expansion later",
                    _join_lines((block.get("priority_ladder") or {}).get("expansion_later")),
                    _join_lines((recommendation_rows[2].get("goal_link") if len(recommendation_rows) > 2 else [])),
                ),
            ],
            col_widths=[32 * mm, 66 * mm, 68 * mm],
        )
        _append_labeled_table(
            story,
            styles,
            title="Brique systeme / Etat actuel / Impact",
            headers=("Brique systeme", "Etat actuel", "Impact"),
            rows=[
                (
                    _safe_line(layer),
                    _safe_line(gap),
                    _safe_line(metric),
                )
                for layer, gap, metric in zip(
                    _coerce_lines(block.get("platform_layers")),
                    _coerce_lines(block.get("capability_gaps")),
                    _coerce_lines(block.get("success_metrics")),
                )
            ][:4],
            col_widths=[40 * mm, 62 * mm, 64 * mm],
        )
        _append_runtime_table(
            story,
            styles,
            issues=_coerce_lines(block.get("observed_runtime_issues")),
            actions=_coerce_lines((block.get("priority_ladder") or {}).get("foundational_now")),
        )
    elif research_profile == "component_discovery":
        block = structured.get("component_discovery_block") or {}
        story.append(Paragraph("Angles morts", styles["ResearchHeading"]))
        _append_bullets(story, styles, block.get("blind_spots"))
        story.append(Paragraph("Leviers externes", styles["ResearchHeading"]))
        _append_bullets(story, styles, block.get("external_leverage"))
        _append_labeled_table(
            story,
            styles,
            title="Priorite / Pourquoi / Ce que ca debloque",
            headers=("Priorite", "Pourquoi", "Ce que ca debloque"),
            rows=[
                (
                    "Highest leverage now",
                    _join_lines((block.get("priority_ladder") or {}).get("highest_leverage_now")),
                    _join_lines((recommendation_rows[0].get("goal_link") if recommendation_rows else [])),
                ),
                (
                    "Major system next",
                    _join_lines((block.get("priority_ladder") or {}).get("major_system_next")),
                    _join_lines((recommendation_rows[1].get("goal_link") if len(recommendation_rows) > 1 else [])),
                ),
                (
                    "Watch and prepare",
                    _join_lines((block.get("priority_ladder") or {}).get("watch_and_prepare")),
                    _join_lines((recommendation_rows[2].get("goal_link") if len(recommendation_rows) > 2 else [])),
                ),
            ],
            col_widths=[32 * mm, 66 * mm, 68 * mm],
        )
        _append_labeled_table(
            story,
            styles,
            title="Pepite externe / Ce qu on vole / Pourquoi c est fort",
            headers=("Pepite externe", "Ce qu on vole", "Pourquoi c est fort"),
            rows=[
                (
                    _safe_line(item.get("system_name")),
                    _join_lines(item.get("what_to_take")),
                    _join_lines(item.get("why")),
                )
                for item in recommendation_rows[:4]
            ],
            col_widths=[40 * mm, 62 * mm, 64 * mm],
        )
        _append_labeled_table(
            story,
            styles,
            title="Manque actuel / Impact / Ce qu il faut changer",
            headers=("Manque actuel", "Impact", "Ce qu il faut changer"),
            rows=[
                (
                    _safe_line(lack),
                    _safe_line(metric),
                    _safe_line(action),
                )
                for lack, metric, action in zip(
                    _coerce_lines(block.get("underbuilt_layers")),
                    _coerce_lines(block.get("success_metrics")),
                    _coerce_lines((block.get("priority_ladder") or {}).get("highest_leverage_now")),
                )
            ][:4],
            col_widths=[44 * mm, 44 * mm, 78 * mm],
        )
        _append_runtime_table(
            story,
            styles,
            issues=_coerce_lines(block.get("observed_runtime_issues")),
            actions=_coerce_lines((block.get("priority_ladder") or {}).get("highest_leverage_now")),
        )
    else:
        story.append(Paragraph("Pourquoi ce rapport compte", styles["ResearchHeading"]))
        _append_bullets(story, styles, structured.get("why_now"))
        story.append(Paragraph("Cohérence avec Project OS", styles["ResearchHeading"]))
        _append_bullets(story, styles, structured.get("repo_fit"))
        story.append(Paragraph("Actions prioritaires", styles["ResearchHeading"]))
        _append_bullets(story, styles, structured.get("priority_actions"))

    if recommendation_rows:
        story.append(Paragraph("Carte rapide des pistes", styles["ResearchHeading"]))
        table_rows = [[_p("Lane", styles, "Lane"), _p("Decision", styles, "Decision"), _p("Systeme", styles, "Systeme")]]
        for item in recommendation_rows:
            table_rows.append(
                [
                    _p(_bucket_label(str(item.get("bucket") or "")), styles, _bucket_label(str(item.get("bucket") or ""))),
                    _p(str(item.get("decision") or "-"), styles, str(item.get("decision") or "-")),
                    _p(str(item.get("system_name") or "-"), styles, str(item.get("system_name") or "-")),
                ]
            )
        summary_table = Table(table_rows, colWidths=[28 * mm, 28 * mm, 108 * mm], repeatRows=1)
        summary_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0D3B66")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
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
        story.append(summary_table)
        story.append(PageBreak())

    group_order = ("a_faire", "a_etudier", "a_rejeter")
    group_titles = {
        "a_faire": "A faire",
        "a_etudier": "A etudier",
        "a_rejeter": "A rejeter pour maintenant",
    }
    for group_name in group_order:
        group_items = [item for item in recommendation_rows if str(item.get("bucket") or "").strip().lower() == group_name]
        if not group_items:
            continue
        story.append(Paragraph(group_titles[group_name], styles["ResearchHeading"]))
        for item in group_items:
            story.append(
                Paragraph(
                    f"{_escape(str(item.get('system_name') or '-'))} - {str(item.get('decision') or '-').upper()}",
                    styles["Heading3"],
                )
            )
            for label, key in (
                ("Lien objectif", "goal_link"),
                ("ROI attendu", "roi"),
                ("Role dans la sequence", "sequence_role"),
                ("Niveau de scope", "scope_level"),
                ("Pourquoi", "why"),
                ("Ce qu'on recupere", "what_to_take"),
                ("Ce qu'on n'importe pas", "what_not_to_take"),
                ("Signal forks / satellites", "fork_signal"),
                ("Base de preuve", "evidence_basis"),
                ("Ou ca entre dans Project OS", "project_os_touchpoints"),
                ("Preuves a obtenir", "proofs"),
            ):
                story.append(Paragraph(label, styles["ResearchMuted"]))
                _append_bullets(story, styles, item.get(key), compact=True)
            blind_spot = str(item.get("blind_spot_addressed") or "").strip()
            if blind_spot:
                story.append(Paragraph("Angle mort adresse", styles["ResearchMuted"]))
                _append_bullets(story, styles, blind_spot, compact=True)
            sources = [source for source in item.get("sources", []) if isinstance(source, dict)]
            if sources:
                story.append(Paragraph("Sources primaires", styles["ResearchMuted"]))
                source_rows = [[_p("Source", styles, "Source"), _p("Date", styles, "Date"), _p("Pourquoi", styles, "Pourquoi")]]
                for source in sources:
                    source_rows.append(
                        [
                            _p(_source_label(source), styles, _source_label(source)),
                            _p(str(source.get("published_at") or "-"), styles, str(source.get("published_at") or "-")),
                            _p(str(source.get("why") or "-"), styles, str(source.get("why") or "-")),
                        ]
                    )
                source_table = Table(source_rows, colWidths=[62 * mm, 24 * mm, 82 * mm], repeatRows=1)
                source_table.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D9E2EC")),
                            ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#BCCCDC")),
                            ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D9E2EC")),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("LEFTPADDING", (0, 0), (-1, -1), 5),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                            ("TOPPADDING", (0, 0), (-1, -1), 4),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                        ]
                    )
                )
                story.append(source_table)
            story.append(Spacer(1, 6))

    story.append(Paragraph("Risques et angles morts", styles["ResearchHeading"]))
    _append_bullets(story, styles, structured.get("risks"))

    story.append(Paragraph("Questions ouvertes", styles["ResearchHeading"]))
    _append_bullets(story, styles, structured.get("open_questions"))

    story.append(Paragraph("Sources globales", styles["ResearchHeading"]))
    for source in [item for item in structured.get("global_sources", []) if isinstance(item, dict)]:
        story.append(Paragraph(_escape(_source_label(source)), styles["ResearchBody"]))
        story.append(
            Paragraph(
                _escape(" | ".join(part for part in [str(source.get("publisher") or "").strip(), str(source.get("published_at") or "").strip()] if part)),
                styles["ResearchMuted"],
            )
        )
        why = str(source.get("why") or "").strip()
        if why:
            story.append(Paragraph(_escape(why), styles["ResearchMuted"]))
        story.append(Spacer(1, 2))

    def _decorate(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#52606D"))
        canvas.drawString(16 * mm, 8 * mm, f"Project OS recherche approfondie - {display_title}")
        canvas.drawRightString(A4[0] - 16 * mm, 8 * mm, f"Page {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_decorate, onLaterPages=_decorate)


def _render_operator_reply_with_reportlab(
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
        _append_bullets(story, styles, highlights, compact=True)
    if questions:
        story.append(Paragraph("Question ouverte", styles["ReplyHeading"]))
        _append_bullets(story, styles, questions, compact=True)

    story.append(Paragraph("Version complete", styles["ReplyHeading"]))
    for paragraph in [part.strip() for part in str(full_response or "").split("\n\n") if part.strip()]:
        story.append(Paragraph(_escape(paragraph), styles["ReplyBody"]))

    def _decorate(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#52606D"))
        canvas.drawString(16 * mm, 8 * mm, f"Project OS - {display_title}")
        canvas.drawRightString(A4[0] - 16 * mm, 8 * mm, f"Page {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_decorate, onLaterPages=_decorate)


def _append_bullets(story: list[Any], styles: Any, payload: Any, *, compact: bool = False) -> None:
    from reportlab.platypus import Paragraph

    try:
        body_style = styles["ReplyBody"]
    except Exception:
        try:
            body_style = styles["ResearchBody"]
        except Exception:
            body_style = styles["BodyText"]
    for line in _coerce_lines(payload):
        bullet = "-"
        story.append(Paragraph(f"{bullet} {_escape(line)}", body_style))


def _append_labeled_table(
    story: list[Any],
    styles: Any,
    *,
    title: str,
    headers: tuple[str, str, str],
    rows: list[tuple[str, str, str]],
    col_widths: list[float],
) -> None:
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Table, TableStyle

    clean_rows = [row for row in rows if any(str(cell or "").strip() for cell in row)]
    if not clean_rows:
        return
    story.append(Paragraph(title, styles["ResearchHeading"]))
    table_rows = [[_p(headers[0], styles, headers[0]), _p(headers[1], styles, headers[1]), _p(headers[2], styles, headers[2])]]
    for row in clean_rows:
        table_rows.append([_p(row[0], styles, row[0]), _p(row[1], styles, row[1]), _p(row[2], styles, row[2])])
    table = Table(table_rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0D3B66")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
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
    story.append(table)


def _append_runtime_table(story: list[Any], styles: Any, *, issues: list[str], actions: list[str]) -> None:
    from reportlab.lib.units import mm

    rows = [
        (_safe_line(issue), _safe_line(issue), _safe_line(actions[index] if index < len(actions) else "A clarifier"))
        for index, issue in enumerate(issues[:4])
    ]
    if not rows:
        return
    _append_labeled_table(
        story,
        styles,
        title="Incident observe / Impact / Correction visee",
        headers=("Incident observe", "Impact", "Correction visee"),
        rows=rows,
        col_widths=[42 * mm, 42 * mm, 82 * mm],
    )


def _join_lines(payload: Any) -> str:
    return " | ".join(_coerce_lines(payload))


def _safe_line(value: Any) -> str:
    text = str(value or "").strip()
    return text or "-"


def _coerce_lines(payload: Any) -> list[str]:
    if isinstance(payload, str):
        text = payload.strip()
        return [text] if text else ["a remplir"]
    if isinstance(payload, list):
        lines = [str(item).strip() for item in payload if str(item).strip()]
        return lines or ["a remplir"]
    return ["a remplir"]


def _bucket_label(raw: str) -> str:
    mapping = {
        "a_faire": "A faire",
        "a_etudier": "A etudier",
        "a_rejeter": "A rejeter",
    }
    return mapping.get(str(raw or "").strip().lower(), str(raw or "-").strip() or "-")


def _source_label(source: dict[str, Any]) -> str:
    title = str(source.get("title") or source.get("url") or "Source").strip()
    url = str(source.get("url") or "").strip()
    if url:
        return f"{title} - {url}"
    return title


def _p(text: str, styles: Any, fallback: str) -> Any:
    from reportlab.platypus import Paragraph

    value = str(text or "").strip() or str(fallback)
    return Paragraph(_escape(value), styles["ResearchBody"])


def _kv(label: str, value: str, styles: Any) -> Any:
    from reportlab.platypus import Paragraph

    payload = f"<b>{_escape(label)}</b><br/>{_escape(str(value or '-'))}"
    return Paragraph(payload, styles["ResearchBody"])


def _escape(value: str) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )


def _render_fallback_pdf(
    destination: Path,
    *,
    display_title: str,
    request: dict[str, Any],
    structured: dict[str, Any],
    repo_context: dict[str, Any],
    dossier_relative_path: str | None,
    archive_relative_path: str | None,
) -> None:
    lines = _fallback_lines(
        display_title=display_title,
        request=request,
        structured=structured,
        repo_context=repo_context,
        dossier_relative_path=dossier_relative_path,
        archive_relative_path=archive_relative_path,
    )
    _write_minimal_pdf(destination, lines)


def _render_operator_reply_fallback(
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


def _fallback_lines(
    *,
    display_title: str,
    request: dict[str, Any],
    structured: dict[str, Any],
    repo_context: dict[str, Any],
    dossier_relative_path: str | None,
    archive_relative_path: str | None,
) -> list[str]:
    research_profile = str(structured.get("research_profile") or request.get("research_profile") or "domain_audit").strip().lower()
    research_intensity = str(structured.get("research_intensity") or request.get("research_intensity") or "simple").strip().lower()
    lines = [
        display_title,
        "",
        f"Type: {request.get('kind') or 'audit'}",
        f"Profile: {research_profile}",
        f"Intensity: {research_intensity}",
        f"Question: {request.get('question') or '-'}",
        f"Repo dossier: {dossier_relative_path or '-'}",
        f"Archive cold: {archive_relative_path or '-'}",
        f"Branche: {repo_context.get('current_branch') or '-'}",
        f"Modele: {structured.get('metadata', {}).get('model') or '-'}",
        f"Tool: {structured.get('metadata', {}).get('tool_type') or '-'}",
        "",
        "Synthese",
        *["- " + item for item in _coerce_lines(structured.get("summary"))],
        "",
        "Pourquoi ce rapport compte",
        *["- " + item for item in _coerce_lines(structured.get("why_now"))],
        "",
        "Cohérence Project OS",
        *["- " + item for item in _coerce_lines(structured.get("repo_fit"))],
        "",
        "Actions prioritaires",
        *["- " + item for item in _coerce_lines(structured.get("priority_actions"))],
    ]
    if research_profile == "project_audit":
        block = structured.get("project_audit_block") or {}
        lines.extend(
            [
                "",
                "Cap nord",
                *["- " + item for item in _coerce_lines(block.get("north_star"))],
                "",
                "These systeme",
                *["- " + item for item in _coerce_lines(block.get("system_thesis"))],
                "",
                "Couches plateforme",
                *["- " + item for item in _coerce_lines(block.get("platform_layers"))],
                "",
                "Gaps",
                *["- " + item for item in _coerce_lines(block.get("capability_gaps"))],
                "",
                "Incidents observes",
                *["- " + item for item in _coerce_lines(block.get("observed_runtime_issues"))],
            ]
        )
    elif research_profile == "component_discovery":
        block = structured.get("component_discovery_block") or {}
        lines.extend(
            [
                "",
                "Angles morts",
                *["- " + item for item in _coerce_lines(block.get("blind_spots"))],
                "",
                "Leviers externes",
                *["- " + item for item in _coerce_lines(block.get("external_leverage"))],
                "",
                "Sous-couches sous-construites",
                *["- " + item for item in _coerce_lines(block.get("underbuilt_layers"))],
                "",
                "Incidents observes",
                *["- " + item for item in _coerce_lines(block.get("observed_runtime_issues"))],
            ]
        )
    for item in [entry for entry in structured.get("recommendations", []) if isinstance(entry, dict)]:
        lines.extend(
            [
                "",
                f"{_bucket_label(str(item.get('bucket') or ''))} - {item.get('decision') or '-'} - {item.get('system_name') or '-'}",
                "Pourquoi",
                *["  - " + value for value in _coerce_lines(item.get("why"))],
                "Ce qu'on recupere",
                *["  - " + value for value in _coerce_lines(item.get("what_to_take"))],
                "Ce qu'on n'importe pas",
                *["  - " + value for value in _coerce_lines(item.get("what_not_to_take"))],
                "Signal forks / satellites",
                *["  - " + value for value in _coerce_lines(item.get("fork_signal"))],
                "Ou ca entre dans Project OS",
                *["  - " + value for value in _coerce_lines(item.get("project_os_touchpoints"))],
                "Preuves a obtenir",
                *["  - " + value for value in _coerce_lines(item.get("proofs"))],
                "Sources",
            ]
        )
        for source in [source for source in item.get("sources", []) if isinstance(source, dict)]:
            lines.append(
                "  - "
                + " | ".join(
                    part
                    for part in [
                        str(source.get("title") or "").strip(),
                        str(source.get("publisher") or "").strip(),
                        str(source.get("published_at") or "").strip(),
                        str(source.get("url") or "").strip(),
                    ]
                    if part
                )
            )
    lines.extend(
        [
            "",
            "Risques",
            *["- " + item for item in _coerce_lines(structured.get("risks"))],
            "",
            "Questions ouvertes",
            *["- " + item for item in _coerce_lines(structured.get("open_questions"))],
            "",
            "Sources globales",
        ]
    )
    for source in [source for source in structured.get("global_sources", []) if isinstance(source, dict)]:
        lines.append(
            "- "
            + " | ".join(
                part
                for part in [
                    str(source.get("title") or "").strip(),
                    str(source.get("publisher") or "").strip(),
                    str(source.get("published_at") or "").strip(),
                    str(source.get("url") or "").strip(),
                ]
                if part
            )
        )
    return lines


def _write_minimal_pdf(destination: Path, lines: list[str]) -> None:
    page_width = 595
    page_height = 842
    left = 48
    top = 790
    leading = 13
    max_lines = 54
    normalized_lines: list[str] = []
    for raw_line in lines:
        text = unicodedata.normalize("NFKD", str(raw_line or "")).encode("ascii", "ignore").decode("ascii")
        wrapped = textwrap.wrap(text, width=92) or [""]
        normalized_lines.extend(wrapped)
    pages = [normalized_lines[index : index + max_lines] for index in range(0, len(normalized_lines), max_lines)] or [[]]

    objects: list[bytes] = []

    def add_object(payload: bytes) -> int:
        objects.append(payload)
        return len(objects)

    catalog_id = add_object(b"")
    pages_id = add_object(b"")
    font_id = add_object(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    page_ids: list[int] = []
    content_ids: list[int] = []

    for page_lines in pages:
        commands = ["BT", f"/F1 10 Tf", f"{left} {top} Td"]
        for line in page_lines:
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            commands.append(f"({escaped}) Tj")
            commands.append(f"0 -{leading} Td")
        commands.append("ET")
        content = "\n".join(commands).encode("latin-1", "replace")
        content_id = add_object(f"<< /Length {len(content)} >>\nstream\n".encode("ascii") + content + b"\nendstream")
        page_id = add_object(
            (
                f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {page_width} {page_height}] "
                f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>"
            ).encode("ascii")
        )
        content_ids.append(content_id)
        page_ids.append(page_id)

    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[catalog_id - 1] = f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode("ascii")
    objects[pages_id - 1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("ascii")

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii"))
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref_start = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\nstartxref\n{xref_start}\n%%EOF"
        ).encode("ascii")
    )
    destination.write_bytes(bytes(output))
