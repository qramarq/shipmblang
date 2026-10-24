"""In-process MiniCPM-V engine loaded through the shipmb_vision C ABI.

Compilation does not need the shared library. Loading it is explicit, matching
the VLC bridge: build native/vision and point SHIPMB_VISION_BRIDGE at
libshipmb_vision.so, libshipmb_vision.dylib, or shipmb_vision.dll.
"""
from __future__ import annotations

import ctypes
import json
import os
import re
import sys
import threading
from pathlib import Path

# Language-model pin from native/vision/pins.json. Bytecode records this hash.
MODEL_SHA256 = "6b0c74962c44bc6bf4b655b9b02c13eda9d5a0491543ae976d1ac18e4b7892e2"
LLM_FILENAME = "MiniCPM-V-4_6-Q4_K_M.gguf"
MMPROJ_FILENAME = "mmproj-model-q8_0.gguf"
MISSING_WEIGHTS = "Vision weights are not installed. Run `shipmblang setup --vision`."

# operation -> (argument types, return type). count is (thing, image); the rest start with the image.
OPERATIONS = {
    "describe": (["text"], "text"),
    "ask": (["text", "text"], "text"),
    "read_text": (["text"], "text"),
    "yes_no": (["text", "text"], "boolean"),
    "count": (["text", "text"], "integer"),
}

_TOKEN = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_void_p)
_RESIDENT = None
_RESIDENT_LOCK = threading.Lock()


def _library_name():
    if sys.platform == "win32":
        return "shipmb_vision.dll"
    if sys.platform == "darwin":
        return "libshipmb_vision.dylib"
    return "libshipmb_vision.so"


def vision_library_path(bridge_path=None):
    chosen = bridge_path or os.environ.get("SHIPMB_VISION_BRIDGE")
    if chosen:
        return str(Path(chosen))
    return str(Path(__file__).with_name("native") / _library_name())


class VisionEngine:
    """Resident recognizer. One process loads the weights once."""

    def __init__(self, model_dir=None, model_path=None, mmproj_path=None, bridge_path=None,
                 n_threads=0, n_ctx=4096, max_tokens=16, flash_attn=True, detailed=False,
                 use_gpu=None, warmup=True):
        self._config = {
            "model_dir": str(model_dir) if model_dir else "",
            "model_path": str(model_path) if model_path else "",
            "mmproj_path": str(mmproj_path) if mmproj_path else "",
            "n_threads": int(n_threads),
            "n_ctx": int(n_ctx),
            "max_tokens": int(max_tokens),
            "flash_attn": bool(flash_attn),
            "detailed": bool(detailed),
            "warmup": bool(warmup),
        }
        if use_gpu is not None:
            self._config["use_gpu"] = bool(use_gpu)
        self._path = vision_library_path(bridge_path)
        self._lib = None
        self._handle = None

    def _load(self):
        if self._handle:
            return
        if not Path(self._path).is_file():
            raise ValueError(
                "Vision execution requires the shipmb_vision library; build native/vision "
                "and set SHIPMB_VISION_BRIDGE. Missing weights are reported by the library "
                "as: run `shipmblang setup --vision`."
            )
        lib = ctypes.CDLL(str(Path(self._path).resolve()))
        lib.smb_vision_create.argtypes = [ctypes.c_char_p]
        lib.smb_vision_create.restype = ctypes.c_void_p
        lib.smb_vision_query.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p]
        lib.smb_vision_query.restype = ctypes.c_char_p
        lib.smb_vision_query_stream.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, _TOKEN, ctypes.c_void_p]
        lib.smb_vision_query_stream.restype = ctypes.c_char_p
        lib.smb_vision_free.argtypes = [ctypes.c_void_p]
        lib.smb_vision_free.restype = None
        lib.smb_vision_last_error.argtypes = []
        lib.smb_vision_last_error.restype = ctypes.c_char_p
        handle = lib.smb_vision_create(json.dumps(self._config).encode())
        if not handle:
            err = lib.smb_vision_last_error()
            message = err.decode() if err else "Vision engine failed to load."
            raise ValueError(message)
        self._lib = lib
        self._handle = handle

    def query(self, image, question, detailed=None, max_tokens=None, embed_only=False):
        self._load()
        options = {}
        if detailed is not None:
            options["detailed"] = bool(detailed)
        if max_tokens is not None:
            options["max_tokens"] = int(max_tokens)
        if embed_only:
            options["embed_only"] = True
        raw = self._lib.smb_vision_query(
            self._handle,
            str(image).encode(),
            str(question).encode(),
            json.dumps(options).encode(),
        )
        return self._decode(raw)

    def query_stream(self, image, question, on_token, detailed=None, max_tokens=None):
        self._load()
        options = {}
        if detailed is not None:
            options["detailed"] = bool(detailed)
        if max_tokens is not None:
            options["max_tokens"] = int(max_tokens)

        def forward(piece, _user):
            if piece:
                on_token(piece.decode("utf-8", "surrogateescape"))

        callback = _TOKEN(forward)
        raw = self._lib.smb_vision_query_stream(
            self._handle,
            str(image).encode(),
            str(question).encode(),
            json.dumps(options).encode(),
            callback,
            None,
        )
        return self._decode(raw)

    def close(self):
        if self._handle:
            self._lib.smb_vision_free(self._handle)
            self._handle = None

    def __enter__(self):
        self._load()
        return self

    def __exit__(self, *_args):
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    @staticmethod
    def _decode(raw):
        if not raw:
            raise ValueError("Vision query returned nothing.")
        payload = json.loads(raw.decode())
        if not payload.get("ok"):
            raise ValueError(payload.get("error") or "Vision query failed.")
        return payload


