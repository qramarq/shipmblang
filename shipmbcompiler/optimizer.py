from __future__ import annotations

from dataclasses import replace

from .ir import generated_span
from .models import IROp


PRELUDE_EFFECT_OPS = {"DEVICE_TARGET", "DECLARE_CAPABILITY", "INSTALL_PACKAGE", "DECLARE_INTERFACE", "ON_ERROR"}


def code_optimization(intermediate_code: list[IROp]) -> list[IROp]:
    optimized: list[IROp] = []
    seen_preludes: set[str] = set()
    seen_uses: set[tuple[str, str, str]] = set()
    seen_imports: set[tuple[str, str]] = set()
    seen_devices: set[tuple[str, str, str]] = set()
    seen_capabilities: set[tuple[str, str, bool]] = set()
    seen_interfaces: set[tuple[str, str]] = set()
    needs_prelude = any(op.op in PRELUDE_EFFECT_OPS for op in intermediate_code)
    has_prelude = any(op.op == "USE_PRELUDE" and op.arg1 == "shipmb" for op in intermediate_code)

    if needs_prelude and not has_prelude:
        optimized.append(
            IROp(
                "ir_0000",
                "USE_PRELUDE",
                "prelude.shipmb",
                "shipmb",
                None,
                {"name": "shipmb", "generated": True},
                "Module",
                [],
                generated_span(),
            )
        )

    for op in intermediate_code:
        if op.op == "USE_PRELUDE":
            key = str(op.args.get("name"))
            if key in seen_preludes:
                continue
            seen_preludes.add(key)
        if op.op == "USE_DECLARATION":
            key = (
                str(op.args.get("name")),
                str(op.args.get("source")),
                str(op.args.get("declaration_kind")),
            )
            if key in seen_uses:
                continue
            seen_uses.add(key)
        if op.op == "IMPORT_LIBRARY":
            key = (str(op.args.get("name")), str(op.args.get("source")))
            if key in seen_imports:
                continue
            seen_imports.add(key)
        if op.op == "DEVICE_TARGET":
            key = (str(op.args.get("name")), str(op.args.get("platform")), str(op.args.get("alias")))
            if key in seen_devices:
                continue
            seen_devices.add(key)
        if op.op == "DECLARE_CAPABILITY":
            key = (str(op.args.get("target")), str(op.args.get("name")), bool(op.args.get("agentic")))
            if key in seen_capabilities:
                continue
            seen_capabilities.add(key)
        if op.op == "DECLARE_INTERFACE":
            key = (str(op.args.get("name")), str(op.args.get("mode")))
            if key in seen_interfaces:
                continue
            seen_interfaces.add(key)
        optimized.append(op)

    return _renumber(optimized)


def _renumber(ops: list[IROp]) -> list[IROp]:
    return [replace(op, ir=f"ir_{index:04d}") for index, op in enumerate(ops, start=1)]
