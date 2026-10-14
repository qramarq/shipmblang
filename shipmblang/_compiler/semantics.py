from __future__ import annotations

from .models import Diagnostic, SemanticModel, SemanticOp, Span, Symbol, SyntaxNode


def semantic_analysis(syntax_tree: SyntaxNode) -> SemanticModel:
    model = SemanticModel()
    model.diagnostics.extend(syntax_tree.diagnostics)

    _predeclare_symbols(model, syntax_tree)
    _warn_duplicate_declarations(model, list(_walk_statements(syntax_tree.children)))

    for statement in syntax_tree.children:
        _analyze_statement(model, statement)

    _dedupe_effects(model)
    return model


def _predeclare_symbols(model: SemanticModel, syntax_tree: SyntaxNode) -> None:
    statements = list(_walk_statements(syntax_tree.children))
    explicit_device_aliases: set[str] = set()
    explicit_capabilities: set[str] = set()

    for statement in statements:
        if statement.kind == "UsePrelude":
            model.symbols.setdefault(
                "shipmb",
                Symbol("shipmb", "prelude", "Module", statement.span, {"explicit": True, "predeclared": True}),
            )
        elif statement.kind == "UseDeclaration":
            name = statement.roles["name"]
            model.symbols.setdefault(
                name,
                Symbol(
                    name,
                    "use",
                    "Module",
                    statement.span,
                    {
                        "source": statement.roles.get("source"),
                        "declaration_kind": statement.roles.get("declaration_kind", "use"),
                        "predeclared": True,
                    },
                ),
            )
        elif statement.kind == "ImportLibrary":
            library = statement.roles["library"]
            model.symbols.setdefault(
                library,
                Symbol(
                    library,
                    "library",
                    "Module",
                    statement.span,
                    {"source": statement.roles["source"], "predeclared": True},
                ),
            )
        elif statement.kind == "DeviceTarget":
            alias = statement.roles["alias"]
            explicit_device_aliases.add(alias)
            model.symbols.setdefault(
                alias,
                Symbol(
                    alias,
                    "device",
                    "Device",
                    statement.span,
                    {"platform": statement.roles["platform"], "predeclared": True},
                ),
            )
        elif statement.kind == "CapabilityStatement":
            target = statement.roles.get("target") or "remote"
            if target == "remote":
                _ensure_remote_symbol(model, statement.span)
            for capability in statement.roles.get("capabilities", []):
                explicit_capabilities.add(f"{target}.{capability}")
                _declare_capability_symbol(
                    model,
                    statement.span,
                    target,
                    capability,
                    bool(statement.roles.get("agentic", True)),
                    predeclared=True,
                )
        elif statement.kind == "InterfaceStatement":
            for interface in statement.roles.get("interfaces", []):
                model.symbols.setdefault(
                    interface,
                    Symbol(
                        interface,
                        "interface",
                        "Interface",
                        statement.span,
                        {"mode": statement.roles["mode"], "predeclared": True},
                    ),
                )

    for statement in statements:
        if statement.kind != "ImportLibrary":
            continue
        purpose = statement.roles.get("purpose", "").lower()
        is_core_source = statement.roles.get("source_layer") == "shipmb-core"
        if is_core_source:
            continue
        if "roku" in purpose and "tv" in purpose and "tv" not in explicit_device_aliases:
            _ensure_tv_device(model, statement.span, emit_op=False, predeclared=True, inferred=True)
        if "remote" in purpose and "remote.remote_control" not in explicit_capabilities:
            _ensure_remote_symbol(model, statement.span)
            _declare_capability_symbol(
                model,
                statement.span,
                "remote",
                "remote_control",
                agentic=True,
                predeclared=True,
                inferred=True,
            )


def _walk_statements(statements: list[SyntaxNode]) -> list[SyntaxNode]:
    walked: list[SyntaxNode] = []
    for statement in statements:
        if statement.kind == "StatementSequence":
            walked.extend(_walk_statements(statement.children))
        else:
            walked.append(statement)
    return walked


