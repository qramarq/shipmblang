"""Unicode text segmentation and streaming chunks.

Sentence, word, and grapheme boundaries follow UAX #29, with a small set of
extra rules for the languages the compiler and editors actually emit:

- sentence ends used by those languages, including ``。！？؟।`` and ellipsis
- closing quotes and brackets stay with the sentence they close
- per-language abbreviation lists
- Han, Hiragana, and Thai break without spaces
- German does not split an abbreviation, and a chunk does not leave the
  trailing verb of a clause alone when an earlier break fits
- a cut never lands inside a UTF-8 sequence or a grapheme cluster

No third-party data files. Grapheme classes that are just combining marks use
``unicodedata``, which is already part of the interpreter.
"""

from __future__ import annotations

import struct
import unicodedata

HEADER_SIZE = 8
DEFAULT_MAX_FRAME = 150
MIN_BYTES = 4
FLAG_LAST_SENTENCE = 0x01
FLAG_AUDIO = 0x02
FLAG_CONTROL = 0x04
# High 16 bits of the former uint32 message id. They no longer fit in the
# 8-byte header, so they lead the first frame's payload.
_MSG_ID_TAIL = 2

_CR = "cr"
_LF = "lf"
_CONTROL = "control"
_EXTEND = "extend"
_ZWJ = "zwj"
_RI = "ri"
_PREPEND = "prepend"
_SPACING = "spacing"
_L = "l"
_V = "v"
_T = "t"
_LV = "lv"
_LVT = "lvt"
_EXTPICT = "extpict"
_OTHER = "other"

_INCB_NONE = 0
_INCB_CONSONANT = 1
_INCB_LINKER = 2
_INCB_EXTEND = 3

_LANG_ALIASES = {
    "en": "en", "english": "en",
    "es": "es", "spanish": "es",
    "fr": "fr", "french": "fr",
    "de": "de", "german": "de",
    "pt": "pt", "portuguese": "pt",
    "it": "it", "italian": "it",
    "ru": "ru", "russian": "ru",
    "zh": "zh", "chinese": "zh", "cmn": "zh",
    "ja": "ja", "japanese": "ja",
    "ko": "ko", "korean": "ko",
    "ar": "ar", "arabic": "ar",
    "hi": "hi", "hindi": "hi",
    "th": "th", "thai": "th",
}

# Dotted forms omit the trailing dot. Single-letter entries stay on the
# language that uses them so an unspecified language does not swallow "M.".
_SHARED_ABBREV = frozenset({
    "dr", "prof", "mr", "mrs", "ms", "etc", "e.g", "i.e", "vs", "cf", "jr", "sr",
})
_LANG_ABBREV = {
    "en": frozenset({
        "st", "gen", "gov", "sgt", "capt", "rev", "hon", "esq", "inc", "ltd", "co",
        "corp", "dept", "univ", "approx", "vol", "ed", "fig", "jan", "feb", "mar",
        "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec", "a.m", "p.m",
        "u.s", "u.k", "ph.d",
    }),
    "es": frozenset({
        "sr", "sra", "srta", "dra", "ud", "uds", "p.ej", "art", "vol", "lic", "ing",
        "atte", "dna", "ee.uu",
    }),
    "fr": frozenset({
        "m", "mme", "mlle", "pr", "av", "bd", "vol", "chap", "fig", "ste", "env",
        "c-à-d",
    }),
    "de": frozenset({
        "hr", "fr", "usw", "z.b", "d.h", "u.a", "vgl", "bzgl", "ggf", "ca", "nr",
        "str", "inkl", "exkl", "evtl", "bspw", "bzw", "geb", "s.o", "s.u", "o.ä",
        "u.ä", "dgl", "abs", "zzgl",
    }),
    "pt": frozenset({
        "sra", "dra", "art", "vol", "av", "tel", "ex", "obs", "eng", "pág", "prof",
    }),
    "it": frozenset({
        "sig", "sig.ra", "dott", "dott.ssa", "ecc", "cfr", "vol", "avv", "ing",
        "geom", "cav", "rag",
    }),
    "ru": frozenset({
        "г", "т.е", "т.д", "т.п", "др", "см", "проф", "ул", "стр", "им", "тыс",
        "млн", "руб", "напр", "рис", "табл", "вв",
    }),
    "zh": frozenset(),
    "ja": frozenset(),
    "ko": frozenset(),
    "ar": frozenset({"د", "م"}),
    "hi": frozenset({"डॉ", "श्री", "श्रीमती", "प्रो"}),
}
_UNION_ABBREV = _SHARED_ABBREV.union(*(
    {item for item in words if len(item.replace(".", "")) > 1}
    for words in _LANG_ABBREV.values()
))

