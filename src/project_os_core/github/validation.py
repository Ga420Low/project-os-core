from __future__ import annotations

from typing import Any

from .parsing import RESERVED_SECTION_HEADINGS, parse_issue_sections, section_is_filled


def validate_issue_resolution_body(body: str | None) -> dict[str, Any]:
    sections = parse_issue_sections(body)
    missing = [heading for heading in RESERVED_SECTION_HEADINGS if not section_is_filled(sections.get(heading, ""))]
    return {
        "valid": not missing,
        "missing_sections": missing,
        "sections": sections,
    }