def _warn_duplicate_declarations(model: SemanticModel, statements: list[SyntaxNode]) -> None:
    seen: dict[tuple, Span] = {}
    for statement in statements:
        for key in _declaration_keys(statement):
            if key in seen:
                model.diagnostics.append(
                    Diagnostic(
                        "warning",
                        "SMB2101",
                        "This declaration exactly duplicates an earlier declaration and will be merged.",
                        statement.span,
                        "Remove the duplicate declaration unless you meant to declare a different symbol or option.",
                    )
                )
                continue
            seen[key] = statement.span


def _declaration_keys(statement: SyntaxNode) -> list[tuple]:
    if statement.kind == "UsePrelude":
        return [("prelude", statement.roles.get("name"))]
    if statement.kind == "UseDeclaration":
        return [
            (
                "use",
                statement.roles.get("name"),
                statement.roles.get("source"),
                statement.roles.get("declaration_kind", "use"),
            )
        ]
    if statement.kind == "ImportLibrary":
        return [
            (
                "library",
                statement.roles.get("library"),
                statement.roles.get("source"),
                statement.roles.get("purpose", ""),
            )
        ]
    if statement.kind == "DeviceTarget":
        return [
            (
                "device",
                statement.roles.get("name"),
                statement.roles.get("platform"),
                statement.roles.get("alias"),
            )
        ]
    if statement.kind == "CapabilityStatement":
        target = statement.roles.get("target") or "remote"
        return [
            ("capability", target, capability, bool(statement.roles.get("agentic", True)))
            for capability in statement.roles.get("capabilities", [])
        ]
    if statement.kind == "InterfaceStatement":
        return [
            ("interface", interface, statement.roles.get("mode"))
            for interface in statement.roles.get("interfaces", [])
        ]
    return []


def _analyze_statement(model: SemanticModel, statement: SyntaxNode) -> None:
    if statement.kind == "StatementSequence":
        for child in statement.children:
            _analyze_statement(model, child)
    elif statement.kind == "UsePrelude":
        model.symbols["shipmb"] = Symbol("shipmb", "prelude", "Module", statement.span, {"explicit": True})
        model.ops.append(SemanticOp("prelude.use", {"name": "shipmb", "generated": False}, statement.span, "Module"))
    elif statement.kind == "UseDeclaration":
        model.symbols[statement.roles["name"]] = Symbol(
            statement.roles["name"],
            "use",
            "Module",
            statement.span,
            {
                "source": statement.roles.get("source"),
                "declaration_kind": statement.roles.get("declaration_kind", "use"),
            },
        )
        model.ops.append(
            SemanticOp(
                "use.declare",
                {
                    "name": statement.roles["name"],
                    "source": statement.roles.get("source"),
                    "declaration_kind": statement.roles.get("declaration_kind", "use"),
                },
                statement.span,
                "Module",
            )
        )
    elif statement.kind == "ImportLibrary":
        _import_library(model, statement)
    elif statement.kind == "DeviceTarget":
        model.symbols[statement.roles["alias"]] = Symbol(
            statement.roles["alias"],
            "device",
            "Device",
            statement.span,
            {"platform": statement.roles["platform"]},
        )
        model.ops.append(
            SemanticOp(
                "device.target",
                {"name": statement.roles["name"], "platform": statement.roles["platform"], "alias": statement.roles["alias"]},
                statement.span,
                "Device",
                ["device"],
            )
        )
        model.effects.append("device")
    elif statement.kind == "CapabilityStatement":
        _capabilities(model, statement)
    elif statement.kind == "ErrorHandler":
        _error_handler(model, statement)
    elif statement.kind == "InstallPackage":
        _install(model, statement)
    elif statement.kind == "InterfaceStatement":
        _interfaces(model, statement)
    elif statement.kind == "RunCommand":
        model.ops.append(
            SemanticOp(
                "runtime.run",
                {"command": statement.roles["command"], "target": statement.roles["target"]},
                statement.span,
                "Result",
                ["device"],
            )
        )
        model.effects.append("device")
    elif statement.kind == "MCPToolCall":
        model.ops.append(
            SemanticOp(
                "mcp.tool.call",
                {
                    "server": statement.roles["server"],
                    "tool": statement.roles["tool"],
                    "arguments": statement.roles.get("arguments", {}),
                    "execute_at_compile_time": False,
                },
                statement.span,
                "MCPToolResult",
                ["mcp", "network"],
            )
        )
        model.effects.extend(["mcp", "network"])
    elif statement.kind == "CorePipeline":
        return
    elif statement.kind == "ArchitectureDebug":
        model.diagnostics.append(
            Diagnostic(
                "note",
                "SMB7001",
                "Architecture inspection is a compile-time debug instruction and is not emitted to runtime bytecode.",
                statement.span,
                "Use it while debugging; remove it when you only want runtime bytecode.",
            )
        )
    elif statement.kind == "UnsupportedStatement":
        model.diagnostics.extend(statement.diagnostics)


