"""Shared checks for the self-contained shipmblang executable.

The Python package does not set ``sys.frozen``. PyInstaller and Nuitka do.
"""

from __future__ import annotations

import sys

# Local training and chat. Direct compilation does not use these.
MODEL_COMMANDS = frozenset({"train", "prepare", "chat", "download"})


def is_standalone() -> bool:
    return bool(getattr(sys, "frozen", False))


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
