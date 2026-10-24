"""Vision setup: hash checks, resume, idempotence, cache paths, and the frozen library."""

import hashlib
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

from shipmblang import setup_tools
from shipmblang.standalone import activate_packed_vision_library
from shipmblang.vision_build import default_compilers
from shipmblang.vision_setup import (
    FilePin, VisionPins, VisionSetupError, download_verified, setup_vision, vision_model_dir,
)


def _pin(name, payload, url="http://example.test/" + "file"):
    return FilePin(name, hashlib.sha256(payload).hexdigest(), len(payload), url)


class Response:
    def __init__(self, status, body, *, fail_after=None):
        self.status = status
        self.headers = {}
        self._body = body
        self._off = 0
        self._fail_after = fail_after

    def read(self, size):
        if self._fail_after is not None and self._off >= self._fail_after:
            raise urllib.error.URLError("connection reset")
        take = size
        if self._fail_after is not None:
            take = min(size, self._fail_after - self._off)
        chunk = self._body[self._off:self._off + take]
        self._off += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _pins(llm, f16, q8):
    return VisionPins(
        llm=_pin("MiniCPM-V-4_6-Q4_K_M.gguf", llm, "http://example.test/llm"),
        f16=_pin("mmproj-model-f16.gguf", f16, "http://example.test/f16"),
        q8=FilePin("mmproj-model-q8_0.gguf", hashlib.sha256(q8).hexdigest(), len(q8), None),
    )


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache = Path(self.temp.name)

    def test_hash_mismatch_is_rejected_and_removed(self):
        payload = b"correct-model"
        pin = _pin("model.gguf", payload, "http://example.test/model")
        calls = []

        def opener(url, headers):
            calls.append((url, headers))
            return Response(200, b"wrong-model")

        with patch("sys.stdout", io.StringIO()), self.assertRaises(VisionSetupError) as raised:
            download_verified(pin, self.cache / pin.filename, opener=opener, offline=False)
        self.assertIn(pin.sha256, str(raised.exception))
        self.assertIn("failed verification", str(raised.exception))
        self.assertFalse((self.cache / pin.filename).exists())
        self.assertFalse((self.cache / (pin.filename + ".partial")).exists())
        self.assertEqual(len(calls), 1)

    def test_resume_after_a_dropped_connection(self):
        payload = b"0123456789abcdef"
        pin = _pin("model.gguf", payload, "http://example.test/model")
        calls = []
        state = {"failed": False}

        def opener(url, headers):
            calls.append(dict(headers))
            if not state["failed"]:
                state["failed"] = True
                return Response(200, payload, fail_after=4)
            start = int(headers["Range"].split("=", 1)[1].rstrip("-"))
            return Response(206, payload[start:])

        with patch("sys.stdout", io.StringIO()), self.assertRaises(VisionSetupError) as raised:
            download_verified(pin, self.cache / pin.filename, opener=opener, offline=False)
        self.assertIn("network is unavailable", str(raised.exception))
        partial = self.cache / (pin.filename + ".partial")
        self.assertEqual(partial.read_bytes(), payload[:4])
        with patch("sys.stdout", io.StringIO()):
            status = download_verified(pin, self.cache / pin.filename, opener=opener, offline=False)
        self.assertEqual(status, "downloaded")
        self.assertEqual((self.cache / pin.filename).read_bytes(), payload)
        self.assertFalse(partial.exists())
        self.assertIn("Range", calls[1])
        self.assertEqual(calls[1]["Range"], "bytes=4-")

    def test_offline_names_the_network(self):
        pin = _pin("model.gguf", b"abc", "http://example.test/model")
        with self.assertRaises(VisionSetupError) as raised:
            download_verified(pin, self.cache / pin.filename, opener=lambda *_: (_ for _ in ()).throw(AssertionError("network")), offline=True)
        self.assertIn("The network is off (--offline)", str(raised.exception))
        self.assertIn(pin.filename, str(raised.exception))


class SetupIdempotenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache = Path(self.temp.name) / "vision"
        self.llm = b"language-model"
        self.f16 = b"projector-f16"
        self.q8 = b"projector-q8"
        self.pins = _pins(self.llm, self.f16, self.q8)
        self.downloads = []
        self.quantized = []
        self.library = Path(self.temp.name) / "libshipmb_vision.so"
        self.library.write_bytes(b"library")

    def opener(self, url, headers):
        self.downloads.append((url, dict(headers)))
        body = {"http://example.test/llm": self.llm, "http://example.test/f16": self.f16}[url]
        return Response(200, body)

    def quantize(self, source, dest):
        self.quantized.append((Path(source).read_bytes(), Path(dest)))
        Path(dest).write_bytes(self.q8)

    def ensure(self):
        return self.library

    def run_setup(self, **kwargs):
        stdout, stderr = io.StringIO(), io.StringIO()
        options = {
            "assume_yes": True,
            "cache_dir": self.cache,
            "opener": self.opener,
            "quantize_fn": self.quantize,
            "ensure_library": self.ensure,
            "pins": self.pins,
        }
        options.update(kwargs)
        with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            code = setup_vision(**options)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_second_run_does_not_download_or_quantize_again(self):
        code, out, err = self.run_setup()
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.downloads), 2)
        self.assertEqual(len(self.quantized), 1)
        self.assertIn(self.pins.llm.sha256, out)
        self.assertIn(self.pins.q8.sha256, out)
        self.assertEqual((self.cache / self.pins.llm.filename).read_bytes(), self.llm)
        self.assertEqual((self.cache / self.pins.q8.filename).read_bytes(), self.q8)
        code, out, err = self.run_setup()
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.downloads), 2)
        self.assertEqual(len(self.quantized), 1)
        self.assertIn("already installed", out)
        self.assertIn("already quantized", out)

    def test_bad_download_does_not_become_the_installed_file(self):
        def opener(url, headers):
            return Response(200, b"not-the-model")

        code, _out, err = self.run_setup(opener=opener)
        self.assertEqual(code, 1)
        self.assertIn("failed verification", err)
        self.assertFalse((self.cache / self.pins.llm.filename).exists())
        self.assertEqual(self.quantized, [])

    def test_offline_refuses_a_missing_weight_without_calling_the_network(self):
        def opener(*_args):
            raise AssertionError("offline setup used the network")

        code, _out, err = self.run_setup(offline=True, opener=opener)
        self.assertEqual(code, 1)
        self.assertIn("The network is off (--offline)", err)

    def test_noninteractive_setup_asks_for_yes(self):
        def opener(*_args):
            raise AssertionError("declined setup used the network")

        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("sys.stdout", stdout), patch("sys.stderr", stderr), patch.object(sys.stdin, "isatty", return_value=False):
            code = setup_vision(
                assume_yes=False, cache_dir=self.cache, opener=opener, quantize_fn=self.quantize,
                ensure_library=self.ensure, pins=self.pins,
            )
        self.assertEqual(code, 2)
        self.assertIn("--yes", stderr.getvalue())
        self.assertFalse((self.cache / self.pins.llm.filename).exists())


