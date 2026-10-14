from __future__ import annotations

import re

from .thesaurus import TriggerLexicon, normalize_trigger_word


SMART_TRANSLATION = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u00a0": " ",
    }
)


def normalize_source(source: str) -> str:
    return source.translate(SMART_TRANSLATION).replace("\r\n", "\n").replace("\r", "\n")


def normalize_word(word: str, lexicon: TriggerLexicon | None = None) -> str:
    lowered = word.lower()
    if lowered in {"let's", "lets"}:
        return "let us"
    if lowered in {"agenticallly", "agentically"}:
        return "agentically"
    return normalize_trigger_word(lowered, lexicon)


def to_snake_case(text: str) -> str:
    words = re.findall(r"[a-zA-Z0-9]+", text.lower())
    return "_".join(words)


def strip_articles(text: str) -> str:
    return re.sub(r"\b(the|a|an|this|that)\b", " ", text, flags=re.IGNORECASE).strip()


def compact_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
