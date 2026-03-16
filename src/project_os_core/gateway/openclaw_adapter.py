from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..models import (
    ActionRiskClass,
    ChannelEvent,
    ConversationThreadRef,
    OperatorAttachment,
    OperatorMessage,
    new_id,
)


@dataclass(slots=True)
class OpenClawDispatchEnvelope:
    event: ChannelEvent
    target_profile: str | None = None
    requested_worker: str | None = None
    risk_class: ActionRiskClass | None = None
    metadata: dict[str, Any] | None = None


def build_dispatch_from_openclaw_payload(payload: dict[str, Any]) -> OpenClawDispatchEnvelope:
    event = payload.get("event")
    context = payload.get("context")
    if not isinstance(event, dict):
        raise ValueError("openclaw payload missing event object")
    if not isinstance(context, dict):
        raise ValueError("openclaw payload missing context object")

    metadata = event.get("metadata")
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise ValueError("openclaw payload event.metadata must be an object")

    config = payload.get("config")
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise ValueError("openclaw payload config must be an object")

    surface = _as_text(payload.get("surface")) or _as_text(metadata.get("surface")) or _as_text(context.get("channelId")) or "unknown"
    channel = (
        _as_text(metadata.get("originatingChannel"))
        or _as_text(metadata.get("channelName"))
        or _as_text(context.get("channelId"))
        or surface
    )
    actor_id = _as_text(metadata.get("senderId")) or _as_text(event.get("from")) or "unknown_sender"
    message_text = _as_text(event.get("content")) or ""
    thread_id = (
        _as_text(metadata.get("threadId"))
        or _as_text(context.get("conversationId"))
        or _as_text(metadata.get("messageId"))
        or new_id("openclaw_thread")
    )
    external_thread_id = _as_text(context.get("conversationId")) or _as_text(metadata.get("originatingTo"))
    thread_metadata = {
        "surface": surface,
        "provider": _as_text(metadata.get("provider")),
        "originating_channel": _as_text(metadata.get("originatingChannel")),
        "originating_to": _as_text(metadata.get("originatingTo")),
        "channel_name": _as_text(metadata.get("channelName")),
        "guild_id": _as_text(metadata.get("guildId")),
        "is_group": bool(payload.get("isGroup", False)),
    }
    thread_ref = ConversationThreadRef(
        thread_id=thread_id,
        channel=channel,
        external_thread_id=external_thread_id,
        metadata={key: value for key, value in thread_metadata.items() if value not in (None, "")},
    )
    attachments = _build_attachments_from_metadata(metadata)
    message_metadata = {
        "source": "openclaw",
        "context": context,
        "provider": _as_text(metadata.get("provider")),
        "surface": surface,
        "to": _as_text(metadata.get("to")),
        "message_id": _as_text(metadata.get("messageId")),
        "sender_name": _as_text(metadata.get("senderName")),
        "sender_username": _as_text(metadata.get("senderUsername")),
        "sender_e164": _as_text(metadata.get("senderE164")),
        "channel_name": _as_text(metadata.get("channelName")),
        "guild_id": _as_text(metadata.get("guildId")),
        "originating_channel": _as_text(metadata.get("originatingChannel")),
        "originating_to": _as_text(metadata.get("originatingTo")),
    }
    channel_event = ChannelEvent(
        event_id=new_id("channel_event"),
        surface=surface,
        event_type=_as_text(payload.get("event_type")) or "message.received",
        message=OperatorMessage(
            message_id=_as_text(metadata.get("messageId")) or new_id("message"),
            actor_id=actor_id,
            channel=channel,
            text=message_text,
            thread_ref=thread_ref,
            attachments=attachments,
            metadata={key: value for key, value in message_metadata.items() if value not in (None, "")},
        ),
        raw_payload=payload,
    )
    risk_class = _as_risk_class(config.get("risk_class"))
    dispatch_metadata = config.get("metadata")
    if dispatch_metadata is None:
        dispatch_metadata = {}
    if not isinstance(dispatch_metadata, dict):
        raise ValueError("openclaw payload config.metadata must be an object")
    return OpenClawDispatchEnvelope(
        event=channel_event,
        target_profile=_as_text(config.get("target_profile")),
        requested_worker=_as_text(config.get("requested_worker")),
        risk_class=risk_class,
        metadata=dispatch_metadata,
    )


