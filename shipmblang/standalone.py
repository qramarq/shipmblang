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


# os.add_dll_directory returns a cookie that removes the directory when it is
# collected. Keep every cookie for the life of the process.
_DLL_DIRECTORIES: list[tuple[str, object]] = []


def remember_dll_directory(path: str | Path | None) -> None:
    """Search this directory when Windows loads shipmb_vision.dll.

    LoadLibrary of an absolute path does not search that directory for
    dependent DLLs. vision.py then calls ctypes.CDLL on the path inside
    ``_MEIPASS``. Adding the directory first is what makes sibling DLLs
    resolve. The static CRT build has no VC++ redistributable siblings;
    the call still covers a DLL placed next to the library.
    """
    if os.name != "nt" or not path or not hasattr(os, "add_dll_directory"):
        return
    text = os.path.abspath(os.fspath(path))
    directory = os.path.dirname(text) if os.path.isfile(text) or os.path.splitext(text)[1] else text
    if not os.path.isdir(directory):
        return
    resolved = os.path.abspath(directory)
    if any(item[0] == resolved for item in _DLL_DIRECTORIES):
        return
    _DLL_DIRECTORIES.append((resolved, os.add_dll_directory(resolved)))


def activate_packed_vision_library() -> None:
    """Point vision.py at the packed library when the user did not choose one.

    vision.py opens SHIPMB_VISION_BRIDGE, otherwise native/<library> beside
    itself. PyInstaller extracts the packed file under sys._MEIPASS at that
    relative path. Setting the bridge makes the lookup succeed even when the
    frozen module's __file__ is not a real file next to the extracted library.
    On Windows the same call registers that directory with the loader.
    """
    bridge = os.environ.get("SHIPMB_VISION_BRIDGE")
    if bridge:
        remember_dll_directory(bridge)
        return
    found = packed_vision_library()
    if found is not None:
        remember_dll_directory(found)
        os.environ["SHIPMB_VISION_BRIDGE"] = str(found)
        return
    source = Path(__file__).resolve().parent / "_compiler" / "native" / vision_library_filename()
    if source.is_file():
        remember_dll_directory(source)


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
