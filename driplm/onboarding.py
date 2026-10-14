"""ShipMB onboarding contract for preparing ShipMBLang locally."""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from importlib import metadata
from pathlib import Path
from typing import Any, Callable

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 source checkouts can still use metadata defaults.
    tomllib = None


SCHEMA_VERSION = 1
PROBE_PROGRAM = "Use ShipMB. When an error happens, explain it with printurf and show the report."
PROBE_DECLARATION_PROGRAM = (
    "Use Python. Call helper with total. "
    "Define a function helper that takes value and returns total. "
    "Declare an integer variable total set to 0."
)
REQUIRED_PUBLIC_API = (
    "compile_natural_program",
    "run_natural_program",
    "printurf",
)


def build_onboarding_manifest(
    *,
    root: str | os.PathLike[str] | None = None,
    python_executable: str | None = None,
    run_checks: bool = False,
) -> dict[str, Any]:
    """Return the machine-readable contract ShipMB should use during setup."""

    source_root = find_source_root()
    project_root = Path(root or os.getcwd()).resolve()
    python = python_executable or sys.executable
    project_metadata = read_project_metadata(source_root)

    install_command = [python, "-m", "pip", "install", "-e", str(source_root)]
    verify_command = [
        python,
        "-m",
        "shipmblang",
        "onboarding",
        "--format",
        "json",
        "--check",
        "--root",
        str(project_root),
    ]

    checks = run_onboarding_checks(project_root) if run_checks else []
    return {
        "schema_version": SCHEMA_VERSION,
        "name": "shipmblang",
        "version": project_metadata.get("version", "0.1.0"),
        "description": project_metadata.get(
            "description",
            "ShipMBLang local compiler, runtime, printurf, and MCP support for ShipMB.",
        ),
        "status": checks_status(checks) if run_checks else "metadata",
        "source_root": str(source_root),
        "project_root": str(project_root),
        "requires_python": project_metadata.get("requires_python", ">=3.10"),
        "python": {
            "executable": python,
            "version": platform.python_version(),
        },
        "install": {
            "mode": "editable-source",
            "argv": install_command,
            "description": "Install ShipMBLang from this checkout into the Python environment used by ShipMB.",
        },
        "verify": {
            "argv": verify_command,
            "description": "Validate that ShipMBLang imports, compiles, runs lightweight bytecode, and exposes MCP entrypoints.",
        },
        "commands": {
            "compile": [python, "-m", "shipmblang", "compile"],
            "run": [python, "-m", "shipmblang", "run"],
            "printurf": [python, "-m", "shipmblang", "printurf"],
            "mcp": [python, "-m", "shipmblang", "mcp"],
            "onboarding": [python, "-m", "shipmblang", "onboarding"],
        },
        "compiler_contract": {
            "target": "shipmblang-bytecode",
            "core": "ShipMBLangCore",
            "declaration_resolution": "order-insensitive within a compilation unit",
            "declaration_pass": "collect declarations before resolving references",
            "effectful_action_order": "preserve source bytecode order at runtime",
        },
        "mcp": {
            "server_name": "shipmblang",
            "command": python,
            "args": ["-m", "shipmblang", "mcp"],
            "tools": [
                "printurf",
                "shipmblang_explain_error",
                "shipmblang_index_codebase",
                "shipmblang_list_device_families",
                "shipmblang_select_device_family",
                "shipmblang_get_device_resource",
            ],
        },
        "environment": {
            "SHIPMBLANG_HOME": str(source_root),
            "SHIPMBLANG_PYTHON": python,
            "SHIPLANG_CHECKPOINT": "checkpoints/best_model.pt",
            "SHIPLANG_TOKENIZER": "data/tokenizer.json",
            "SHIPLANG_DEVICE": "cpu",
        },
        "artifacts": {
            "docs": str(source_root / "docs" / "shipmb-onboarding.md"),
            "static_manifest": str(source_root / "shipmblang-onboarding.json"),
            "vscode_extension": str(source_root / "extensions" / "vscode-shipmblang"),
        },
        "checks": checks,
    }


def run_onboarding_checks(root: str | os.PathLike[str] | None = None) -> list[dict[str, str]]:
    """Run a safe local readiness smoke test without downloads or training."""

    project_root = Path(root or os.getcwd()).resolve()
    return [
        _check("python", "Python runtime is supported", _check_python),
        _check("public_api", "ShipMBLang public API imports", _check_public_api),
        _check("compiler", "Natural syntax compiles to ShipMBLang bytecode", lambda: _check_compiler(project_root)),
        _check("runtime", "Supported bytecode executes locally", lambda: _check_runtime(project_root)),
        _check("printurf", "printurf returns a structured diagnostic", _check_printurf),
        _check("mcp_entrypoint", "MCP server entrypoint imports", _check_mcp_entrypoint),
    ]


def checks_status(checks: list[dict[str, str]]) -> str:
    if not checks:
        return "metadata"
    if all(check["status"] == "pass" for check in checks):
        return "ready"
    return "blocked"


def find_source_root() -> Path:
    """Locate the ShipMBLang source checkout when running from source or editable install."""

    start = Path(__file__).resolve()
    for parent in (start.parent, *start.parents):
        if (parent / "pyproject.toml").exists() and (parent / "README.md").exists():
            return parent
    return Path.cwd().resolve()


