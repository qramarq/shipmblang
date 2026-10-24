"""Shared checks for the self-contained shipmblang executable.

The Python package does not set ``sys.frozen``. PyInstaller and Nuitka do.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

# Local training and chat. Direct compilation does not use these.
MODEL_COMMANDS = frozenset({"train", "prepare", "chat", "download"})


def is_standalone() -> bool:
    return bool(getattr(sys, "frozen", False))


def vision_library_filename() -> str:
    if sys.platform == "win32":
        return "shipmb_vision.dll"
    if sys.platform == "darwin":
        return "libshipmb_vision.dylib"
    return "libshipmb_vision.so"


def packed_vision_library() -> Path | None:
    """CPU library packed next to vision.py inside a frozen executable."""
    if not is_standalone():
        return None
    root = getattr(sys, "_MEIPASS", None)
    if not root:
        return None
    path = Path(root) / "shipmblang" / "_compiler" / "native" / vision_library_filename()
    return path if path.is_file() else None


def activate_packed_vision_library() -> None:
    """Point vision.py at the packed library when the user did not choose one.

    vision.py opens SHIPMB_VISION_BRIDGE, otherwise native/<library> beside
    itself. PyInstaller extracts the packed file under sys._MEIPASS at that
    relative path. Setting the bridge makes the lookup succeed even when the
    frozen module's __file__ is not a real file next to the extracted library.
    """
    if os.environ.get("SHIPMB_VISION_BRIDGE"):
        return
    found = packed_vision_library()
    if found is not None:
        os.environ["SHIPMB_VISION_BRIDGE"] = str(found)


def model_extras_message() -> str:
    return (
        "this standalone executable does not include optional model extras "
        "(PyTorch, tokenizers, and the local training stack). "
        "The train, prepare, chat, and download commands, and "
        "SHIPMB_MODEL_PROVIDER=drip, require Python 3.11+ with "
        'pip install "shipmblang[model]". '
        "Compile and run on the direct pipeline do not need a model. "
        "A remote or local OpenAI-compatible endpoint still works: set "
        "SHIPMB_MODEL_PROVIDER=openai_compatible, SHIPMB_MODEL_BASE_URL, and SHIPMB_MODEL_NAME."
    )
