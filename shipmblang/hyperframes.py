"""Deterministic HyperFrames adapters for the private compiler snapshot."""
from __future__ import annotations

import argparse
import importlib
import json
import math
from pathlib import Path

from .pipelines import CompilerUnavailableError


def _compiler():
    try:
        return importlib.import_module("shipmblang._compiler.hyperframes")
    except ModuleNotFoundError as error:
        if error.name not in {"shipmblang._compiler", "shipmblang._compiler.hyperframes"}:
            raise
        raise CompilerUnavailableError(
            "This ShipMBLang compiler snapshot lacks HyperFrames support. "
            "Install a ShipMBLang build containing the HyperFrames compiler."
        ) from error


def compile_hyperframes(source):
    """Compile supported prose without a model or rendering subprocess."""
    return _compiler().compile_hyperframes(source)


def write_hyperframes_project(artifact, directory, *, asset_root=None):
    """Write the compiled project and resolve assets relative to asset_root."""
    return _compiler().write_hyperframes_project(artifact, directory, asset_root=asset_root)


def render_hyperframes_project(directory, output, *, timeout=600):
    """Explicitly invoke the optional HyperFrames renderer."""
    return _compiler().render_hyperframes_project(directory, output, timeout=timeout)


def _timeout(value):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("timeout must be a finite positive number")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    compile_parser = commands.add_parser("compile", help="Compile a source file into an HTML project")
    compile_parser.add_argument("source", type=Path)
    compile_parser.add_argument("--out", "--output", "-o", dest="output", type=Path, required=True)
    compile_parser.add_argument("--asset-root", type=Path, help="Defaults to the source file's directory")
    render_parser = commands.add_parser("render", help="Render an existing project using optional Node tools")
    render_parser.add_argument("directory", type=Path)
    render_parser.add_argument("--out", "--output", "-o", dest="output", type=Path, required=True)
    render_parser.add_argument("--timeout", type=_timeout, default=600)
    args = parser.parse_args()
    try:
        if args.command == "compile":
            artifact = compile_hyperframes(args.source.read_text(encoding="utf-8-sig"))
            result = artifact
            if artifact.get("status") == "compiled":
                result = write_hyperframes_project(
                    artifact, args.output,
                    asset_root=args.asset_root or args.source.resolve().parent,
                )
                result = {**result, "diagnostics": [*artifact.get("diagnostics", []), *result.get("diagnostics", [])]}
        else:
            result = render_hyperframes_project(args.directory, args.output, timeout=args.timeout)
    except (OSError, ValueError, CompilerUnavailableError) as error:
        result = {"status": "error", "diagnostics": [{"level": "error", "message": str(error)}]}
    print(json.dumps(result, indent=2))
    if result.get("status") not in {"compiled", "written", "rendered"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