def read_project_metadata(source_root: Path) -> dict[str, str]:
    try:
        return {
            "version": metadata.version("shipmblang"),
            "description": metadata.metadata("shipmblang").get("Summary", ""),
            "requires_python": metadata.metadata("shipmblang").get("Requires-Python", ""),
        }
    except metadata.PackageNotFoundError:
        pyproject_path = source_root / "pyproject.toml"
        if not pyproject_path.exists() or tomllib is None:
            return {}
        with pyproject_path.open("rb") as handle:
            pyproject = tomllib.load(handle)
        project = pyproject.get("project", {})
        return {
            "version": str(project.get("version", "")),
            "description": str(project.get("description", "")),
            "requires_python": str(project.get("requires-python", "")),
        }


def render_text_manifest(manifest: dict[str, Any]) -> str:
    lines = [
        f"ShipMBLang onboarding: {manifest['status']}",
        f"source_root: {manifest['source_root']}",
        f"project_root: {manifest['project_root']}",
        "install: " + _join_argv(manifest["install"]["argv"]),
        "verify: " + _join_argv(manifest["verify"]["argv"]),
        "mcp: " + _join_argv([manifest["mcp"]["command"], *manifest["mcp"]["args"]]),
    ]
    if manifest["checks"]:
        lines.append("checks:")
        lines.extend(
            f"- {check['status']} {check['name']}: {check['detail']}"
            for check in manifest["checks"]
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print and validate the ShipMBLang onboarding contract.")
    parser.add_argument("--root", default=".", help="ShipMB project root to use for lightweight validation.")
    parser.add_argument("--check", action="store_true", help="Run safe import/compiler/runtime/MCP readiness checks.")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args(argv)

    manifest = build_onboarding_manifest(root=args.root, run_checks=args.check)
    if args.format == "json":
        print(json.dumps(manifest, indent=2))
    else:
        print(render_text_manifest(manifest))

    return 1 if args.check and manifest["status"] != "ready" else 0


def _check(name: str, description: str, func: Callable[[], str]) -> dict[str, str]:
    try:
        detail = func()
        return {"name": name, "description": description, "status": "pass", "detail": detail}
    except Exception as exc:  # pragma: no cover - exercised by failure mode in callers
        return {
            "name": name,
            "description": description,
            "status": "fail",
            "detail": f"{type(exc).__name__}: {exc}",
        }


def _check_python() -> str:
    if sys.version_info < (3, 10):
        raise RuntimeError(f"Python 3.10+ is required; found {platform.python_version()}")
    return platform.python_version()


def _check_public_api() -> str:
    import shipmblang

    missing = [name for name in REQUIRED_PUBLIC_API if not hasattr(shipmblang, name)]
    if missing:
        raise RuntimeError("missing public API: " + ", ".join(missing))
    return "available: " + ", ".join(REQUIRED_PUBLIC_API)


def _check_compiler(project_root: Path) -> str:
    from .natural_syntax import compile_natural_program

    program = compile_natural_program(PROBE_PROGRAM, root=str(project_root))
    target_code = program.get("target_code") or {}
    bytecode = program.get("bytecode") or []
    if target_code.get("target") != "shipmblang-bytecode":
        raise RuntimeError(f"unexpected target: {target_code.get('target')!r}")
    if not any(op.get("op") == "use" and op.get("module") == "shipmb" for op in bytecode):
        raise RuntimeError("compiled bytecode did not load shipmb")
    declaration_program = compile_natural_program(PROBE_DECLARATION_PROGRAM, root=str(project_root))
    resolution = declaration_program.get("semantic_model", {}).get("declaration_resolution", {})
    references = resolution.get("references", [])
    if resolution.get("name_resolution") != "order_insensitive":
        raise RuntimeError("compiler did not report order-insensitive declaration resolution")
    if resolution.get("unresolved_references"):
        raise RuntimeError("forward declaration references were not resolved")
    if not any(reference.get("target") == "function:helper" for reference in references):
        raise RuntimeError("forward function reference did not resolve")
    if not any(reference.get("target") == "variable:total" for reference in references):
        raise RuntimeError("forward variable reference did not resolve")
    return f"{len(bytecode)} bytecode ops; declaration references resolve after collection"


def _check_runtime(project_root: Path) -> str:
    from .natural_syntax import run_natural_program

    result = run_natural_program("Use ShipMB. Show program.", root=str(project_root))
    if "program" not in result or "state" not in result:
        raise RuntimeError("runtime result is missing program or state")
    return "local bytecode runner returned program and state"


def _check_printurf() -> str:
    from .error_explainer import build_printurf_report, render_printurf_report

    report = build_printurf_report(
        raw_error="NameError: name 'SHIPMBLANG_READY' is not defined",
        code_context="> 1: print(SHIPMBLANG_READY)",
    )
    if not report.get("diagnostics"):
        raise RuntimeError("printurf returned no diagnostics")
    rendered = render_printurf_report(report)
    if not (rendered.startswith("Error: ") and " Cause: " in rendered and " Fix: " in rendered):
        raise RuntimeError("printurf did not return the strict editor contract")
    return "strict Error/Cause/Fix diagnostic"


def _check_mcp_entrypoint() -> str:
    from .mcp_server import main as mcp_main

    if not callable(mcp_main):
        raise RuntimeError("mcp main is not callable")
    return "python -m shipmblang mcp"


def _join_argv(argv: list[str]) -> str:
    return " ".join(_quote_arg(part) for part in argv)


def _quote_arg(value: str) -> str:
    if not value:
        return '""'
    if any(char.isspace() for char in value):
        return '"' + value.replace('"', '\\"') + '"'
    return value


if __name__ == "__main__":
    raise SystemExit(main())
