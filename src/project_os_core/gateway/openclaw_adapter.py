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
    media_path = _as_text(metadata.get("mediaPath"))
    if media_path:
        attachments.append(
            OperatorAttachment(
                attachment_id=new_id("attachment"),
                name=media_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1],
                kind="file",
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
    return text or None


def _as_risk_class(value: Any) -> ActionRiskClass | None:
    text = _as_text(value)
    if text is None:
        return None
    return ActionRiskClass(text)