def _import_library(model: SemanticModel, node: SyntaxNode) -> None:
    library = node.roles["library"]
    source = node.roles["source"]
    model.symbols[library] = Symbol(library, "library", "Module", node.span, {"source": source})
    model.ops.append(
        SemanticOp(
            "library.import",
            {"name": library, "source": source, "purpose": node.roles.get("purpose", "")},
            node.span,
            "Module",
        )
    )

    purpose = node.roles.get("purpose", "").lower()
    is_core_source = node.roles.get("source_layer") == "shipmb-core"
    tv_symbol = model.symbols.get("tv")
    remote_control_symbol = model.symbols.get("remote.remote_control")
    should_infer_device = (
        not is_core_source
        and "roku" in purpose
        and "tv" in purpose
        and not _has_device_target_op(model, "tv")
        and (tv_symbol is None or bool(tv_symbol.metadata.get("inferred")))
    )
    should_infer_remote = (
        not is_core_source
        and "remote" in purpose
        and not _has_capability_op(model, "remote", "remote_control")
        and (remote_control_symbol is None or bool(remote_control_symbol.metadata.get("inferred")))
    )
    if should_infer_device:
        _ensure_tv_device(model, node.span)
    if should_infer_remote:
        _ensure_remote_symbol(model, node.span)
        _declare_capability(model, node.span, "remote", "remote_control", agentic=True)


def _capabilities(model: SemanticModel, node: SyntaxNode) -> None:
    target = node.roles.get("target") or "remote"
    if target == "remote":
        _ensure_remote_symbol(model, node.span)
    if "tv" not in model.symbols:
        model.diagnostics.append(
            Diagnostic(
                "error",
                "SMB3001",
                "Capabilities need a device target, but no TV device has been declared yet.",
                node.span,
                "Add a sentence like 'Use the tv pack library from shipmblang to control this Roku TV like a remote.'",
            )
        )
    for capability in node.roles.get("capabilities", []):
        _declare_capability(model, node.span, target, capability, bool(node.roles.get("agentic", True)))
    if any(child.kind == "ErrorHandler" for child in node.children):
        _error_handler(model, node)
    if node.roles.get("run"):
        model.ops.append(
            SemanticOp(
                "runtime.run",
                {"command": node.roles["run"], "target": "remote"},
                node.span,
                "Result",
                ["device"],
            )
        )
        model.effects.append("device")


def _error_handler(model: SemanticModel, node: SyntaxNode) -> None:
    model.ops.append(
        SemanticOp(
            "error.handler",
            {"condition": "command_failure", "pipeline": ["error", "printurf", "show"]},
            node.span,
            "ErrorHandler",
            ["io"],
        )
    )
    model.effects.append("io")


