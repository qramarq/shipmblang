from __future__ import annotations

from typing import Any, Callable
from copy import deepcopy
from dataclasses import replace

from .models import BytecodeProgram, Diagnostic, Span
from .target import BYTECODE_OPCODE_BY_IR


SHIPMB_LIBRARY_ALLOWLIST = {"tv_pack"}
SHIPMB_PACKAGE_ALLOWLIST = {"shipmb"}
SHIPMB_DEVICE_PLATFORMS = {"roku"}
SHIPMB_CAPABILITY_ALLOWLIST = {
    "remote_control",
    "search_apps",
    "open_app",
    "close_app",
    "list_resources",
    "execute_command",
}
SHIPMB_INTERFACE_ALLOWLIST = {"voice", "chat_bot"}
SHIPMB_PRELUDE = "shipmb"
LEGACY_BYTECODE_OPCODE_ALIASES = BYTECODE_OPCODE_BY_IR
KNOWN_BYTECODE_OPCODES = set(BYTECODE_OPCODE_BY_IR.values())


AbilityChecker = Callable[[dict[str, Any]], dict[str, Any]]
ActionExecutor = Callable[[dict[str, Any]], Any]
GUARDABLE_OPCODES = {"run", "install_package", "declare_interface"}


def run_artifact(artifact: dict[str, Any], *, ability_checker: AbilityChecker | None = None,
                 action_executor: ActionExecutor | None = None, host=None, ffmpeg_executor=None) -> tuple[dict[str, Any], list[Diagnostic]]:
    """Load compiler artifacts without accepting artifacts from another bytecode producer."""
    if isinstance(artifact, dict) and artifact.get("version") in ("0.3", "0.4"):
        from .general_runtime import run_general_artifact
        return run_general_artifact(artifact, host=host, ffmpeg_executor=ffmpeg_executor)
    if (not isinstance(artifact, dict)
            or not isinstance(artifact.get("debug", {}), dict)
            or artifact.get("producer", artifact.get("debug", {}).get("producer")) != "shipmbcompiler"
            or not isinstance(artifact.get("bytecode"), list)
            or not isinstance(artifact.get("runtime_contract", {}), dict)):
        return {"events": []}, [Diagnostic("error", "SMB6011", "Invalid compiler artifact or producer.", Span(0, 0))]
    program = BytecodeProgram(artifact.get("target"), artifact.get("version"),
                              artifact.get("native_machine_code"), deepcopy(artifact["bytecode"]),
                              deepcopy(artifact.get("debug", {})), deepcopy(artifact.get("runtime_contract", {})))
    program.debug["producer"] = "shipmbcompiler"
    return run_bytecode(program, ability_checker=ability_checker, action_executor=action_executor)


