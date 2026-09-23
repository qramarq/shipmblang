from __future__ import annotations

from .models import IROp, SemanticModel, SemanticOp, Span


OPCODE_MAP = {
    "prelude.use": "USE_PRELUDE",
    "use.declare": "USE_DECLARATION",
    "library.import": "IMPORT_LIBRARY",
    "device.target": "DEVICE_TARGET",
    "capability.declare": "DECLARE_CAPABILITY",
    "error.handler": "ON_ERROR",
    "package.install": "INSTALL_PACKAGE",
    "interface.declare": "DECLARE_INTERFACE",
    "runtime.run": "RUN",
    "mcp.tool.call": "MCP_TOOL_CALL",
}


def intermediate_code_generation(semantic_model: SemanticModel) -> list[IROp]:
    ir: list[IROp] = []
    for index, op in enumerate(semantic_model.ops, start=1):
        ir.append(_lower_op(index, op))
    return ir


def generated_span() -> Span:
    return Span(0, 0)


def _lower_op(index: int, op: SemanticOp) -> IROp:
    opcode = OPCODE_MAP.get(op.op, op.op.upper().replace(".", "_"))
    result, arg1, arg2 = _three_address_parts(op)
    return IROp(
        ir=f"ir_{index:04d}",
        op=opcode,
        result=result,
        arg1=arg1,
        arg2=arg2,
        args=op.args,
        type=op.type,
        effects=op.effects,
        span=op.span,
    )


def _three_address_parts(op: SemanticOp) -> tuple[str | None, str | None, str | None]:
    if op.op == "prelude.use":
        return f"prelude.{op.args['name']}", op.args["name"], None
    if op.op == "use.declare":
        return f"use.{op.args['name']}", op.args["name"], op.args.get("source")
    if op.op == "library.import":
        return f"lib.{op.args['name']}", op.args["name"], op.args["source"]
    if op.op == "device.target":
        return op.args["alias"], op.args["platform"], op.args["name"]
    if op.op == "capability.declare":
        return op.args["name"], op.args["target"], op.args["name"]
    if op.op == "error.handler":
        return "error_handler", "error", "printurf_show"
    if op.op == "package.install":
        return f"install.{op.args['package']}", op.args["package"], op.args["target"]
    if op.op == "interface.declare":
        return op.args["name"], op.args["name"], op.args["mode"]
    if op.op == "mcp.tool.call":
        return f"mcp.{op.args['tool']}", op.args["server"], op.args["tool"]
    return None, None, None