_STERM = frozenset({
    "!", "?",
    "\uFF01", "\uFF1F",
    "\u3002", "\uFF61",
    "\u061F",
    "\u0964", "\u0965",
    "\u0E2F",
})
_ATERM = frozenset({".", "\uFF0E", "\u06D4"})
_CLOSE = frozenset("\"')]}>}»›”’」』】〕〉》）］｝\u201C\u201D\u2019\u2018\u00BB\u203A")
_CLAUSE = frozenset(",;:，、；：؛،—–")
_GERMAN_SUBORDINATORS = frozenset({
    "dass", "weil", "ob", "wenn", "obwohl", "als", "indem", "sodass", "damit",
    "falls", "während", "bevor", "nachdem", "seit", "bis", "wobei",
})


def normalize_lang(lang: str | None) -> str | None:
    """Return a supported language code, or None when ``lang`` is unset."""
    if lang is None:
        return None
    key = str(lang).strip().lower().replace("_", "-").split("-", 1)[0]
    return _LANG_ALIASES.get(key)


def grapheme_spans(text: str) -> list[tuple[int, int]]:
    """Return ``[start, end)`` code-point spans, one per grapheme cluster."""
    if not text:
        return []
    classes = [_gcb(ord(ch)) for ch in text]
    incb = [_incb(ord(ch)) for ch in text]
    n = len(text)
    spans = []
    start = 0
    for index in range(n - 1):
        if _grapheme_break(classes, incb, index):
            spans.append((start, index + 1))
            start = index + 1
    spans.append((start, n))
    return spans


def graphemes(text: str) -> list[str]:
    """Split ``text`` into grapheme clusters."""
    return [text[start:end] for start, end in grapheme_spans(text)]


def word_spans(text: str, lang: str | None = None) -> list[tuple[int, int]]:
    """Return spans of words. Punctuation and whitespace are not words.

    ``lang`` is accepted so callers can pass the same tag they use for
    sentences. Han, kana, and Thai breaks follow the script.
    """
    del lang
    clusters = grapheme_spans(text)
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(clusters):
        kind = _word_kind(text, clusters[index])
        if kind is None:
            index += 1
            continue
        end_index = index + 1
        while end_index < len(clusters) and _word_extends(text, clusters, end_index, kind):
            grapheme = text[clusters[end_index][0]:clusters[end_index][1]]
            end_index += 2 if kind == "alnum" and grapheme in {"'", "’", ".", ","} else 1
        spans.append((clusters[index][0], clusters[end_index - 1][1]))
        index = end_index
    return spans


def words(text: str, lang: str | None = None) -> list[str]:
    """Split ``text`` into words."""
    return [text[start:end] for start, end in word_spans(text, lang)]


def sentence_spans(text: str, lang: str | None = None) -> list[tuple[int, int]]:
    """Return spans that concatenate back to ``text``."""
    if text == "":
        return []
    lang = normalize_lang(lang)
    n = len(text)
    ends: list[int] = []
    index = 0
    while index < n:
        kind, nxt = _terminator_at(text, index)
        if kind is None:
            index += 3 if text.startswith("\u0e2f\u0e25\u0e2f", index) else 1
            continue
        if kind == "sep":
            while nxt < n:
                more, after = _terminator_at(text, nxt)
                if more != "sep":
                    break
                nxt = after
            ends.append(nxt)
            index = nxt
            continue
        if kind == "aterm" and _suppress_aterm(text, index, nxt, lang):
            index = nxt
            continue
        cursor = nxt
        while cursor < n and _is_close(text[cursor]):
            cursor += 1
        while cursor < n and _is_space(text[cursor]):
            cursor += 1
        if cursor < n:
            sep_kind, sep_end = _terminator_at(text, cursor)
            if sep_kind == "sep":
                ends.append(sep_end)
                index = sep_end
                continue
        if kind in {"aterm", "ellipsis"} and cursor < n and _is_lower(text[cursor]):
            index = nxt
            continue
        if kind == "sterm" and cursor < n and _continues_term(text, cursor):
            index = nxt
            continue
        if cursor < n:
            ends.append(cursor)
            index = cursor
            continue
        break
    ends.append(n)
    spans = []
    prev = 0
    for end in ends:
        if end > prev:
            spans.append((prev, end))
            prev = end
    return spans


def sentences(text: str, lang: str | None = None) -> list[str]:
    """Split ``text`` into sentences, keeping separators on the left piece."""
    return [text[start:end] for start, end in sentence_spans(text, lang)]


