"""Natural sentence compiler for ShipMBLang programs.

This module intentionally starts small: it lowers ordinary sentences into a
stable ShipMBLangCore form and a JSON-friendly instruction list that future
runners can execute.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from .device_families import (
    find_device_family_keyword,
    find_device_resource_keyword,
    require_device_family,
    require_device_resource,
)
from .error_explainer import build_printurf_report, collect_code_context, render_printurf_report
from .project_context import build_codebase_index


DEFAULT_ROOT = "."

LANGUAGE_ALIASES = {
    "python": "python",
    "py": "python",
    "javascript": "javascript",
    "java script": "javascript",
    "js": "javascript",
    "typescript": "typescript",
    "type script": "typescript",
    "ts": "typescript",
    "java": "java",
    "c sharp": "csharp",
    "c#": "csharp",
    "csharp": "csharp",
    "c plus plus": "cpp",
    "c++": "cpp",
    "cpp": "cpp",
    "c": "c",
    "go": "go",
    "golang": "go",
    "rust": "rust",
    "ruby": "ruby",
    "php": "php",
    "swift": "swift",
    "kotlin": "kotlin",
    "scala": "scala",
    "r": "r",
    "sql": "sql",
    "shell": "shell",
    "bash": "shell",
}

LANGUAGE_DISPLAY_NAMES = {
    "python": "Python",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "java": "Java",
    "csharp": "C#",
    "cpp": "C++",
    "c": "C",
    "go": "Go",
    "rust": "Rust",
    "ruby": "Ruby",
    "php": "PHP",
    "swift": "Swift",
    "kotlin": "Kotlin",
    "scala": "Scala",
    "r": "R",
    "sql": "SQL",
    "shell": "Shell",
}

ENGLISH_COMPILER_KEYWORDS = {
    "use",
    "import",
    "include",
    "require",
    "load",
    "library",
    "package",
    "module",
    "install",
    "declare",
    "create",
    "define",
    "make",
    "set",
    "target",
    "control",
    "device",
    "resource",
    "resources",
    "capability",
    "capabilities",
    "remote",
    "controller",
    "tv",
    "roku",
    "app",
    "apps",
    "search",
    "close",
    "command",
    "commands",
    "voice",
    "chat",
    "bot",
    "access",
    "error",
    "errors",
    "function",
    "method",
    "class",
    "property",
    "variable",
    "constant",
    "const",
    "let",
    "var",
    "takes",
    "accepts",
    "receives",
    "with",
    "has",
    "extends",
    "implements",
    "inherits",
    "does",
    "print",
    "prints",
    "return",
    "returns",
    "equal",
    "equals",
    "plus",
    "call",
    "invoke",
    "if",
    "then",
    "when",
    "for",
    "each",
    "loop",
    "in",
    "show",
    "display",
    "write",
    "save",
    "export",
    "run",
    "execute",
    "open",
    "scan",
    "index",
    "explain",
    "debug",
    "fix",
    "suggest",
}

TOKEN_PATTERN = re.compile(
    r"(?P<string>\"[^\"]*\"|'[^']*')"
    r"|(?P<number>\b\d+(?:\.\d+)?\b)"
    r"|(?P<identifier>\b[A-Za-z_][A-Za-z0-9_#:+./-]*\b)"
    r"|(?P<sentence>[.!?;])"
    r"|(?P<symbol>[(),:=<>[\]{}])"
    r"|(?P<other>\S)",
)


def compile_natural_program(text: str, *, root: str | None = None) -> dict[str, Any]:
    """Compile natural sentences through the ShipMBLang compiler pipeline."""
    source = text.strip()
    tokens = lexical_analysis(source)
    syntax_tree = syntax_analysis(source, tokens)
    semantic_model = semantic_analysis(syntax_tree, root=root)
    intermediate_code = intermediate_code_generation(semantic_model)
    optimized_intermediate_code = code_optimization(intermediate_code, root=root)
    target_code = target_code_generation(optimized_intermediate_code)
    ops = target_code["bytecode"]
    return {
        "source": source,
        "tokens": tokens,
        "syntax_tree": syntax_tree,
        "semantic_model": semantic_model,
        "intermediate_code": intermediate_code,
        "optimized_intermediate_code": optimized_intermediate_code,
        "target_code": target_code,
        "core": render_core_program(ops),
        "bytecode": ops,
    }


def lexical_analysis(source: str) -> list[dict[str, Any]]:
    """Tokenize English prose while preserving enough source position for tooling."""
    tokens: list[dict[str, Any]] = []
    for match in TOKEN_PATTERN.finditer(source):
        kind = match.lastgroup or "other"
        value = match.group(0)
        normalized = value.lower().strip("\"'")
        token_type = kind
        if kind == "identifier":
            token_type = "keyword" if normalized in ENGLISH_COMPILER_KEYWORDS else "identifier"
        elif kind == "sentence":
            token_type = "sentence_boundary"
        tokens.append(
            {
                "type": token_type,
                "value": value,
                "normalized": normalized,
                "start": match.start(),
                "end": match.end(),
            }
        )
    return tokens


def syntax_analysis(source: str, tokens: list[dict[str, Any]]) -> dict[str, Any]:
    """Group tokens into sentence-level syntax nodes for the English compiler."""
    statements = _split_statements(source)
    nodes: list[dict[str, Any]] = []
    cursor = 0
    for index, statement in enumerate(statements):
        start = source.find(statement, cursor)
        if start < 0:
            start = cursor
        end = start + len(statement)
        cursor = end
        statement_tokens = [token for token in tokens if start <= token["start"] < end]
        nodes.append(
            {
                "type": "statement",
                "index": index,
                "text": statement,
                "span": {"start": start, "end": end},
                "role": _classify_statement(statement),
                "tokens": [token["value"] for token in statement_tokens],
            }
        )
    return {"type": "program", "language": "english", "statements": nodes}


def semantic_analysis(syntax_tree: dict[str, Any], *, root: str | None = None) -> dict[str, Any]:
    """Resolve statement meaning into symbols, diagnostics, and preliminary ops."""
    ops: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    symbols = _new_symbol_table()

    for statement in syntax_tree.get("statements", []):
        statement_ops = _compile_statement(statement["text"], root=root)
        if len(statement_ops) == 1 and statement_ops[0].get("op") == "intent":
            diagnostics.append(
                {
                    "level": "info",
                    "statement": statement["index"],
                    "message": "Statement preserved as intent because no executable English syntax pattern matched.",
                }
            )
        ops.extend(statement_ops)

    # ShipMBLangCore declaration resolution is order-insensitive inside a
    # compilation unit: collect every declaration before resolving references.
    for op in ops:
        _record_semantic_symbol(symbols, op)
    declaration_resolution = _resolve_declaration_references(ops, symbols)

    return {
        "symbols": symbols,
        "declaration_resolution": declaration_resolution,
        "diagnostics": diagnostics,
        "unresolved_intents": [op["text"] for op in ops if op.get("op") == "intent"],
        "ops": ops,
    }


def intermediate_code_generation(semantic_model: dict[str, Any]) -> list[dict[str, Any]]:
    """Lower semantic operations into ShipMBLang intermediate instructions."""
    ir: list[dict[str, Any]] = []
    for index, op in enumerate(semantic_model.get("ops", [])):
        instruction = {"ir": f"i{index:04d}", **op}
        ir.append(instruction)
    return ir


def code_optimization(intermediate_code: list[dict[str, Any]], *, root: str | None = None) -> list[dict[str, Any]]:
    """Normalize and lightly optimize intermediate instructions before codegen."""
    ops = [{key: value for key, value in instruction.items() if key != "ir"} for instruction in intermediate_code]
    normalized_ops = _dedupe_ops(_normalize_ops(ops, root=root))
    optimized: list[dict[str, Any]] = []
    for index, op in enumerate(normalized_ops):
        optimized.append({"ir": f"o{index:04d}", **op})
    return optimized


def target_code_generation(optimized_intermediate_code: list[dict[str, Any]]) -> dict[str, Any]:
    """Emit the v0.1 target code: executable ShipMBLang runtime bytecode."""
    bytecode = [
        {key: value for key, value in instruction.items() if key != "ir"}
        for instruction in optimized_intermediate_code
    ]
    return {
        "target": "shipmblang-bytecode",
        "native_machine_code": False,
        "bytecode": bytecode,
    }


def run_natural_program(
    text: str,
    *,
    root: str | None = None,
    raw_error: str = "",
    paths: list[str] | tuple[str, ...] = (),
    code_context: str = "",
    line: int | None = None,
    max_files: int = 80,
) -> dict[str, Any]:
    """Compile and execute the currently supported ShipMBLang bytecode ops."""
    program = compile_natural_program(text, root=root)
    state: dict[str, Any] = {
        "root": str(Path(root or DEFAULT_ROOT).resolve()),
        "project": None,
        "report": None,
        "output": [],
        "writes": [],
        "events": [],
        "runs": [],
        "device_family": None,
        "device_resources": [],
        "libraries": [],
        "device_target": None,
        "device_capabilities": [],
        "installs": [],
        "interfaces": [],
        "language": None,
        "imports": [],
        "variables": {},
        "constants": {},
        "functions": {},
        "classes": {},
        "calls": [],
        "returns": [],
        "conditions": [],
        "loops": [],
    }

    for op in program["bytecode"]:
        code = op["op"]
        if code == "use":
            state["module"] = op["module"]
        elif code == "open_project":
            state["root"] = str(Path(op.get("target") or root or DEFAULT_ROOT).resolve())
        elif code == "index_project":
            state["project"] = build_codebase_index(Path(state["root"]), max_files=max_files)
        elif code == "on_error":
            state["events"].append("error")
        elif code == "printurf":
            target_paths = list(paths)
            if not target_paths and state.get("project"):
                target_paths = [state["root"]]
            context = code_context
            report = build_printurf_report(
                raw_error=raw_error,
                code_context=context,
                paths=target_paths,
                root=state["root"],
                line=line,
                engine=None,
                max_files=max_files,
            )
            state["report"] = report
        elif code == "suggest_fix":
            if state.get("report") is None:
                state["report"] = build_printurf_report(raw_error=raw_error, code_context=code_context, root=state["root"], line=line)
        elif code == "show":
            state["output"].append(_render_state_value(state, op.get("value", "report")))
        elif code == "write":
            text_value = _render_state_value(state, op.get("value", "report"))
            target = _safe_output_path(op.get("target") or "shipmb-output.json", state["root"])
            target.write_text(text_value + "\n", encoding="utf-8")
            state["writes"].append(str(target))
        elif code == "run":
            state["runs"].append(
                {
                    "target": op.get("target") or "program",
                    "status": "planned",
                    "reason": "ShipMBLang runtime recorded this run instruction; native command execution is not enabled yet.",
                }
            )
        elif code == "use_device_family":
            state["device_family"] = require_device_family(op.get("family"))
        elif code == "use_device_resource":
            family_name = op.get("family")
            if family_name is None and state.get("device_family"):
                family_name = state["device_family"]["name"]
            if family_name is None:
                family_name = "host"
                state["device_family"] = require_device_family(family_name)
            state["device_resources"].append(require_device_resource(family_name, op.get("resource")))
        elif code == "use_library":
            state["libraries"].append(
                {
                    "name": op.get("name"),
                    "namespace": op.get("namespace"),
                    "purpose": op.get("purpose"),
                }
            )
        elif code == "target_device":
            state["device_target"] = {
                "kind": op.get("kind"),
                "platform": op.get("platform"),
                "alias": op.get("alias"),
            }
        elif code == "use_capability":
            state["device_capabilities"].append(
                {
                    "name": op.get("name"),
                    "target": op.get("target"),
                    "agentic": bool(op.get("agentic")),
                }
            )
        elif code == "install_runtime":
            state["installs"].append({"runtime": op.get("runtime"), "target": op.get("target")})
        elif code == "enable_interface":
            state["interfaces"].append({"name": op.get("name"), "mode": op.get("mode", "client")})
        elif code == "target_language":
            state["language"] = op.get("language")
        elif code == "import":
            state["imports"].append(
                {
                    "module": op.get("module"),
                    "symbols": op.get("symbols", []),
                    "kind": op.get("kind", "import"),
                    "alias": op.get("alias"),
                }
            )
        elif code == "declare_variable":
            target = state["constants"] if op.get("constant") else state["variables"]
            target[op["name"]] = {
                "type": op.get("type"),
                "value": op.get("value"),
                "constant": bool(op.get("constant")),
            }
        elif code == "define_function":
            state["functions"][op["name"]] = {
                "parameters": op.get("parameters", []),
                "returns": op.get("returns"),
                "body": op.get("body", []),
            }
        elif code == "define_class":
            class_model = state["classes"].setdefault(
                op["name"],
                {"extends": None, "implements": [], "properties": [], "methods": []},
            )
            if op.get("extends"):
                class_model["extends"] = op.get("extends")
            _merge_unique(class_model["implements"], op.get("implements", []))
        elif code == "define_property":
            class_name = op.get("class")
            if class_name:
                class_model = state["classes"].setdefault(
                    class_name,
                    {"extends": None, "implements": [], "properties": [], "methods": []},
                )
                if not any(property_model.get("name") == op["name"] for property_model in class_model["properties"]):
                    class_model["properties"].append(
                        {"name": op["name"], "type": op.get("type"), "value": op.get("value")}
                    )
            else:
                state["variables"][op["name"]] = {"type": op.get("type"), "value": op.get("value"), "property": True}
        elif code == "define_method":
            class_name = op.get("class")
            method = {
                "name": op["name"],
                "parameters": op.get("parameters", []),
                "returns": op.get("returns"),
                "body": op.get("body", []),
            }
            if class_name:
                class_model = state["classes"].setdefault(
                    class_name,
                    {"extends": None, "implements": [], "properties": [], "methods": []},
                )
                if not any(method_model.get("name") == op["name"] for method_model in class_model["methods"]):
                    class_model["methods"].append(method)
            else:
                state["functions"][op["name"]] = method
        elif code == "return":
            state["returns"].append(op.get("value"))
        elif code == "call":
            state["calls"].append({"target": op.get("target"), "arguments": op.get("arguments", [])})
        elif code == "condition":
            state["conditions"].append({"condition": op.get("condition"), "action": op.get("action")})
        elif code == "loop":
            state["loops"].append({"iterator": op.get("iterator"), "source": op.get("source"), "action": op.get("action")})
        elif code == "intent":
            state["output"].append(f"Intent: {op['text']}")

    return {
        "program": program,
        "state": state,
        "output": "\n\n".join(part for part in state["output"] if part),
    }


def render_core_program(ops: list[dict[str, Any]]) -> str:
    """Render bytecode ops as the small functional ShipMBLangCore syntax."""
    lines: list[str] = []
    in_error_block = False
    pipe: list[str] = []

    def flush_pipe() -> None:
        nonlocal pipe
        if pipe:
            prefix = "  " if in_error_block else ""
            lines.append(prefix + " |> ".join(pipe))
            pipe = []

    for op in ops:
        code = op["op"]
        if code == "use":
            flush_pipe()
            lines.append(f"use {op['module']}")
        elif code == "open_project":
            flush_pipe()
            target = _quote(op.get("target") or DEFAULT_ROOT)
            lines.append(f"project = open {target}")
        elif code == "index_project":
            flush_pipe()
            lines.append("project |> index")
        elif code == "on_error":
            flush_pipe()
            lines.append("on error:")
            in_error_block = True
        elif code == "printurf":
            if not pipe:
                pipe.append("error")
            pipe.append("printurf")
        elif code == "suggest_fix":
            if not pipe:
                pipe.append("report")
            pipe.append("suggest_fix")
        elif code == "show":
            if not pipe:
                pipe.append(op.get("value", "report"))
            pipe.append("show")
            flush_pipe()
        elif code == "write":
            flush_pipe()
            value = op.get("value", "report")
            target = _quote(op.get("target") or "shipmb-output.json")
            prefix = "  " if in_error_block else ""
            lines.append(f"{prefix}write {value} to {target}")
        elif code == "run":
            flush_pipe()
            target = _quote(op.get("target") or "")
            lines.append(f"run {target}")
        elif code == "use_device_family":
            flush_pipe()
            family = _quote(op.get("family") or "host")
            lines.append(f"device = family {family}")
        elif code == "use_device_resource":
            if not pipe:
                pipe.append("device")
            pipe.append(f"resource {_quote(op.get('resource') or '')}")
            flush_pipe()
        elif code == "use_library":
            flush_pipe()
            line = f"library {_quote(op.get('name') or '')}"
            if op.get("namespace"):
                line += f" from {_quote(op['namespace'])}"
            if op.get("purpose"):
                line += f" for {_quote(op['purpose'])}"
            lines.append(line)
        elif code == "target_device":
            flush_pipe()
            kind = op.get("kind") or "device"
            platform = op.get("platform")
            alias = op.get("alias")
            line = f"device_target = {kind}"
            if platform:
                line += f" platform {_quote(platform)}"
            if alias:
                line += f" as {alias}"
            lines.append(line)
        elif code == "use_capability":
            flush_pipe()
            target = op.get("target") or "device"
            suffix = " agentic" if op.get("agentic") else ""
            lines.append(f"{target} |> capability {_quote(op.get('name') or '')}{suffix}")
        elif code == "install_runtime":
            flush_pipe()
            lines.append(f"install {_quote(op.get('runtime') or 'runtime')} on {op.get('target') or 'device'}")
        elif code == "enable_interface":
            flush_pipe()
            lines.append(f"interface {_quote(op.get('name') or '')} mode {_quote(op.get('mode') or 'client')}")
        elif code == "target_language":
            flush_pipe()
            language = op.get("language") or "language"
            lines.append(f"target language {_quote(language)}")
        elif code == "import":
            flush_pipe()
            module = _quote(op.get("module") or "")
            symbols = op.get("symbols") or []
            alias = op.get("alias")
            if symbols:
                rendered_symbols = ", ".join(symbols)
                line = f"from {module} import {rendered_symbols}"
            else:
                line = f"import {module}"
            if alias:
                line += f" as {alias}"
            lines.append(line)
        elif code == "declare_variable":
            flush_pipe()
            keyword = "const" if op.get("constant") else "let"
            name = op["name"]
            type_name = op.get("type")
            value = op.get("value")
            line = f"{keyword} {name}"
            if type_name:
                line += f": {type_name}"
            if value is not None:
                line += f" = {value}"
            lines.append(line)
        elif code == "define_function":
            flush_pipe()
            params = ", ".join(op.get("parameters") or [])
            returns = f" -> {op['returns']}" if op.get("returns") else ""
            lines.append(f"fn {op['name']}({params}){returns}:")
            for body_line in op.get("body") or ["pass"]:
                lines.append(f"  {body_line}")
        elif code == "define_class":
            flush_pipe()
            suffix_parts = []
            if op.get("extends"):
                suffix_parts.append(f"extends {op['extends']}")
            if op.get("implements"):
                suffix_parts.append("implements " + ", ".join(op["implements"]))
            suffix = " " + " ".join(suffix_parts) if suffix_parts else ""
            lines.append(f"class {op['name']}{suffix}:")
        elif code == "define_property":
            flush_pipe()
            owner = f"{op['class']}." if op.get("class") else ""
            type_name = f": {op['type']}" if op.get("type") else ""
            value = f" = {op['value']}" if op.get("value") is not None else ""
            lines.append(f"property {owner}{op['name']}{type_name}{value}")
        elif code == "define_method":
            flush_pipe()
            owner = f"{op['class']}." if op.get("class") else ""
            params = ", ".join(op.get("parameters") or [])
            returns = f" -> {op['returns']}" if op.get("returns") else ""
            lines.append(f"method {owner}{op['name']}({params}){returns}:")
            for body_line in op.get("body") or ["pass"]:
                lines.append(f"  {body_line}")
        elif code == "return":
            flush_pipe()
            lines.append(f"return {op.get('value') or ''}".rstrip())
        elif code == "call":
            flush_pipe()
            args = ", ".join(op.get("arguments") or [])
            lines.append(f"call {op.get('target') or 'function'}({args})")
        elif code == "condition":
            flush_pipe()
            lines.append(f"if {op.get('condition') or 'condition'}:")
            if op.get("action"):
                lines.append(f"  {op['action']}")
        elif code == "loop":
            flush_pipe()
            iterator = op.get("iterator") or "item"
            source = op.get("source") or "items"
            lines.append(f"for {iterator} in {source}:")
            if op.get("action"):
                lines.append(f"  {op['action']}")
        elif code == "intent":
            flush_pipe()
            lines.append(f"# intent: {op['text']}")

    flush_pipe()
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile natural ShipMBLang sentences into executable core syntax.")
    parser.add_argument("text", nargs="*", help="Sentence or paragraph to compile.")
    parser.add_argument("--file", help="Read natural ShipMBLang from a text file.")
    parser.add_argument("--root", help="Default project root for open/index instructions.")
    parser.add_argument("--format", choices=["core", "json"], default="core")
    args = parser.parse_args()

    if args.file:
        text = Path(args.file).read_text(encoding="utf-8", errors="replace")
    else:
        text = " ".join(args.text)

    program = compile_natural_program(text, root=args.root)
    if args.format == "json":
        print(json.dumps(program, indent=2))
        return
    print(program["core"])


def run_main() -> None:
    parser = argparse.ArgumentParser(description="Run natural ShipMBLang sentences through the local ShipMBLang runtime.")
    parser.add_argument("text", nargs="*", help="Sentence or paragraph to run.")
    parser.add_argument("--file", help="Read natural ShipMBLang from a text file.")
    parser.add_argument("--root", help="Default project root for open/index instructions.")
    parser.add_argument("--error", help="Raw error or traceback text for printurf.")
    parser.add_argument("--error-file", help="File containing the raw error or traceback.")
    parser.add_argument("--context-file", action="append", default=[], help="Source file to include as context.")
    parser.add_argument("--line", type=int, help="1-based line number for the failing code.")
    parser.add_argument("--max-files", type=int, default=80)
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--path", action="append", default=[], help="File or directory for printurf to inspect/index.")
    args = parser.parse_args()

    if args.file:
        text = Path(args.file).read_text(encoding="utf-8", errors="replace")
    else:
        text = " ".join(args.text)

    raw_error = args.error or ""
    if args.error_file:
        raw_error = Path(args.error_file).read_text(encoding="utf-8", errors="replace")
    code_context = collect_code_context(args.context_file) if args.context_file else ""
    result = run_natural_program(
        text,
        root=args.root,
        raw_error=raw_error,
        paths=args.path,
        code_context=code_context,
        line=args.line,
        max_files=args.max_files,
    )
    if args.format == "json":
        print(json.dumps(result, indent=2))
        return

    if result["output"]:
        print(result["output"])
        return
    print(result["program"]["core"])


def _classify_statement(statement: str) -> str:
    normalized = _normalize_text(statement)
    checks = [
        ("target_language", _extract_target_language(normalized) is not None),
        ("library", _extract_library_use(statement) is not None),
        ("device", _extract_target_device(statement) is not None),
        ("capability", bool(_extract_capabilities(statement))),
        ("install", _extract_install_runtime(statement) is not None),
        ("interface", bool(_extract_client_interfaces(statement))),
        ("import", _extract_import(statement) is not None),
        ("class", _extract_class(statement) is not None),
        ("method", _extract_method(statement) is not None),
        ("property", _extract_property(statement) is not None),
        ("function", _extract_function(statement) is not None),
        ("variable", _extract_variable(statement) is not None),
        ("loop", _extract_loop(statement) is not None),
        ("condition", _extract_condition(statement) is not None),
        ("return", _extract_return(statement) is not None),
        ("call", _extract_call(statement) is not None),
        ("device_family", _extract_device_family(statement) is not None or _extract_device_resource(statement) is not None),
        ("project", _mentions_open_project(normalized) or _mentions_index(normalized)),
        ("error_handler", _mentions_error_event(normalized) or "printurf" in normalized),
        ("runtime_output", _extract_show_value(statement) is not None),
        ("run", _mentions_run(normalized)),
    ]
    for role, matched in checks:
        if matched:
            return role
    return "intent"


def _new_symbol_table() -> dict[str, Any]:
    return {
        "languages": [],
        "imports": [],
        "libraries": [],
        "devices": [],
        "capabilities": [],
        "installs": [],
        "interfaces": [],
        "variables": {},
        "constants": {},
        "functions": {},
        "classes": {},
    }


def _record_semantic_symbol(symbols: dict[str, Any], op: dict[str, Any]) -> None:
    code = op.get("op")
    if code == "target_language":
        language = op.get("language")
        if language and language not in symbols["languages"]:
            symbols["languages"].append(language)
    elif code == "use_library":
        symbols["libraries"].append(
            {"name": op.get("name"), "namespace": op.get("namespace"), "purpose": op.get("purpose")}
        )
    elif code == "target_device":
        symbols["devices"].append({"kind": op.get("kind"), "platform": op.get("platform"), "alias": op.get("alias")})
    elif code == "use_capability":
        symbols["capabilities"].append(
            {"name": op.get("name"), "target": op.get("target"), "agentic": bool(op.get("agentic"))}
        )
    elif code == "install_runtime":
        symbols["installs"].append({"runtime": op.get("runtime"), "target": op.get("target")})
    elif code == "enable_interface":
        symbols["interfaces"].append({"name": op.get("name"), "mode": op.get("mode", "client")})
    elif code == "import":
        symbols["imports"].append(
            {
                "module": op.get("module"),
                "symbols": op.get("symbols", []),
                "kind": op.get("kind", "import"),
                "alias": op.get("alias"),
            }
        )
    elif code == "declare_variable":
        bucket = symbols["constants"] if op.get("constant") else symbols["variables"]
        bucket[op["name"]] = {"type": op.get("type"), "value": op.get("value")}
    elif code == "define_function":
        symbols["functions"][op["name"]] = {
            "parameters": op.get("parameters", []),
            "returns": op.get("returns"),
        }
    elif code == "define_class":
        class_symbol = _ensure_class_symbol(symbols, op["name"])
        if op.get("extends"):
            class_symbol["extends"] = op.get("extends")
        _merge_unique(class_symbol["implements"], op.get("implements", []))
    elif code == "define_property":
        class_name = op.get("class")
        if class_name:
            class_symbol = _ensure_class_symbol(symbols, class_name)
            if op["name"] not in class_symbol["properties"]:
                class_symbol["properties"].append(op["name"])
    elif code == "define_method":
        class_name = op.get("class")
        if class_name:
            class_symbol = _ensure_class_symbol(symbols, class_name)
            if op["name"] not in class_symbol["methods"]:
                class_symbol["methods"].append(op["name"])
        else:
            symbols["functions"][op["name"]] = {
                "parameters": op.get("parameters", []),
                "returns": op.get("returns"),
            }


def _ensure_class_symbol(symbols: dict[str, Any], class_name: str) -> dict[str, Any]:
    return symbols["classes"].setdefault(
        class_name,
        {"extends": None, "implements": [], "properties": [], "methods": []},
    )


def _merge_unique(target: list[Any], values: list[Any]) -> None:
    for value in values:
        if value not in target:
            target.append(value)


def _resolve_declaration_references(ops: list[dict[str, Any]], symbols: dict[str, Any]) -> dict[str, Any]:
    declared_classes = {op["name"] for op in ops if op.get("op") == "define_class"}
    declared_functions = set(symbols["functions"])
    declared_variables = set(symbols["variables"]) | set(symbols["constants"])
    declared_properties = {
        (class_name, property_name)
        for class_name, class_symbol in symbols["classes"].items()
        for property_name in class_symbol.get("properties", [])
    }
    declared_methods = {
        (class_name, method_name)
        for class_name, class_symbol in symbols["classes"].items()
        for method_name in class_symbol.get("methods", [])
    }
    declared_interfaces = {
        interface.get("name")
        for interface in symbols.get("interfaces", [])
        if interface.get("name")
    }
    references: list[dict[str, Any]] = []

    def add_reference(index: int, kind: str, name: str | None, resolved: bool, target: str | None = None) -> None:
        if not name:
            return
        reference = {"op_index": index, "kind": kind, "name": name, "resolved": resolved}
        if target:
            reference["target"] = target
        references.append(reference)

    for index, op in enumerate(ops):
        code = op.get("op")
        if code == "define_class":
            extends = op.get("extends")
            if extends:
                add_reference(index, "base_class", extends, extends in declared_classes, f"class:{extends}" if extends in declared_classes else None)
            for interface in op.get("implements", []):
                resolved = interface in declared_classes or interface in declared_interfaces
                target = f"class:{interface}" if interface in declared_classes else f"interface:{interface}" if interface in declared_interfaces else None
                add_reference(index, "implemented_type", interface, resolved, target)
        elif code == "define_property":
            class_name = op.get("class")
            add_reference(index, "owner_class", class_name, class_name in declared_classes, f"class:{class_name}" if class_name in declared_classes else None)
            _add_expression_references(references, index, op.get("value"), symbols, set(), class_name)
        elif code == "define_method":
            class_name = op.get("class")
            add_reference(index, "owner_class", class_name, class_name in declared_classes, f"class:{class_name}" if class_name in declared_classes else None)
            parameters = set(op.get("parameters", []))
            _add_expression_references(references, index, op.get("returns"), symbols, parameters, class_name)
            for body_line in op.get("body", []):
                _add_expression_references(references, index, body_line, symbols, parameters, class_name)
        elif code == "define_function":
            parameters = set(op.get("parameters", []))
            _add_expression_references(references, index, op.get("returns"), symbols, parameters, None)
            for body_line in op.get("body", []):
                _add_expression_references(references, index, body_line, symbols, parameters, None)
        elif code == "declare_variable":
            _add_expression_references(references, index, op.get("value"), symbols, set(), None)
        elif code == "call":
            target = op.get("target")
            resolved_target = _resolve_callable_target(target, declared_functions, declared_methods, declared_classes)
            add_reference(index, "call_target", target, resolved_target is not None, resolved_target)
            for argument in op.get("arguments", []):
                _add_expression_references(references, index, argument, symbols, set(), None)

    return {
        "scope": "compilation_unit",
        "name_resolution": "order_insensitive",
        "declaration_pass": "collect_declarations_before_resolving_references",
        "effectful_action_order": "bytecode_order",
        "declared": {
            "variables": sorted(symbols["variables"]),
            "constants": sorted(symbols["constants"]),
            "functions": sorted(symbols["functions"]),
            "classes": sorted(declared_classes),
            "properties": sorted(f"{class_name}.{name}" for class_name, name in declared_properties),
            "methods": sorted(f"{class_name}.{name}" for class_name, name in declared_methods),
        },
        "references": references,
        "unresolved_references": [reference for reference in references if not reference["resolved"]],
    }


def _add_expression_references(
    references: list[dict[str, Any]],
    op_index: int,
    expression: str | None,
    symbols: dict[str, Any],
    local_names: set[str],
    owner_class: str | None,
) -> None:
    if not expression:
        return
    for name in _extract_identifier_references(expression):
        if name in local_names:
            continue
        resolved_target = _resolve_value_target(name, symbols, owner_class)
        reference = {"op_index": op_index, "kind": "value", "name": name, "resolved": resolved_target is not None}
        if resolved_target:
            reference["target"] = resolved_target
        references.append(reference)


def _extract_identifier_references(expression: str) -> list[str]:
    ignored = {
        "and",
        "or",
        "not",
        "plus",
        "minus",
        "times",
        "divided",
        "by",
        "mod",
        "true",
        "false",
        "null",
        "none",
        "empty",
        "error",
        "errors",
    }
    names: list[str] = []
    for match in re.finditer(r"\b[A-Za-z_][A-Za-z0-9_]*\b", expression):
        name = match.group(0)
        if name.lower() in ignored or name in LANGUAGE_ALIASES:
            continue
        if name not in names:
            names.append(name)
    return names


def _resolve_value_target(name: str, symbols: dict[str, Any], owner_class: str | None) -> str | None:
    if name in symbols["variables"]:
        return f"variable:{name}"
    if name in symbols["constants"]:
        return f"constant:{name}"
    if owner_class:
        class_symbol = symbols["classes"].get(owner_class) or {}
        if name in class_symbol.get("properties", []):
            return f"property:{owner_class}.{name}"
        if name in class_symbol.get("methods", []):
            return f"method:{owner_class}.{name}"
    if name in symbols["functions"]:
        return f"function:{name}"
    if name in symbols["classes"]:
        return f"class:{name}"
    return None


def _resolve_callable_target(
    name: str | None,
    declared_functions: set[str],
    declared_methods: set[tuple[str, str]],
    declared_classes: set[str],
) -> str | None:
    if not name:
        return None
    if "." in name:
        class_name, method_name = name.split(".", 1)
        if (class_name, method_name) in declared_methods:
            return f"method:{class_name}.{method_name}"
        if class_name in declared_classes:
            return f"class:{class_name}"
        return None
    if name in declared_functions:
        return f"function:{name}"
    matching_methods = sorted(f"{class_name}.{method_name}" for class_name, method_name in declared_methods if method_name == name)
    if len(matching_methods) == 1:
        return f"method:{matching_methods[0]}"
    if name in declared_classes:
        return f"class:{name}"
    return None


def _compile_statement(statement: str, *, root: str | None = None) -> list[dict[str, Any]]:
    normalized = _normalize_text(statement)
    ops: list[dict[str, Any]] = []

    if _mentions_use_shipmb(normalized):
        ops.append({"op": "use", "module": "shipmb"})

    domain_ops = _compile_domain_statement(statement)
    ops.extend(domain_ops)

    if _mentions_open_project(normalized):
        ops.append({"op": "open_project", "target": _extract_target(statement) or root or DEFAULT_ROOT})

    device_family = _extract_device_family(statement)
    if device_family:
        ops.append({"op": "use_device_family", "family": device_family})

    device_resource = _extract_device_resource(statement)
    if device_resource:
        ops.append({"op": "use_device_resource", "resource": device_resource})

    programming_ops = _compile_programming_statement(statement)
    ops.extend(programming_ops)

    if _mentions_index(normalized):
        ops.append({"op": "index_project"})

    if _mentions_error_event(normalized):
        ops.append({"op": "on_error"})

    if "printurf" in normalized or "explain" in normalized or "debug" in normalized:
        ops.append({"op": "printurf"})

    if "fix" in normalized or "suggest" in normalized or "repair" in normalized:
        ops.append({"op": "suggest_fix"})

    if "show" in normalized or "display" in normalized or ("print " in f" {normalized} " and not programming_ops):
        value = _extract_show_value(statement)
        if value is None:
            value = "report" if "error" in normalized else "device_resources" if "device" in normalized or "resource" in normalized else "report"
        ops.append({"op": "show", "value": value})

    if ("write" in normalized or "save" in normalized or "export" in normalized) and not programming_ops:
        ops.append({"op": "write", "value": "report", "target": _extract_target(statement) or "shipmb-output.json"})

    if _mentions_run(normalized):
        ops.append({"op": "run", "target": _extract_run_target(statement)})

    if not ops:
        ops.append({"op": "intent", "text": statement.strip()})

    return ops


def _compile_domain_statement(statement: str) -> list[dict[str, Any]]:
    ops: list[dict[str, Any]] = []

    library_op = _extract_library_use(statement)
    if library_op:
        ops.append(library_op)

    device_op = _extract_target_device(statement)
    if device_op:
        ops.append(device_op)

    ops.extend(_extract_capabilities(statement))

    install_op = _extract_install_runtime(statement)
    if install_op:
        ops.append(install_op)

    ops.extend(_extract_client_interfaces(statement))

    if _mentions_command_error_reporting(statement):
        ops.extend([{"op": "on_error"}, {"op": "printurf"}, {"op": "show", "value": "report"}])

    return ops


def _compile_programming_statement(statement: str) -> list[dict[str, Any]]:
    normalized = _normalize_text(statement)
    ops: list[dict[str, Any]] = []

    language = _extract_target_language(normalized)
    if language:
        ops.append({"op": "target_language", "language": language})

    import_op = _extract_import(statement)
    if import_op:
        ops.append(import_op)

    class_op = _extract_class(statement)
    if class_op:
        ops.append(class_op)

    property_op = _extract_property(statement)
    if property_op:
        ops.append(property_op)

    function_op = _extract_function(statement)
    if function_op:
        ops.append(function_op)

    method_op = _extract_method(statement)
    if method_op:
        ops.append(method_op)

    variable_op = _extract_variable(statement)
    if variable_op:
        ops.append(variable_op)

    loop_op = _extract_loop(statement)
    if loop_op:
        ops.append(loop_op)

    condition_op = _extract_condition(statement)
    if condition_op:
        ops.append(condition_op)

    return_op = _extract_return(statement)
    if return_op and not any((function_op, method_op, class_op, property_op, condition_op, loop_op)):
        ops.append(return_op)

    call_op = _extract_call(statement)
    if call_op and not condition_op and not loop_op:
        ops.append(call_op)

    return ops


def _normalize_ops(ops: list[dict[str, Any]], *, root: str | None = None) -> list[dict[str, Any]]:
    if not ops:
        return [{"op": "use", "module": "shipmb"}]

    normalized: list[dict[str, Any]] = []
    seen_use = False
    has_project_action = any(op["op"] in {"open_project", "index_project"} for op in ops)
    has_error_action = any(op["op"] in {"on_error", "printurf", "suggest_fix"} for op in ops)

    if not any(op["op"] == "use" for op in ops):
        normalized.append({"op": "use", "module": "shipmb"})
        seen_use = True

    if has_project_action and not any(op["op"] == "open_project" for op in ops):
        normalized.append({"op": "open_project", "target": root or DEFAULT_ROOT})

    if has_error_action and not any(op["op"] == "on_error" for op in ops):
        normalized.append({"op": "on_error"})

    for op in ops:
        if op["op"] == "use":
            if seen_use:
                continue
            seen_use = True
        normalized.append(op)

    return normalized


def _dedupe_ops(ops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    capability_indexes: dict[tuple[str | None, str | None], int] = {}

    for op in ops:
        if deduped and op == deduped[-1]:
            continue
        if op.get("op") == "use_capability":
            key = (op.get("target"), op.get("name"))
            previous_index = capability_indexes.get(key)
            if previous_index is not None:
                if op.get("agentic") and not deduped[previous_index].get("agentic"):
                    deduped[previous_index] = op
                continue
            capability_indexes[key] = len(deduped)
        if op.get("op") == "show" and op.get("value") == "report":
            if any(previous.get("op") == "show" and previous.get("value") == "report" for previous in deduped[-2:]):
                continue
        deduped.append(op)
    return deduped


def _split_statements(text: str) -> list[str]:
    parts = re.split(r"(?:[;!?]|\n+|\.(?=\s|$))+", text)
    return [part.strip() for part in parts if part.strip()]


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _mentions_use_shipmb(text: str) -> bool:
    return "use shipmb" in text or "use the shipmb" in text or "load shipmb" in text


def _mentions_open_project(text: str) -> bool:
    return "open" in text and ("project" in text or "folder" in text or "repo" in text or "workspace" in text)


def _mentions_index(text: str) -> bool:
    return any(word in text for word in ("index", "scan", "read the codebase", "read my code", "load the codebase"))


def _mentions_error_event(text: str) -> bool:
    return (
        "when an error" in text
        or "on error" in text
        or "if an error" in text
        or "whenever an error" in text
        or "errors happen" in text
    )


def _mentions_run(text: str) -> bool:
    return text.startswith("run ") or " run the " in text or "run tests" in text or "execute" in text


def _extract_target(text: str) -> str | None:
    quoted = re.search(r"['\"]([^'\"]+)['\"]", text)
    if quoted:
        return quoted.group(1)
    pathish = re.search(r"\b(?:\.{1,2}/|\.{1,2}\\|[A-Za-z]:\\|/)[^\s,;]+", text)
    if pathish:
        return pathish.group(0)
    if "current" in text.lower():
        return DEFAULT_ROOT
    return None


def _extract_run_target(text: str) -> str:
    quoted = re.search(r"['\"]([^'\"]+)['\"]", text)
    if quoted:
        return quoted.group(1)
    lowered = text.lower()
    if "test" in lowered:
        return "tests"
    match = re.search(r"(?:run|execute)\s+(.+)$", text, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return "program"


def _extract_library_use(text: str) -> dict[str, Any] | None:
    normalized = _normalize_text(text)
    pack_match = re.search(
        r"\b(?:use|load|add|import)\s+(?:the\s+)?([A-Za-z0-9_ -]+?)\s+pack\s+library\b(?:\s+in\s+([A-Za-z0-9_ -]+?))?(?:\s+to\s+(.+))?$",
        text,
        flags=re.IGNORECASE,
    )
    if pack_match:
        name = f"{pack_match.group(1)} pack"
        namespace = _clean_value(pack_match.group(2))
        purpose = _clean_value(pack_match.group(3)) or _extract_purpose(text)
        return {
            "op": "use_library",
            "name": _clean_library_name(name),
            "namespace": _clean_identifier(namespace) if namespace else None,
            "purpose": purpose,
        }

    match = re.search(
        r"\b(?:use|load|add|import)\s+(?:the\s+)?([A-Za-z0-9_ -]+?)\s+(?:library|package|module|pack)\b(?:\s+in\s+([A-Za-z0-9_ -]+))?(?:\s+to\s+(.+))?",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        pack_match = re.search(r"\b([A-Za-z0-9_ -]+?)\s+pack\s+library\b", text, flags=re.IGNORECASE)
        if not pack_match:
            return None
        name = f"{pack_match.group(1)} pack"
        namespace = "shipmblang" if "shipmblang" in normalized else None
        purpose = _extract_purpose(text)
    else:
        name = match.group(1)
        namespace = _clean_value(match.group(2))
        purpose = _clean_value(match.group(3)) or _extract_purpose(text)
    return {
        "op": "use_library",
        "name": _clean_library_name(name),
        "namespace": _clean_identifier(namespace) if namespace else None,
        "purpose": purpose,
    }


def _extract_target_device(text: str) -> dict[str, Any] | None:
    normalized = _normalize_text(text)
    if normalized.startswith("install "):
        return None
    platform = None
    kind = None
    if "roku" in normalized:
        platform = "roku"
    if re.search(r"\btv\b|television", normalized):
        kind = "tv"
    elif "remote" in normalized or "controller" in normalized:
        kind = "remote_controller"
    elif "device" in normalized:
        kind = "device"
    if not kind and not platform:
        return None
    return {"op": "target_device", "kind": kind or "device", "platform": platform, "alias": kind or platform}


def _extract_capabilities(text: str) -> list[dict[str, Any]]:
    normalized = _normalize_text(text)
    target = "device"
    if "remote" in normalized:
        target = "remote"
    capabilities: list[tuple[str, bool]] = []
    agentic = "agentic" in normalized or "agentically" in normalized

    capability_triggers = [
        ("remote_control", "remote" in normalized or "controller" in normalized),
        ("list_resources", "resource" in normalized or "resources" in normalized),
        ("search_apps", "search" in normalized and "app" in normalized),
        ("open_app", "open" in normalized and "app" in normalized),
        ("close_app", "close" in normalized and "app" in normalized),
        ("execute_command", "execute command" in normalized or "execute commands" in normalized),
    ]
    for name, matched in capability_triggers:
        if matched:
            capabilities.append((name, agentic))

    seen: set[str] = set()
    ops: list[dict[str, Any]] = []
    for name, is_agentic in capabilities:
        if name in seen:
            continue
        seen.add(name)
        ops.append({"op": "use_capability", "name": name, "target": target, "agentic": is_agentic})
    return ops


def _extract_install_runtime(text: str) -> dict[str, Any] | None:
    match = re.search(
        r"\binstall\s+([A-Za-z0-9_-]+)\s+on\s+(?:the\s+)?([A-Za-z0-9_ -]+?)(?:\s+and\b|$)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return {
        "op": "install_runtime",
        "runtime": _clean_identifier(match.group(1)),
        "target": _clean_identifier(match.group(2)),
    }


def _extract_client_interfaces(text: str) -> list[dict[str, Any]]:
    normalized = _normalize_text(text)
    ops: list[dict[str, Any]] = []
    if "voice" in normalized:
        ops.append({"op": "enable_interface", "name": "voice", "mode": "client"})
    if "chat bot" in normalized or "chatbot" in normalized or "chat" in normalized:
        ops.append({"op": "enable_interface", "name": "chat_bot", "mode": "client"})
    return ops


def _mentions_command_error_reporting(text: str) -> bool:
    normalized = _normalize_text(text)
    return "error" in normalized and ("command" in normalized or "execute" in normalized)


def _extract_purpose(text: str) -> str | None:
    match = re.search(r"\bto\s+(.+)$", text, flags=re.IGNORECASE)
    if match:
        return _clean_value(match.group(1))
    return None


def _clean_library_name(value: str) -> str:
    cleaned = re.sub(r"\b(?:the|a|an)\b", " ", value, flags=re.IGNORECASE)
    return _clean_identifier(cleaned)


def _extract_target_language(text: str) -> str | None:
    for alias in sorted(LANGUAGE_ALIASES, key=len, reverse=True):
        escaped = re.escape(alias)
        token = rf"(?<![A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])"
        patterns = [
            rf"\b(?:target|use|select|set|choose|compile|build|write|create|make|program)\s+(?:in|with|for|as|to)?\s*(?:the\s+)?{token}",
            rf"{token}\s+(?:program|application|app|script|syntax|code|language)\b",
        ]
        if any(re.search(pattern, text) for pattern in patterns):
            return LANGUAGE_ALIASES[alias]
    return None


def _extract_import(text: str) -> dict[str, Any] | None:
    normalized = _normalize_text(text)
    if (
        _mentions_use_shipmb(normalized)
        or "device family" in normalized
        or "device resource" in normalized
        or _extract_library_use(text) is not None
    ):
        return None

    from_match = re.search(
        r"\bfrom\s+([A-Za-z0-9_./:-]+)\s+import\s+([A-Za-z0-9_., *{} -]+)(?:\s+as\s+([A-Za-z_][A-Za-z0-9_]*))?\b",
        text,
        flags=re.IGNORECASE,
    )
    if from_match:
        return {
            "op": "import",
            "kind": "from",
            "module": from_match.group(1).strip(),
            "symbols": _split_name_list(from_match.group(2)),
            "alias": from_match.group(3),
        }

    import_match = re.search(
        r"\b(?:import|include|require|load)\s+(?:the\s+)?(?:library|package|module)?\s*([A-Za-z0-9_./:#<>-]+)(?:\s+as\s+([A-Za-z_][A-Za-z0-9_]*))?\b",
        text,
        flags=re.IGNORECASE,
    )
    if import_match:
        return {
            "op": "import",
            "kind": "include" if normalized.startswith("include ") else "import",
            "module": import_match.group(1).strip("<>"),
            "symbols": [],
            "alias": import_match.group(2),
        }

    library_match = re.search(
        r"\b(?:use|add|load)\s+(?:the\s+)?([A-Za-z0-9_./:#-]+)\s+(?:library|package|module)\b",
        text,
        flags=re.IGNORECASE,
    )
    if library_match:
        return {"op": "import", "kind": "import", "module": library_match.group(1), "symbols": [], "alias": None}
    return None


def _extract_variable(text: str) -> dict[str, Any] | None:
    normalized = _normalize_text(text)
    if "function" in normalized or "method" in normalized or "class" in normalized:
        return None

    patterns = [
        r"\b(?:declare|create|define|make|set)\s+(?:a\s+|an\s+|the\s+)?(?P<constant>constant|const)?\s*(?P<type>integer|int|string|str|boolean|bool|float|double|number|list|array|map|dictionary|object)?\s*(?:variable|var|value)?\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?:to|as|=|equal(?:s)?|with value)?\s*(?P<value>.+)?$",
        r"\b(?P<constant>const|constant|let|var)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?::\s*(?P<type>[A-Za-z_][A-Za-z0-9_<>[\]]*))?\s*(?:=|to|as|equal(?:s)?)\s*(?P<value>.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        name = _clean_identifier(groups.get("name") or "")
        if not name or name in LANGUAGE_ALIASES:
            continue
        raw_type = groups.get("type")
        raw_constant = groups.get("constant") or ""
        value = _clean_value(groups.get("value"))
        return {
            "op": "declare_variable",
            "name": name,
            "type": _normalize_type(raw_type),
            "value": value,
            "constant": raw_constant.lower() in {"constant", "const"},
        }
    return None


def _extract_function(text: str) -> dict[str, Any] | None:
    match = re.search(
        r"\b(?:define|create|write|make|declare)\s+(?:an?\s+)?(?:async\s+)?function\s+(?:named\s+|called\s+)?([A-Za-z_][A-Za-z0-9_]*)\b|\bfunction\s+([A-Za-z_][A-Za-z0-9_]*)\b",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    name = _clean_identifier(match.group(1) or match.group(2) or "")
    return {
        "op": "define_function",
        "name": name,
        "parameters": _extract_parameters(text),
        "returns": _extract_return_value(text),
        "body": _extract_body_steps(text),
    }


def _extract_class(text: str) -> dict[str, Any] | None:
    match = re.search(
        r"\b(?:define|create|write|make|declare)?\s*(?:an?\s+)?class\s+(?:named\s+|called\s+)?([A-Za-z_][A-Za-z0-9_]*)\b",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    prefix = _normalize_text(text[: match.start()])
    if re.search(r"\b(?:on|in|for)$", prefix):
        return None
    extends = None
    implements: list[str] = []
    extends_match = re.search(r"\bextends\s+([A-Za-z_][A-Za-z0-9_]*)\b|\binherits\s+from\s+([A-Za-z_][A-Za-z0-9_]*)\b", text, flags=re.IGNORECASE)
    if extends_match:
        extends = _clean_identifier(extends_match.group(1) or extends_match.group(2) or "")
    implements_match = re.search(r"\bimplements\s+([A-Za-z0-9_, and]+)\b", text, flags=re.IGNORECASE)
    if implements_match:
        implements = [_clean_identifier(name) for name in _split_name_list(implements_match.group(1))]
        implements = [name for name in implements if name]
    return {"op": "define_class", "name": _clean_identifier(match.group(1)), "extends": extends, "implements": implements}


def _extract_property(text: str) -> dict[str, Any] | None:
    patterns = [
        r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)\b.*?\bproperty\s+(?:named\s+|called\s+)?([A-Za-z_][A-Za-z0-9_]*)\b",
        r"\bproperty\s+(?:named\s+|called\s+)?([A-Za-z_][A-Za-z0-9_]*)\s+(?:on|in|for)\s+class\s+([A-Za-z_][A-Za-z0-9_]*)\b",
        r"\b(?:define|create|add|declare)\s+(?:a\s+|an\s+)?property\s+(?:named\s+|called\s+)?([A-Za-z_][A-Za-z0-9_]*)\b",
    ]
    for index, pattern in enumerate(patterns):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        if index == 0:
            class_name = _clean_identifier(match.group(1))
            name = _clean_identifier(match.group(2))
        elif index == 1:
            name = _clean_identifier(match.group(1))
            class_name = _clean_identifier(match.group(2))
        else:
            name = _clean_identifier(match.group(1))
            class_name = _extract_class_name_reference(text)
        return {
            "op": "define_property",
            "class": class_name,
            "name": name,
            "type": _extract_type_hint(text),
            "value": _extract_assigned_value(text),
        }
    return None


def _extract_method(text: str) -> dict[str, Any] | None:
    patterns = [
        r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)\b.*?\bmethod\s+(?:named\s+|called\s+)?([A-Za-z_][A-Za-z0-9_]*)\b",
        r"\bmethod\s+(?:named\s+|called\s+)?([A-Za-z_][A-Za-z0-9_]*)\s+(?:on|in|for)\s+class\s+([A-Za-z_][A-Za-z0-9_]*)\b",
        r"\b(?:define|create|write|make|declare)\s+(?:a\s+|an\s+)?method\s+(?:named\s+|called\s+)?([A-Za-z_][A-Za-z0-9_]*)\b",
    ]
    for index, pattern in enumerate(patterns):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        if index == 0:
            class_name = _clean_identifier(match.group(1))
            name = _clean_identifier(match.group(2))
        elif index == 1:
            name = _clean_identifier(match.group(1))
            class_name = _clean_identifier(match.group(2))
        else:
            name = _clean_identifier(match.group(1))
            class_name = _extract_class_name_reference(text)
        return {
            "op": "define_method",
            "class": class_name,
            "name": name,
            "parameters": _extract_parameters(text),
            "returns": _extract_return_value(text),
            "body": _extract_body_steps(text),
        }
    return None


def _extract_return(text: str) -> dict[str, Any] | None:
    value = _extract_return_value(text)
    if value is None:
        return None
    return {"op": "return", "value": value}


def _extract_call(text: str) -> dict[str, Any] | None:
    match = re.search(
        r"\b(?:call|invoke|run)\s+(?:the\s+)?(?:function\s+|method\s+)?([A-Za-z_][A-Za-z0-9_.]*)\b(?:\s+with\s+(.+))?",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    if match.group(1).lower() in {"and", "use", "the", "resources", "resource"}:
        return None
    return {"op": "call", "target": match.group(1), "arguments": _split_name_list(match.group(2) or "")}


def _extract_condition(text: str) -> dict[str, Any] | None:
    normalized = _normalize_text(text)
    if _mentions_error_event(normalized):
        return None
    match = re.search(r"\bif\s+(.+?)\s+then\s+(.+)$|\bwhen\s+(.+?),\s*(.+)$", text, flags=re.IGNORECASE)
    if not match:
        return None
    condition = match.group(1) or match.group(3)
    action = match.group(2) or match.group(4)
    return {"op": "condition", "condition": _clean_value(condition), "action": _clean_value(action)}


def _extract_loop(text: str) -> dict[str, Any] | None:
    match = re.search(
        r"\bfor\s+each\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\s+([A-Za-z_][A-Za-z0-9_.]*)\s*(?:,|then)?\s*(.+)?$|\bloop\s+over\s+([A-Za-z_][A-Za-z0-9_.]*)\s*(?:as\s+([A-Za-z_][A-Za-z0-9_]*))?\s*(?:and|to|then)?\s*(.+)?$",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    if match.group(1):
        return {"op": "loop", "iterator": match.group(1), "source": match.group(2), "action": _clean_value(match.group(3))}
    return {"op": "loop", "iterator": match.group(5) or "item", "source": match.group(4), "action": _clean_value(match.group(6))}


def _extract_parameters(text: str) -> list[str]:
    match = re.search(
        r"\b(?:takes|accepts|receives|with parameters|with params|with arguments|with args)\s+(.+?)(?:\s+and\s+returns\b|\s+returns\b|\s+and\s+prints?\b|\s+prints?\b|\s+and\s+does\b|\s+does\b|\s+that\b|\s+to\b|$)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return []
    return [_clean_identifier(name) for name in _split_name_list(match.group(1)) if _clean_identifier(name)]


def _extract_return_value(text: str) -> str | None:
    match = re.search(r"\breturns?\s+(.+?)(?:\s+and\s+then\b|\s+then\b|$)", text, flags=re.IGNORECASE)
    if not match:
        return None
    return _clean_value(match.group(1))


def _extract_body_steps(text: str) -> list[str]:
    steps: list[str] = []
    for pattern in (
        r"\bprints?\s+(.+?)(?:\s+and\s+returns\b|\s+returns\b|$)",
        r"\bdoes\s+(.+?)(?:\s+and\s+returns\b|\s+returns\b|$)",
        r"\bthen\s+(.+)$",
    ):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = _clean_value(match.group(1))
            if value:
                prefix = "print " if pattern.startswith(r"\bprints?") else ""
                steps.append(prefix + value)
    return steps


def _extract_show_value(text: str) -> str | None:
    match = re.search(r"\b(?:show|display|print)\s+(?:the\s+)?([A-Za-z_][A-Za-z0-9_ -]*)\b", text, flags=re.IGNORECASE)
    if not match:
        return None
    value = _normalize_text(match.group(1))
    mapping = {
        "program": "program",
        "program model": "program",
        "imports": "imports",
        "libraries": "imports",
        "variables": "variables",
        "constants": "constants",
        "functions": "functions",
        "classes": "classes",
        "calls": "calls",
        "loops": "loops",
        "conditions": "conditions",
        "libraries": "libraries",
        "device": "device",
        "devices": "device",
        "capabilities": "capabilities",
        "interfaces": "interfaces",
        "errors": "report",
        "device resources": "device_resources",
        "resources": "device_resources",
        "report": "report",
        "project": "project",
    }
    return mapping.get(value)


def _extract_type_hint(text: str) -> str | None:
    match = re.search(r"\b(?:as|type|typed as|of type)\s+([A-Za-z_][A-Za-z0-9_<>[\]]*)\b", text, flags=re.IGNORECASE)
    if match:
        return _normalize_type(match.group(1))
    return None


def _extract_assigned_value(text: str) -> str | None:
    match = re.search(r"\b(?:to|as|=|with value)\s+(.+)$", text, flags=re.IGNORECASE)
    if not match:
        return None
    return _clean_value(match.group(1))


def _extract_class_name_reference(text: str) -> str | None:
    match = re.search(r"\b(?:on|in|for)\s+class\s+([A-Za-z_][A-Za-z0-9_]*)\b", text, flags=re.IGNORECASE)
    if match:
        return _clean_identifier(match.group(1))
    class_match = re.search(r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)\b", text, flags=re.IGNORECASE)
    if class_match:
        return _clean_identifier(class_match.group(1))
    return None


def _split_name_list(value: str) -> list[str]:
    cleaned = value.strip().strip("{}[]()")
    if not cleaned:
        return []
    cleaned = re.sub(r"\s+and\s+", ",", cleaned, flags=re.IGNORECASE)
    return [item.strip() for item in cleaned.split(",") if item.strip()]


def _clean_identifier(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", value.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if cleaned and cleaned[0].isdigit():
        cleaned = "_" + cleaned
    return cleaned


def _normalize_type(value: str | None) -> str | None:
    if not value:
        return None
    aliases = {
        "integer": "int",
        "str": "string",
        "boolean": "bool",
        "dictionary": "map",
        "array": "list",
    }
    normalized = value.strip().lower()
    return aliases.get(normalized, normalized)


def _clean_value(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().strip(".;,")
    cleaned = re.sub(r"^(?:set\s+to|be|equal(?:s)?\s+to)\s+", "", cleaned, flags=re.IGNORECASE)
    return cleaned or None


def _extract_device_family(text: str) -> str | None:
    normalized = _normalize_text(text)
    patterns = [
        r"\b(?:use|select|set|target|load)\s+(?:the\s+)?([a-z0-9 _-]+?)\s+device\s+family\b",
        r"\bdevice\s+family\s+(?:to\s+|as\s+)?([a-z0-9 _-]+)\b",
        r"\b(?:use|select|set|target|load)\s+(?:device\s+)?([a-z0-9 _-]+?)\s+(?:device|target)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            candidate = _clean_device_phrase(match.group(1))
            if not candidate:
                continue
            try:
                return require_device_family(candidate)["name"]
            except ValueError:
                continue
    if _has_device_keyword_trigger(normalized):
        return find_device_family_keyword(normalized)
    return None


def _extract_device_resource(text: str) -> str | None:
    normalized = _normalize_text(text)
    patterns = [
        r"\b(?:use|expose|open|read|write|select)\s+(?:the\s+)?(?:device\s+)?resource\s+([a-z0-9 _-]+)\b",
        r"\b(?:use|expose|open|read|write|select)\s+(?:the\s+)?([a-z0-9 _-]+?)\s+resource\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            candidate = _clean_device_phrase(match.group(1))
            if candidate:
                return candidate
    if _has_resource_keyword_trigger(normalized):
        return find_device_resource_keyword(normalized)
    return None


def _clean_device_phrase(value: str) -> str:
    return re.sub(r"\b(?:at|any|point|in|time|current|currently|specified|the|a|an)\b", " ", value).strip(" -_")


def _has_device_keyword_trigger(text: str) -> bool:
    return re.search(r"\b(?:use|select|set|target|load|program|on|with|for)\b", text) is not None


def _has_resource_keyword_trigger(text: str) -> bool:
    return re.search(r"\b(?:use|expose|open|read|write|select|show|display|access)\b", text) is not None


def _quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _render_state_value(state: dict[str, Any], value: str) -> str:
    if value == "report" and state.get("report") is not None:
        return render_printurf_report(state["report"], include_context=False)
    if value == "project" and state.get("project") is not None:
        project = state["project"]
        return f"Project: indexed {project.get('file_count', 0)} files under {project.get('root', '')}"
    if value in {"program", "program_model"}:
        return _render_program_model(state)
    if value == "imports":
        return _render_collection("Imports", state.get("imports") or [])
    if value == "variables":
        return _render_mapping("Variables", state.get("variables") or {})
    if value == "constants":
        return _render_mapping("Constants", state.get("constants") or {})
    if value == "functions":
        return _render_mapping("Functions", state.get("functions") or {})
    if value == "classes":
        return _render_mapping("Classes", state.get("classes") or {})
    if value == "calls":
        return _render_collection("Calls", state.get("calls") or [])
    if value == "conditions":
        return _render_collection("Conditions", state.get("conditions") or [])
    if value == "loops":
        return _render_collection("Loops", state.get("loops") or [])
    if value == "libraries":
        return _render_collection("Libraries", state.get("libraries") or [])
    if value in {"device", "device_target"} and state.get("device_target"):
        return _render_collection("Devices", [state["device_target"]])
    if value == "capabilities":
        return _render_collection("Capabilities", state.get("device_capabilities") or [])
    if value == "interfaces":
        return _render_collection("Interfaces", state.get("interfaces") or [])
    if value in {"device", "devices", "resources", "device_resources"} and state.get("device_family"):
        family = state["device_family"]
        selected = state.get("device_resources") or family.get("resources") or []
        lines = [f"Device family: {family.get('display_name')} ({family.get('name')})"]
        lines.extend(f"- {resource.get('name')}: {resource.get('description')}" for resource in selected)
        return "\n".join(lines)
    if state.get("report") is not None:
        return render_printurf_report(state["report"], include_context=False)
    if state.get("project") is not None:
        project = state["project"]
        return f"Project: indexed {project.get('file_count', 0)} files under {project.get('root', '')}"
    if _has_program_model(state):
        return _render_program_model(state)
    return "ShipMBLang ran with no visible output."


def _has_program_model(state: dict[str, Any]) -> bool:
    return any(
        state.get(key)
        for key in (
            "language",
            "imports",
            "libraries",
            "device_target",
            "device_capabilities",
            "installs",
            "interfaces",
            "variables",
            "constants",
            "functions",
            "classes",
            "calls",
            "conditions",
            "loops",
        )
    )


def _render_program_model(state: dict[str, Any]) -> str:
    lines = ["Program model:"]
    if state.get("language"):
        language = state["language"]
        lines.append(f"- language: {LANGUAGE_DISPLAY_NAMES.get(language, language)}")
    if state.get("imports"):
        lines.append(f"- imports: {len(state['imports'])}")
    if state.get("libraries"):
        lines.append("- libraries: " + ", ".join(item.get("name") or "" for item in state["libraries"]))
    if state.get("device_target"):
        device = state["device_target"]
        descriptor = " ".join(part for part in (device.get("platform"), device.get("kind")) if part)
        lines.append(f"- device: {descriptor or device.get('alias') or 'device'}")
    if state.get("device_capabilities"):
        lines.append("- capabilities: " + ", ".join(item.get("name") or "" for item in state["device_capabilities"]))
    if state.get("installs"):
        lines.append("- installs: " + ", ".join(item.get("runtime") or "" for item in state["installs"]))
    if state.get("interfaces"):
        lines.append("- interfaces: " + ", ".join(item.get("name") or "" for item in state["interfaces"]))
    if state.get("variables"):
        lines.append(f"- variables: {', '.join(state['variables'])}")
    if state.get("constants"):
        lines.append(f"- constants: {', '.join(state['constants'])}")
    if state.get("functions"):
        lines.append(f"- functions: {', '.join(state['functions'])}")
    if state.get("classes"):
        lines.append(f"- classes: {', '.join(state['classes'])}")
    if state.get("calls"):
        lines.append(f"- calls: {len(state['calls'])}")
    if state.get("conditions"):
        lines.append(f"- conditions: {len(state['conditions'])}")
    if state.get("loops"):
        lines.append(f"- loops: {len(state['loops'])}")
    if len(lines) == 1:
        lines.append("- no programming constructs were declared")
    return "\n".join(lines)


def _render_collection(title: str, values: list[Any]) -> str:
    if not values:
        return f"{title}: none"
    lines = [f"{title}:"]
    lines.extend(f"- {json.dumps(value, sort_keys=True)}" for value in values)
    return "\n".join(lines)


def _render_mapping(title: str, values: dict[str, Any]) -> str:
    if not values:
        return f"{title}: none"
    lines = [f"{title}:"]
    lines.extend(f"- {name}: {json.dumps(detail, sort_keys=True)}" for name, detail in values.items())
    return "\n".join(lines)


def _safe_output_path(target: str, root: str) -> Path:
    root_path = Path(root).resolve()
    path = Path(target)
    if not path.is_absolute():
        path = root_path / path
    resolved = path.resolve()
    try:
        resolved.relative_to(root_path)
    except ValueError as exc:
        raise ValueError(f"Refusing to write outside the ShipMBLang root: {resolved}") from exc
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


if __name__ == "__main__":
    main()