def run_bytecode(program: BytecodeProgram, *, ability_checker: AbilityChecker | None = None,
                 action_executor: ActionExecutor | None = None) -> tuple[dict[str, Any], list[Diagnostic]]:
    diagnostics = _validate_program(program)
    runtime_contract = _runtime_contract(program if not diagnostics else replace(program, runtime_contract={}))
    state: dict[str, Any] = {
        "identity": runtime_contract["identity"],
        "orchestration_role": runtime_contract["orchestration_role"],
        "capability_context": runtime_contract["capability_context"],
        "prelude_loaded": False,
        "libraries": {},
        "devices": {},
        "capabilities": {},
        "interfaces": {},
        "installed": [],
        "events": [],
    }
    # The runtime is a security boundary: never partially execute a program
    # that failed validation, even though the current v0.1 implementation only
    # records events. Future device backends must preserve this fail-closed rule.
    if diagnostics:
        return state, diagnostics

    for instruction in program.bytecode:
        opcode = normalize_bytecode_opcode(instruction["opcode"])
        operands = instruction["operands"]
        span = _span_from_instruction(instruction)

        if opcode == "guarded_action":
            action = deepcopy(operands["action"])
            try:
                ability = ability_checker(deepcopy(action)) if ability_checker else {
                    "status": "unknown", "reason": "No runtime ability checker is configured."}
                if not isinstance(ability, dict) or ability.get("status") not in ("able", "unable", "unknown"):
                    ability = {"status": "unknown", "reason": "Invalid ability checker response."}
            except Exception as exc:
                ability = {"status": "unknown", "reason": f"Ability check failed: {exc}"}
            if ability["status"] != "able":
                state["events"].append({"event": "action.skipped", "action": action,
                                        "status": ability["status"],
                                        "reason": ability.get("reason") or "Action ability could not be established."})
                continue
            opcode, operands = normalize_bytecode_opcode(action["opcode"]), action["operands"]

        if opcode in GUARDABLE_OPCODES and action_executor is not None:
            try:
                action_executor(deepcopy({"opcode": opcode, "operands": operands}))
            except Exception as exc:
                failure = {"event": "action.failed", "action": {"opcode": opcode, "operands": operands},
                           "reason": str(exc)}
                state["events"].append(failure)
                if "error_handler" in state:
                    state["events"].append({"event": "error.reported", "reason": str(exc),
                                            "pipeline": state["error_handler"].get("pipeline", [])})
                continue

        if opcode == "use_prelude":
            state["prelude_loaded"] = operands.get("name") == SHIPMB_PRELUDE
            state["events"].append({"event": "prelude.loaded", "name": operands.get("name")})
        elif opcode == "use_declaration":
            state["events"].append(
                {
                    "event": "use.declared",
                    "name": operands.get("name"),
                    "source": operands.get("source"),
                    "declaration_kind": operands.get("declaration_kind"),
                }
            )
        elif opcode == "import_library":
            name = operands["name"]
            state["libraries"][name] = operands
            state["events"].append({"event": "library.loaded", "name": name, "source": operands.get("source")})
        elif opcode == "device_target":
            state["devices"][operands["alias"]] = operands
            state["events"].append({"event": "device.bound", "name": operands["alias"], "platform": operands["platform"]})
        elif opcode == "declare_capability":
            key = f"{operands['target']}.{operands['name']}"
            state["capabilities"][key] = operands
            _record_runtime_capability(state, operands)
            state["events"].append(
                {
                    "event": "capability.ready",
                    "target": operands["target"],
                    "name": operands["name"],
                    "agentic": operands.get("agentic", False),
                }
            )
        elif opcode == "on_error":
            state["error_handler"] = operands
            state["events"].append({"event": "error_handler.ready", "pipeline": operands.get("pipeline", [])})
        elif opcode == "run":
            missing = _missing_capabilities(state, ["remote.execute_command"])
            if missing:
                diagnostics.append(_missing_runtime_capability(missing[0], span))
                continue
            state["events"].append({"event": "command.run", "target": operands.get("target"), "command": operands.get("command")})
        elif opcode == "install_package":
            state["installed"].append(operands)
            state["events"].append(
                {"event": "package.installed", "package": operands["package"], "target": operands["target"]}
            )
        elif opcode == "declare_interface":
            state["interfaces"][operands["name"]] = operands
            state["events"].append({"event": "interface.ready", "name": operands["name"], "mode": operands["mode"]})
        elif opcode == "mcp_tool_call":
            state["events"].append(
                {
                    "event": "mcp.tool.declared",
                    "server": operands.get("server"),
                    "tool": operands.get("tool"),
                    "arguments": operands.get("arguments", {}),
                    "executed": False,
                }
            )

    return state, diagnostics


