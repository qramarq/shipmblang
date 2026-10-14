"""Optional memory boundary shared by the direct and legacy entry points."""
from __future__ import annotations

import os
from pathlib import Path


def open_memory(enabled=True, path=None):
    if not enabled or (path is None and os.environ.get("SHIPMB_MEMORY", "on").lower() == "off"):
        return None
    from .memory import MemoryStore
    return MemoryStore(path)


def project_context(project=None):
    return str(Path(project or Path.cwd()).expanduser().resolve())


def capture_submission(source, result, *, pipeline, memory=True, memory_path=None, project=None):
    try:
        store = open_memory(memory, memory_path)
        if store is not None:
            return store.record_submission(source, project_context(project), pipeline, result)
    except Exception as error:
        result.setdefault("diagnostics", []).append({
            "level": "warning", "code": "SMBM001", "message": f"Memory persistence failed: {error}",
            "span": {"start": 0, "end": 0},
        })
    return None
