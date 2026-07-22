"""Runtime wrapper for explaining code errors with ShipMBLang."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Iterable, Protocol

from .project_context import (
    build_codebase_index,
    collect_project_context,
    extract_traceback_location,
    format_editor_context as _format_editor_context,
    scan_python_syntax,
)


STRICT_ERROR_PROMPT = """YOUR CORE DIRECTIVE:
Do not chat. Do not converse. Do not roleplay.
Your sole function is to intercept runtime errors, compiler warnings, and stack traces from the specific codebase you are trained on, and immediately output a concise, plain-English explanation of the error followed by a direct, actionable solution.

TRAINING DATA INSTRUCTIONS:
INPUT: You receive [Code Context + Raw Error Message] from this specific repository.
OUTPUT: Generate a single paragraph that explains what broke in simple terms, why it broke based on the immediate code context, the exact line or function causing the issue, and a one-line code fix or logic correction.

STYLE GUIDELINES:
Tone: Professional, direct, and helpful.
Format: "Error: [Simple Explanation]. Cause: [Specific Reason]. Fix: [Solution]."
Constraint: Never output more than what caused the issue, how the logic caused this issue, and how to fix the issue. Never ask questions. Never say "As an AI...".
Context Awareness: If an error involves a custom function, explain the failure using that function's specific logic, not generic definitions.

CODE CONTEXT:
{code_context}

RAW ERROR:
{raw_error}
"""

COMPACT_ERROR_PROMPT = """No chat. Output one paragraph only.
Format exactly: Error: [simple explanation]. Cause: [specific reason in this code]. Fix: [one-line code or logic correction].

CODE:
{code_context}

