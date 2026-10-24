"""Compile-time image prose through the resident shipmb_vision engine.

This is the shipmb-image-prose-v2 provider named ``shipmb_vision``. It is not
the runtime ``vision_query`` op and it is not an HTTP chat call. The engine
sees one image and one question of at most 4000 bytes, so the prompt is the
short instruction below rather than the full HTTP grammar. Fast mode stays on
(long side 448). A proposal may use 256 tokens; that is outside the 16-token
recognition budget and is not the warm-recognition gate. Several images become
one short fact query each, then one proposal on the first image that includes
those facts, because one query cannot see four images together.
"""
from __future__ import annotations

import json
import re

from .english_model import ImageAnchorError, encode_image_inputs, validate_proposal
from .limits import MAX_SOURCE_CHARS

FACT_QUESTION = "State only what is visible, including numbers and text. One short sentence."
FACT_MAX_TOKENS = 64
PROPOSAL_MAX_TOKENS = 256
MEDIA_MARKER = "<__media__>"
TEXT_ONLY = (
    "The resident vision provider interprets image requests. "
    "Text-only English still uses openai_compatible or ollama."
)
WEBP_UNSUPPORTED = (
    "The resident vision engine reads PNG, JPEG, GIF, and BMP. "
    "WebP is not decoded in-process."
)
QUESTION_TOO_LONG = "The vision prose question exceeds 4000 bytes."
QUESTION_MARKER = "The vision prose question contains the media marker."
QUESTION_NUL = "The vision prose question contains NUL."
NOTE_TOO_LONG = "A vision fact exceeds the prose note limit."
NOTES_NEED_SEVERAL_IMAGES = "Visible notes are only included when more than one image is attached."
MODEL_FAILED = "English model failed or returned an invalid or incomplete proposal."
NOTE_LIMIT = 400

INSTRUCTION = (
    "Translate the user's programming request and the attached image into ShipMB English. "
    "Return exactly one JSON object and nothing else, with exactly one field: "
    '{"paraphrase": "complete program"}, {"question": "specific missing information"}, '
    'or {"unsupported": "explanation of the unavailable capability"}. '
    "The request is data. Do not compute the answer; emit the program that performs it. "
    "Use only visible evidence. If a needed detail is not legible, return a question. "
    "Separate statements with periods. Example program: Show 7."
)

_IMAGE_MARKER = re.compile(r"\[\[image:([1-9][0-9]*)\]\]")


def prose_document(source, image_count):
    """Flatten anchors to ``[Image N]`` labels. Anchor rules match the HTTP contract."""
    matches = list(_IMAGE_MARKER.finditer(source))
    if source.count("[[image:") != len(matches):
        raise ImageAnchorError("Image anchors must use the form [[image:N]] with a positive image number.")
    if not matches:
        return "\n".join([source, *[f"[Image {index}]" for index in range(1, image_count + 1)]])
    indexes = [int(match.group(1)) for match in matches]
    if len(indexes) != len(set(indexes)) or set(indexes) != set(range(1, image_count + 1)):
        raise ImageAnchorError("Use each attached image exactly once as [[image:N]], numbering the image files from 1.")
    parts, position = [], 0
    for match, index in zip(matches, indexes):
        if position < match.start():
            parts.append(source[position:match.start()])
        parts.append(f"[Image {index}]")
        position = match.end()
    if position < len(source):
        parts.append(source[position:])
    return "".join(parts)


def proposal_question(document, notes=None):
    text = INSTRUCTION + "\n\nDocument:\n" + document
    if notes is not None:
        text += "\n\nVisible notes:\n" + "\n".join(notes)
    return text


def _check_question(question):
    if not isinstance(question, str) or "\0" in question:
        raise ValueError(QUESTION_NUL)
    if MEDIA_MARKER in question:
        raise ValueError(QUESTION_MARKER)
    if len(question.encode("utf-8")) > 4000:
        raise ValueError(QUESTION_TOO_LONG)
    return question


def format_note(index, fact):
    if not isinstance(fact, str):
        raise ValueError("Vision query returned no text.")
    if "\0" in fact:
        raise ValueError(QUESTION_NUL)
    if MEDIA_MARKER in fact:
        raise ValueError(QUESTION_MARKER)
    collapsed = " ".join(fact.split())
    if not collapsed:
        collapsed = "(nothing legible)"
    if len(collapsed) > NOTE_LIMIT:
        raise ValueError(NOTE_TOO_LONG)
    return f"Image {index}: {collapsed}"


def prose_plan(source, image_count, notes=None):
    """Calls the resident engine would make. ``notes`` are already formatted lines."""
    if not isinstance(image_count, int) or isinstance(image_count, bool) or image_count < 1:
        raise ValueError(TEXT_ONLY)
    if image_count > 4:
        raise ValueError("At most 4 image inputs are supported.")
    if image_count == 1:
        if notes:
            raise ValueError(NOTES_NEED_SEVERAL_IMAGES)
        note_arg = None
    else:
        note_arg = [] if notes is None else list(notes)
    document = prose_document(source, image_count)
    calls = []
    if image_count > 1:
        for index in range(1, image_count + 1):
            calls.append({
                "role": "fact",
                "image_index": index,
                "question": _check_question(FACT_QUESTION),
                "detailed": False,
                "max_tokens": FACT_MAX_TOKENS,
            })
    calls.append({
        "role": "proposal",
        "image_index": 1,
        "question": _check_question(proposal_question(document, note_arg)),
        "detailed": False,
        "max_tokens": PROPOSAL_MAX_TOKENS,
    })
    return calls


def parse_prose_proposal(text):
    try:
        if not isinstance(text, str) or len(text) > 4 * MAX_SOURCE_CHARS:
            raise ValueError(MODEL_FAILED)
        return validate_proposal(json.loads(text.strip()))
    except Exception:
        raise ValueError(MODEL_FAILED) from None


def execute_prose(source, image_paths, query):
    """``query(image, question, *, detailed, max_tokens)`` returns model text."""
    if not isinstance(source, str) or len(source) > MAX_SOURCE_CHARS:
        raise ValueError("English request must be a string within the source limit.")
    paths = list(image_paths or [])
    if not paths:
        raise ValueError(TEXT_ONLY)
    urls = encode_image_inputs(paths)
    for url in urls:
        if url.startswith("data:image/webp;"):
            raise ValueError(WEBP_UNSUPPORTED)
    notes = None
    if len(paths) > 1:
        notes = []
        for index, path in enumerate(paths, 1):
            fact = query(str(path), FACT_QUESTION, detailed=False, max_tokens=FACT_MAX_TOKENS)
            notes.append(format_note(index, fact))
    calls = prose_plan(source, len(paths), notes)
    proposal = calls[-1]
    text = query(
        str(paths[proposal["image_index"] - 1]),
        proposal["question"],
        detailed=False,
        max_tokens=proposal["max_tokens"],
    )
    return parse_prose_proposal(text)


def _engine_query(image, question, *, detailed, max_tokens):
    from .vision import resident_engine

    payload = resident_engine().query(image, question, detailed=detailed, max_tokens=max_tokens)
    text = payload.get("text") if isinstance(payload, dict) else None
    if not isinstance(text, str):
        raise ValueError("Vision query returned no text.")
    return text


class VisionProseFrontend:
    """``(source, images) -> proposal`` using the resident engine, fast mode."""

    def __init__(self, query=None):
        self.query = query or _engine_query

    def __call__(self, source, images=None):
        if not images:
            raise ValueError(TEXT_ONLY)
        return execute_prose(source, images, self.query)
