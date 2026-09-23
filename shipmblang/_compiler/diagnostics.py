from __future__ import annotations

from .models import Diagnostic


def printurf(diagnostic: Diagnostic, source: str = "") -> str:
    """Return a friendly compiler diagnostic explanation.

    The intentionally odd name mirrors the ShipMBLang examples and gives the
    language a stable function for explaining syntax and semantic errors.
    """
    location = f"{diagnostic.span.start}:{diagnostic.span.end}"
    snippet = source[diagnostic.span.start : diagnostic.span.end].strip()
    parts = [f"{diagnostic.level.upper()} {diagnostic.code} at {location}: {diagnostic.message}"]
    if snippet:
        parts.append(f"  source: {snippet}")
    if diagnostic.help:
        parts.append(f"  help: {diagnostic.help}")
    return "\n".join(parts)


def has_errors(diagnostics: list[Diagnostic]) -> bool:
    return any(diagnostic.level == "error" for diagnostic in diagnostics)
