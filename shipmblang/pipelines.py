"""Optional compiler integration; legacy and compiler artifacts stay distinct."""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import os
from pathlib import Path
import sys


class CompilerUnavailableError(RuntimeError):
    """The selected optional compiler cannot be loaded."""


def _compiler():
    if sys.version_info < (3, 11):
        raise CompilerUnavailableError("The direct and ir pipelines require Python 3.11 or newer.")
    try:
        compiler = importlib.import_module("shipmbcompiler")
    except ModuleNotFoundError as error:
        if error.name != "shipmbcompiler":
            raise
        raise CompilerUnavailableError(
            'Install the optional compiler with: python -m pip install "shipmblang[direct]"'
        ) from error
    if not callable(getattr(compiler, "compile_direct_program", None)):
        raise CompilerUnavailableError("Install shipmbcompiler>=0.2.1,<0.3; this compiler lacks the direct API.")
    return compiler


def _memory_enabled(requested, memory_path=None):
    return requested and (memory_path is not None or os.environ.get("SHIPMB_MEMORY", "").lower() not in {"off", "0", "false"})


def compile_direct_program(source, *, memory=True, memory_path=None, project=None,
                           bindings=None, clarification_answers=None, model_provider=None,
                           profile="roku"):
    """Delegate to the optional compiler without importing the legacy pipeline.

    Results retain the compiler's status, diagnostics and artifact schema. No
    automatic fallback or model selection occurs.
    """
    if profile not in {"roku", "general"}:
        raise ValueError("profile must be 'roku' or 'general'")
    compile_program = _compiler().compile_direct_program
    parameters = inspect.signature(compile_program).parameters
    supports_profile = "profile" in parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values())
    if profile == "general" and not supports_profile:
        raise CompilerUnavailableError("This compiler does not support the general profile. Install a profile-capable shipmbcompiler>=0.2.1,<0.3 build.")
    return compile_program(
        source, memory=_memory_enabled(memory, memory_path),
        memory_path=memory_path or os.environ.get("SHIPMB_MEMORY_DB"), project=project,
        bindings=bindings, clarification_answers=clarification_answers,
        model_provider=model_provider,
        **({"profile": profile} if supports_profile else {}),
    )


def _ready(result):
    return (result.get("status", "compiled") == "compiled"
            and result.get("target_code") is not None
            and not any(d.get("level") == "error" for d in result.get("diagnostics", [])))


def _run_direct_result(result, *, host=None):
    if not _ready(result):
        return result
    from shipmbcompiler.runtime import run_artifact

    state, diagnostics = run_artifact(result["target_code"], **({"host": host} if host is not None else {}))
    return {**result, "runtime": state,
            "diagnostics": [*result.get("diagnostics", []), *[d.to_dict() for d in diagnostics]]}


def run_direct_program(source, *, host=None, **compile_options):
    """Compile and run a direct artifact; only an explicitly supplied host is used."""
    return _run_direct_result(compile_direct_program(source, **compile_options), host=host)


def main():
    _main(run=False)


def run_main():
    _main(run=True)


def _main(*, run):
    selector = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    selector.add_argument("--pipeline", choices=["legacy", "direct", "ir"], default="legacy")
    selector.add_argument("--profile", choices=["roku", "general"])
    selector.add_argument("--run", action="store_true")
    selector.add_argument("--memory", choices=["on", "off"], default="on")
    selector.add_argument("--memory-path", "--memory-db", dest="memory_path")
    selected, remaining = selector.parse_known_args()
    if selected.run and selected.pipeline != "direct":
        selector.error("--run requires --pipeline direct; use the run command for legacy or ir.")
    run = run or selected.run
    if selected.profile is not None and selected.pipeline != "direct":
        selector.error("--profile requires --pipeline direct.")
    if selected.pipeline == "legacy":
        from driplm import natural_syntax

        previous = sys.argv
        memory_args = ["--memory", selected.memory]
        if selected.memory_path:
            memory_args.extend(["--memory-path", selected.memory_path])
        sys.argv = [previous[0], *memory_args, *remaining]
        try:
            (natural_syntax.run_main if run else natural_syntax.main)()
        finally:
            sys.argv = previous
        return

    parser = argparse.ArgumentParser(description="Compile English using the optional ShipMB compiler.")
    parser.add_argument("text", nargs="*")
    parser.add_argument("--file")
    parser.add_argument("--root")
    parser.add_argument("--interpretation", help="Explicit clarified English for the original source (direct pipeline only).")
    parser.add_argument("--format", choices=["bytecode", "json", "core", "text"], default="json" if run else "bytecode")
    args = parser.parse_args(remaining)
    if args.format == "core" or (args.format == "text" and not run):
        parser.error("Use --pipeline legacy for Core output; direct and ir here emit compiler bytecode or JSON.")
    if args.interpretation is not None and selected.pipeline != "direct":
        parser.error("--interpretation requires --pipeline direct.")
    try:
        source = Path(args.file).read_text(encoding="utf-8") if args.file else " ".join(args.text)
        if selected.pipeline == "direct":
            result = compile_direct_program(
                source, memory=selected.memory == "on", memory_path=selected.memory_path,
                project=args.root,
                clarification_answers={"interpretation": args.interpretation} if args.interpretation is not None else None,
                profile=selected.profile or "roku",
            )
        else:
            result = _compiler().compile_source(
                source, include_core=False, run=run, memory=_memory_enabled(selected.memory == "on", selected.memory_path),
                memory_path=selected.memory_path or os.environ.get("SHIPMB_MEMORY_DB"), project=args.root,
            )
        ready = _ready(result)
        if run and ready and selected.pipeline == "direct":
            result = _run_direct_result(result)
            ready = _ready(result)
        # Never hide clarification questions or unsupported explanations behind null bytecode.
        output = result if run or args.format == "json" or not ready else result["target_code"]
        if output is result.get("target_code"):
            for diagnostic in result.get("diagnostics", []):
                if diagnostic.get("level") == "warning":
                    print(f"shipmblang: {diagnostic.get('code', 'warning')}: {diagnostic.get('message', '')}", file=sys.stderr)
        print(json.dumps(output, indent=2))
        if not ready:
            raise SystemExit(1)
    except (CompilerUnavailableError, OSError, ValueError) as error:
        print(f"shipmblang: {error}", file=sys.stderr)
        raise SystemExit(2) from error