def _validate_program(program: BytecodeProgram) -> list[Diagnostic]:
    """Validate untrusted bytecode before it reaches the runtime event loop."""
    diagnostics: list[Diagnostic] = []
    if (program.version not in ("0.1", "0.2")
            or not isinstance(program.debug, dict) or not isinstance(program.runtime_contract, dict)
            or not isinstance(program.bytecode, list)
            or (program.version == "0.2" and program.debug.get("producer") != "shipmbcompiler")):
        return [Diagnostic("error", "SMB6011", "Unsupported bytecode version or producer.", Span(0, 0))]
    for key in ("identity", "orchestration_role", "capability_context"):
        if not isinstance(program.runtime_contract.get(key, {}), dict):
            return [Diagnostic("error", "SMB6011", "Invalid runtime contract.", Span(0, 0))]
    declared = program.runtime_contract.get("capability_context", {}).get("declared", [])
    if not isinstance(declared, list) or any(
            not isinstance(item, dict)
            or not isinstance(item.get("target"), str)
            or not isinstance(item.get("name"), str)
            or type(item.get("agentic", False)) is not bool
            for item in declared):
        return [Diagnostic("error", "SMB6011", "Invalid runtime capability context.", Span(0, 0))]
    if program.target != "shipmblang-bytecode" or program.native_machine_code is not False:
        return [
            Diagnostic(
                "error",
                "SMB6005",
                "Runtime only accepts non-native shipmblang-bytecode programs.",
                Span(0, 0),
                "Compile for the supported bytecode target; native code is not executable by this runtime.",
            )
        ]
    if not program.bytecode:
        return [Diagnostic("error", "SMB6000", "Bytecode program is empty.", Span(0, 0), "Emit a ShipMB prelude first.")]

    # Validate every nested action with the same declaration-order rules before
    # dispatching any instruction. Guards cannot hide invalid bytecode.
    flattened = []
    has_guards = False
    for instruction in program.bytecode:
        if isinstance(instruction, dict) and not _valid_source_span(instruction):
            return [Diagnostic("error", "SMB6013", "Invalid instruction source span.", Span(0, 0))]
        if isinstance(instruction, dict) and instruction.get("opcode") == "guarded_action":
            has_guards = True
            operands = instruction.get("operands")
            action = operands.get("action") if isinstance(operands, dict) else None
            if (program.version != "0.2" or not isinstance(action, dict)
                    or operands.get("guard") != "if_able"
                    or not isinstance(action.get("opcode"), str)
                    or normalize_bytecode_opcode(action["opcode"]) not in GUARDABLE_OPCODES
                    or not isinstance(action.get("operands"), dict)
                    or not _valid_source_span(action)):
                return [Diagnostic("error", "SMB6012", "Invalid guarded action.", _span_from_instruction(instruction))]
            flattened.append({**action, "source_span": instruction.get("source_span", {})})
        else:
            flattened.append(instruction)
    if has_guards:
        return _validate_program(replace(program, bytecode=flattened))

    declared_libraries: set[str] = set()
    declared_devices: set[str] = set()
    declared_capabilities: set[str] = set()
    for index, instruction in enumerate(program.bytecode):
        span = _span_from_instruction(instruction) if isinstance(instruction, dict) else Span(0, 0)
        if not isinstance(instruction, dict):
            diagnostics.append(Diagnostic("error", "SMB6006", "Bytecode instruction must be an object.", span))
            continue
        opcode_value = instruction.get("opcode")
        if not isinstance(opcode_value, str):
            diagnostics.append(Diagnostic("error", "SMB6006", "Bytecode opcode must be a string.", span))
            continue
        opcode = normalize_bytecode_opcode(opcode_value)
        operands = instruction.get("operands")
        if opcode not in KNOWN_BYTECODE_OPCODES:
            diagnostics.append(Diagnostic("error", "SMB6006", f"Unsupported runtime opcode '{opcode_value}'.", span))
            continue
        if not isinstance(operands, dict):
            diagnostics.append(Diagnostic("error", "SMB6006", f"Opcode '{opcode}' requires object operands.", span))
            continue
        if index == 0 and (opcode != "use_prelude" or operands.get("name") != SHIPMB_PRELUDE):
            diagnostics.append(
                Diagnostic("error", "SMB6000", "The ShipMB prelude must be the first bytecode instruction.", span)
            )
            continue

        if opcode == "use_prelude":
            if index != 0 or operands.get("name") != SHIPMB_PRELUDE:
                diagnostics.append(Diagnostic("error", "SMB6000", "Runtime only accepts one ShipMB prelude at the beginning.", span))
        elif opcode == "import_library":
            name = operands.get("name")
            if operands.get("source") != "shipmblang" or name not in list(SHIPMB_LIBRARY_ALLOWLIST):
                diagnostics.append(
                    Diagnostic(
                        "error", "SMB6001", f"Runtime does not allow library {name!r} from this source.", span,
                        "Use the allowlisted tv_pack library from shipmblang.",
                    )
                )
            else:
                declared_libraries.add(name)
        elif opcode == "device_target":
            alias = operands.get("alias")
            if operands.get("name") != "tv" or alias != "tv" or operands.get("platform") not in list(SHIPMB_DEVICE_PLATFORMS):
                diagnostics.append(
                    Diagnostic("error", "SMB6007", "Runtime only supports the declared Roku TV target.", span)
                )
            else:
                declared_devices.add(alias)
        elif opcode == "declare_capability":
            target, name = operands.get("target"), operands.get("name")
            if target != "remote" or name not in list(SHIPMB_CAPABILITY_ALLOWLIST) or not isinstance(operands.get("agentic"), bool):
                diagnostics.append(Diagnostic("error", "SMB6008", "Runtime rejected an unsupported capability declaration.", span))
            else:
                declared_capabilities.add(f"{target}.{name}")
        elif opcode == "run":
            command = operands.get("command")
            if (
                operands.get("target") != "remote"
                or not isinstance(command, str)
                or not command.strip()
                or len(command) > 256
                or "tv_pack" not in declared_libraries
                or "tv" not in list(declared_devices)
                or "remote.execute_command" not in declared_capabilities
            ):
                diagnostics.append(
                    Diagnostic(
                        "error", "SMB6003", "Runtime command lacks an approved, previously declared execution context.", span,
                        "Declare the ShipMB prelude, tv_pack, Roku TV, and remote.execute_command before run.",
                    )
                )
        elif opcode == "install_package":
            if operands.get("package") not in list(SHIPMB_PACKAGE_ALLOWLIST) or operands.get("target") not in list(declared_devices):
                diagnostics.append(Diagnostic("error", "SMB6002", "Runtime rejected this package installation request.", span))
        elif opcode == "declare_interface":
            if operands.get("name") not in list(SHIPMB_INTERFACE_ALLOWLIST) or operands.get("mode") != "client":
                diagnostics.append(Diagnostic("error", "SMB6009", "Runtime rejected this interface declaration.", span))
        elif opcode == "on_error":
            if not isinstance(operands.get("pipeline", []), list):
                diagnostics.append(Diagnostic("error", "SMB6010", "Error handler pipeline must be a list.", span))
        elif opcode == "mcp_tool_call":
            if not isinstance(operands.get("server"), str) or not isinstance(operands.get("tool"), str) or not isinstance(operands.get("arguments", {}), dict):
                diagnostics.append(Diagnostic("error", "SMB6010", "MCP declaration has invalid operands.", span))

    return diagnostics


