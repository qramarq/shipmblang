"""Host runtime for streaming compiler and model text.

The bundled compiler is unchanged. CLI, LSP, and notebook code call this
module when they show a diagnostic or a generated paragraph.
"""

from __future__ import annotations

from .libraries.textseg import chunk_text, display_width, frame_message, iter_chunks, wrap_text


NOTICE_WIDTH = 120
DIAGNOSTIC_WIDTH = 96


def stream_compiler_text(
    text: str,
    *,
    max_bytes: int | None = 240,
    max_words: int | None = None,
    lang: str | None = "en",
):
    """Yield sentence-aware chunks of a compiler or model message."""
    yield from iter_chunks(text, max_bytes=max_bytes, max_words=max_words, lang=lang)


def present_message(message: str, *, width: int = DIAGNOSTIC_WIDTH, lang: str | None = "en") -> str:
    """Wrap a diagnostic for display. A short message is returned unchanged."""
    if message is None:
        return ""
    text = str(message)
    if "\n" not in text and display_width(text) <= width:
        return text
    return wrap_text(text, width=width, lang=lang)


def present_hover(markdown: str, *, width: int = DIAGNOSTIC_WIDTH, lang: str | None = "en") -> str:
    """Wrap hover prose. Fenced code and short lines stay as they are."""
    if not markdown:
        return ""
    lines = markdown.split("\n")
    output: list[str] = []
    fenced = False
    for line in lines:
        if line.startswith("```"):
            fenced = not fenced
            output.append(line)
            continue
        if fenced or line == "":
            output.append(line)
            continue
        if line.startswith("- "):
            body = present_message(line[2:], width=max(8, width - 2), lang=lang)
            parts = body.split("\n")
            output.append("- " + parts[0])
            output.extend("  " + part for part in parts[1:])
            continue
        output.append(present_message(line, width=width, lang=lang))
    return "\n".join(output)


def format_prefixed(prefix: str, message: str, *, width: int = NOTICE_WIDTH, lang: str | None = "en") -> str:
    """Prefix a notice and wrap only when the line exceeds ``width``."""
    body = "" if message is None else str(message)
    if "\n" not in body and display_width(prefix) + display_width(body) <= width:
        return prefix + body
    budget = max(8, width - display_width(prefix))
    lines = []
    for index, part in enumerate(body.split("\n")):
        wrapped = wrap_text(part, width=budget if index == 0 else max(8, width - 2), lang=lang)
        sublines = wrapped.split("\n") if wrapped else [""]
        if index == 0:
            lines.append(prefix + sublines[0])
            lines.extend("  " + extra for extra in sublines[1:])
        else:
            lines.extend(("  " if extra else "") + extra for extra in sublines)
    return "\n".join(lines)


def write_notice(stream, message: str, *, prefix: str = "shipmblang: ", width: int = NOTICE_WIDTH, lang: str | None = "en") -> None:
    """Write one notice, flushing each streamed chunk."""
    text = format_prefixed(prefix, message, width=width, lang=lang)
    _write_chunks(stream, text)


def write_stream(stream, text: str, *, max_bytes: int = 240, lang: str | None = "en") -> None:
    """Write generated text in sentence chunks and end with a newline."""
    _write_chunks(stream, "" if text is None else str(text), max_bytes=max_bytes, lang=lang)


def frame_compiler_text(msg_id: int, text: str, *, max_frame: int = 150) -> list[bytes]:
    """Frame a compiler message. LSP keeps its own Content-Length frames."""
    return frame_message(msg_id, text, max_frame=max_frame)


def _write_chunks(stream, text: str, *, max_bytes: int = 240, lang: str | None = "en") -> None:
    chunks = chunk_text(text, max_bytes=max_bytes, lang=lang) if text else []
    if not chunks:
        stream.write("\n")
        _flush(stream)
        return
    for chunk in chunks:
        stream.write(chunk)
        _flush(stream)
    if not text.endswith("\n"):
        stream.write("\n")
        _flush(stream)


def _flush(stream) -> None:
    flush = getattr(stream, "flush", None)
    if flush is not None:
        flush()
