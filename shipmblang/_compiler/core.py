from __future__ import annotations

import re

from .source_format import looks_like_core, _strip_hash_comment
from .models import Diagnostic, Span, SyntaxNode
from .normalizer import strip_articles, to_snake_case


def core_lowering(syntax_tree: SyntaxNode) -> str:
    lines: list[str] = []
    needs_shipmb = _needs_shipmb_prelude(syntax_tree)
    if needs_shipmb:
        lines.append("use shipmb")
    for child in syntax_tree.children:
        _append_core_lines(lines, child)
    return "\n".join(dict.fromkeys(lines))


def core_syntax_analysis(source: str) -> tuple[SyntaxNode, list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    children: list[SyntaxNode] = []
    offset = 0
    for raw_line in source.splitlines():
        double_slash_index = _find_double_slash_comment(raw_line)
        if double_slash_index is not None:
            span = Span(offset + double_slash_index, offset + len(raw_line))
            diagnostic = Diagnostic(
                "error",
                "SMB1002",
                "ShipMB Core comments use # only; // is not a comment delimiter.",
                span,
                "Replace // comments with # comments, or put literal slashes inside a string.",
            )
            diagnostics.append(diagnostic)
            children.append(
                SyntaxNode("UnsupportedStatement", span, raw_line[double_slash_index:].strip(), diagnostics=[diagnostic])
            )
            offset += len(raw_line) + 1
            continue

        code_line = _strip_hash_comment(raw_line)
        line = code_line.strip()
        start = offset + raw_line.find(line) if line else offset
        end = start + len(line)
        offset += len(raw_line) + 1
        if not line:
            continue
        node = _parse_core_line(line, Span(start, end))
        diagnostics.extend(node.diagnostics)
        children.append(node)

    root = SyntaxNode(
        "CompilationUnit",
        Span(0, len(source)),
        source.strip(),
        roles={"source_layer": "shipmb-core", "editable": True},
        children=children,
    )
    root.diagnostics.extend(diagnostics)
    return root, diagnostics


def _append_core_lines(lines: list[str], node: SyntaxNode) -> None:
    if node.kind == "StatementSequence":
        for child in node.children:
            _append_core_lines(lines, child)
    elif node.kind == "ImportLibrary":
        purpose = node.roles.get("purpose", "")
        if purpose:
            lines.append(f'library "{node.roles["library"]}" from "{node.roles["source"]}" for "{purpose}"')
            if "roku" in purpose.lower() and "tv" in purpose.lower():
                lines.append('device_target = tv platform "roku" as tv')
            if "remote" in purpose.lower():
                lines.append('remote |> capability "remote_control" agentic')
        else:
            lines.append(f'library "{node.roles["library"]}" from "{node.roles["source"]}"')
    elif node.kind == "CapabilityStatement":
        for capability in node.roles.get("capabilities", []):
            suffix = " agentic" if node.roles.get("agentic") else ""
            lines.append(f'remote |> capability "{capability}"{suffix}')
        if any(child.kind == "ErrorHandler" for child in node.children):
            lines.append("on error:")
            lines.append("  error |> printurf |> show")
        if node.roles.get("run"):
            lines.append(f'run "{node.roles["run"]}"')
    elif node.kind == "ErrorHandler":
        lines.append("on error:")
        lines.append("  error |> printurf |> show")
    elif node.kind == "InstallPackage":
        lines.append(f'install "{node.roles["package"]}" on {node.roles["target"]}')
    elif node.kind == "InterfaceStatement":
        for interface in node.roles.get("interfaces", []):
            lines.append(f'interface "{interface}" mode "{node.roles["mode"]}"')


def _needs_shipmb_prelude(node: SyntaxNode) -> bool:
    if node.kind in {"ImportLibrary", "CapabilityStatement", "ErrorHandler", "InstallPackage", "InterfaceStatement"}:
        return True
    return any(_needs_shipmb_prelude(child) for child in node.children)


# Specific forms first. The generic pipeline is last so Roku lines that already
# matched above are not reclassified, and so `project = open` / `device = family`
# are not treated as plain assignments.
_CORE_DECLARATION_PATTERNS: list[tuple[str | None, re.Pattern[str]]] = [
    ("target_language", re.compile(r'^target language "(?P<language>[^"]+)"$')),
    ("import", re.compile(r'^import "(?P<module>[^"]+)"(?: as (?P<alias>[A-Za-z_][A-Za-z0-9_]*))?$')),
    ("from_import", re.compile(r'^from "(?P<module>[^"]+)" import (?P<symbols>\S.*)$')),
    ("open_project", re.compile(r'^project = open "(?P<target>(?:\\.|[^"\\])*)"$')),
    ("device_family", re.compile(r'^device = family "(?P<family>[^"]+)"$')),
    ("write", re.compile(r'^write (?P<value>[A-Za-z_][A-Za-z0-9_.]*) to "(?P<path>[^"]+)"$')),
    (
        None,
        re.compile(
            r'^(?P<form>let|const) (?P<name>[A-Za-z_][A-Za-z0-9_]*)'
            r'(?:\s*:\s*(?P<type>\S+))?(?:\s*=\s*(?P<value>.+))?$'
        ),
    ),
    ("function", re.compile(r'^fn (?P<name>[A-Za-z_][A-Za-z0-9_]*)\((?P<params>[^)]*)\)(?:\s*->\s*(?P<returns>\S+))?\s*:$')),
    (
        "class",
        re.compile(
            r'^class (?P<name>[A-Za-z_][A-Za-z0-9_]*)'
            r'(?:\s+extends\s+(?P<extends>[A-Za-z_][A-Za-z0-9_]*))?'
            r'(?:\s+implements\s+(?P<implements>[A-Za-z_][A-Za-z0-9_]*(?:\s*,\s*[A-Za-z_][A-Za-z0-9_]*)*))?\s*:$'
        ),
    ),
    ("property", re.compile(r'^property (?P<name>[A-Za-z_][A-Za-z0-9_.]*)(?:\s*:\s*(?P<type>\S+))?(?:\s*=\s*(?P<value>.+))?$')),
    ("method", re.compile(r'^method (?P<name>[A-Za-z_][A-Za-z0-9_.]*)\((?P<params>[^)]*)\)(?:\s*->\s*(?P<returns>\S+))?\s*:$')),
    ("call", re.compile(r'^call (?P<name>[A-Za-z_][A-Za-z0-9_.]*)\((?P<args>[^)]*)\)$')),
    ("call", re.compile(r'^call (?P<name>[A-Za-z_][A-Za-z0-9_.]*) with (?P<args>.+)$')),
    ("if", re.compile(r'^if (?P<condition>.+):\s*$')),
    ("for", re.compile(r'^for (?P<name>[A-Za-z_][A-Za-z0-9_]*) in (?P<source>.+):\s*$')),
    ("device_target", re.compile(r'^(?:device_target|device\s+target)\s*=\s*(?P<body>\S.*)$')),
    ("bridge", re.compile(r'^bridge (?P<left>[A-Za-z_][A-Za-z0-9_.]*) <-> (?P<right>[A-Za-z_][A-Za-z0-9_.]*) using "(?P<protocol>[^"]+)"$')),
    ("capability", re.compile(r'^(?P<target>[A-Za-z_][A-Za-z0-9_]*)\s+\|>\s+capability\s+"(?P<name>[^"]+)"\s+native$')),
    ("resource", re.compile(r'^(?P<target>[A-Za-z_][A-Za-z0-9_]*)\s+\|>\s+resource\s+"(?P<name>[^"]+)"$')),
    ("type", re.compile(r'^type (?P<name>[A-Za-z_][A-Za-z0-9_]*):\s*$')),
    ("field", re.compile(r'^field (?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*(?P<type>\S+)\s*$')),
    ("interface", re.compile(r'^interface (?P<name>[A-Za-z_][A-Za-z0-9_]*):\s*$')),
    ("mode", re.compile(r'^mode "(?P<mode>[^"]+)"$')),
    ("notify_user", re.compile(r'^notify_user (?P<value>true|false)$')),
    ("privacy", re.compile(r'^privacy "(?P<value>[^"]+)"$')),
    ("device", re.compile(r'^device (?P<name>[A-Za-z_][A-Za-z0-9_]*):\s*$')),
    ("interlock", re.compile(r'^interlock (?P<body>.+)$')),
    ("policy", re.compile(r'^policy (?P<body>.+)$')),
    ("capability", re.compile(r'^capability (?P<name>[A-Za-z_][A-Za-z0-9_]*):\s*$')),
    ("provider", re.compile(r'^provider (?P<name>[A-Za-z_][A-Za-z0-9_]*) priority (?P<priority>\d+)(?: native)?$')),
    ("append", re.compile(r'^(?P<name>[A-Za-z_][A-Za-z0-9_.]*) append (?P<value>.+)$')),
    ("assignment", re.compile(r'^(?P<name>[A-Za-z_][A-Za-z0-9_.]*) = (?P<value>.+)$')),
    ("pass", re.compile(r'^pass$')),
    ("return", re.compile(r'^return(?: (?P<value>.+))?$')),
    ("print", re.compile(r'^print (?P<value>.+)$')),
    ("library", re.compile(r'^library "(?P<name>[^"]+)"(?: from "(?P<source>[^"]+)")?(?: for "(?P<purpose>[^"]+)")?$')),
]

_GENERIC_PIPELINE = re.compile(
    r'^(?P<steps>[A-Za-z_][A-Za-z0-9_]*(?:\s+\|>\s+[A-Za-z_][A-Za-z0-9_]*)+)$'
)
# Not a total swallow: prose and junk such as "???" stay unsupported.
_DECLARATION_SHAPED = re.compile(
    r'^[A-Za-z_][A-Za-z0-9_.]*\s*(?:=|\|>|append)\s*\S.*$'
)


def _parse_core_declaration(line: str, span: Span) -> SyntaxNode | None:
    for form, pattern in _CORE_DECLARATION_PATTERNS:
        match = pattern.match(line)
        if match is None:
            continue
        resolved = match.group("form") if form is None else form
        return SyntaxNode("CoreDeclaration", span, line, roles={"form": resolved, "text": line})
    if _GENERIC_PIPELINE.match(line):
        return SyntaxNode("CoreDeclaration", span, line, roles={"form": "pipeline", "text": line})
    if "?" not in line and _DECLARATION_SHAPED.match(line):
        return SyntaxNode("CoreDeclaration", span, line, roles={"form": "declaration", "text": line})
    return None


def _parse_core_line(line: str, span: Span) -> SyntaxNode:
    if line == "use shipmb":
        return SyntaxNode("UsePrelude", span, line, roles={"name": "shipmb"})

    if re.search(r"\[[^\]]*,\s*\]", line):
        return SyntaxNode(
            "UnsupportedStatement",
            span,
            line,
            diagnostics=[
                Diagnostic(
                    "error",
                    "SMB1006",
                    "Inline lists cannot end with a trailing comma.",
                    span,
                    "Remove the comma before the closing bracket.",
                )
            ],
        )

    use_list_match = re.match(r"^use\s+\[(?P<items>[^\]]+)\]$", line)
    if use_list_match:
        children: list[SyntaxNode] = []
        for item in use_list_match.group("items").split(","):
            name = _normalize_reference(item.strip())
            if name == "shipmb":
                children.append(SyntaxNode("UsePrelude", span, item.strip(), roles={"name": "shipmb"}))
            else:
                children.append(
                    SyntaxNode(
                        "UseDeclaration",
                        span,
                        item.strip(),
                        roles={"name": name, "source": None, "declaration_kind": "use"},
                    )
                )
        return SyntaxNode("StatementSequence", span, line, roles={"separator": "inline_list"}, children=children)

    use_match = re.match(
        r"^use\s+(?P<name>[A-Za-z][A-Za-z0-9_./-]*)(?:\s+from\s+(?P<source>.+))?$",
        line,
        re.IGNORECASE,
    )
    if use_match:
        source = use_match.group("source")
        return SyntaxNode(
            "UseDeclaration",
            span,
            line,
            roles={
                "name": _normalize_reference(use_match.group("name")),
                "source": to_snake_case(strip_articles(source)) if source else None,
                "declaration_kind": "use",
            },
        )

    module_access_match = re.match(r"^(?P<name>[A-Za-z][A-Za-z0-9_-]*(?:\.[A-Za-z][A-Za-z0-9_-]*)+)$", line)
    if module_access_match:
        return SyntaxNode(
            "UseDeclaration",
            span,
            line,
            roles={"name": _normalize_reference(module_access_match.group("name")), "source": None, "declaration_kind": "module_access"},
        )

    if line == "architecture |> show":
        return SyntaxNode(
            "ArchitectureDebug",
            span,
            line,
            roles={"instruction": "architecture_show", "compile_time_only": True},
        )

    library_match = re.match(
        r'^library\s+"(?P<library>[^"]+)"\s+from\s+"(?P<source>[^"]+)"(?:\s+for\s+"(?P<purpose>[^"]+)")?$',
        line,
    )
    if library_match:
        return SyntaxNode(
            "ImportLibrary",
            span,
            line,
            roles={
                "operator": "use_library",
                "library": library_match.group("library"),
                "source": library_match.group("source"),
                "purpose": library_match.group("purpose") or "",
                "source_layer": "shipmb-core",
            },
        )

    device_match = re.match(r'^(?:device_target|device\s+target)\s*=\s*(?P<name>\w+)\s+platform\s+"(?P<platform>[^"]+)"\s+as\s+(?P<alias>\w+)$', line)
    if device_match:
        return SyntaxNode(
            "DeviceTarget",
            span,
            line,
            roles={"name": device_match.group("name"), "platform": device_match.group("platform"), "alias": device_match.group("alias")},
        )

    capability_match = re.match(r'^(?P<target>\w+)\s+\|>\s+capability\s+"(?P<capability>[^"]+)"(?P<agentic>\s+agentic)?$', line)
    if capability_match:
        capability = capability_match.group("capability")
        return SyntaxNode(
            "CapabilityStatement",
            span,
            line,
            roles={"target": capability_match.group("target"), "capabilities": [capability], "agentic": bool(capability_match.group("agentic")), "run": None},
            children=[SyntaxNode("CapabilityAction", span, capability, roles={"capability": capability, "target": capability_match.group("target")})],
        )

    if line == "on error:":
        return SyntaxNode("ErrorHandler", span, line, roles={"condition": "command_failure", "handler": "error |> printurf |> show"})

    if line == "error |> printurf |> show":
        return SyntaxNode("CorePipeline", span, line, roles={"pipeline": ["error", "printurf", "show"]})

    run_match = re.match(r'^run\s+"(?P<command>[^"]+)"$', line)
    if run_match:
        return SyntaxNode("RunCommand", span, line, roles={"command": run_match.group("command"), "target": "remote"})

    install_match = re.match(r'^install\s+"(?P<package>[^"]+)"\s+on\s+(?P<target>\w+)$', line)
    if install_match:
        return SyntaxNode("InstallPackage", span, line, roles={"package": install_match.group("package"), "target": install_match.group("target")})

    interface_match = re.match(r'^interface\s+"(?P<name>[^"]+)"\s+mode\s+"(?P<mode>[^"]+)"$', line)
    if interface_match:
        return SyntaxNode("InterfaceStatement", span, line, roles={"interfaces": [interface_match.group("name")], "mode": interface_match.group("mode"), "condition": None})

    mcp_match = re.match(
        r'^mcp\s+"(?P<server>[^"]+)"\s+\|>\s+tool\s+"(?P<tool>[^"]+)"(?:\s+with\s+(?P<arg_name>\w+)\s+"(?P<arg_value>[^"]+)")?$',
        line,
    )
    if mcp_match:
        args = {}
        if mcp_match.group("arg_name"):
            args[mcp_match.group("arg_name")] = mcp_match.group("arg_value")
        return SyntaxNode(
            "MCPToolCall",
            span,
            line,
            roles={
                "server": mcp_match.group("server"),
                "tool": mcp_match.group("tool"),
                "arguments": args,
                "execute_at_compile_time": False,
            },
        )

    declared = _parse_core_declaration(line, span)
    if declared is not None:
        return declared

    return SyntaxNode(
        "UnsupportedStatement",
        span,
        line,
        diagnostics=[
            Diagnostic(
                "error",
                "SMB1005",
                "This shipmb-core line is an unknown or unsupported declaration.",
                span,
                'Use explicit Core syntax such as: library "tv_pack" from "shipmblang".',
            )
        ],
    )


def _find_double_slash_comment(line: str) -> int | None:
    in_quote: str | None = None
    for index, char in enumerate(line[:-1]):
        if char in {'"', "'"}:
            if in_quote == char:
                in_quote = None
            elif in_quote is None:
                in_quote = char
        elif char == "/" and line[index + 1] == "/" and in_quote is None:
            if index == 0 or line[index - 1].isspace():
                return index
    return None


def _normalize_reference(text: str) -> str:
    return ".".join(to_snake_case(part) for part in text.strip().split("."))
