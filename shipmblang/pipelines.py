"""Bundled compiler integration; legacy and compiler artifacts stay distinct."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import importlib
import inspect
import json
import math
import os
from pathlib import Path
import sys


class CompilerUnavailableError(RuntimeError):
    """The bundled compiler cannot be loaded."""


_CONFIGURED_MODEL = object()


def _english_model(profile, ffmpeg_catalog=None, ffmpeg_path=None):
    """Load the configured model only if deterministic parsing needs help."""
    def propose(source, images=None):
        from .providers import load_chat_provider
        from shipmblang._compiler.english_model import EnglishModelFrontend

        provider = load_chat_provider()
        if provider is None:
            return {"question": (
                "Broader English translation needs a configured model. Set "
                "SHIPMB_MODEL_PROVIDER=openai_compatible, SHIPMB_MODEL_BASE_URL, "
                "and SHIPMB_MODEL_NAME, or restate the request in supported English."
            )}
        catalog = ffmpeg_catalog
        if catalog is None and ffmpeg_path is not None:
            from shipmblang._compiler.ffmpeg_catalog import available_catalog
            catalog = available_catalog(source, ffmpeg_path)
        frontend = EnglishModelFrontend(provider, profile=profile,
                                        **({"ffmpeg_catalog": catalog} if catalog is not None else {}))
        return frontend(source) if images is None else frontend(source, images=images)
    return propose


def _compiler():
    if sys.version_info < (3, 11):
        raise CompilerUnavailableError("The direct and ir pipelines require Python 3.11 or newer.")
    try:
        compiler = importlib.import_module("shipmblang._compiler")
    except ModuleNotFoundError as error:
        if error.name != "shipmblang._compiler":
            raise
        raise CompilerUnavailableError(
            'The bundled compiler is missing. Reinstall ShipMBLang: python -m pip install --force-reinstall shipmblang'
        ) from error
    if not callable(getattr(compiler, "compile_direct_program", None)):
        raise CompilerUnavailableError("Reinstall ShipMBLang; its bundled compiler lacks the direct API.")
    return compiler


def _memory_enabled(requested, memory_path=None):
    return requested and (memory_path is not None or os.environ.get("SHIPMB_MEMORY", "").lower() not in {"off", "0", "false"})


def compile_direct_program(source, *, memory=True, memory_path=None, project=None,
                           bindings=None, clarification_answers=None, model_provider=_CONFIGURED_MODEL,
                           profile="general", accept_model_interpretation=True,
                           ffmpeg_catalog=None, ffmpeg_path=None, image_inputs=None,
                           multimodal_model_provider=None):
    """Delegate to the bundled compiler without importing the legacy pipeline.

    Broader English translation is the default when deterministic parsing needs
    help. Pass model_provider=None for deterministic-only compilation, or
    accept_model_interpretation=False to review translations before compiling.
    Results retain the compiler's status, diagnostics and artifact schema.
    """
    if profile not in {"roku", "general"}:
        raise ValueError("profile must be 'roku' or 'general'")
    compile_program = _compiler().compile_direct_program
    parameters = inspect.signature(compile_program).parameters
    supports_images = "image_inputs" in parameters or any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values())
    supports_multimodal_provider = "multimodal_model_provider" in parameters or any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values())
    if image_inputs and not supports_images:
        raise CompilerUnavailableError("Reinstall ShipMBLang; its bundled compiler does not support image inputs.")
    supports_profile = "profile" in parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values())
    if profile != "roku" and not supports_profile:
        raise CompilerUnavailableError("Reinstall ShipMBLang; its bundled compiler does not support the general profile.")
    supports_acceptance = "accept_model_interpretation" in parameters or any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values())
    automatic_model = model_provider is _CONFIGURED_MODEL
    if automatic_model:
        configured = os.environ.get("SHIPMB_MODEL_PROVIDER", "none").strip().lower() not in {"", "none", "disabled"}
        model_provider = _english_model(profile, ffmpeg_catalog, ffmpeg_path) if configured else None
    if image_inputs and multimodal_model_provider is None and automatic_model and model_provider is not None:
        multimodal_model_provider = lambda text, paths: model_provider(text, images=paths)
    if image_inputs and not supports_multimodal_provider:
        raise CompilerUnavailableError("Reinstall ShipMBLang; its bundled compiler lacks the multimodal provider interface.")
    if model_provider is not None and not supports_acceptance:
        raise CompilerUnavailableError("Update ShipMBLang to a build supporting broader English translation, or pass model_provider=None.")
    result = compile_program(
        source, memory=_memory_enabled(memory, memory_path),
        memory_path=memory_path or os.environ.get("SHIPMB_MEMORY_DB"), project=project,
        bindings=bindings, clarification_answers=clarification_answers,
        model_provider=model_provider,
        **({"image_inputs": image_inputs} if supports_images else {}),
        **({"multimodal_model_provider": multimodal_model_provider} if supports_multimodal_provider else {}),
        **({"profile": profile} if supports_profile else {}),
        **({"accept_model_interpretation": accept_model_interpretation} if supports_acceptance else {}),
        **({"ffmpeg_catalog": ffmpeg_catalog} if ffmpeg_catalog is not None else {}),
    )
    if automatic_model and model_provider is None and result.get("status") != "compiled":
        result = {**result, "diagnostics": [*result.get("diagnostics", []), {
            "level": "warning", "code": "SMBL001",
            "message": "Broader English translation needs a configured model. Set SHIPMB_MODEL_PROVIDER=openai_compatible, SHIPMB_MODEL_BASE_URL, and SHIPMB_MODEL_NAME, or supply --interpretation.",
            "span": {"start": 0, "end": len(source)},
        }]}
    return result


def _ready(result):
    return (result.get("status", "compiled") == "compiled"
            and result.get("target_code") is not None
            and not any(d.get("level") == "error" for d in result.get("diagnostics", [])))


VISION_LIBRARY_REQUIRED = (
    "Vision execution requires the shipmb_vision library / run shipmblang setup --vision"
)


def _vision_executor_for(result, vision_executor):
    """Use a supplied executor, or the native library when that file is present."""
    capabilities = (result.get("target_code") or {}).get("runtime_contract", {}).get("required_capabilities") or []
    if "vision" not in capabilities or vision_executor is not None:
        return vision_executor
    from shipmblang.standalone import activate_packed_vision_library
    from shipmblang._compiler.vision import VisionExecutor, vision_library_path

    activate_packed_vision_library()
    if not Path(vision_library_path()).is_file():
        raise ValueError(VISION_LIBRARY_REQUIRED)
    return VisionExecutor()


def _run_direct_result(result, *, host=None, ffmpeg_executor=None, vlc_executor=None, vision_executor=None):
    if not _ready(result):
        return result
    from shipmblang._compiler.runtime import run_artifact

    options = {"host": host} if host is not None else {}
    if ffmpeg_executor is not None:
        options["ffmpeg_executor"] = ffmpeg_executor
    if vlc_executor is not None:
        options["vlc_executor"] = vlc_executor
    vision_executor = _vision_executor_for(result, vision_executor)
    if vision_executor is not None:
        options["vision_executor"] = vision_executor
    state, diagnostics = run_artifact(result["target_code"], **options)
    return {**result, "runtime": state,
            "diagnostics": [*result.get("diagnostics", []), *[d.to_dict() for d in diagnostics]]}


def run_direct_program(source, *, host=None, ffmpeg_executor=None, vlc_executor=None, vision_executor=None, **compile_options):
    """Compile and run a direct artifact; only an explicitly supplied host is used."""
    return _run_direct_result(compile_direct_program(source, **compile_options),
                              host=host, ffmpeg_executor=ffmpeg_executor, vlc_executor=vlc_executor,
                              vision_executor=vision_executor)


def _legacy_core_has_statement(core):
    """True when Core has a line other than ``use shipmb`` or a ``#`` comment.

    Unrecognized sentences stay ``# intent:`` plus ``use shipmb`` and must not hint.
    """
    if not isinstance(core, str):
        return False
    for line in core.splitlines():
        text = line.strip()
        if not text or text.startswith("#") or text.lower() == "use shipmb":
            continue
        return True
    return False


def _with_legacy_pipeline_hint(source, result):
    """Append SMBL002 when unsupported general English still lowers to Core."""
    if result.get("status") != "unsupported":
        return result
    try:
        from driplm.natural_syntax import compile_natural_program

        program = compile_natural_program(source, memory=False)
    except Exception:
        return result
    core = program.get("core") if isinstance(program, dict) else None
    if not _legacy_core_has_statement(core):
        return result
    diagnostics = result.get("diagnostics")
    if not isinstance(diagnostics, list):
        diagnostics = []
    hint = {
        "level": "hint",
        "code": "SMBL002",
        "message": (
            "This sentence is outside the general computation grammar. "
            "It compiles as Core with --pipeline legacy."
        ),
    }
    return {**result, "diagnostics": [*diagnostics, hint]}


def _offset_line_column(source, span):
    """Map a compiler code-point span to a 1-based line and column.

    Spans are Unicode code points, matching the JSON diagnostic contract.
    A missing or non-positive start is the first character.
    """
    start = 0
    if isinstance(span, dict):
        value = span.get("start")
        if type(value) is int and value > 0:
            start = value
    text = source if isinstance(source, str) else ""
    if start > len(text):
        start = len(text)
    line_break = text.rfind("\n", 0, start)
    return text.count("\n", 0, start) + 1, start - line_break


def _plain_source_name(file_argument):
    if not file_argument or file_argument == "-":
        return "<stdin>"
    return file_argument


def _one_line(text):
    return " ".join(str(text).split())


def _plain_line(path, source, span, message):
    line, column = _offset_line_column(source, span)
    return f"{path}:{line}:{column}: {_one_line(message)}".rstrip()


def _diagnostic_text(diagnostic):
    level = diagnostic.get("level")
    if not isinstance(level, str) or not level.strip():
        level = "error"
    code = diagnostic.get("code")
    message = diagnostic.get("message")
    if not isinstance(message, str):
        message = "" if message is None else str(message)
    prefix = f"{level} {code}" if isinstance(code, str) and code.strip() else level
    return f"{prefix}: {_one_line(message)}".rstrip()


def _clarification_parts(item):
    if isinstance(item, str):
        text, span = item, None
    elif isinstance(item, dict):
        question = item.get("question")
        if question is None:
            question = item.get("message")
        text, span = question, item.get("span")
    else:
        return None
    if not isinstance(text, str):
        text = "" if text is None else str(text)
    text = _one_line(text)
    if not text:
        return None
    return span, f"question: {text}"


def _plain_failure_lines(result, source, path):
    lines = []
    diagnostics = result.get("diagnostics")
    if isinstance(diagnostics, list):
        for diagnostic in diagnostics:
            if isinstance(diagnostic, dict):
                lines.append(_plain_line(path, source, diagnostic.get("span"), _diagnostic_text(diagnostic)))
    clarifications = result.get("clarifications")
    if isinstance(clarifications, list):
        for item in clarifications:
            parts = _clarification_parts(item)
            if parts is not None:
                span, text = parts
                lines.append(_plain_line(path, source, span, text))
    if lines:
        return lines
    status = result.get("status")
    if not isinstance(status, str) or not status.strip():
        status = "failed"
    return [_plain_line(path, source, None, status)]


def _write_plain_output(result, source, path, *, ready):
    """Print program stdout, and readable diagnostics when the run did not succeed."""
    runtime = result.get("runtime") if isinstance(result.get("runtime"), dict) else {}
    program_stdout = runtime.get("stdout")
    if isinstance(program_stdout, str) and (ready or program_stdout):
        sys.stdout.write(program_stdout)
        sys.stdout.flush()
    if ready:
        return
    print("\n".join(_plain_failure_lines(result, source, path)), file=sys.stderr)
    sys.stderr.flush()


def _positive_timeout(value):
    try:
        timeout = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Timeout must be a positive finite number.") from error
    if not math.isfinite(timeout) or timeout <= 0:
        raise argparse.ArgumentTypeError("Timeout must be a positive finite number.")
    return timeout


def main():
    _main(run=False)


def run_main():
    _main(run=True)


def _main(*, run):
    selector = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    selector.add_argument("--pipeline", choices=["legacy", "direct", "ir"], default="direct")
    selector.add_argument("--profile", choices=["roku", "general"])
    selector.add_argument("--run", action="store_true")
    selector.add_argument("--ffmpeg-path", help="Path to the separately installed FFmpeg executable.")
    selector.add_argument("--ffprobe-path", help="Path to the separately installed ffprobe executable.")
    selector.add_argument("--ffmpeg-timeout", type=_positive_timeout, help="Media process timeout in seconds.")
    selector.add_argument("--vlc-dir", help="Directory containing the separately installed LibVLC libraries.")
    selector.add_argument("--vlc-bridge", help="Path to the separately built shipmb_vlc native adapter.")
    selector.add_argument("--vlc-startup-timeout", type=_positive_timeout, help="VLC startup timeout in seconds.")
    selector.add_argument("--headless", action="store_true", help="Disable native VLC video window creation.")
    selector.add_argument("--memory", choices=["on", "off"], default="on")
    selector.add_argument("--memory-path", "--memory-db", dest="memory_path")
    selector.add_argument("--image", action="append", default=[], help="Local image file for inline [[image:N]] anchors; repeat for additional images.")
    selector.add_argument("--no-english-model", action="store_true", help="Use only the deterministic English grammar.")
    selector.add_argument("--plain", action="store_true", help="Print program stdout for run and compile --run. On failure, write file:line:col: message to stderr instead of JSON.")
    selector.add_argument("--review-model-interpretation", "--review-interpretation", action="store_true", help="Review validated model translations before compilation.")
    selected, remaining = selector.parse_known_args()
    media_options = any(value is not None for value in
                        (selected.ffmpeg_path, selected.ffprobe_path, selected.ffmpeg_timeout))
    vlc_options = selected.headless or any(value is not None for value in
                        (selected.vlc_dir, selected.vlc_bridge, selected.vlc_startup_timeout))
    if vlc_options and (selected.pipeline != "direct" or selected.profile == "roku"):
        selector.error("VLC options require the direct general pipeline.")
    if selected.vlc_startup_timeout is not None and not 1 <= selected.vlc_startup_timeout * 1000 <= 2147483647:
        selector.error("VLC startup timeout must be between 0.001 and 2147483.647 seconds.")
    if media_options and (selected.pipeline != "direct" or selected.profile == "roku"):
        selector.error("FFmpeg options require the direct general pipeline.")
    if selected.image and selected.pipeline != "direct":
        selector.error("--image requires --pipeline direct.")
    if (selected.no_english_model or selected.review_model_interpretation) and selected.pipeline != "direct":
        selector.error("English model options require --pipeline direct.")
    if selected.run and selected.pipeline != "direct":
        selector.error("--run requires --pipeline direct; use the run command for legacy or ir.")
    run = run or selected.run
    if selected.plain and not run:
        selector.error("--plain requires run or compile --run.")
    if selected.plain and selected.pipeline != "direct":
        selector.error("--plain requires --pipeline direct.")
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

    parser = argparse.ArgumentParser(parents=[selector], description="Compile English using the bundled ShipMB compiler.")
    parser.add_argument("text", nargs="*")
    parser.add_argument("--file", help="UTF-8 source file, or - to read pasted/piped text from stdin.")
    parser.add_argument("--root")
    parser.add_argument("--thesaurus-path", help="Reviewed slang thesaurus for the ir compatibility pipeline.")
    parser.add_argument("--interpretation", help="Explicit clarified English for the original source (direct pipeline only).")
    parser.add_argument("--format", choices=["bytecode", "json", "core", "text"], default="json" if run else "bytecode")
    args = parser.parse_args(remaining)
    if args.file and args.text:
        parser.error("Use either source text or --file, not both.")
    if args.thesaurus_path is not None and selected.pipeline != "ir":
        parser.error("--thesaurus-path requires --pipeline ir.")
    if args.format == "core" or (args.format == "text" and not run):
        parser.error("Use --pipeline legacy for Core output; direct and ir here emit compiler bytecode or JSON.")
    if args.interpretation is not None and selected.pipeline != "direct":
        parser.error("--interpretation requires --pipeline direct.")
    try:
        if args.file == "-":
            source = sys.stdin.read()
        elif args.file:
            # Preserve editor offsets, including Windows CRLF. utf-8-sig drops a leading BOM only.
            with Path(args.file).open(encoding="utf-8-sig", newline="") as source_file:
                source = source_file.read()
        else:
            source = " ".join(args.text)
        if selected.pipeline == "direct":
            result = compile_direct_program(
                source, memory=selected.memory == "on", memory_path=selected.memory_path,
                project=args.root,
                clarification_answers={"interpretation": args.interpretation} if args.interpretation is not None else None,
                profile=selected.profile or "general",
                model_provider=None if selected.no_english_model else _CONFIGURED_MODEL,
                accept_model_interpretation=not selected.review_model_interpretation,
                ffmpeg_path=selected.ffmpeg_path,
                image_inputs=selected.image,
            )
        else:
            result = _compiler().compile_source(
                source, include_core=False, run=run, thesaurus_path=args.thesaurus_path,
                memory=_memory_enabled(selected.memory == "on", selected.memory_path),
                memory_path=selected.memory_path or os.environ.get("SHIPMB_MEMORY_DB"), project=args.root,
            )
        ready = _ready(result)
        if run and ready and selected.pipeline == "direct":
            capabilities = result["target_code"].get("runtime_contract", {}).get("required_capabilities", [])
            base_dir = Path(args.file).resolve().parent if args.file and args.file != "-" else Path.cwd()
            with ExitStack() as stack:
                executor = None
                vlc_executor = None
                if "ffmpeg" in capabilities:
                    from shipmblang._compiler.ffmpeg import FFmpegExecutor

                    executor = FFmpegExecutor(
                        ffmpeg_path=selected.ffmpeg_path, ffprobe_path=selected.ffprobe_path,
                        timeout=selected.ffmpeg_timeout, base_dir=base_dir,
                    )
                if "vlc" in capabilities:
                    from shipmblang._compiler.vlc import VLCExecutor

                    vlc_executor = stack.enter_context(VLCExecutor(
                        vlc_dir=selected.vlc_dir, bridge_path=selected.vlc_bridge, base_dir=base_dir,
                        startup_timeout_ms=int((selected.vlc_startup_timeout or 10) * 1000),
                        headless=selected.headless,
                    ))
                result = _run_direct_result(result, ffmpeg_executor=executor, vlc_executor=vlc_executor)
            ready = _ready(result)
        if selected.pipeline == "direct" and not ready and (selected.profile or "general") == "general":
            result = _with_legacy_pipeline_hint(source, result)
        # Never hide clarification questions or unsupported explanations behind null bytecode.
        output = result if run or args.format == "json" or not ready else result["target_code"]
        if output is result.get("target_code"):
            if result.get("interpretation_source"):
                print("shipmblang: translated English:\n" + result["interpretation_source"], file=sys.stderr)
            for diagnostic in result.get("diagnostics", []):
                if diagnostic.get("level") == "warning":
                    print(f"shipmblang: {diagnostic.get('code', 'warning')}: {diagnostic.get('message', '')}", file=sys.stderr)
        if selected.plain:
            _write_plain_output(result, source, _plain_source_name(args.file), ready=ready)
        elif run and args.format == "text" and ready and "stdout" in result.get("runtime", {}):
            sys.stdout.write(result["runtime"]["stdout"])
            for diagnostic in result.get("diagnostics", []):
                print(f"shipmblang: {diagnostic.get('code', 'diagnostic')}: {diagnostic.get('message', '')}", file=sys.stderr)
        else:
            print(json.dumps(output, indent=2))
        if not ready:
            raise SystemExit(1)
    except (CompilerUnavailableError, OSError, ValueError) as error:
        print(f"shipmblang: {error}", file=sys.stderr)
        from .setup_tools import missing_tool_hint

        hint = missing_tool_hint(str(error))
        if hint:
            print(f"shipmblang: {hint}", file=sys.stderr)
        raise SystemExit(2) from error