def slice_text(text: str, start: int, end: int | None = None, *, unit: str = "bytes") -> str:
    """Slice ``text`` on a grapheme boundary.

    ``unit="bytes"`` addresses UTF-8 offsets. A start that lands inside a
    code point or cluster moves forward; an end moves backward. ``unit="chars"``
    addresses Unicode code points and snaps the same way.
    """
    if unit not in {"bytes", "chars"}:
        raise ValueError("unit must be 'bytes' or 'chars'")
    if end is None:
        end = len(text.encode("utf-8")) if unit == "bytes" else len(text)
    if start < 0 or end < 0:
        raise ValueError("slice offsets must be >= 0")
    spans = grapheme_spans(text)
    if not spans:
        return ""
    if unit == "chars":
        start_cp, end_cp = start, end
    else:
        start_cp = _snap_byte_forward(text, start)
        end_cp = _snap_byte_backward(text, end)
    start_cp = _snap_span_forward(spans, start_cp)
    end_cp = _snap_span_backward(spans, end_cp)
    if end_cp <= start_cp:
        return ""
    return text[start_cp:end_cp]


def chunk_text(
    text: str,
    *,
    max_bytes: int | None = None,
    max_words: int | None = None,
    lang: str | None = None,
) -> list[str]:
    """Split ``text`` into streamable chunks.

    Sentences come first. A sentence longer than ``max_bytes`` or ``max_words``
    breaks at clause punctuation, then whitespace, then a word boundary.
    A grapheme boundary is used only when nothing softer fits. Joining the
    chunks reproduces ``text``.
    """
    if max_bytes is not None and max_bytes < MIN_BYTES:
        raise ValueError(f"max_bytes must be at least {MIN_BYTES}")
    if max_words is not None and max_words < 1:
        raise ValueError("max_words must be at least 1")
    lang = normalize_lang(lang)
    parts: list[str] = []
    for start, end in sentence_spans(text, lang):
        parts.extend(_pack(text[start:end], max_bytes=max_bytes, max_words=max_words, lang=lang))
    return parts


def iter_chunks(
    text: str,
    *,
    max_bytes: int | None = None,
    max_words: int | None = None,
    lang: str | None = None,
):
    """Yield chunks from :func:`chunk_text`."""
    yield from chunk_text(text, max_bytes=max_bytes, max_words=max_words, lang=lang)


def display_width(text: str) -> int:
    """Column width. Combining marks add nothing; wide characters add two."""
    total = 0
    for start, end in grapheme_spans(text):
        total += _cluster_cols(text[start:end])
    return total


def wrap_text(text: str, *, width: int = 88, lang: str | None = None) -> str:
    """Wrap each existing line. Lines that already fit are unchanged."""
    if width < 8:
        raise ValueError("width must be at least 8")
    lang = normalize_lang(lang)
    return "\n".join(_wrap_line(line, width, lang) if line else "" for line in text.split("\n"))


