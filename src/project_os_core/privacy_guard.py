from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

from .models import SensitivityClass


_PRIVATE_KEY_BLOCK = re.compile(r"-----BEGIN [A-Z0-9 ]+-----[\s\S]+?-----END [A-Z0-9 ]+-----", re.IGNORECASE)
_ASSIGNED_SECRET = re.compile(
    r"(?i)\b(api[_ -]?key|access[_ -]?token|refresh[_ -]?token|token|secret|password|client[_ -]?secret|authorization)\b\s*[:=]\s*\S+"
)
_BEARER_TOKEN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-+/=]{12,}")
_OPENAI_KEY = re.compile(r"\bsk-[A-Za-z0-9_\-]{10,}\b")
_GITHUB_TOKEN = re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")
_SLACK_TOKEN = re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")
_AWS_ACCESS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_JWT_TOKEN = re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b")
_EMAIL = re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d .\-()]{7,}\d)(?!\w)")
_SECRET_REFERENCE = re.compile(
    r"(?i)\b(api[_ -]?key|access[_ -]?token|refresh[_ -]?token|bot[_ -]?token|token|secret|password|client[_ -]?secret|credential|auth[_ -]?cookie|session[_ -]?id|session[_ -]?token|private[_ -]?repo)\b"
)
_ENV_SECRET_REFERENCE = re.compile(r"\b[A-Z][A-Z0-9_]{2,}(?:API_KEY|TOKEN|SECRET|PASSWORD|COOKIE|SESSION)\b")
_SENSITIVE_ATTACHMENT = re.compile(
    r"(?:^|[\\/])(\.env(?:\..*)?|secrets?\.json|id_(?:rsa|dsa|ecdsa|ed25519)|.*\.(?:pem|p12|pfx|key|crt))$|"
    r"(?:token|secret|credential|private[_ -]?key|session)",
    re.IGNORECASE,
)


@dataclass(slots=True)
class SensitivityAssessment:
    classification: SensitivityClass
    reason: str
    clean_text: str | None = None
    sensitive_attachments: list[str] = field(default_factory=list)


def assess_sensitivity(text: str, *, attachment_names: Sequence[str] | None = None) -> SensitivityAssessment:
    normalized = " ".join((text or "").strip().split())
    sensitive_attachments = [name for name in (attachment_names or []) if _SENSITIVE_ATTACHMENT.search(name)]

    if sensitive_attachments:
        return SensitivityAssessment(
            classification=SensitivityClass.S3,
            reason="sensitive_attachment_name_detected",
            clean_text=_attachment_safe_summary(attachment_names, hide_names=True),
            sensitive_attachments=sensitive_attachments,
        )

    if normalized:
        for pattern, reason in (
            (_PRIVATE_KEY_BLOCK, "private_key_block_detected"),
            (_ASSIGNED_SECRET, "assigned_secret_detected"),
            (_BEARER_TOKEN, "bearer_token_detected"),
            (_OPENAI_KEY, "openai_key_detected"),
            (_GITHUB_TOKEN, "github_token_detected"),
            (_SLACK_TOKEN, "slack_token_detected"),
            (_AWS_ACCESS_KEY, "aws_access_key_detected"),
            (_JWT_TOKEN, "jwt_token_detected"),
        ):
            if pattern.search(normalized):
                return SensitivityAssessment(
                    classification=SensitivityClass.S3,
                    reason=reason,
                    clean_text=sanitize_sensitive_text(normalized),
                )

        sanitized = sanitize_sensitive_text(normalized)
        if sanitized != normalized:
            return SensitivityAssessment(
                classification=SensitivityClass.S2,
                reason=_first_s2_reason(normalized),
                clean_text=sanitized,
            )

    clean_text = _attachment_safe_summary(attachment_names, hide_names=False) if attachment_names else None
    return SensitivityAssessment(
        classification=SensitivityClass.S1,
        reason="passthrough",
        clean_text=clean_text,
    )


def sanitize_sensitive_text(text: str) -> str:
    sanitized = text
    replacements = (
        (_PRIVATE_KEY_BLOCK, "[REDACTED_PRIVATE_KEY]"),
        (_OPENAI_KEY, "[REDACTED_API_KEY]"),
        (_GITHUB_TOKEN, "[REDACTED_GITHUB_TOKEN]"),
        (_SLACK_TOKEN, "[REDACTED_SLACK_TOKEN]"),
        (_AWS_ACCESS_KEY, "[REDACTED_AWS_ACCESS_KEY]"),
        (_JWT_TOKEN, "[REDACTED_JWT]"),
        (_BEARER_TOKEN, "Bearer [REDACTED_TOKEN]"),
        (_EMAIL, "[REDACTED_EMAIL]"),
        (_PHONE, "[REDACTED_PHONE]"),
        (_ASSIGNED_SECRET, "[REDACTED_SECRET_ASSIGNMENT]"),
        (_ENV_SECRET_REFERENCE, "[REDACTED_SECRET_REF]"),
        (_SECRET_REFERENCE, "[REDACTED_SECRET_REF]"),
    )
    for pattern, replacement in replacements:
        sanitized = pattern.sub(replacement, sanitized)
    return " ".join(sanitized.split())


def attachment_safe_summary(attachment_names: Sequence[str], *, sensitivity: SensitivityClass) -> str:
    return _attachment_safe_summary(attachment_names, hide_names=sensitivity is not SensitivityClass.S1)


def _attachment_safe_summary(attachment_names: Sequence[str] | None, *, hide_names: bool) -> str | None:
    names = [name for name in (attachment_names or []) if name]
    if not names:
        return None
    if hide_names:
        return "Pieces jointes sensibles referencees."
    joined = ", ".join(names[:3])
    return f"Pieces jointes referencees: {joined}"


def _first_s2_reason(text: str) -> str:
    if _EMAIL.search(text):
        return "email_address_detected"
    if _PHONE.search(text):
        return "phone_number_detected"
    if _ENV_SECRET_REFERENCE.search(text):
        return "secret_env_reference_detected"
    if _SECRET_REFERENCE.search(text):
        return "secret_reference_detected"
    return "desensitize_required"
