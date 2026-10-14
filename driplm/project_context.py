"""Project intake and indexing helpers for printurf."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Iterable


SOURCE_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".css",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".java",
    ".js",
    ".jsx",
    ".json",
    ".md",
    ".py",
    ".rs",
    ".ts",
    ".tsx",
    ".toml",
    ".yaml",
    ".yml",
}

SKIP_DIRS = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}


@dataclass(frozen=True)
class CodeFile:
    path: Path
    rel_path: str
    language: str
    size: int


def discover_source_files(
    targets: Iterable[str | Path],
    *,
    root: str | Path | None = None,
    max_files: int = 80,
) -> list[CodeFile]:
    """Return bounded source files from explicit files/directories."""
    root_path = Path(root).resolve() if root else Path.cwd().resolve()
    seen: set[Path] = set()
    files: list[CodeFile] = []
    for targetish in targets:
        target = Path(targetish).expanduser()
        if not target.is_absolute():
            target = (root_path / target).resolve()
        if not target.exists():
            continue
        candidates = [target] if target.is_file() else _walk_source_files(target)
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved in seen or not _is_source_file(resolved):
                continue
            seen.add(resolved)
            files.append(
                CodeFile(
                    path=resolved,
                    rel_path=_relative_to(resolved, root_path),
                    language=_language_for(resolved),
                    size=resolved.stat().st_size,
                )
            )
            if len(files) >= max_files:
                return files
    return files


def build_codebase_index(
    root: str | Path,
    *,
    targets: Iterable[str | Path] | None = None,
    max_files: int = 80,
) -> dict[str, Any]:
    """Build a lightweight project map for editor/MCP context."""
    root_path = Path(root).resolve()
    source_targets = list(targets) if targets else [root_path]
    files = discover_source_files(source_targets, root=root_path, max_files=max_files)
    summaries = [_summarize_file(file) for file in files]
    languages: dict[str, int] = {}
    for file in files:
        languages[file.language] = languages.get(file.language, 0) + 1
    return {
        "root": str(root_path),
        "file_count": len(files),
        "languages": languages,
        "files": summaries,
    }


def format_codebase_index(index: dict[str, Any], *, max_files: int = 30) -> str:
    """Render a compact index for prompts and terminal output."""
    lines = [
        f"PROJECT ROOT: {index.get('root', '')}",
        f"FILES INDEXED: {index.get('file_count', 0)}",
    ]
    languages = index.get("languages") or {}
    if languages:
        rendered = ", ".join(f"{name}={count}" for name, count in sorted(languages.items()))
        lines.append(f"LANGUAGES: {rendered}")
    lines.append("PROJECT FILES:")
    for file in (index.get("files") or [])[:max_files]:
        detail = []
        if file.get("symbols"):
            detail.append("symbols: " + ", ".join(file["symbols"][:8]))
        if file.get("imports"):
            detail.append("imports: " + ", ".join(file["imports"][:8]))
        suffix = " (" + "; ".join(detail) + ")" if detail else ""
        lines.append(f"- {file.get('path', '')}{suffix}")
    return "\n".join(lines)


def collect_project_context(
    targets: Iterable[str | Path],
    *,
    root: str | Path | None = None,
    raw_error: str = "",
    line: int | None = None,
    max_files: int = 12,
    max_file_chars: int = 1200,
) -> tuple[str, dict[str, Any]]:
    """Collect project index plus bounded file context for printurf."""
    root_path = Path(root).resolve() if root else Path.cwd().resolve()
    files = discover_source_files(targets, root=root_path, max_files=max_files)
    index = build_codebase_index(root_path, targets=[file.path for file in files], max_files=max_files)
    focus_path, focus_line = extract_traceback_location(raw_error)
    if line and focus_line is None:
        focus_line = line

    chunks = [format_codebase_index(index)]
    for file in _rank_files(files, focus_path):
        source = file.path.read_text(encoding="utf-8", errors="replace")
        if focus_path and _same_pathish(file.path, focus_path):
            chunks.append(format_editor_context(str(file.path), source, focus_line))
        else:
            chunks.append(f"--- {file.rel_path} ---\n{_clip_middle(source.rstrip(), max_file_chars)}")
    return "\n\n".join(chunks), index


def scan_python_syntax(
    targets: Iterable[str | Path],
    *,
    root: str | Path | None = None,
    max_files: int = 80,
) -> list[dict[str, Any]]:
    """Find parse-time Python errors before a runtime error exists."""
    diagnostics: list[dict[str, Any]] = []
    for file in discover_source_files(targets, root=root, max_files=max_files):
        if file.path.suffix.lower() != ".py":
            continue
        source = file.path.read_text(encoding="utf-8", errors="replace")
        try:
            ast.parse(source, filename=str(file.path))
        except SyntaxError as exc:
            line = exc.lineno or 1
            diagnostics.append(
                {
                    "error": f"SyntaxError: {exc.msg}",
                    "file": str(file.path),
                    "line": line,
                    "context": format_editor_context(str(file.path), source, line, radius=4),
                }
            )
    return diagnostics


def extract_traceback_location(raw_error: str) -> tuple[str | None, int | None]:
    """Extract the last Python traceback file/line pair from raw error text."""
    matches = re.findall(r'File "([^"]+)", line (\d+)', raw_error)
    if matches:
        file_path, line = matches[-1]
        return file_path, int(line)
    line_match = re.search(r"\bline\s+(\d+)\b", raw_error, flags=re.IGNORECASE)
    if line_match:
        return None, int(line_match.group(1))
    return None, None


def format_editor_context(file_path: str, source: str, line: int | None = None, radius: int = 8) -> str:
    """Format editor text around a line with stable 1-based line numbers."""
    lines = source.splitlines()
    if line is None or line < 1:
        start, end = 1, min(len(lines), radius * 2 + 1)
    else:
        start = max(1, line - radius)
        end = min(len(lines), line + radius)
    numbered = []
    for idx in range(start, end + 1):
        marker = ">" if line == idx else " "
        text = lines[idx - 1] if idx - 1 < len(lines) else ""
        numbered.append(f"{marker} {idx}: {text}")
    return f"--- {file_path} ---\n" + "\n".join(numbered)


def _walk_source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.is_file() and _is_source_file(path):
            files.append(path)
    return files


def _is_source_file(path: Path) -> bool:
    if path.suffix.lower() not in SOURCE_EXTENSIONS:
        return False
    try:
        return path.stat().st_size <= 250_000
    except OSError:
        return False


def _summarize_file(file: CodeFile) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "path": file.rel_path,
        "language": file.language,
        "size": file.size,
        "imports": [],
        "symbols": [],
    }
    if file.path.suffix.lower() != ".py":
        return summary
    try:
        tree = ast.parse(file.path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return summary
    imports: list[str] = []
    symbols: list[str] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append("." * node.level + (node.module or ""))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.append(node.name)
    summary["imports"] = imports[:12]
    summary["symbols"] = symbols[:12]
    return summary


def _rank_files(files: list[CodeFile], focus_path: str | None) -> list[CodeFile]:
    if not focus_path:
        return files
    return sorted(files, key=lambda file: 0 if _same_pathish(file.path, focus_path) else 1)


def _same_pathish(path: Path, other: str) -> bool:
    other_path = Path(other)
    if other_path.is_absolute():
        return path.resolve() == other_path.resolve()
    normalized = other.replace("\\", "/")
    return path.name == other_path.name or str(path).replace("\\", "/").endswith(normalized)


def _language_for(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".")
    return {"py": "python", "js": "javascript", "ts": "typescript"}.get(suffix, suffix or "text")


def _relative_to(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _clip_middle(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    half = max_chars // 2
    return text[:half].rstrip() + "\n... clipped ...\n" + text[-half:].lstrip()
