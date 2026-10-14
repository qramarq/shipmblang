"""Runtime-owned identity and capability context for ShipMB Lang."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

_DEFAULT_DEVICE_FAMILIES: tuple[dict[str, Any], ...] = (
    {
        "name": "host",
        "display_name": "Host machine",
        "description": "The local machine running ShipMB Lang.",
        "resources": (
            {"name": "project", "kind": "filesystem", "capabilities": ("read", "summarize")},
            {"name": "runtime", "kind": "process", "capabilities": ("plan", "record")},
        ),
    },
    {
        "name": "codebase",
        "display_name": "Codebase",
        "description": "Source files and diagnostics explicitly provided to ShipMB Lang.",
        "resources": (
            {"name": "files", "kind": "source", "capabilities": ("inspect", "explain")},
            {"name": "diagnostics", "kind": "error-context", "capabilities": ("explain", "suggest-fix")},
        ),
    },
)


def _serialize_device_families() -> list[dict[str, Any]]:
    return deepcopy([
        {
            **family,
            "resources": [dict(resource) for resource in family["resources"]],
        }
        for family in _DEFAULT_DEVICE_FAMILIES
    ])


def build_runtime_context(*, active_device_family: str | None = None, task: str | None = None) -> dict[str, Any]:
    """Return ShipMB's durable identity independently of the selected model."""
    return {
        "identity": "ShipMB is a local-first orchestration and programming layer for approved devices, software resources, and operator workflows.",
        "role": "Coordinate work, explain available capabilities, and propose safe next steps. Do not invent devices, state, permissions, or completed actions.",
        "device_families": _serialize_device_families(),
        "active_device_family": active_device_family or "host",
        "task": task or "",
    }


def build_system_prompt(*, active_device_family: str | None = None, task: str | None = None) -> str:
    """Build the standard system message supplied to every optional chat provider."""
    context = build_runtime_context(active_device_family=active_device_family, task=task)
    lines = [
        "You are ShipMB.",
        context["identity"],
        context["role"],
        "Your identity, safety boundaries, and capabilities come from this runtime context, not from model training or persona.",
        "Available device families and resources:",
    ]
    for family in context["device_families"]:
        resources = ", ".join(resource["name"] for resource in family["resources"])
        lines.append(f"- {family['display_name']} ({family['name']}): {family['description']} Resources: {resources}.")
    if context["task"]:
        lines.append(f"Current task: {context['task']}")
    return "\n".join(lines)