def _runtime_contract(program: BytecodeProgram) -> dict[str, Any]:
    contract = program.runtime_contract or {}
    identity = {
        "name": "shipmb",
        "owner": "runtime",
        "namespace": "shipmb.runtime",
        "model_neutral": True,
        **contract.get("identity", {}),
    }
    orchestration_role = {
        "name": "shipmb_runtime_orchestrator",
        "owner": "runtime",
        "scope": "bytecode_execution",
        **contract.get("orchestration_role", {}),
    }
    capability_context = {
        "declared": list(contract.get("capability_context", {}).get("declared", [])),
        "source": contract.get("capability_context", {}).get("source", "runtime_observed_declarations"),
    }
    return {
        "identity": identity,
        "orchestration_role": orchestration_role,
        "capability_context": capability_context,
    }


def _record_runtime_capability(state: dict[str, Any], operands: dict[str, Any]) -> None:
    declaration = {
        "target": operands["target"],
        "name": operands["name"],
        "agentic": bool(operands.get("agentic", False)),
        "source": "runtime_declaration",
    }
    existing = {
        (
            capability.get("target"),
            capability.get("name"),
            bool(capability.get("agentic", False)),
        )
        for capability in state["capability_context"]["declared"]
    }
    key = (declaration["target"], declaration["name"], declaration["agentic"])
    if key not in existing:
        state["capability_context"]["declared"].append(declaration)


def normalize_bytecode_opcode(opcode: str) -> str:
    """Accept legacy uppercase bytecode while canonical output stays lowercase."""
    return LEGACY_BYTECODE_OPCODE_ALIASES.get(opcode, opcode)


def _missing_capabilities(state: dict[str, Any], required: list[str]) -> list[str]:
    return [capability for capability in required if capability not in state["capabilities"]]


def _missing_runtime_capability(capability: str, span: Span) -> Diagnostic:
    return Diagnostic(
        "error",
        "SMB6003",
        f"Runtime command requires missing capability '{capability}'.",
        span,
        "Declare the capability in prose before executing commands.",
    )


def _valid_source_span(instruction: dict[str, Any]) -> bool:
    span = instruction.get("source_span", {})
    if not isinstance(span, dict):
        return False
    start, end = span.get("start", 0), span.get("end", 0)
    return type(start) is int and type(end) is int and 0 <= start <= end


def _span_from_instruction(instruction: dict[str, Any]) -> Span:
    source_span = instruction.get("source_span", {})
    if not isinstance(source_span, dict):
        return Span(0, 0)
    try:
        start = int(source_span.get("start", 0))
        end = int(source_span.get("end", 0))
    except (TypeError, ValueError, OverflowError):
        return Span(0, 0)
    return Span(max(0, start), max(0, end))
