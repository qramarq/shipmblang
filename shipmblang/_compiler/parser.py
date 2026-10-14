from __future__ import annotations

import re

from .diagnostics import printurf
from .models import Diagnostic, Span, SyntaxNode, Token
from .normalizer import compact_spaces, normalize_source, strip_articles, to_snake_case
from .thesaurus import TriggerLexicon, normalize_trigger_text


def syntax_analysis(
    source: str,
    tokens: list[Token],
    lexicon: TriggerLexicon | None = None,
) -> tuple[SyntaxNode, list[Diagnostic]]:
    normalized_source = normalize_source(source)
    statements = _split_statements(normalized_source, tokens)
    diagnostics: list[Diagnostic] = []
    children: list[SyntaxNode] = []

    for surface, span in statements:
        if not surface.strip():
            continue
        node = _parse_statement(surface, span, lexicon)
        diagnostics.extend(node.diagnostics)
        children.append(node)

    unit_span = Span(0, len(normalized_source))
    root = SyntaxNode(
        "CompilationUnit",
        unit_span,
        normalized_source.strip(),
        roles={"yield_matches_source": _unit_yield(children) == compact_spaces(normalized_source.strip())},
        children=children,
    )
    root.diagnostics.extend(diagnostics)
    return root, diagnostics


def explain_syntax_errors(tree: SyntaxNode, source: str) -> list[str]:
    seen = set()
    explanations: list[str] = []
    for diagnostic in _walk_diagnostics(tree):
        key = (diagnostic.code, diagnostic.span.start, diagnostic.span.end, diagnostic.message)
        if key in seen:
            continue
        seen.add(key)
        explanations.append(printurf(diagnostic, source))
    return explanations


def _walk_diagnostics(node: SyntaxNode) -> list[Diagnostic]:
    diagnostics = list(node.diagnostics)
    for child in node.children:
        diagnostics.extend(_walk_diagnostics(child))
    return diagnostics


def _unit_yield(children: list[SyntaxNode]) -> str:
    return compact_spaces(" ".join(child.surface_text for child in children))


def _split_statements(source: str, tokens: list[Token]) -> list[tuple[str, Span]]:
    statements: list[tuple[str, Span]] = []
    start: int | None = None
    last_end = 0

    for token in tokens:
        if token.kind in {"comment", "newline"}:
            continue
        if start is None:
            start = token.span.start
        last_end = token.span.end
        if token.kind == "sentence_boundary":
            end = token.span.end
            statements.append((source[start:end], Span(start, end)))
            start = None

    if start is not None and last_end > start:
        statements.append((source[start:last_end], Span(start, last_end)))
    return statements


def _parse_statement(surface_text: str, span: Span, lexicon: TriggerLexicon | None = None) -> SyntaxNode:
    sentence = surface_text.strip()
    body = sentence.rstrip(".!?;").strip()
    normalized = compact_spaces(normalize_trigger_text(body, lexicon))

    return (
        _parse_sequence(normalized, normalized, span, sentence)
        or
        _parse_library_use(normalized, normalized, span, sentence)
        or _parse_capability_sentence(body, normalized, span, sentence)
        or _parse_error_handler(body, normalized, span, sentence)
        or _parse_install(normalized, normalized, span, sentence)
        or _parse_interfaces(normalized, normalized, span, sentence)
        or _unsupported(sentence, span)
    )


def _parse_sequence(body: str, normalized: str, span: Span, sentence: str) -> SyntaxNode | None:
    match = re.match(r"^(?P<install>install\s+.+?\s+on\s+.+?)\s+and\s+(?P<rest>give\s+me\s+.+)$", body, re.IGNORECASE)
    if not match:
        return None

    install_text = match.group("install")
    rest_text = match.group("rest")
    install_start = span.start
    install_end = span.start + match.end("install")
    rest_start = span.start + match.start("rest")
    rest_end = span.start + match.end("rest")
    install_node = _parse_install(install_text, compact_spaces(install_text.lower()), Span(install_start, install_end), install_text)
    interface_node = _parse_interfaces(rest_text, compact_spaces(rest_text.lower()), Span(rest_start, rest_end), rest_text)
    if install_node is None or interface_node is None:
        return None
    return SyntaxNode(
        "StatementSequence",
        span,
        sentence,
        roles={"separator": "and", "yield_matches_source": True},
        children=[install_node, interface_node],
    )


def _parse_library_use(body: str, normalized: str, span: Span, sentence: str) -> SyntaxNode | None:
    pattern = re.compile(
        r"^(?:let(?:'s| us)?\s+)?use\s+(?:the\s+)?(?P<library>[a-zA-Z0-9 _-]+?)\s+library\s+"
        r"(?P<source_keyword>from|in)\s+(?P<source>[a-zA-Z0-9_-]+)"
        r"(?:\s+to\s+(?P<purpose>.+))?$",
        re.IGNORECASE,
    )
    match = pattern.match(body)
    if not match:
        return None

    library = compact_spaces(match.group("library"))
    source = match.group("source")
    purpose = compact_spaces(match.group("purpose") or "")
    roles = {
        "operator": "use_library",
        "library": to_snake_case(library),
        "source": source.lower(),
        "source_keyword": match.group("source_keyword").lower(),
        "purpose": purpose,
    }
    children = [
        SyntaxNode("Identifier", span, library, roles={"name": to_snake_case(library)}),
        SyntaxNode("Identifier", span, source, roles={"name": source.lower()}),
    ]
    if purpose:
        children.append(SyntaxNode("PurposeClause", span, purpose, roles=_purpose_roles(purpose)))

    return SyntaxNode("ImportLibrary", span, sentence, roles=roles, children=children)