def _blank(value):
    return not value.strip(" \t\r\n")


def validate_arguments(operation, values):
    if operation not in OPERATIONS or not isinstance(values, list):
        raise ValueError("Unknown vision operation or arguments.")
    types, _ = OPERATIONS[operation]
    if len(values) != len(types) or any(type(value) is not str or _blank(value) or "\0" in value or len(value.encode("utf-8")) > 1000000 for value in values):
        raise ValueError("Vision text argument is empty or invalid.")


def image_and_question(operation, values):
    """Short prompts. Fast mode stays one 448-pixel chunk and at most 16 tokens."""
    validate_arguments(operation, values)
    if operation == "describe":
        return values[0], "What is in this image?"
    if operation == "ask":
        return values[0], values[1]
    if operation == "read_text":
        return values[0], "Read the text in this image."
    if operation == "yes_no":
        return values[0], "Does this image show " + values[1] + "? Answer yes or no."
    if operation == "count":
        return values[1], "How many " + values[0] + "? Answer with an integer."
    raise ValueError("Unknown vision operation.")


def _strip_answer(text):
    if type(text) is not str or "\0" in text:
        raise ValueError("Vision answer is not valid text.")
    text = text.strip(" \t\r\n")
    if text.endswith("."):
        text = text[:-1].strip(" \t\r\n")
    if len(text.encode("utf-8")) > 1000000:
        raise ValueError("Vision answer is not valid text.")
    return text


def parse_answer(return_type, text):
    """Model output is data. It is never compiled or executed."""
    cleaned = _strip_answer(text)
    if return_type == "text":
        return cleaned
    if return_type == "boolean":
        word = cleaned.lower()
        if word in {"yes", "true"}:
            return True
        if word in {"no", "false"}:
            return False
        raise ValueError("Vision answer is not a boolean.")
    if return_type == "integer":
        if not re.fullmatch(r"-?(0|[1-9][0-9]*)", cleaned):
            raise ValueError("Vision answer is not an integer.")
        value = int(cleaned)
        if value.bit_length() > 4096:
            raise ValueError("Vision answer is not an integer.")
        return value
    raise ValueError("Unknown vision result type.")


def resident_engine():
    """One engine per process, so recognition after the first load stays warm."""
    global _RESIDENT
    with _RESIDENT_LOCK:
        if _RESIDENT is None:
            _RESIDENT = VisionEngine()
        return _RESIDENT


class VisionExecutor:
    """Catalog-checked call into the resident engine. Fast mode is the default."""

    def __init__(self, engine=None):
        self.engine = engine

    def invoke(self, operation, values):
        image, question = image_and_question(operation, values)
        engine = self.engine if self.engine is not None else resident_engine()
        payload = engine.query(image, question)
        if not isinstance(payload, dict) or "text" not in payload:
            raise ValueError("Vision query returned no text.")
        return parse_answer(OPERATIONS[operation][1], payload["text"])
