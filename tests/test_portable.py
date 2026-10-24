"""Portable Windows zip: manifest, pins, weight directory, and the size report."""

import hashlib
import importlib.util
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from shipmblang.portable import (
    COMPRESS_LEVEL,
    SIZE_TABLE_KEYS,
    VISION_BUILD_CONFIG,
    PortableBuildError,
    assemble_portable_tree,
    discover_vc_dlls,
    not_built_weight_lines,
    pinned_size_lines,
    pyinstaller_argv,
    pyinstaller_excludes,
    report_zip,
    require_size_keys,
    runtime_weights,
    verify_weight_file,
    write_portable_zip,
    zip_filename,
)
from shipmblang.standalone import activate_bundled_vision_weights, choose_vision_model_dir
from shipmblang.vision_setup import FilePin, VisionPins, load_pins


def _pin(name: str, payload: bytes) -> FilePin:
    return FilePin(name, hashlib.sha256(payload).hexdigest(), len(payload), None)


def _load_builder():
    path = Path(__file__).resolve().parents[1] / "tools" / "build_portable.py"
    spec = importlib.util.spec_from_file_location("build_portable", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ManifestTests(unittest.TestCase):
    def test_excludes_leave_sqlite3_and_drop_tk_and_torch(self):
        excludes = pyinstaller_excludes()
        self.assertIn("tkinter", excludes)
        self.assertIn("torch", excludes)
        self.assertIn("unittest", excludes)
        self.assertNotIn("sqlite3", excludes)
        self.assertIn("sqlite3.test", excludes)

    def test_pyinstaller_command_is_onedir_without_upx(self):
        command = pyinstaller_argv(Path("entry.py"), Path("dist"), Path("work"), [])
        self.assertIn("--onedir", command)
        self.assertIn("--noupx", command)
        self.assertNotIn("--onefile", command)
        self.assertNotIn("--upx-dir", command)
        self.assertNotIn("sqlite3", command)

    def test_vision_library_stays_release(self):
        self.assertEqual(VISION_BUILD_CONFIG, "Release")
        self.assertEqual(COMPRESS_LEVEL, 9)

    def test_runtime_weights_omit_the_f16_projector(self):
        pins = load_pins()
        names = [pin.filename for pin in runtime_weights(pins)]
        self.assertEqual(names, [pins.llm.filename, pins.q8.filename])
        self.assertNotIn(pins.f16.filename, names)

    def test_pinned_sizes_match_the_readme_table(self):
        pins = load_pins()
        self.assertEqual(pins.llm.size, 529101504)
        self.assertEqual(pins.f16.size, 1108746944)
        self.assertEqual(pins.q8.size, 726599744)
        lines = pinned_size_lines(pins)
        self.assertIn("SIZE weight_llm_bytes=529101504", lines)
        self.assertIn("SIZE weight_f16_bytes=1108746944", lines)
        self.assertIn("SIZE weight_q8_bytes=726599744", lines)
        self.assertIn("SIZE download_bytes=1637848448", lines)
        self.assertIn("SIZE weights_on_disk_bytes=2364448192", lines)

    def test_readme_table_uses_those_keys_and_does_not_invent_a_url(self):
        readme = Path(__file__).resolve().parents[1].joinpath("README.md").read_text(encoding="utf-8")
        start = readme.index("## Portable Windows zip")
        end = readme.index("\n## ", start + 1)
        section = readme[start:end]
        for key in SIZE_TABLE_KEYS:
            self.assertIn(f"`{key}`", section)
        self.assertNotIn("TBD (measured on Windows)", section)
        self.assertIn("16398332", section)
        self.assertIn("16.4 MB", section)
        self.assertIn("2399844148", section)
        self.assertIn("2.4 GB", section)
        self.assertIn("1284", section)
        self.assertIn("1420", section)
        self.assertIn("529101504", section)
        self.assertIn("1108746944", section)
        self.assertIn("726599744", section)
        self.assertIn("1637848448", section)
        self.assertIn("2364448192", section)
        self.assertNotIn("http://", section)
        self.assertNotIn("https://", section)
        self.assertIn("python tools/build_portable.py", section)


class PinTests(unittest.TestCase):
    def test_mismatch_and_missing_file_are_errors(self):
        pin = _pin("MiniCPM-V-4_6-Q4_K_M.gguf", b"weights")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / pin.filename
            path.write_bytes(b"nope")
            with self.assertRaises(PortableBuildError) as raised:
                verify_weight_file(path, pin)
            self.assertIn(pin.sha256, str(raised.exception))
            missing = Path(directory) / "absent.gguf"
            with self.assertRaises(PortableBuildError) as raised:
                verify_weight_file(missing, pin)
            self.assertIn("Missing", str(raised.exception))


class TreeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.onedir = self.root / "onedir"
        native = self.onedir / "_internal" / "shipmblang" / "_compiler" / "native"
        native.mkdir(parents=True)
        (self.onedir / "shipmblang.exe").write_bytes(b"exe")
        (native / "shipmb_vision.dll").write_bytes(b"dll-native")
        (self.onedir / "_internal" / "shipmb_vision.dll").write_bytes(b"dll-dup")
        (native / "bin").mkdir()
        (native / "bin" / "llama-quantize.exe").write_bytes(b"quant")
        (self.onedir / "_internal" / "llama-quantize.exe").write_bytes(b"quant-dup")
        (self.onedir / "debug.pdb").write_bytes(b"pdb")
        (self.onedir / "tool.lib").write_bytes(b"lib")
        (self.onedir / "tool.exp").write_bytes(b"exp")
        (self.onedir / "fixtures").mkdir()
        (self.onedir / "fixtures" / "sample.png").write_bytes(b"png")
        (self.onedir / "_internal" / "vcruntime140.dll").write_bytes(b"vc-internal")
        self.redist = self.root / "redist"
        self.redist.mkdir()
        (self.redist / "vcruntime140.dll").write_bytes(b"vc140")
        (self.redist / "vcruntime140_1.dll").write_bytes(b"vc1401")
        self.vc = {
            "vcruntime140.dll": self.redist / "vcruntime140.dll",
            "vcruntime140_1.dll": self.redist / "vcruntime140_1.dll",
        }
        real = load_pins()
        self.llm = b"llm-bytes"
        self.q8 = b"q8-bytes"
        self.f16 = b"f16-bytes"
        self.pins = VisionPins(
            llm=_pin("MiniCPM-V-4_6-Q4_K_M.gguf", self.llm),
            f16=_pin("mmproj-model-f16.gguf", self.f16),
            q8=_pin("mmproj-model-q8_0.gguf", self.q8),
            source=real.source,
        )

    def test_default_tree_has_no_weights_and_one_copy_of_each_tool(self):
        destination = self.root / "out"
        assemble_portable_tree(
            self.onedir, destination, with_weights=False, pins=self.pins, vc_dlls=self.vc, version="0.6.0",
        )
        self.assertFalse(list(destination.rglob("*.gguf")))
        self.assertFalse(list(destination.rglob("*.pdb")))
        self.assertFalse(list(destination.rglob("*.lib")))
        self.assertFalse(list(destination.rglob("*.exp")))
        self.assertFalse((destination / "fixtures").exists())
        dlls = list(destination.rglob("shipmb_vision.dll"))
        self.assertEqual(len(dlls), 1)
        self.assertEqual(dlls[0].read_bytes(), b"dll-native")
        self.assertIn("native", dlls[0].parts)
        quants = list(destination.rglob("llama-quantize.exe"))
        self.assertEqual(len(quants), 1)
        self.assertEqual(quants[0].read_bytes(), b"quant")
        self.assertEqual((destination / "vcruntime140.dll").read_bytes(), b"vc140")
        self.assertEqual((destination / "vcruntime140_1.dll").read_bytes(), b"vc1401")
        self.assertFalse((destination / "_internal" / "vcruntime140.dll").exists())
        self.assertTrue((destination / "licenses" / "VC-RUNTIME.txt").is_file())
        self.assertTrue((destination / "pins" / "weight_pins.json").is_file())
        readme = (destination / "README.txt").read_text(encoding="ascii")
        self.assertIn("does not include model weights", readme)
        self.assertIn(str(self.pins.llm.size), readme)

    def test_with_weights_packs_the_runtime_files_only(self):
        cache = self.root / "cache"
        cache.mkdir()
        (cache / self.pins.llm.filename).write_bytes(self.llm)
        (cache / self.pins.q8.filename).write_bytes(self.q8)
        (cache / self.pins.f16.filename).write_bytes(self.f16)
        smuggled = self.onedir / "vision"
        smuggled.mkdir()
        (smuggled / self.pins.f16.filename).write_bytes(self.f16)
        destination = self.root / "out"
        assemble_portable_tree(
            self.onedir,
            destination,
            with_weights=True,
            weight_source=cache,
            pins=self.pins,
            vc_dlls=self.vc,
            version="0.6.0",
        )
        names = sorted(path.name for path in (destination / "vision").iterdir())
        self.assertEqual(names, [self.pins.llm.filename, self.pins.q8.filename])
        self.assertNotIn(self.pins.f16.filename, names)
        text = (destination / "README.txt").read_text(encoding="ascii")
        self.assertIn("includes the two runtime weight files", text)

    def test_missing_vc_runtime_is_an_error(self):
        with self.assertRaises(PortableBuildError):
            discover_vc_dlls([self.root / "empty"])
        found = discover_vc_dlls([self.redist])
        self.assertEqual(set(found), {"vcruntime140.dll", "vcruntime140_1.dll"})
        only_internal = self.root / "later"
        internal = only_internal / "_internal"
        internal.mkdir(parents=True)
        (internal / "vcruntime140.dll").write_bytes(b"from-onedir")
        (internal / "vcruntime140_1.dll").write_bytes(b"from-onedir-1")
        found = discover_vc_dlls([self.root / "absent"], only_internal)
        self.assertEqual(found["vcruntime140.dll"].read_bytes(), b"from-onedir")


class ZipReportTests(unittest.TestCase):
    def test_zip_is_deflated_zip64_and_prints_the_table_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "shipmblang-0.6.0-windows-x64"
            source.mkdir()
            (source / "shipmblang.exe").write_bytes(b"hello portable")
            (source / "vcruntime140.dll").write_bytes(b"a")
            (source / "vcruntime140_1.dll").write_bytes(b"b")
            native = source / "_internal" / "native"
            native.mkdir(parents=True)
            (native / "shipmb_vision.dll").write_bytes(b"dll" * 20)
            (native / "llama-quantize.exe").write_bytes(b"quant" * 10)
            archive = root / "out.zip"
            write_portable_zip(source, archive)
            raw = archive.read_bytes()
            self.assertIn(b"\x01\x00\x10\x00", raw)
            with zipfile.ZipFile(archive) as opened:
                infos = opened.infolist()
                self.assertTrue(infos)
                self.assertGreaterEqual(infos[0].create_version, 45)
                self.assertEqual(infos[0].compress_type, zipfile.ZIP_DEFLATED)
                names = [info.filename for info in infos]
            self.assertTrue(all(name.startswith("shipmblang-0.6.0-windows-x64/") for name in names))
            roots = {name.split("/", 1)[0] for name in names}
            self.assertEqual(roots, {"shipmblang-0.6.0-windows-x64"})
            pins = load_pins()
            lines = report_zip(archive, "default", pins)
            lines.extend(not_built_weight_lines())
            values = require_size_keys(lines)
            self.assertEqual(values["with_weights_zip_bytes"], "not_built")
            self.assertEqual(values["with_weights_unzipped_bytes"], "not_built")
            self.assertEqual(values["weight_llm_bytes"], "529101504")
            self.assertEqual(values["download_bytes"], "1637848448")
            self.assertEqual(values["weights_on_disk_bytes"], "2364448192")
            self.assertNotEqual(values["default_zip_bytes"], "not_built")
            self.assertTrue(any(line.startswith("SIZE top 1 ") for line in lines))
            unzipped = int(values["default_unzipped_bytes"])
            self.assertEqual(int(values["disk_after_setup_bytes"]), unzipped + pins.llm.size + pins.f16.size + pins.q8.size)
            self.assertGreater(int(values["vision_dll_uncompressed_bytes"]), 0)
            self.assertGreater(int(values["llama_quantize_uncompressed_bytes"]), 0)
            self.assertEqual(int(values["vc_msvcp140_uncompressed_bytes"]), 0)
            extracted = root / "extracted"
            with zipfile.ZipFile(archive) as opened:
                opened.extractall(extracted)
            self.assertTrue((extracted / "shipmblang-0.6.0-windows-x64" / "shipmblang.exe").is_file())

    def test_other_platform_refuses_the_exe_zip(self):
        module = _load_builder()
        with patch.object(sys, "platform", "linux"):
            self.assertEqual(module.main([]), 2)

    def test_check_weights_prints_sizes_without_building(self):
        module = _load_builder()
        payload_llm = b"llm"
        payload_q8 = b"q8"
        payload_f16 = b"f16"
        pins = VisionPins(
            llm=_pin("MiniCPM-V-4_6-Q4_K_M.gguf", payload_llm),
            f16=_pin("mmproj-model-f16.gguf", payload_f16),
            q8=_pin("mmproj-model-q8_0.gguf", payload_q8),
        )
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            (cache / pins.llm.filename).write_bytes(payload_llm)
            (cache / pins.q8.filename).write_bytes(payload_q8)
            stdout = io.StringIO()
            with patch("shipmblang.portable.load_pins", return_value=pins), patch(
                "shipmblang.vision_setup.vision_model_dir", return_value=cache,
            ), patch("sys.stdout", stdout):
                code = module.main(["--check-weights"])
            self.assertEqual(code, 0)
            text = stdout.getvalue()
            self.assertIn(f"SIZE weight_llm_bytes={len(payload_llm)}", text)
            self.assertNotIn("with_weights_zip_bytes", text)
            self.assertNotIn("not_built", text)
            self.assertIn(f"weights_ok {cache}", text)


class ModelDirTests(unittest.TestCase):
    def test_resolution_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root / "shipmblang.exe"
            exe.write_bytes(b"")
            vision = root / "vision"
            chosen, path = choose_vision_model_dir(
                {"SHIPMB_VISION_MODEL_DIR": str(root / "explicit")}, frozen=True, executable=exe,
            )
            self.assertEqual(chosen, "env")
            self.assertEqual(path, root / "explicit")
            chosen, path = choose_vision_model_dir(
                {"SHIPMB_VISION_MODEL_DIR": "   "}, frozen=False, executable=exe,
            )
            self.assertEqual((chosen, path), ("cache", None))
            vision.mkdir()
            chosen, path = choose_vision_model_dir({}, frozen=True, executable=exe)
            self.assertEqual(chosen, "bundled")
            self.assertEqual(path, vision.resolve())
            chosen, path = choose_vision_model_dir({}, frozen=False, executable=exe)
            self.assertEqual((chosen, path), ("cache", None))
            vision.rmdir()
            chosen, path = choose_vision_model_dir({}, frozen=True, executable=exe)
            self.assertEqual((chosen, path), ("cache", None))

    def test_activate_sets_the_variable_only_for_a_shipped_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root / "shipmblang.exe"
            exe.write_bytes(b"")
            vision = root / "vision"
            vision.mkdir()
            with patch.dict(os.environ, {}, clear=True), patch.object(sys, "frozen", True, create=True), patch.object(
                sys, "executable", str(exe),
            ):
                found = activate_bundled_vision_weights()
                self.assertEqual(found.resolve(), vision.resolve())
                self.assertEqual(Path(os.environ["SHIPMB_VISION_MODEL_DIR"]).resolve(), vision.resolve())
                os.environ["SHIPMB_VISION_MODEL_DIR"] = str(root / "keep")
                self.assertIsNone(activate_bundled_vision_weights())
                self.assertEqual(os.environ["SHIPMB_VISION_MODEL_DIR"], str(root / "keep"))
            with patch.dict(os.environ, {}, clear=True), patch.object(sys, "frozen", False, create=True), patch.object(
                sys, "executable", str(exe),
            ):
                self.assertIsNone(activate_bundled_vision_weights())
                self.assertNotIn("SHIPMB_VISION_MODEL_DIR", os.environ)


class NameTests(unittest.TestCase):
    def test_zip_names(self):
        self.assertEqual(zip_filename("0.6.0"), "shipmblang-0.6.0-windows-x64.zip")
        self.assertEqual(
            zip_filename("0.6.0", with_weights=True),
            "shipmblang-0.6.0-windows-x64-with-weights.zip",
        )


if __name__ == "__main__":
    unittest.main()