def _purpose_roles(purpose: str) -> dict[str, str]:
    lowered = purpose.lower()
    roles: dict[str, str] = {"text": purpose}
    if "roku" in lowered and "tv" in lowered:
        roles["device"] = "tv"
        roles["platform"] = "roku"
    if "remote" in lowered:
        roles["capability"] = "remote_control"
    return roles


def _parse_capability_sentence(body: str, normalized: str, span: Span, sentence: str) -> SyntaxNode | None:
    actions: list[str] = []
    if re.search(r"\bsearch\b", normalized):
        actions.append("search_apps")
    if re.search(r"\bopen\b", normalized):
        actions.append("open_app")
    if re.search(r"\bclose\b", normalized):
        actions.append("close_app")
    if re.search(r"\b(call|use)\b.*\bresources?\b", normalized):
        actions.append("list_resources")
    if re.search(r"\bexecute\b.*\bcommands?\b", normalized):
        actions.append("execute_command")
    if re.search(r"\bcontrol\b.*\bremote\b", normalized):
        actions.append("remote_control")

    is_capability_sentence = bool(actions) and (
        "app" in normalized
        or "resource" in normalized
        or "command" in normalized
        or "remote" in normalized
        or "control" in normalized
    )
    if not is_capability_sentence:
        return None

    diagnostics: list[Diagnostic] = []
    children = [
        SyntaxNode("CapabilityAction", span, action, roles={"capability": action, "target": "remote"})
        for action in dict.fromkeys(actions)
    ]

    if "error" in normalized and "show" in normalized:
        children.append(
            SyntaxNode(
                "ErrorHandler",
                span,
                "show errors",
                roles={"condition": "command_failure", "handler": "error |> printurf |> show"},
            )
        )

    return SyntaxNode(
        "CapabilityStatement",
        span,
        sentence,
        roles={
            "target": "remote",
            "capabilities": list(dict.fromkeys(actions)),
            "agentic": bool(re.search(r"\bagentical+ly\b", normalized)),
            "run": "commands" if "execute" in normalized and "command" in normalized else None,
        },
        children=children,
        diagnostics=diagnostics,
    )


def _parse_error_handler(body: str, normalized: str, span: Span, sentence: str) -> SyntaxNode | None:
    if not normalized.startswith("when ") or not re.search(r"\bfails?\b", normalized):
        return None
    if "show" not in normalized or "error" not in normalized:
        return SyntaxNode(
            "ErrorHandler",
            span,
            sentence,
            roles={"condition": "failure"},
            diagnostics=[
                Diagnostic(
                    "error",
                    "SMB1004",
                    "This failure handler does not say what to do with the error.",
                    span,
                    "Use a phrase like 'When commands fail, show the error.'",
                )
            ],
        )
    return SyntaxNode(
        "ErrorHandler",
        span,
        sentence,
        roles={"condition": "command_failure", "handler": "error |> printurf |> show"},
    )


def _parse_install(body: str, normalized: str, span: Span, sentence: str) -> SyntaxNode | None:
    match = re.match(r"^install\s+(?P<package>[a-zA-Z0-9_-]+)\s+on\s+(?P<target>.+)$", body, re.IGNORECASE)
    if not match:
        return None
    target = to_snake_case(strip_articles(match.group("target")))
    if target == "":
        target = "tv"
    return SyntaxNode(
        "InstallPackage",
        span,
        sentence,
        roles={"package": match.group("package").lower(), "target": target},
    )


def _parse_interfaces(body: str, normalized: str, span: Span, sentence: str) -> SyntaxNode | None:
    if not normalized.startswith("give me ") or "access" not in normalized:
        return None

    interfaces: list[str] = []
    if "voice" in normalized:
        interfaces.append("voice")
    if "chat bot" in normalized or "chatbot" in normalized:
        interfaces.append("chat_bot")

    if not interfaces:
        return None

    return SyntaxNode(
        "InterfaceStatement",
        span,
        sentence,
        roles={"interfaces": interfaces, "mode": "client", "condition": "if_able" if "if able" in normalized else None},
    )


def _unsupported(sentence: str, span: Span) -> SyntaxNode:
    return SyntaxNode(
        "UnsupportedStatement",
        span,
        sentence,
        diagnostics=[
            Diagnostic(
                "error",
                "SMB1003",
                "This prose does not match a supported ShipMBLang sentence pattern.",
                span,
                "Try an explicit form such as 'Use the tv pack library from shipmblang.'",
            )
        ],
    )
