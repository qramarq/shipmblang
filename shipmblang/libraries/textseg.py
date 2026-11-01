"""Unicode text segmentation for ShipMBLang programs.

The bundled compiler owns the implementation. A program calls it with the
compiler's text forms, such as ``the graphemes of "cafe"``. This module
re-exports those functions so existing Python imports keep working.

Frames use the 8-byte little-endian voiceboi-chunk header. The two bytes
that used to widen the message id to a uint32 lead the first frame's payload.
"""

from shipmblang._compiler.textseg import (
    DEFAULT_MAX_FRAME,
    HEADER_SIZE,
    MIN_BYTES,
    chunk_text,
    crc16_ccitt,
    display_width,
    frame_message,
    grapheme_spans,
    graphemes,
    iter_chunks,
    normalize_lang,
    parse_frame,
    sentence_spans,
    sentences,
    slice_text,
    unframe_message,
    word_spans,
    words,
    wrap_text,
)

__all__ = [
    "DEFAULT_MAX_FRAME",
    "HEADER_SIZE",
    "MIN_BYTES",
    "chunk_text",
    "crc16_ccitt",
    "display_width",
    "frame_message",
    "grapheme_spans",
    "graphemes",
    "iter_chunks",
    "normalize_lang",
    "parse_frame",
    "sentence_spans",
    "sentences",
    "slice_text",
    "unframe_message",
    "word_spans",
    "words",
    "wrap_text",
]
