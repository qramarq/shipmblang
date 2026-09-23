"""Best-effort shared prose capture, independent of compiler execution."""

import os
from pathlib import Path
import warnings


def capture_submission(source, result, *, pipeline, project=None, memory=True, memory_path=None):
    if not memory or (memory_path is None and os.environ.get("SHIPMB_MEMORY", "").lower() in {"off", "0", "false"}):
        return
    try:
        from shipmblang._compiler.memory import MemoryStore

        store = MemoryStore(memory_path or os.environ.get("SHIPMB_MEMORY_DB"))
        store.record_submission(source, str(project or Path.cwd().resolve()), pipeline, result)
    except Exception as error:
        # Capture is optional; its failure must not discard a compilation result.
        warnings.warn(
            f"ShipMB memory capture failed ({type(error).__name__}: {error}). "
            "Check the memory database path or disable capture with SHIPMB_MEMORY=off / --memory off.",
            RuntimeWarning, stacklevel=2,
        )