class CacheAndCliTests(unittest.TestCase):
    def test_cache_paths_follow_the_native_library(self):
        self.assertEqual(
            vision_model_dir({"XDG_CACHE_HOME": "/tmp/xdg", "HOME": "/home/person"}, "linux"),
            Path("/tmp/xdg/shipmblang/vision"),
        )
        self.assertEqual(
            vision_model_dir({"HOME": "/home/person"}, "linux"),
            Path("/home/person/.cache/shipmblang/vision"),
        )
        self.assertEqual(
            vision_model_dir({"HOME": ""}, "linux"),
            Path(".") / ".cache" / "shipmblang" / "vision",
        )
        self.assertEqual(
            vision_model_dir({"HOME": "/Users/person"}, "darwin"),
            Path("/Users/person/Library/Caches/shipmblang/vision"),
        )
        self.assertEqual(
            vision_model_dir({"LOCALAPPDATA": r"C:\Users\person\AppData\Local"}, "win32"),
            Path(r"C:\Users\person\AppData\Local") / "shipmblang" / "vision",
        )
        self.assertEqual(
            vision_model_dir({"USERPROFILE": r"C:\Users\person"}, "win32"),
            Path(r"C:\Users\person") / "AppData" / "Local" / "shipmblang" / "vision",
        )
        self.assertEqual(
            vision_model_dir({"SHIPMB_VISION_MODEL_DIR": "/models", "HOME": "/home/person"}, "linux"),
            Path("/models"),
        )

    def test_default_compiler_prefers_gcc_over_c_plus_plus(self):
        def which(name):
            return {
                "gcc": "/usr/bin/gcc",
                "g++": "/usr/bin/g++",
                "clang": "/usr/bin/clang",
                "clang++": "/usr/bin/clang++",
            }.get(name)

        with patch.dict(os.environ, {}, clear=True), patch("shipmblang.vision_build.shutil.which", side_effect=which):
            self.assertEqual(default_compilers(), ("/usr/bin/gcc", "/usr/bin/g++"))
        with patch.dict(os.environ, {"CC": "/usr/bin/clang", "CXX": "/usr/bin/clang++"}, clear=True):
            self.assertEqual(default_compilers(), ("/usr/bin/clang", "/usr/bin/clang++"))

    def test_frozen_executable_sets_the_bridge_vision_py_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = root / "shipmblang" / "_compiler" / "native" / "libshipmb_vision.so"
            if sys.platform == "win32":
                library = library.with_name("shipmb_vision.dll")
            elif sys.platform == "darwin":
                library = library.with_name("libshipmb_vision.dylib")
            library.parent.mkdir(parents=True)
            library.write_bytes(b"packed")
            environ = os.environ.copy()
            environ.pop("SHIPMB_VISION_BRIDGE", None)
            with patch.object(sys, "frozen", True, create=True), patch.object(sys, "_MEIPASS", str(root), create=True), patch.dict(os.environ, environ, clear=True):
                activate_packed_vision_library()
                from shipmblang._compiler.vision import vision_library_path

                self.assertEqual(vision_library_path(), str(library))
                os.environ["SHIPMB_VISION_BRIDGE"] = str(root / "elsewhere.so")
                activate_packed_vision_library()
                self.assertEqual(os.environ["SHIPMB_VISION_BRIDGE"], str(root / "elsewhere.so"))

    def test_cli_vision_flags(self):
        with tempfile.TemporaryDirectory() as directory:
            env = os.environ.copy()
            env["SHIPMB_VISION_MODEL_DIR"] = directory
            with patch.dict(os.environ, env, clear=True), patch("sys.stderr", io.StringIO()) as stderr, patch("sys.stdout", io.StringIO()) as stdout:
                code = setup_tools.main(["--vision", "--offline", "--check"])
            self.assertEqual(code, 1)
            self.assertIn("missing", stdout.getvalue())
            self.assertIn("shipmblang setup --vision", stderr.getvalue())
        with patch("sys.stderr", io.StringIO()) as stderr:
            self.assertEqual(setup_tools.main(["--offline"]), 2)
        self.assertIn("--offline is only valid with setup --vision", stderr.getvalue())
        with patch("sys.stderr", io.StringIO()) as stderr:
            self.assertEqual(setup_tools.main(["--vision", "--only", "ffmpeg"]), 2)
        self.assertIn("does not take --only", stderr.getvalue())
        with patch.object(sys, "argv", ["shipmblang", "setup", "--help"]), patch("sys.stdout", io.StringIO()) as stdout:
            with self.assertRaises(SystemExit) as raised:
                from shipmblang.cli import main

                main()
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--vision", stdout.getvalue())
        self.assertIn("--offline", stdout.getvalue())


class RealPinTests(unittest.TestCase):
    def test_vendored_pins_agree_with_vision_py(self):
        from shipmblang.vision_setup import load_pins

        pins = load_pins()
        self.assertEqual(pins.llm.sha256, "6b0c74962c44bc6bf4b655b9b02c13eda9d5a0491543ae976d1ac18e4b7892e2")
        self.assertEqual(pins.llm.size, 529101504)
        self.assertEqual(pins.f16.sha256, "ca931d861d0801d9003e50697cd764721a334107c0e0415a51168ee1938462de")
        self.assertEqual(pins.f16.size, 1108746944)
        self.assertEqual(pins.q8.sha256, "cc6e95b117ade93ca9dfc5a81998d14a19b9ae8ce4eb44658a20b55407a7d54f")
        self.assertEqual(pins.q8.size, 726599744)
        self.assertIn("afe9accb78d2995d214cd912920c9c92f4015faa", pins.llm.url)
        self.assertIn("afe9accb78d2995d214cd912920c9c92f4015faa", pins.f16.url)
        self.assertIsNone(pins.q8.url)


if __name__ == "__main__":
    unittest.main()
