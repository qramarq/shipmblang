"""Try the local language sources without installing packages."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shipmblang.pipelines import run_direct_program

EXAMPLES = [
    ("Show 2 plus 3.", "5\n"),
    ("Start with total at 4, then add 8 to total and show total.", "12\n"),
    (ROOT / "examples/general_sum.shipmb", "27\n"),
    (ROOT / "examples/general_functions.shipmb", "720\n"),
]


def run(source, *, model=False, expected=None, verbose=False):
    options = {} if model else {"model_provider": None}
    result = run_direct_program(source, memory=False, **options)
    if verbose:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    if result.get("interpretation_source"):
        print("Interpretation:", result["interpretation_source"])
    output = result.get("runtime", {}).get("stdout", "")
    print("Output:\n" + (output or "(no output)"))
    for item in result.get("clarifications", []):
        print("Clarification:", item["question"])
    for item in result.get("diagnostics", []):
        print(item["level"] + ":", item["message"])
    ok = result.get("status") == "compiled" and "runtime" in result
    ok = ok and not any(d["level"] == "error" for d in result.get("diagnostics", []))
    if expected is not None:
        ok = ok and output == expected
        print("PASS" if ok else f"FAIL (expected {expected!r})")
    return ok


def suite(model=False):
    passed = 0
    for source, expected in EXAMPLES:
        if isinstance(source, Path):
            source = source.read_text(encoding="utf-8-sig")
        print("\nProgram:\n" + source)
        passed += run(source, model=model, expected=expected)
    print(f"\n{passed}/{len(EXAMPLES)} checks passed.")
    return passed == len(EXAMPLES)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--file", type=Path)
    mode.add_argument("--request")
    mode.add_argument("--suite", action="store_true")
    parser.add_argument("--model", action="store_true", help="Allow your configured model to translate broader English.")
    parser.add_argument("--json", action="store_true", help="Also show the full compiler/runtime result.")
    args = parser.parse_args()
    print("ShipMBLang tester | " + ("configured model enabled" if args.model else "offline grammar; no model requests"))
    if args.suite:
        return 0 if suite(args.model) else 1
    if args.file is not None or args.request is not None:
        source = args.file.read_text(encoding="utf-8-sig") if args.file else args.request
        return 0 if run(source, model=args.model, verbose=args.json) else 1
    print('Try: Show 2 plus 3.\nCommands: :suite, :paste, :file PATH, :quit')
    while True:
        try:
            source = input("\nEnglish> ").strip()
            if source == ":quit":
                return 0
            if source == ":suite":
                suite(args.model)
                continue
            if source == ":paste":
                print("Paste your program. Enter :end on its own line to run it.")
                lines = []
                while (line := input()) != ":end":
                    lines.append(line)
                source = "\n".join(lines)
            elif source.startswith(":file "):
                source = Path(source[6:].strip().strip('"')).read_text(encoding="utf-8-sig")
            if source:
                run(source, model=args.model, verbose=args.json)
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        except (OSError, ValueError, RuntimeError) as error:
            print("Error:", error)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print("Error:", error, file=sys.stderr)
        sys.exit(1)
