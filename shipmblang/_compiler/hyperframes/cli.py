"""Development CLI, also reusable by the language's bundled compiler."""
import argparse
import json
from pathlib import Path
import sys

from ..limits import MAX_SOURCE_CHARS, read_text_limited
from . import compile_hyperframes, write_hyperframes_project, render_hyperframes_project


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        print(json.dumps({"status": "error", "diagnostics": [{"level": "error", "code": "SMBCLI001", "message": message, "span": None}]}))
        self.exit(2)


def main(argv=None):
    parser = _Parser(prog="shipmbc hyperframes")
    commands = parser.add_subparsers(dest="command", required=True)
    compile_parser = commands.add_parser("compile")
    compile_parser.add_argument("source", nargs="?")
    compile_parser.add_argument("--out", "--output", required=True)
    compile_parser.add_argument("--asset-root")
    render_parser = commands.add_parser("render")
    render_parser.add_argument("directory")
    render_parser.add_argument("--out", "--output", required=True)
    render_parser.add_argument("--timeout", type=float, default=600)
    for command in (compile_parser, render_parser):
        command.add_argument("--diagnostic-format", choices=["json", "text"], default="json")
    args = parser.parse_args(argv)
    try:
        if args.command == "compile":
            source = read_text_limited(Path(args.source), MAX_SOURCE_CHARS) if args.source else sys.stdin.read(MAX_SOURCE_CHARS + 1)
            result = compile_hyperframes(source)
            if result["status"] == "compiled":
                written = write_hyperframes_project(result["target_code"], args.out,
                    asset_root=args.asset_root or (Path(args.source).resolve().parent if args.source else Path.cwd()))
                result = {**written, "diagnostics": result["diagnostics"] + written["diagnostics"]}
        else:
            result = render_hyperframes_project(args.directory, args.out, timeout=args.timeout)
    except (OSError, ValueError) as error:
        result = {"status": "error", "diagnostics": [{"level": "error", "code": "SMBHF100", "message": str(error), "span": None}]}
    print(json.dumps(result, indent=2))
    return 1 if result["status"] == "error" else 0