def _build_attachments_from_metadata(metadata: dict[str, Any]) -> list[OperatorAttachment]:
    attachments: list[OperatorAttachment] = []
    attachment_payloads = metadata.get("attachments")
    seen_keys: set[tuple[str | None, str | None, str | None]] = set()

    if isinstance(attachment_payloads, list):
        for index, item in enumerate(attachment_payloads):
            if not isinstance(item, dict):
                continue
            name = (
                _as_text(item.get("name"))
                or _as_text(item.get("filename"))
                or _as_text(item.get("fileName"))
                or _as_text(item.get("title"))
                or f"attachment-{index + 1}"
            )
            mime_type = (
                _as_text(item.get("mimeType"))
                or _as_text(item.get("mime_type"))
                or _as_text(item.get("contentType"))
                or _as_text(item.get("content_type"))
                or _as_text(metadata.get("mediaType"))
            )
            path = _as_text(item.get("path")) or _as_text(item.get("filePath")) or _as_text(item.get("localPath"))
            url = _as_text(item.get("url")) or _as_text(item.get("downloadUrl")) or _as_text(item.get("download_url"))
            size_bytes = _as_int(item.get("sizeBytes") or item.get("size_bytes") or item.get("size"))
            attachment_key = (name, path, url)
            if attachment_key in seen_keys:
                continue
            seen_keys.add(attachment_key)
            attachments.append(
                OperatorAttachment(
                    attachment_id=new_id("attachment"),
                    name=name,
                    kind=_attachment_kind(name=name, mime_type=mime_type, metadata=item),
                    mime_type=mime_type,
                    path=path,
                    url=url,
                    size_bytes=size_bytes,
                    metadata={
                        "source": "openclaw",
                        "kind": "attachments_array",
                        "duration_secs": _as_int(item.get("durationSecs") or item.get("duration_secs")),
                        "is_transcript": bool(item.get("isTranscript") or item.get("is_transcript")),
                    },
                )
            )

    media_path = _as_text(metadata.get("mediaPath"))
    if media_path:
        attachment_key = (
            media_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1],
            media_path,
            None,
        )
        if attachment_key in seen_keys:
            return attachments
        attachments.append(
            OperatorAttachment(
                attachment_id=new_id("attachment"),
                name=media_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1],
                kind=_attachment_kind(
                    name=media_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1],
                    mime_type=_as_text(metadata.get("mediaType")),
                    metadata=metadata,
                ),
                mime_type=_as_text(metadata.get("mediaType")),
                path=media_path,
                metadata={"source": "openclaw", "kind": "media_path"},
            )
        )
    return attachments


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return _repair_mojibake_text(text)


def _repair_mojibake_text(text: str) -> str:
    suspicious_markers = ("Ã", "Â", "â€", "â€™", "â€œ", "â€\x9d", "â€“", "â€”", "â‚¬")
    if not any(marker in text for marker in suspicious_markers):
        return text
    original_score = _mojibake_score(text)
    for encoding in ("cp1252", "latin-1"):
        try:
            repaired = text.encode(encoding, errors="strict").decode("utf-8", errors="strict").strip()
        except (UnicodeDecodeError, UnicodeEncodeError):
            continue
        if repaired and _mojibake_score(repaired) < original_score:
            return repaired
    return text


def _mojibake_score(text: str) -> int:
    markers = ("Ã", "Â", "â€", "â€™", "â€œ", "â€\x9d", "â€“", "â€”", "â‚¬")
    return sum(text.count(marker) for marker in markers)


def _as_risk_class(value: Any) -> ActionRiskClass | None:
    text = _as_text(value)
    if text is None:
        return None
    return ActionRiskClass(text)


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _attachment_kind(*, name: str, mime_type: str | None, metadata: dict[str, Any]) -> str:
    normalized_name = name.lower()
    normalized_mime = (mime_type or "").lower()
    if bool(metadata.get("isTranscript") or metadata.get("is_transcript")):
        return "transcript"
    if normalized_mime.startswith("audio/") or normalized_name.endswith((".mp3", ".wav", ".ogg", ".m4a", ".flac")):
        return "audio"
    if normalized_mime.startswith("image/") or normalized_name.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
        return "image"
    if normalized_mime in {
        "application/pdf",
        "text/plain",
        "text/markdown",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    } or normalized_name.endswith((".pdf", ".txt", ".md", ".doc", ".docx")):
        return "document"
    return "file"
