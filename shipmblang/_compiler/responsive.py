"""Offline diagnostics that name a nearby wording, kind, or field.

No model call and no lookup outside this module. The C++ compiler repeats
the same rules in cpp/src/compiler.cpp. Keep the two copies in step.

SMBG120: a clause the general grammar does not implement.
SMBG121: a value that is one edit from a declared name, or a word used as a
field of a declared value. There are no object fields on this branch, so a
field phrase names the value's kind and says that word is not a field.

A one-line kind-and-value opcode is PROPOSED and is not emitted. Kind and
value output, when requested in English, uses the existing const and show
instructions only.
"""
from __future__ import annotations

import re

PLACEHOLDERS = {"NAME", "VALUE", "CONDITION", "LIST", "TYPE"}
OF_WORDS = frozenset({
    "sum", "total", "aggregate", "difference", "product", "quotient",
    "remainder", "length", "number", "result", "graphemes", "words",
    "sentences", "chunks", "frames", "list", "empty", "first", "last",
    "item", "verified",
})
# Display text is the suggestion. Tokens drive the edit distance.
# Placeholders match any one input word at cost 0.
TEMPLATES = (
    ("Let NAME be VALUE.", ("Let", "NAME", "be", "VALUE")),
    ("Show VALUE.", ("Show", "VALUE")),
    ("Set NAME to VALUE.", ("Set", "NAME", "to", "VALUE")),
    ("Add VALUE to NAME.", ("Add", "VALUE", "to", "NAME")),
    ("Subtract VALUE from NAME.", ("Subtract", "VALUE", "from", "NAME")),
    ("Multiply NAME by VALUE.", ("Multiply", "NAME", "by", "VALUE")),
    ("Divide NAME by VALUE.", ("Divide", "NAME", "by", "VALUE")),
    ("Append VALUE to NAME.", ("Append", "VALUE", "to", "NAME")),
    ("What is VALUE.", ("What", "is", "VALUE")),
    ("If CONDITION then.", ("If", "CONDITION", "then")),
    ("While CONDITION.", ("While", "CONDITION")),
    ("For each NAME in LIST.", ("For", "each", "NAME", "in", "LIST")),
    ("Return VALUE.", ("Return", "VALUE")),
    ("Define a function NAME returning TYPE.", ("Define", "a", "function", "NAME", "returning", "TYPE")),
    ("Start with NAME at VALUE.", ("Start", "with", "NAME", "at", "VALUE")),
    ("Show the kind for NAME.", ("Show", "the", "kind", "for", "NAME")),
    ("Show the kind and the value for NAME.", ("Show", "the", "kind", "and", "the", "value", "for", "NAME")),
)
# First-word hints win over edit distance. They only apply once a clause has
# already failed to match a real form, so they do not accept new sentences.
HINTS = {
    "make": "Set NAME to VALUE.",
    "update": "Set NAME to VALUE.",
    "assign": "Set NAME to VALUE.",
    "put": "Set NAME to VALUE.",
    "output": "Show VALUE.",
    "write": "Show VALUE.",
    "give": "Show VALUE.",
    "exhibit": "Show VALUE.",
    "create": "Let NAME be VALUE.",
    "declare": "Let NAME be VALUE.",
    "plus": "Add VALUE to NAME.",
    "minus": "Subtract VALUE from NAME.",
}
WORD = re.compile(r"[a-z0-9_]+")


def _words(text):
    return WORD.findall(text.lower())


def _decls(symbols):
    found = {}
    for symbol in symbols or ():
        name = str(symbol.get("name", ""))
        if not name or name.startswith("$"):
            continue
        found[name] = (name, str(symbol.get("type", "")), int(symbol.get("id", 0)))
    return list(found.values())


def _token_match(word, token):
    return token in PLACEHOLDERS or word == token.lower()


def edit_distance(left, right):
    """Levenshtein. `right` items may be placeholders, which match at cost 0."""
    previous = list(range(len(right) + 1))
    for i, item in enumerate(left, 1):
        current = [i]
        for j, token in enumerate(right, 1):
            cost = 0 if _token_match(item, token) else 1
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + cost))
        previous = current
    return previous[-1]


def string_distance(left, right):
    return edit_distance(list(left.lower()), list(right.lower()))


def nearest_wording(clause):
    words = _words(clause)
    if words and words[0] in HINTS:
        return HINTS[words[0]]
    best = TEMPLATES[0][0]
    best_distance = None
    for wording, tokens in TEMPLATES:
        distance = edit_distance(words, tokens)
        if best_distance is None or distance < best_distance:
            best, best_distance = wording, distance
    return best


def _by_name(name, decls):
    for decl in decls:
        if decl[0] == name:
            return decl
    return None


def _field(words, decls):
    index = 0
    while index + 3 < len(words):
        if words[index] == "the" and words[index + 2] == "of" and words[index + 1] not in OF_WORDS:
            owner_at = index + 3
            if words[owner_at] in {"the", "a", "an"} and owner_at + 1 < len(words):
                owner_at += 1
            owner = _by_name(words[owner_at], decls)
            if owner is not None:
                return words[index + 1], owner
        index += 1
    return None


def _end_index(words, name):
    parts = name.split()
    last = -1
    width = len(parts)
    for index in range(len(words) - width + 1):
        if words[index:index + width] == parts:
            last = index + width - 1
    return last


def _exact_mentioned(words, decls):
    best, best_at = None, -1
    for decl in decls:
        at = _end_index(words, decl[0])
        if at > best_at:
            best, best_at = decl, at
    return best


def _nearest_typo(words, decls):
    best = None
    for word in words:
        for decl in decls:
            if " " in decl[0] or word == decl[0]:
                continue
            if string_distance(word, decl[0]) != 1:
                continue
            if best is None or (decl[0], decl[2]) < (best[0], best[2]):
                best = decl
    return best


def _kind_suffix(words, decls):
    field = _field(words, decls)
    if field is not None:
        word, owner = field
        return f" '{word}' is not a field of '{owner[0]}' (kind {owner[1]})."
    exact = _exact_mentioned(words, decls)
    if exact is not None:
        return f" Kind of '{exact[0]}' is {exact[1]}."
    near = _nearest_typo(words, decls)
    if near is not None:
        return f" Nearest declared value is '{near[0]}' (kind {near[1]})."
    return ""


def clause_diagnostic(clause, symbols):
    """SMBG120 message. The caller attaches the code."""
    decls = _decls(symbols)
    words = _words(clause)
    return (
        "This clause is not implemented by the general computation grammar. "
        f"Nearest supported wording: {nearest_wording(clause)}"
        f"{_kind_suffix(words, decls)}"
    )


def value_diagnostic(token, following, symbols):
    """SMBG121 message, or None to keep the existing question."""
    word = token.lower()
    if not WORD.fullmatch(word):
        return None
    decls = _decls(symbols)
    rest = [item.lower() for item in following]
    if rest and rest[0] == "of" and word not in OF_WORDS:
        owner_words = rest[1:]
        if owner_words and owner_words[0] in {"the", "a", "an"}:
            owner_words = owner_words[1:]
        if owner_words:
            owner = _by_name(owner_words[0], decls)
            if owner is not None:
                suggestion = f"Show the kind for {owner[0]}." if word == "kind" else f"Show {owner[0]}."
                return (
                    f"'{word}' is not a field of '{owner[0]}' (kind {owner[1]}). "
                    f"Nearest supported wording: {suggestion}"
                )
    near = _nearest_typo([word], decls)
    if near is not None:
        return f"'{word}' is not a declared value. Did you mean '{near[0]}' (kind {near[1]})?"
    return None
