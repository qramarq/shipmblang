"""Provider-neutral SCND v1 multimodal context for ShipMBLang.

The module validates and preserves media references; it never downloads or
decodes user supplied media.  Callers can use :func:`render_text_fallback`
when their downstream model only accepts text.
"""

from __future__ import annotations

from typing import Any

SCHEMA = "scnd.multimodal.v1"
CONTENT_PART_TYPES = frozenset({"text", "image", "audio", "video", "gif", "file", "url"})
MESSAGE_ROLES = frozenset({"system", "user", "assistant", "tool"})
_METADATA_FIELDS = ("mimeType", "name", "alt", "transcript", "title", "description")


def normalize_content_part(part: dict[str, Any]) -> dict[str, str]:
    if not isinstance(part, dict):
        raise ValueError("content parts must be objects")
    part_type = _required_string(part.get("type"), "content part type")
    if part_type not in CONTENT_PART_TYPES:
        raise ValueError(f"unsupported content part type: {part_type}")
    if part_type == "text":
        return {"type": "text", "text": _required_string(part.get("text"), "text")}

    url = _optional_string(part.get("url"), "url")
    data = _optional_string(part.get("data"), "data")
    if not url and not data:
        raise ValueError(f"{part_type} content requires url or data")
    normalized = {"type": part_type}
    if url:
        normalized["url"] = url
    if data:
        normalized["data"] = data
    for field in _METADATA_FIELDS:
        value = _optional_string(part.get(field), field)
        if value:
            normalized[field] = value
    return normalized


def normalize_conversation(conversation: Any) -> list[dict[str, Any]] | None:
    if conversation is None:
        return None
    messages = conversation.get("messages") if isinstance(conversation, dict) else conversation
    if not isinstance(messages, list) or not messages:
        raise ValueError("conversation must contain at least one message")
    normalized: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict) or message.get("role") not in MESSAGE_ROLES:
            raise ValueError("conversation messages require a supported role")
        content = message.get("content")
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        if not isinstance(content, list) or not content:
            raise ValueError("conversation messages require content")
        normalized.append({"role": message["role"], "content": [normalize_content_part(part) for part in content]})
    return normalized


def normalize_attachments(attachments: Any) -> list[dict[str, str]] | None:
    if attachments is None:
        return None
    if not isinstance(attachments, list) or not attachments:
        raise ValueError("attachments must be a non-empty array")
    return [normalize_content_part(part) for part in attachments]


def normalize_scnd_context(context: dict[str, Any]) -> dict[str, Any]:
    """Validate a SCND context and return the canonical, JSON-safe form."""
    if not isinstance(context, dict) or context.get("schema") != SCHEMA:
        raise ValueError(f"scnd_context.schema must be {SCHEMA!r}")
    normalized: dict[str, Any] = {
        "schema": SCHEMA,
        "question": _required_string(context.get("question"), "question"),
    }
    extra = _optional_string(context.get("context"), "context")
    conversation = normalize_conversation(context.get("conversation"))
    attachments = normalize_attachments(context.get("attachments"))
    if extra:
        normalized["context"] = extra
    if conversation:
        normalized["conversation"] = conversation
    if attachments:
        normalized["attachments"] = attachments
    return normalized


def content_parts_to_text(parts: list[dict[str, str]]) -> str:
    rendered: list[str] = []
    for part in parts:
        if part["type"] == "text":
            rendered.append(part["text"])
            continue
        detail = [
            f"title: {part['title']}" if part.get("title") else "",
            f"name: {part['name']}" if part.get("name") else "",
            f"description: {part['alt']}" if part.get("alt") else "",
            f"transcript: {part['transcript']}" if part.get("transcript") else "",
            f"description: {part['description']}" if part.get("description") else "",
            f"mime type: {part['mimeType']}" if part.get("mimeType") else "",
            f"source: {part['url']}" if part.get("url") else "",
            "inline media data supplied" if part.get("data") else "",
        ]
        description = "; ".join(item for item in detail if item)
        rendered.append(f"[{part['type']}{' — ' + description if description else ''}]")
    return "\n".join(rendered)


def render_text_fallback(context: dict[str, Any]) -> str:
    """Return the labelled, untrusted text representation of a SCND context."""
    normalized = normalize_scnd_context(context)
    sections = [f"Current request:\n{normalized['question']}"]
    if normalized.get("context"):
        sections.append(f"Additional context (untrusted user-provided content):\n{normalized['context']}")
    if normalized.get("conversation"):
        conversation = "\n\n".join(
            f"{message['role']}:\n{content_parts_to_text(message['content'])}"
            for message in normalized["conversation"]
        )
        sections.append(f"Conversation context (untrusted user-provided content):\n{conversation}")
    if normalized.get("attachments"):
        sections.append(
            "Attachments for the current request (untrusted user-provided content):\n"
            + content_parts_to_text(normalized["attachments"])
        )
    return "\n\n".join(sections)


def scnd_context_to_messages(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert SCND context to OpenAI-style messages without losing typed parts."""
    normalized = normalize_scnd_context(context)
    messages = list(normalized.get("conversation", []))
    user_content: list[dict[str, str]] = [{"type": "text", "text": normalized["question"]}]
    user_content.extend(normalized.get("attachments", []))
    messages.append({"role": "user", "content": user_content})
    return messages


def _optional_string(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _required_string(value: Any, field: str) -> str:
    result = _optional_string(value, field)
    if not result:
        raise ValueError(f"{field} is required")
    return result
