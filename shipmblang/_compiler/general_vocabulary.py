"""Reviewed senses for pure computation; never rewrite source or identifiers.

External/WordNet synonyms are deliberately excluded until sense-reviewed here.
"""
import re

from .thesaurus import CANONICAL_TRIGGERS

VOCABULARY_VERSION = "contextual-general-2"
OUTPUT_VERBS = tuple(sorted(CANONICAL_TRIGGERS["show"]))
OUTPUT_PATTERN = "(?:" + "|".join(map(re.escape, OUTPUT_VERBS)) + ")"
SUM_NOUNS = ("sum", "total", "aggregate")


def retrieved_meanings(source):
    """Bounded, trusted sense hints selected by words outside quoted text."""
    words = set(re.findall(r"[a-z]+", re.sub(r'"(?:\\.|[^"\\])*"', '', source).lower()))
    hints = []
    if words.intersection(OUTPUT_VERBS):
        hints.append("show/print/display/present: output a value when used as an instruction verb.")
    if words.intersection(SUM_NOUNS):
        hints.append("sum/total/aggregate of two integers: arithmetic addition; other aggregation senses require clarification.")
    if "add" in words:
        hints.append("add: integer addition in arithmetic context; adding packages or list items is not this operation.")
    return "\n".join(hints)