ERROR:
{raw_error}
"""


class ChatEngine(Protocol):
    """Small protocol implemented by DripInference."""

    def chat_completion(self, messages, temperature=0.7, max_tokens=64, top_k=50, **kwargs):
        """Return an OpenAI-style chat completion response."""


def build_error_prompt(raw_error: str, code_context: str = "", max_context_chars: int = 2500) -> str:
    """Format code context and a raw error into the strict explanation prompt."""
    clipped_context = _clip_middle(code_context.strip(), max_context_chars)
    return STRICT_ERROR_PROMPT.format(
        code_context=clipped_context or "(no code context provided)",
        raw_error=raw_error.strip() or "(no raw error provided)",
    )


def build_compact_error_prompt(raw_error: str, code_context: str = "", max_context_chars: int = 900) -> str:
    """Format a shorter runtime prompt for tiny context-window checkpoints."""
    clipped_context = _clip_middle(code_context.strip(), max_context_chars)
    return COMPACT_ERROR_PROMPT.format(
        code_context=clipped_context or "(no code context provided)",
        raw_error=raw_error.strip() or "(no raw error provided)",
    )


def explain_error(
    engine: ChatEngine,
    raw_error: str,
    code_context: str = "",
    *,
    temperature: float = 0.2,
    max_tokens: int = 96,
    top_k: int = 20,
    max_context_chars: int = 2500,
) -> str:
    """Ask a ShipMBLang-compatible engine for one concise error explanation and fix."""
    prompt = build_error_prompt(raw_error, code_context, max_context_chars=max_context_chars)
    prompt = _fit_prompt_to_engine(engine, raw_error, code_context, prompt, max_context_chars)
    result = engine.chat_completion(
        [{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
        top_k=top_k,
    )
    content = result["choices"][0]["message"]["content"].strip()
    if _looks_like_contract(content):
        return _single_paragraph(content)
    return synthesize_error_explanation(raw_error, code_context)


def drip_printf(engine: ChatEngine, raw_error: str, *code_context_parts: str, **kwargs) -> str:
    """Printf-style convenience wrapper: pass an engine, error, then context chunks."""
    return explain_error(engine, raw_error, "\n\n".join(part for part in code_context_parts if part), **kwargs)


def printurf(
    raw_error: str = "",
    *,
    paths: Iterable[str | Path] = (),
    code_context: str = "",
    root: str | Path | None = None,
    line: int | None = None,
    engine: ChatEngine | None = None,
    checkpoint: str = "checkpoints/best_model.pt",
    tokenizer: str = "data/tokenizer.json",
    device: str = "cpu",
    max_context_chars: int = 2500,
    max_files: int = 12,
    output: str = "dict",
) -> dict | str:
    """High-level printurf module API for codebases, editors, and MCP clients.

    output="dict" returns the structured report, output="text" returns terminal
    text, and output="json" returns serialized JSON.
    """
    path_list = list(paths)
    if engine is None:
        engine = _load_engine_or_none(checkpoint, tokenizer, device)
    report = build_printurf_report(
        raw_error=raw_error,
        code_context=code_context,
        paths=path_list,
        root=root,
        line=line,
        engine=engine,
        max_context_chars=max_context_chars,
        max_files=max_files,
    )
    if output == "text":
        return render_printurf_report(report, include_context=bool(path_list))
    if output == "json":
        return json.dumps(report, indent=2)
    if output != "dict":
        raise ValueError("printurf output must be 'dict', 'text', or 'json'")
    return report


def build_printurf_report(
    *,
    raw_error: str = "",
    code_context: str = "",
    paths: Iterable[str | Path] = (),
    root: str | Path | None = None,
    line: int | None = None,
    engine: ChatEngine | None = None,
    max_context_chars: int = 2500,
    max_files: int = 12,
) -> dict:
    """Build the structured printurf diagnostic report used by CLI and MCP."""
    path_list = list(paths)
    project_index = None
    project_context = ""
    if path_list:
        project_context, project_index = collect_project_context(
            path_list,
            root=root,
            raw_error=raw_error,
            line=line,
            max_files=max_files,
            max_file_chars=min(max_context_chars, 1200),
        )

    combined_context = "\n\n".join(part for part in (code_context, project_context) if part)
    diagnostics = []

    if raw_error.strip():
        diagnostics.append(
            _build_diagnostic(
                raw_error=raw_error,
                code_context=combined_context,
                line=line,
                engine=engine,
                max_context_chars=max_context_chars,
            )
        )
    elif path_list:
        syntax_diagnostics = scan_python_syntax(path_list, root=root, max_files=max_files)
        for item in syntax_diagnostics:
            diagnostics.append(
                _build_diagnostic(
                    raw_error=item["error"],
                    code_context=item["context"],
                    file_path=item.get("file"),
                    line=item.get("line"),
                    engine=engine,
                    max_context_chars=max_context_chars,
                )
            )
        if project_index is None:
            project_index = build_codebase_index(root or Path.cwd(), targets=path_list, max_files=max_files)

    return {
        "status": "error" if diagnostics else "ok",
        "diagnostic_count": len(diagnostics),
        "diagnostics": diagnostics,
        "project": project_index,
    }


def render_printurf_report(report: dict, *, include_context: bool = True) -> str:
    """Render a report for terminals while keeping the first line editor-safe."""
    diagnostics = report.get("diagnostics") or []
    if not diagnostics:
        project = report.get("project") or {}
        count = project.get("file_count", 0)
        return f"printurf found no errors. Indexed {count} files."

    lines = []
    for idx, diagnostic in enumerate(diagnostics, start=1):
        if idx > 1:
            lines.append("")
        lines.append(diagnostic["explanation"])
        location = _format_location(diagnostic.get("file"), diagnostic.get("line"))
        if location:
            lines.append(f"Location: {location}")
        if include_context and diagnostic.get("context"):
            lines.append("Context:")
            lines.append(diagnostic["context"])
    project = report.get("project") or {}
    if project:
        lines.append("")
        lines.append(f"Project: indexed {project.get('file_count', 0)} files under {project.get('root', '')}")
    return "\n".join(lines)


def synthesize_error_explanation(raw_error: str, code_context: str = "") -> str:
    """Return a deterministic one-paragraph fallback in the drip contract."""
    error = _single_paragraph(raw_error.strip()) or "An unknown error occurred."
    location = _extract_location(raw_error) or _guess_context_location(code_context) or "the highlighted code"
    simple, fix = _classify_error(error)
    return f"Error: {simple}. Cause: {location} triggers `{_short_error(error)}` with the current code path. Fix: {fix}."


def collect_code_context(paths: Iterable[str | Path], max_file_chars: int = 1200) -> str:
    """Read a bounded amount of context from each source file."""
    chunks = []
    for pathish in paths:
        path = Path(pathish)
        text = path.read_text(encoding="utf-8", errors="replace")
        chunks.append(f"--- {path} ---\n{_clip_middle(text.rstrip(), max_file_chars)}")
    return "\n\n".join(chunks)


def format_editor_context(file_path: str, source: str, line: int | None = None, radius: int = 8) -> str:
    """Format editor text around a line with stable 1-based line numbers."""
    return _format_editor_context(file_path, source, line, radius)


def main() -> None:
    parser = argparse.ArgumentParser(description="Explain a code error with ShipMBLang.")
    parser.add_argument("--checkpoint", default="checkpoints/best_model.pt")
    parser.add_argument("--tokenizer", default="data/tokenizer.json")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--error", help="Raw error or traceback text")
    parser.add_argument("--error-file", help="File containing the raw error or traceback")
    parser.add_argument("--root", help="Project root for relative paths and codebase indexing")
    parser.add_argument("--line", type=int, help="1-based line number for the failing code")
    parser.add_argument("--context-file", action="append", default=[], help="Source file to include as context")
    parser.add_argument("--max-files", type=int, default=12, help="Maximum project files to include in context")
    parser.add_argument("--max-context-chars", type=int, default=2500)
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--json", action="store_true", help="Output the structured printurf report as JSON")
    parser.add_argument("--dry-run", action="store_true", help="Print the formatted prompt without running inference")
    parser.add_argument("paths", nargs="*", help="Files or directories for printurf to inspect/index")
    args = parser.parse_args()

    raw_error = args.error or ""
    if args.error_file:
        raw_error = Path(args.error_file).read_text(encoding="utf-8", errors="replace")

    code_context = collect_code_context(args.context_file) if args.context_file else ""
    report = build_printurf_report(
        raw_error=raw_error,
        code_context=code_context,
        paths=args.paths,
        root=args.root,
        line=args.line,
        engine=None,
        max_context_chars=args.max_context_chars,
        max_files=args.max_files,
    )
    report_context = code_context
    if report["diagnostics"]:
        report_context = report["diagnostics"][0].get("context", code_context)
    prompt = build_error_prompt(raw_error, report_context, max_context_chars=args.max_context_chars)

    if args.dry_run:
        print(prompt)
        return

    engine = _load_engine_or_none(args.checkpoint, args.tokenizer, args.device)
    report = build_printurf_report(
        raw_error=raw_error,
        code_context=code_context,
        paths=args.paths,
        root=args.root,
        line=args.line,
        engine=engine,
        max_context_chars=args.max_context_chars,
        max_files=args.max_files,
    )
    if args.json or args.format == "json":
        print(json.dumps(report, indent=2))
        return

    print(render_printurf_report(report, include_context=bool(args.paths)))


def _load_engine_or_none(checkpoint: str, tokenizer: str, device: str) -> ChatEngine | None:
    """Return a local model engine when available; otherwise keep printurf usable."""
    if not Path(checkpoint).exists() or not Path(tokenizer).exists():
        return None
    try:
        from .inference import DripInference

        return DripInference(checkpoint, tokenizer, device)
    except Exception:
        return None


def _build_diagnostic(
    *,
    raw_error: str,
    code_context: str,
    line: int | None = None,
    file_path: str | None = None,
    engine: ChatEngine | None = None,
    max_context_chars: int = 2500,
) -> dict:
    if engine is None:
        explanation = synthesize_error_explanation(raw_error, code_context)
    else:
        explanation = explain_error(engine, raw_error, code_context, max_context_chars=max_context_chars)
    parsed = _parse_explanation(explanation)
    traced_file, traced_line = extract_traceback_location(raw_error)
    return {
        "error": parsed["error"] or _short_error(_single_paragraph(raw_error)),
        "file": file_path or traced_file,
        "line": line or traced_line,
        "context": code_context,
        "cause": parsed["cause"],
        "suggestion": parsed["fix"],
        "explanation": explanation,
    }


def _parse_explanation(explanation: str) -> dict[str, str]:
    pattern = re.compile(r"Error:\s*(?P<error>.*?)\s*Cause:\s*(?P<cause>.*?)\s*Fix:\s*(?P<fix>.*)", re.IGNORECASE)
    match = pattern.search(_single_paragraph(explanation))
    if not match:
        return {"error": "", "cause": "", "fix": ""}
    return {
        "error": match.group("error").strip().rstrip("."),
        "cause": match.group("cause").strip().rstrip("."),
        "fix": match.group("fix").strip().rstrip("."),
    }


def _format_location(file_path: str | None, line: int | None) -> str:
    if file_path and line:
        return f"{file_path}:{line}"
    if file_path:
        return file_path
    if line:
        return f"line {line}"
    return ""


def _clip_middle(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    half = max_chars // 2
    return text[:half].rstrip() + "\n... clipped ...\n" + text[-half:].lstrip()


def _fit_prompt_to_engine(
    engine: ChatEngine,
    raw_error: str,
    code_context: str,
    prompt: str,
    max_context_chars: int,
) -> str:
    tokenizer = getattr(engine, "tokenizer", None)
    config = getattr(engine, "config", None)
    max_seq_len = getattr(config, "max_seq_len", None)
    if tokenizer is None or max_seq_len is None:
        return prompt

    if len(tokenizer.encode(prompt).ids) <= max_seq_len:
        return prompt

    context_chars = min(max_context_chars, len(code_context))
    while context_chars > 0:
        context_chars //= 2
        prompt = build_error_prompt(raw_error, code_context, max_context_chars=context_chars)
        if len(tokenizer.encode(prompt).ids) <= max_seq_len:
            return prompt

    compact_chars = min(900, len(code_context))
    while compact_chars > 0:
        compact_chars //= 2
        prompt = build_compact_error_prompt(raw_error, code_context, max_context_chars=compact_chars)
        if len(tokenizer.encode(prompt).ids) <= max_seq_len:
            return prompt

    return build_compact_error_prompt(raw_error, "", max_context_chars=0)


def _looks_like_contract(text: str) -> bool:
    lowered = text.lower()
    return "error:" in lowered and "cause:" in lowered and "fix:" in lowered


def _single_paragraph(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _short_error(error: str, limit: int = 120) -> str:
    return error if len(error) <= limit else error[: limit - 3].rstrip() + "..."


def _extract_location(raw_error: str) -> str | None:
    file_matches = re.findall(r'File "([^"]+)", line (\d+)', raw_error)
    if file_matches:
        file_path, line = file_matches[-1]
        return f"{file_path} line {line}"
    line_match = re.search(r"\bline\s+(\d+)\b", raw_error, flags=re.IGNORECASE)
    if line_match:
        return f"line {line_match.group(1)}"
    return None


def _guess_context_location(code_context: str) -> str | None:
    for line in code_context.splitlines():
        stripped = line.strip()
        if stripped.startswith(">"):
            return f"line {stripped.split(':', 1)[0].replace('>', '').strip()}"
    return None


def _classify_error(error: str) -> tuple[str, str]:
    lowered = error.lower()
    name_match = re.search(r"name '([^']+)' is not defined", error)
    if name_match:
        name = name_match.group(1)
        return (
            f"`{name}` is used before Python knows what it is",
            f"define `{name}` before this line or correct the misspelled name",
        )
    if "modulenotfounderror" in lowered or "no module named" in lowered:
        return ("a required module is missing", "install the missing package or correct the import name")
    if "typeerror" in lowered:
        return ("a value is being used with the wrong type or call shape", "match the function call to the expected argument types")
    if "attributeerror" in lowered:
        return ("the code is reading a field or method that this object does not have", "use the correct object or attribute name")
    if "keyerror" in lowered:
        return ("the code requested a dictionary key that is not present", "check the key exists before reading it or use the correct key")
    if "indexerror" in lowered:
        return ("the code requested a list position that does not exist", "check the list length before indexing it")
    if "syntaxerror" in lowered:
        return ("the file contains code Python cannot parse", "fix the syntax near the reported line")
    return ("the reported error stopped this code path", "update the highlighted line or surrounding logic to satisfy the error message")


if __name__ == "__main__":
    main()