def _install(model: SemanticModel, node: SyntaxNode) -> None:
    target = node.roles["target"] or "tv"
    if target not in model.symbols:
        model.diagnostics.append(
            Diagnostic(
                "error",
                "SMB2002",
                f"Install target '{target}' has not been declared.",
                node.span,
                "Declare the target device before installing packages on it.",
            )
        )
    model.ops.append(
        SemanticOp(
            "package.install",
            {"package": node.roles["package"], "target": target},
            node.span,
            "Result",
            ["install", "device"],
        )
    )
    model.effects.extend(["install", "device"])


def _interfaces(model: SemanticModel, node: SyntaxNode) -> None:
    for interface in node.roles.get("interfaces", []):
        model.symbols[interface] = Symbol(interface, "interface", "Interface", node.span, {"mode": node.roles["mode"]})
        model.ops.append(
            SemanticOp(
                "interface.declare",
                {"name": interface, "mode": node.roles["mode"]},
                node.span,
                "Interface",
                ["io"],
            )
        )
        model.effects.append("io")


def _ensure_tv_device(
    model: SemanticModel,
    span: Span,
    emit_op: bool = True,
    predeclared: bool = False,
    inferred: bool = False,
) -> None:
    metadata = {"platform": "roku"}
    if predeclared:
        metadata["predeclared"] = True
    if inferred:
        metadata["inferred"] = True
    existing = model.symbols.get("tv")
    if existing is None or (emit_op and existing.metadata.get("predeclared")):
        model.symbols["tv"] = Symbol("tv", "device", "Device", span, metadata)
    if emit_op:
        model.ops.append(
            SemanticOp(
                "device.target",
                {"name": "tv", "platform": "roku", "alias": "tv"},
                span,
                "Device",
                ["device"],
            )
        )
        model.effects.append("device")


def _ensure_remote_symbol(model: SemanticModel, span: Span) -> None:
    model.symbols.setdefault("remote", Symbol("remote", "resource", "Resource", span, {"target": "tv"}))
    model.symbols.setdefault(
        "remote_controller",
        Symbol("remote_controller", "resource", "Resource", span, {"platform": "roku", "target": "tv"}),
    )


def _declare_capability(model: SemanticModel, span: Span, target: str, capability: str, agentic: bool) -> None:
    _declare_capability_symbol(model, span, target, capability, agentic)
    model.ops.append(
        SemanticOp(
            "capability.declare",
            {"target": target, "name": capability, "agentic": agentic},
            span,
            "Capability",
            ["device", "agentic"] if agentic else ["device"],
        )
    )
    model.effects.extend(["device", "agentic"] if agentic else ["device"])


def _declare_capability_symbol(
    model: SemanticModel,
    span: Span,
    target: str,
    capability: str,
    agentic: bool,
    predeclared: bool = False,
    inferred: bool = False,
) -> None:
    symbol_name = f"{target}.{capability}"
    metadata = {"target": target, "agentic": agentic}
    if predeclared:
        metadata["predeclared"] = True
    if inferred:
        metadata["inferred"] = True
    existing = model.symbols.get(symbol_name)
    if existing is not None and not existing.metadata.get("predeclared"):
        return
    if existing is not None and predeclared:
        return
    model.symbols[symbol_name] = Symbol(symbol_name, "capability", "Capability", span, metadata)


def _has_device_target_op(model: SemanticModel, alias: str) -> bool:
    return any(op.op == "device.target" and op.args.get("alias") == alias for op in model.ops)


def _has_capability_op(model: SemanticModel, target: str, capability: str) -> bool:
    return any(
        op.op == "capability.declare" and op.args.get("target") == target and op.args.get("name") == capability
        for op in model.ops
    )


def _dedupe_effects(model: SemanticModel) -> None:
    model.effects = list(dict.fromkeys(model.effects))
