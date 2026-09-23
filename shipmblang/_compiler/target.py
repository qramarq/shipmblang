from __future__ import annotations

from typing import Any

from .models import BytecodeProgram, Diagnostic, IROp, Span


BYTECODE_OPCODE_BY_IR = {
    "USE_PRELUDE": "use_prelude",
    "USE_DECLARATION": "use_declaration",
    "IMPORT_LIBRARY": "import_library",
    "DEVICE_TARGET": "device_target",
    "DECLARE_CAPABILITY": "declare_capability",
    "ON_ERROR": "on_error",
    "INSTALL_PACKAGE": "install_package",
    "DECLARE_INTERFACE": "declare_interface",
    "RUN": "run",
    "MCP_TOOL_CALL": "mcp_tool_call",
}


def target_code_generation(optimized_ir: list[IROp], target: str = "bytecode") -> tuple[BytecodeProgram, list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    if target not in {"bytecode", "shipmblang-bytecode"}:
        diagnostics.append(
            Diagnostic(
                "error",
                "SMB5001",
                f"Unsupported target '{target}'.",
                Span(0, 0),
                "ShipMBCompiler v0.1 emits structured ShipMBLang bytecode. Native machine code is a future backend.",
            )
        )

    bytecode: list[dict] = []
    for pc, op in enumerate(optimized_ir):
        bytecode_opcode = BYTECODE_OPCODE_BY_IR.get(op.op)
        if bytecode_opcode is None:
            diagnostics.append(
                Diagnostic(
                    "error",
                    "SMB5002",
                    f"IR opcode '{op.op}' does not have a bytecode lowering.",
                    op.span,
                    "Add a target-code lowering rule before emitting bytecode.",
                )
            )
            continue
        bytecode.append(
            {
                "pc": pc,
                "opcode": bytecode_opcode,
                "operands": op.args,
                "tac": {"result": op.result, "arg1": op.arg1, "arg2": op.arg2},
                "source_span": op.span.to_dict(),
            }
        )

    return (
        BytecodeProgram(
            "shipmblang-bytecode",
            "0.1",
            False,
            bytecode,
            debug={
                "ir_count": len(optimized_ir),
                "native_target_available": False,
                "canonical_opcode_names": "lowercase",
                "legacy_uppercase_opcode_input_accepted": True,
            },
            runtime_contract=_runtime_contract_from_ir(optimized_ir),
        ),
        diagnostics,
    )


def _runtime_contract_from_ir(optimized_ir: list[IROp]) -> dict[str, Any]:
    declared_capabilities: list[dict[str, Any]] = []
    seen: set[tuple[str, str, bool]] = set()

    for op in optimized_ir:
        if op.op != "DECLARE_CAPABILITY":
            continue
        target = str(op.args.get("target", ""))
        name = str(op.args.get("name", ""))
        agentic = bool(op.args.get("agentic", False))
        key = (target, name, agentic)
        if key in seen:
            continue
        seen.add(key)
        declared_capabilities.append(
            {
                "target": target,
                "name": name,
                "agentic": agentic,
                "source": "compiled_declaration",
            }
        )

    return {
        "identity": {
            "name": "shipmb",
            "owner": "runtime",
            "namespace": "shipmb.runtime",
            "model_neutral": True,
        },
        "orchestration_role": {
            "name": "shipmb_runtime_orchestrator",
            "owner": "runtime",
            "scope": "bytecode_execution",
        },
        "capability_context": {
            "declared": declared_capabilities,
            "source": "compiled_capability_declarations",
        },
    }