def crc16_ccitt(data: bytes) -> int:
    """CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, no reflection, xorout 0."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def frame_message(msg_id: int, payload: str | bytes, *, max_frame: int = DEFAULT_MAX_FRAME) -> list[bytes]:
    """Pack ``payload`` into voiceboi-chunk frames of at most ``max_frame`` bytes.

    Header, exactly 8 bytes, little-endian: message id (uint16), sentence
    index (uint8), chunk index (uint8), chunks in the sentence (uint8),
    flags (uint8), CRC-16/CCITT-FALSE of the payload (uint16). Flag 0x01
    marks every chunk of the last sentence. Flag 0x02 is audio and is left
    clear. Flag 0x04 is control; this encoder never sets it, and
    :func:`parse_frame` rejects it.

    Text is split into sentences, then each sentence is cut on a grapheme
    boundary so a cut never lands inside a UTF-8 sequence. A single grapheme
    longer than the payload budget stays intact, so that one frame can
    exceed ``max_frame``. Bytes are one sentence and are split on raw bytes.

    The previous header was 10 bytes (``>IHHH``: uint32 id, uint16 sequence,
    uint16 total, uint16 crc). The two extra bytes were the high half of
    that uint32. They are now the first two little-endian bytes of the
    message's first payload. The flat sequence and the message-wide total
    are derived from the sentence index, the chunk index, and the
    per-sentence total.
    """
    if isinstance(msg_id, bool) or not isinstance(msg_id, int) or not 0 <= msg_id <= 0xFFFFFFFF:
        raise ValueError("msg_id must fit in uint32")
    if max_frame < HEADER_SIZE + MIN_BYTES:
        raise ValueError(f"max_frame must be at least {HEADER_SIZE + MIN_BYTES}")
    budget = max_frame - HEADER_SIZE
    groups = _message_groups(payload, budget)
    msg_lo = msg_id & 0xFFFF
    tail = struct.pack("<H", msg_id >> 16)
    last = len(groups) - 1
    frames = []
    for sentence_idx, blobs in enumerate(groups):
        total = len(blobs)
        flags = FLAG_LAST_SENTENCE if sentence_idx == last else 0
        for chunk_idx, blob in enumerate(blobs):
            wire = tail + blob if sentence_idx == 0 and chunk_idx == 0 else blob
            header = struct.pack(
                "<HBBBBH",
                msg_lo,
                sentence_idx,
                chunk_idx,
                total,
                flags,
                crc16_ccitt(wire),
            )
            frames.append(header + wire)
    return frames


def parse_frame(frame: bytes) -> dict:
    """Return the 8-byte header fields and the raw payload.

    ``payload`` is every byte after the header, including the two-byte
    message-id tail on the first frame. Reject a short frame, flag 0x04,
    or a CRC that does not match the payload.
    """
    if len(frame) < HEADER_SIZE:
        raise ValueError("frame is shorter than the header")
    msg_id, sentence_idx, chunk_idx, total, flags, crc = struct.unpack("<HBBBBH", frame[:HEADER_SIZE])
    if flags & FLAG_CONTROL:
        raise ValueError("control frames are not text chunks")
    payload = frame[HEADER_SIZE:]
    if crc16_ccitt(payload) != crc:
        raise ValueError("frame crc16 mismatch")
    return {
        "msg_id": msg_id,
        "sentence_idx": sentence_idx,
        "chunk_idx": chunk_idx,
        "total": total,
        "flags": flags,
        "payload": payload,
    }


def unframe_message(frames: list[bytes]) -> bytes:
    """Concatenate frame bodies after checking order, totals, flags, and CRC.

    The two message-id bytes at the start of the first payload are not part
    of the body. Later payloads are appended as they stand.
    """
    if not frames:
        raise ValueError("no frames")
    parsed = [parse_frame(frame) for frame in frames]
    first = parsed[0]
    if first["sentence_idx"] != 0 or first["chunk_idx"] != 0:
        raise ValueError("frame sequence does not match")
    if len(first["payload"]) < _MSG_ID_TAIL:
        raise ValueError("frame is missing the message id tail")
    msg_id = first["msg_id"]
    pieces = [first["payload"][_MSG_ID_TAIL:]]
    sentence = 0
    chunk = 0
    total = first["total"]
    if total == 0 or chunk >= total:
        raise ValueError("frame total does not match the list")
    for item in parsed[1:]:
        if item["msg_id"] != msg_id:
            raise ValueError("frame sequence does not match")
        if chunk + 1 < total and item["sentence_idx"] == sentence and item["chunk_idx"] == chunk + 1 and item["total"] == total:
            chunk += 1
            pieces.append(item["payload"])
            continue
        if chunk + 1 == total and item["sentence_idx"] == sentence + 1 and item["chunk_idx"] == 0 and item["total"] > 0:
            sentence += 1
            chunk = 0
            total = item["total"]
            pieces.append(item["payload"])
            continue
        raise ValueError("frame sequence does not match")
    if chunk + 1 != total:
        raise ValueError("frame total does not match the list")
    for item in parsed:
        is_last = item["sentence_idx"] == sentence
        if bool(item["flags"] & FLAG_LAST_SENTENCE) != is_last:
            raise ValueError("frame flags do not match the sentence")
    return b"".join(pieces)


def _message_groups(payload: str | bytes, budget: int) -> list[list[bytes]]:
    first_limit = budget - _MSG_ID_TAIL
    if isinstance(payload, str):
        if payload == "":
            return [[b""]]
        groups = []
        for start, end in sentence_spans(payload):
            limit = first_limit if not groups else budget
            groups.append(_text_pieces(payload[start:end], budget, limit))
        if len(groups) > 256:
            raise ValueError("payload needs more than uint8 sentences")
        return groups
    if not isinstance(payload, (bytes, bytearray)):
        raise TypeError("payload must be str or bytes")
    return [_byte_pieces(bytes(payload), budget, first_limit)]


def _text_pieces(text: str, budget: int, first_limit: int) -> list[bytes]:
    pieces: list[bytes] = []
    rest = text
    while rest:
        cap = first_limit if not pieces else budget
        prefix = _utf8_prefix(rest, cap)
        if prefix == "":
            prefix = graphemes(rest)[0]
        pieces.append(prefix.encode("utf-8"))
        rest = rest[len(prefix):]
    if len(pieces) > 255:
        raise ValueError("sentence needs more than uint8 chunks")
    return pieces or [b""]


def _byte_pieces(blob: bytes, budget: int, first_limit: int) -> list[bytes]:
    if not blob:
        return [b""]
    pieces = []
    offset = 0
    cap = first_limit
    while offset < len(blob):
        pieces.append(blob[offset:offset + cap])
        offset += cap
        cap = budget
    if len(pieces) > 255:
        raise ValueError("sentence needs more than uint8 chunks")
    return pieces


def _utf8_prefix(text: str, max_bytes: int) -> str:
    built = []
    size = 0
    for cluster in graphemes(text):
        width = len(cluster.encode("utf-8"))
        if size + width > max_bytes:
            break
        built.append(cluster)
        size += width
    return "".join(built)


def _pack(text: str, *, max_bytes: int | None, max_words: int | None, lang: str | None) -> list[str]:
    if text == "":
        return []
    if _fits(text, max_bytes, max_words, lang):
        return [text]
    clusters = grapheme_spans(text)
    clause, spaces, word_ends = _break_sites(text, lang)
    parts: list[str] = []
    start = 0
    while start < len(text):
        rest = text[start:]
        if _fits(rest, max_bytes, max_words, lang):
            parts.append(rest)
            break
        def valid(pos: int) -> bool:
            return pos > start and _fits(text[start:pos], max_bytes, max_words, lang)

        chosen = _select_break(text, start, clause, spaces, word_ends, valid, lang, max_words)
        if chosen is None or chosen <= start:
            chosen = _hard_break(text, start, clusters, max_bytes)
        if chosen <= start:
            chosen = clusters[_cluster_index_after(clusters, start)][1]
        parts.append(text[start:chosen])
        start = chosen
    return parts


def _fits(text: str, max_bytes: int | None, max_words: int | None, lang: str | None) -> bool:
    if max_bytes is not None and len(text.encode("utf-8")) > max_bytes:
        return False
    if max_words is not None and len(word_spans(text, lang)) > max_words:
        return False
    return True


def _break_sites(text: str, lang: str | None):
    clause = []
    spaces = []
    for index, char in enumerate(text):
        if char in _CLAUSE and index + 1 < len(text):
            clause.append(index + 1)
        if _is_space(char) or char == "\u200b":
            spaces.append(index + 1)
    word_ends = [end for _, end in word_spans(text, lang) if end < len(text)]
    return clause, spaces, word_ends


def _select_break(text, start, clause, spaces, word_ends, valid, lang, max_words):
    """Rightmost clause or whitespace break that fits, else a word boundary."""
    groups = (
        sorted(pos for pos in (*clause, *spaces) if pos > start),
        [pos for pos in word_ends if pos > start],
    )
    for positions in groups:
        found = []
        for pos in positions:
            snapped = _with_spaces(text, pos, valid)
            if valid(snapped):
                found.append(snapped)
        if lang == "de" and max_words != 1 and found:
            kept = [pos for pos in found if not _isolates_trailing_word(text, pos)]
            if kept:
                found = kept
            else:
                retreated = _retreat(text, start, found[-1], valid)
                if retreated is not None:
                    return retreated
        if found:
            return found[-1]
    return None


def _retreat(text: str, start: int, pos: int, valid) -> int | None:
    earlier = [span[0] for span in word_spans(text, "de") if start < span[0] < pos]
    if earlier and valid(earlier[-1]):
        return earlier[-1]
    return None


def _with_spaces(text: str, pos: int, valid) -> int:
    cursor = pos
    while cursor < len(text) and _is_space(text[cursor]) and valid(cursor + 1):
        cursor += 1
    return cursor


def _isolates_trailing_word(text: str, pos: int) -> bool:
    tail = text[pos:].strip()
    if not tail:
        return False
    spans = word_spans(tail, "de")
    if len(spans) != 1:
        return False
    # A subordinator starts the next clause; breaking there is the clause edge.
    if tail.split(None, 1)[0].lower() in _GERMAN_SUBORDINATORS:
        return False
    return True


def _hard_break(text: str, start: int, clusters: list[tuple[int, int]], max_bytes: int | None) -> int:
    best = None
    for cluster_start, cluster_end in clusters:
        if cluster_end <= start:
            continue
        if max_bytes is None or len(text[start:cluster_end].encode("utf-8")) <= max_bytes:
            best = cluster_end
            continue
        break
    if best is not None:
        return best
    for cluster_start, cluster_end in clusters:
        if cluster_end > start:
            return cluster_end
    return len(text)


def _cluster_index_after(clusters: list[tuple[int, int]], start: int) -> int:
    for index, (cluster_start, cluster_end) in enumerate(clusters):
        if cluster_end > start:
            return index
    return len(clusters) - 1


def _wrap_line(line: str, width: int, lang: str | None) -> str:
    if display_width(line) <= width:
        return line
    parts = _pack_columns(line, width, lang)
    return "\n".join(parts)


def _pack_columns(text: str, width: int, lang: str | None) -> list[str]:
    clusters = grapheme_spans(text)
    clause, spaces, word_ends = _break_sites(text, lang)
    parts = []
    start = 0
    while start < len(text):
        rest = text[start:]
        if display_width(rest) <= width:
            parts.append(rest)
            break

        def valid(pos: int) -> bool:
            return pos > start and display_width(text[start:pos]) <= width

        chosen = _select_break(text, start, clause, spaces, word_ends, valid, lang, None)
        if chosen is None:
            chosen = start
            for cluster_start, cluster_end in clusters:
                if cluster_end <= start:
                    continue
                if display_width(text[start:cluster_end]) <= width:
                    chosen = cluster_end
                else:
                    break
            if chosen == start:
                for cluster_start, cluster_end in clusters:
                    if cluster_end > start:
                        chosen = cluster_end
                        break
        piece = text[start:chosen]
        parts.append(piece)
        start = chosen
    return parts


def _snap_byte_forward(text: str, byte_off: int) -> int:
    if byte_off <= 0:
        return 0
    raw_len = len(text.encode("utf-8"))
    if byte_off >= raw_len:
        return len(text)
    used = 0
    for index, char in enumerate(text):
        width = len(char.encode("utf-8"))
        if used >= byte_off:
            return index
        if used < byte_off < used + width:
            return index + 1
        used += width
    return len(text)


def _snap_byte_backward(text: str, byte_off: int) -> int:
    if byte_off <= 0:
        return 0
    raw_len = len(text.encode("utf-8"))
    if byte_off >= raw_len:
        return len(text)
    used = 0
    for index, char in enumerate(text):
        width = len(char.encode("utf-8"))
        if used + width > byte_off:
            return index
        used += width
    return len(text)


def _snap_span_forward(spans: list[tuple[int, int]], cp_index: int) -> int:
    if cp_index <= 0:
        return 0
    for start, end in spans:
        if start >= cp_index:
            return start
        if start < cp_index < end:
            return end
    return spans[-1][1]


def _snap_span_backward(spans: list[tuple[int, int]], cp_index: int) -> int:
    if cp_index <= 0:
        return 0
    chosen = 0
    for start, end in spans:
        if end <= cp_index:
            chosen = end
        elif start < cp_index < end:
            return start
        else:
            break
    return chosen


def _grapheme_break(classes: list[str], incb: list[int], index: int) -> bool:
    left, right = classes[index], classes[index + 1]
    if left == _CR and right == _LF:
        return False
    if left in {_CONTROL, _CR, _LF} or right in {_CONTROL, _CR, _LF}:
        return True
    if right in {_EXTEND, _ZWJ, _SPACING} or left == _PREPEND:
        return False
    if left == _L and right in {_L, _V, _LV, _LVT}:
        return False
    if left in {_LV, _V} and right in {_V, _T}:
        return False
    if left in {_LVT, _T} and right == _T:
        return False
    if incb[index + 1] == _INCB_CONSONANT and _incb_link(incb, index):
        return False
    if right == _EXTPICT and left == _ZWJ and _zwj_pict(classes, index):
        return False
    if left == _RI and right == _RI and _ri_pair(classes, index):
        return False
    return True


def _incb_link(incb: list[int], index: int) -> bool:
    seen_linker = False
    cursor = index
    while cursor >= 0:
        kind = incb[cursor]
        if kind == _INCB_LINKER:
            seen_linker = True
            cursor -= 1
            continue
        if kind == _INCB_EXTEND:
            cursor -= 1
            continue
        return kind == _INCB_CONSONANT and seen_linker
    return False


def _zwj_pict(classes: list[str], index: int) -> bool:
    cursor = index - 1
    while cursor >= 0 and classes[cursor] == _EXTEND:
        cursor -= 1
    return cursor >= 0 and classes[cursor] == _EXTPICT


def _ri_pair(classes: list[str], index: int) -> bool:
    count = 0
    cursor = index
    while cursor >= 0 and classes[cursor] == _RI:
        count += 1
        cursor -= 1
    return count % 2 == 1


def _gcb(code: int) -> str:
    if code == 0x0D:
        return _CR
    if code == 0x0A:
        return _LF
    if code == 0x200D:
        return _ZWJ
    if code == 0x200C:
        return _EXTEND
    if 0x1F1E6 <= code <= 0x1F1FF:
        return _RI
    if 0x1F3FB <= code <= 0x1F3FF or 0xFE00 <= code <= 0xFE0F or 0xE0100 <= code <= 0xE01EF:
        return _EXTEND
    if 0xE0020 <= code <= 0xE007F:
        return _EXTEND
    if _is_prepend(code):
        return _PREPEND
    hangul = _hangul_class(code)
    if hangul:
        return hangul
    if _is_extpict(code):
        return _EXTPICT
    category = unicodedata.category(chr(code))
    if category in {"Mn", "Me"}:
        return _EXTEND
    if category == "Mc":
        return _SPACING
    if category in {"Cc", "Cf", "Cs", "Zl", "Zp"}:
        return _CONTROL
    return _OTHER


def _incb(code: int) -> int:
    if code == 0x094D:
        return _INCB_LINKER
    if 0x0915 <= code <= 0x0939 or 0x0958 <= code <= 0x095F or 0x0978 <= code <= 0x097F:
        return _INCB_CONSONANT
    if 0x0900 <= code <= 0x097F and _gcb(code) == _EXTEND:
        return _INCB_EXTEND
    return _INCB_NONE


def _is_prepend(code: int) -> bool:
    return (
        0x0600 <= code <= 0x0605
        or code in {0x06DD, 0x070F, 0x08E2}
        or 0x0890 <= code <= 0x0891
    )


def _hangul_class(code: int) -> str | None:
    if 0x1100 <= code <= 0x115F or 0xA960 <= code <= 0xA97C:
        return _L
    if 0x1160 <= code <= 0x11A7 or 0xD7B0 <= code <= 0xD7C6:
        return _V
    if 0x11A8 <= code <= 0x11FF or 0xD7CB <= code <= 0xD7FB:
        return _T
    if 0xAC00 <= code <= 0xD7A3:
        return _LV if (code - 0xAC00) % 28 == 0 else _LVT
    return None


def _is_extpict(code: int) -> bool:
    if 0x1F300 <= code <= 0x1FAFF and not (0x1F3FB <= code <= 0x1F3FF):
        return True
    if code in {0x00A9, 0x00AE, 0x203C, 0x2049, 0x2122, 0x2139, 0x2328, 0x23CF, 0x24C2, 0x2764}:
        return True
    if 0x2600 <= code <= 0x27BF or 0x231A <= code <= 0x23FA or 0x2B05 <= code <= 0x2B55:
        return True
    return False


def _word_kind(text: str, span: tuple[int, int]) -> str | None:
    code = ord(text[span[0]])
    if _is_han(code) or _is_hiragana(code):
        return "cjk"
    if _is_katakana(code):
        return "kata"
    if _is_thai_letter(code):
        return "thai"
    char = text[span[0]]
    if char.isalpha() or char.isdigit():
        return "alnum"
    return None


def _word_extends(text, clusters, index, kind) -> bool:
    grapheme = text[clusters[index][0]:clusters[index][1]]
    if kind == "cjk":
        return False
    if kind == "kata":
        return _is_katakana(ord(grapheme[0]))
    if kind == "thai":
        if not _is_thai_letter(ord(grapheme[0])):
            return False
        previous = clusters[index - 1]
        last = ord(text[previous[1] - 1])
        return not _thai_break_before(last, ord(grapheme[0]))
    if grapheme in {"'", "’"}:
        nxt = index + 1
        return nxt < len(clusters) and _word_kind(text, clusters[nxt]) == "alnum"
    if grapheme in {".", ","}:
        prev_char = text[clusters[index - 1][1] - 1]
        nxt = index + 1
        return prev_char.isdigit() and nxt < len(clusters) and text[clusters[nxt][0]].isdigit()
    return _word_kind(text, clusters[index]) == "alnum"


def _thai_break_before(previous: int, current: int) -> bool:
    if 0x0E40 <= current <= 0x0E44:
        return True
    if _is_thai_consonant(current) and (
        previous in {0x0E30, 0x0E32, 0x0E33, 0x0E45, 0x0E46, 0x0E2F} or 0x0E48 <= previous <= 0x0E4B
    ):
        return True
    return False


def _is_han(code: int) -> bool:
    return (
        0x3400 <= code <= 0x9FFF
        or 0xF900 <= code <= 0xFAFF
        or 0x20000 <= code <= 0x2A6DF
        or 0x2A700 <= code <= 0x2B73F
    )


def _is_hiragana(code: int) -> bool:
    return 0x3041 <= code <= 0x3096 or 0x309D <= code <= 0x309F


def _is_katakana(code: int) -> bool:
    return (
        0x30A1 <= code <= 0x30FA
        or code == 0x30FC
        or 0x31F0 <= code <= 0x31FF
        or 0xFF66 <= code <= 0xFF9D
    )


def _is_thai_letter(code: int) -> bool:
    return 0x0E01 <= code <= 0x0E3A or 0x0E40 <= code <= 0x0E4E


def _is_thai_consonant(code: int) -> bool:
    return 0x0E01 <= code <= 0x0E2E


def _terminator_at(text: str, index: int) -> tuple[str | None, int]:
    char = text[index]
    if char == "\r":
        return "sep", index + 2 if index + 1 < len(text) and text[index + 1] == "\n" else index + 1
    if char in "\n\u0085\u2028\u2029":
        return "sep", index + 1
    if char == "…" or (char == "." and index + 1 < len(text) and text[index + 1] == "."):
        cursor = index + 1
        if char == ".":
            while cursor < len(text) and text[cursor] == ".":
                cursor += 1
        return "ellipsis", cursor
    if char in _ATERM:
        return "aterm", index + 1
    if char == "\u0E2F" and text.startswith("ฯลฯ", index):
        return None, index + 1
    if char in _STERM:
        return "sterm", index + 1
    return None, index + 1


def _suppress_aterm(text: str, dot: int, nxt: int, lang: str | None) -> bool:
    if _immediate_number(text, nxt):
        return True
    if dot > 0 and text[dot - 1].isdigit() and _spaced_number(text, nxt):
        return True
    return _is_abbreviation(text, dot, lang)


def _immediate_number(text: str, nxt: int) -> bool:
    cursor = nxt
    while cursor < len(text) and _is_close(text[cursor]):
        cursor += 1
    return cursor < len(text) and text[cursor].isdigit()


def _spaced_number(text: str, nxt: int) -> bool:
    cursor = nxt
    while cursor < len(text) and _is_close(text[cursor]):
        cursor += 1
    if cursor >= len(text) or not _is_space(text[cursor]):
        return False
    while cursor < len(text) and _is_space(text[cursor]):
        cursor += 1
    return cursor < len(text) and text[cursor].isdigit()


def _is_abbreviation(text: str, dot: int, lang: str | None) -> bool:
    token = _before_token(text, dot)
    abbrevs = _abbrev_set(lang)
    if token and token in abbrevs:
        return True
    if dot + 1 < len(text) and text[dot + 1].isalpha():
        cursor = dot + 1
        while cursor < len(text) and text[cursor].isalpha():
            cursor += 1
        extended = f"{token}.{text[dot + 1:cursor]}".lower()
        if extended in abbrevs:
            return True
    if len(token) == 1 and token.isalpha() and dot + 1 < len(text) and _is_upper(text[dot + 1]):
        return True
    return False


def _before_token(text: str, dot: int) -> str:
    cursor = dot
    chars: list[str] = []
    while cursor > 0:
        char = text[cursor - 1]
        if char.isalpha() or char in ".'’":
            if char in "'’" and not chars:
                break
            chars.append(char)
            cursor -= 1
            continue
        break
    return "".join(reversed(chars)).lower()


def _abbrev_set(lang: str | None) -> frozenset[str]:
    if lang is None:
        return _UNION_ABBREV
    return _SHARED_ABBREV | _LANG_ABBREV.get(lang, frozenset())


def _continues_term(text: str, index: int) -> bool:
    char = text[index]
    if char in _STERM or char == "…" or char == ".":
        return True
    return False


def _is_close(char: str) -> bool:
    return char in _CLOSE


def _is_space(char: str) -> bool:
    return char == "\t" or unicodedata.category(char) == "Zs"


def _is_lower(char: str) -> bool:
    return unicodedata.category(char) == "Ll"


def _is_upper(char: str) -> bool:
    return unicodedata.category(char) in {"Lu", "Lt"}


def _cluster_cols(cluster: str) -> int:
    columns = 0
    for char in cluster:
        category = unicodedata.category(char)
        if category in {"Mn", "Me", "Cf"}:
            continue
        width = unicodedata.east_asian_width(char)
        columns += 2 if width in {"W", "F"} else 1
    return columns
