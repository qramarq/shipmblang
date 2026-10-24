"""ShipMBLang CLI preserving legacy commands with lazy compiler dispatch."""

import sys
from pathlib import Path

from .standalone import MODEL_COMMANDS, is_standalone, model_extras_message

_CLI_MODULES = frozenset({"shipmblang", "shipmblang.cli", "shipmblang.__main__"})


def is_bare_shipmb_file(token: str) -> bool:
    """True when a token is a ``.shipmb`` path rather than a flag or command."""
    if not token or token.startswith("-"):
        return False
    return token.lower().endswith(".shipmb")


def _option_present(args, *names) -> bool:
    for arg in args:
        for name in names:
            if arg == name or arg.startswith(name + "="):
                return True
    return False


def _option_value(args, name):
    for index, arg in enumerate(args):
        if arg == name and index + 1 < len(args):
            return args[index + 1]
        if arg.startswith(name + "="):
            return arg.split("=", 1)[1]
    return None


def bare_file_argv(argv):
    """Rewrite ``program.shipmb`` into the documented run defaults.

    ``argv`` excludes the program name. Existing subcommands are unchanged.
    Explicit ``--pipeline``, ``--profile``, and ``--memory`` values are kept.
    ``--profile`` is added only for the direct pipeline, matching the run command.
    """
    if not argv or not is_bare_shipmb_file(argv[0]):
        return list(argv)
    program, rest = argv[0], list(argv[1:])
    if _option_present(rest, "--file"):
        print("shipmblang: pass either a .shipmb file or --file, not both.", file=sys.stderr)
        raise SystemExit(2)
    rewritten = ["run"]
    pipeline = _option_value(rest, "--pipeline")
    if pipeline is None:
        rewritten.extend(["--pipeline", "direct"])
        pipeline = "direct"
    if pipeline == "direct" and not _option_present(rest, "--profile"):
        rewritten.extend(["--profile", "general"])
    if not _option_present(rest, "--memory", "--memory-path", "--memory-db"):
        rewritten.extend(["--memory", "off"])
    rewritten.extend(["--file", program])
    return rewritten + rest


def _configure_frozen_stdio():
    if not is_standalone():
        return
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if stream is None or not hasattr(stream, "reconfigure"):
            continue
        try:
            stream.reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass


def _reject_model_extras():
    print(f"shipmblang: {model_extras_message()}", file=sys.stderr)
    raise SystemExit(2)


def _run_frozen_module(module, argv):
    """Emulate ``python -m`` for editor and media callbacks inside the executable."""
    sys.argv = [sys.argv[0], *argv]
    if module == "shipmblang.editor_bridge":
        from .editor_bridge import main as entry

        raise SystemExit(entry())
    if module == "shipmblang.media_worker":
        from .media_worker import run

        if len(argv) != 1:
            print("shipmblang: media worker expects a workspace path.", file=sys.stderr)
            raise SystemExit(2)
        run(Path(argv[0]).resolve())
        raise SystemExit(0)
    if module == "shipmblang.media_preview":
        from .media_preview import worker

        if len(argv) != 1:
            print("shipmblang: media preview expects a status path.", file=sys.stderr)
            raise SystemExit(2)
        worker(Path(argv[0]))
        raise SystemExit(0)
    import importlib

    try:
        imported = importlib.import_module(module)
    except ModuleNotFoundError as error:
        print(f"shipmblang: cannot run {module} from the standalone executable ({error}).", file=sys.stderr)
        raise SystemExit(2) from error
    entry = getattr(imported, "main", None)
    if not callable(entry):
        print(f"shipmblang: {module} has no main entry point in the standalone executable.", file=sys.stderr)
        raise SystemExit(2)
    result = entry()
    raise SystemExit(0 if result is None else result)


def _peel_frozen_python_args(argv):
    """Accept the editor's ``python -X utf8 -m module`` callback when frozen.

    The installed console script does not see Python's ``-X`` / ``-m`` flags,
    so this rewrite runs only for the standalone executable.
    """
    if not is_standalone():
        return list(argv)
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "-X" and index + 1 < len(argv):
            index += 2
            continue
        if token.startswith("-X") and token != "-X":
            index += 1
            continue
        break
    if index >= len(argv) or argv[index] != "-m":
        return list(argv[index:])
    if index + 1 >= len(argv):
        print("shipmblang: -m requires a module name.", file=sys.stderr)
        raise SystemExit(2)
    module = argv[index + 1]
    rest = list(argv[index + 2:])
    if module in _CLI_MODULES:
        return rest
    _run_frozen_module(module, rest)
    return rest


def main():
    _configure_frozen_stdio()
    from .standalone import activate_packed_vision_library

    activate_packed_vision_library()
    from .setup_tools import apply_recorded_tool_env

    apply_recorded_tool_env()
    argv = _peel_frozen_python_args(sys.argv[1:])
    argv = bare_file_argv(argv)
    sys.argv = [sys.argv[0], *argv]
    if is_standalone() and len(sys.argv) > 1 and sys.argv[1] in MODEL_COMMANDS:
        _reject_model_extras()
    if len(sys.argv) > 1 and sys.argv[1] in {"--version", "-V"}:
        from .lsp import shipmblang_version

        print(f"shipmblang {shipmblang_version()}")
        return 0
    if len(sys.argv) > 1 and sys.argv[1] == "lsp":
        from .lsp import main as lsp_main

        previous = sys.argv
        sys.argv = [previous[0], *previous[2:]]
        try:
            return lsp_main()
        finally:
            sys.argv = previous
    if len(sys.argv) > 1 and sys.argv[1] == "hyperframes":
        from .hyperframes import main as hyperframes_main

        previous = sys.argv
        sys.argv = [previous[0], *previous[2:]]
        try:
            return hyperframes_main()
        finally:
            sys.argv = previous
    if len(sys.argv) > 1 and sys.argv[1] in {"notebook", "editor"}:
        from .editor import main as editor_main

        previous = sys.argv
        sys.argv = [previous[0], *previous[2:]]
        try:
            return editor_main()
        finally:
            sys.argv = previous
    if len(sys.argv) > 1 and sys.argv[1] in {"compile", "ship", "run", "ship-run"}:
        from . import pipelines

        command = sys.argv[1]
        previous = sys.argv
        sys.argv = previous[1:]
        try:
            return (pipelines.run_main if command in {"run", "ship-run"} else pipelines.main)()
        finally:
            sys.argv = previous
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        from .setup_tools import main as setup_main

        raise SystemExit(setup_main(sys.argv[2:]))
    from driplm.__main__ import main as legacy_main

    return legacy_main()


__all__ = ["bare_file_argv", "is_bare_shipmb_file", "main"]
