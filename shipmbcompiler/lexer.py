from __future__ import annotations

import re

from .models import Diagnostic, Span, Token
from .normalizer import normalize_source, normalize_word
from .thesaurus import TriggerLexicon


KEYWORDS = {
    "agentically",
    "able",
    "access",
    "app",
    "apps",
    "as",
    "bot",
    "call",
    "chat",
    "class",
    "close",
    "command",
    "commands",
    "control",
    "define",
    "device",
    "device_target",
    "error",
    "errors",
    "execute",
    "fail",
    "fails",
    "function",
    "if",
    "import",
    "in",
    "interface",
    "library",
    "me",
    "method",
    "on",
    "open",
    "package",
    "platform",
    "capability",
    "agentic",
    "remote",
    "resources",
    "search",
    "show",
    "target",
    "run",
    "voice",
    "when",
    "would",
    "let us",
}

ENGLISH_OPERATORS = {
    "and": "logical_and",
    "or": "logical_or",
    "not": "logical_not",
    "equals": "equality",
    "is": "contextual_binding_or_equality",
    "becomes": "assign",
    "plus": "add",
    "minus": "subtract",
    "times": "multiply",
    "use": "use_library",
    "from": "source_relation",
    "in": "source_relation",
    "to": "purpose_relation",
    "control": "control_action",
    "like": "similarity_relation",
    "install": "install_action",
    "give": "grant_access",
    "show": "show_action",
}

SYMBOL_OPERATORS = {
    "|&>": "error_pipe",
    "|>": "pipe",
    "==": "equality",
    "=": "assign_or_equality",
    "+": "add",
    "-": "subtract",
    "*": "multiply",
    "/": "divide",
    "%": "modulo",
    ">": "greater_than",
    "<": "less_than",
}

SENTENCE_BOUNDARIES = {".", "!", "?", ";"}
PUNCTUATORS = {",", ":", "(", ")", "[", "]", "{", "}"}
TOKEN_RE = re.compile(
    r"""
    (?P<comment>\#.*)
    |(?P<bad_comment>//.*)
    |(?P<compound>[A-Za-z0-9][A-Za-z0-9_-]*(?:[./][A-Za-z0-9][A-Za-z0-9_-]*)+)
    |(?P<string>"[^"\n]*"|'[^'\n]*')
    |(?P<operator>\|\&>|\|>|==|[=+\-*/%<>])
    |(?P<number>\d+(?:\.\d+)?)
    |(?P<word>[A-Za-z][A-Za-z0-9_']*)
    |(?P<sentence>[.!?;])
    |(?P<punct>[,:()\[\]{}])
    |(?P<newline>\n)
    |(?P<space>[ \t]+)
    |(?P<unknown>.)
    """,
    re.VERBOSE,
)


def lexical_analysis(source: str, lexicon: TriggerLexicon | None = None) -> tuple[list[Token], list[Diagnostic]]:
    normalized_source = normalize_source(source)
    tokens: list[Token] = []
    diagnostics: list[Diagnostic] = []

    for match in TOKEN_RE.finditer(normalized_source):
        kind = match.lastgroup or "unknown"
        lexeme = match.group(0)
        span = Span(match.start(), match.end())

        if kind == "space":
            continue
        if kind == "word":
            normalized = normalize_word(lexeme, lexicon)
            if normalized in ENGLISH_OPERATORS:
                tokens.append(Token("operator", lexeme, ENGLISH_OPERATORS[normalized], span))
            elif normalized in KEYWORDS:
                tokens.append(Token("keyword", lexeme, normalized, span))
            elif normalized in {"true", "false"}:
                tokens.append(Token("boolean", lexeme, normalized, span))
            else:
                tokens.append(Token("identifier", lexeme, normalized, span))
        elif kind == "operator":
            tokens.append(Token("operator", lexeme, SYMBOL_OPERATORS[lexeme], span))
        elif kind == "compound":
            tokens.append(Token("identifier", lexeme, lexeme.lower(), span))
        elif kind == "string":
            tokens.append(Token("string", lexeme, lexeme[1:-1], span))
        elif kind == "number":
            tokens.append(Token("number", lexeme, lexeme, span))
        elif kind == "sentence":
            tokens.append(Token("sentence_boundary", lexeme, lexeme, span))
        elif kind == "punct":
            token_kind = "delimiter" if lexeme in {"(", ")", "[", "]", "{", "}"} else "punctuator"
            tokens.append(Token(token_kind, lexeme, lexeme, span))
        elif kind == "newline":
            tokens.append(Token("newline", lexeme, "\\n", span))
        elif kind == "comment":
            tokens.append(Token("comment", lexeme, lexeme, span))
        elif kind == "bad_comment":
            diagnostics.append(
                Diagnostic(
                    "error",
                    "SMB1002",
                    "ShipMB Core comments use # only; // is not a comment delimiter.",
                    span,
                    "Replace // comments with # comments, or put literal slashes inside a string.",
                )
            )
            tokens.append(Token("unknown", lexeme, lexeme, span, confidence=0.0))
        else:
            diagnostics.append(
                Diagnostic(
                    "error",
                    "SMB1001",
                    f"Unexpected character {lexeme!r}.",
                    span,
                    "Remove the character or put it inside a string literal.",
                )
            )
            tokens.append(Token("unknown", lexeme, lexeme, span, confidence=0.0))

    return tokens, diagnostics
