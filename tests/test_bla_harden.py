"""BLA packaging step: which files are hardened, and which stay byte-for-byte."""

import importlib.util
import inspect
from pathlib import Path
import tempfile
import unittest


def _load():
    path = Path(__file__).resolve().parents[1] / "tools" / "bla_harden.py"
    spec = importlib.util.spec_from_file_location("bla_harden", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_builder():
    path = Path(__file__).resolve().parents[1] / "tools" / "build_portable.py"
    spec = importlib.util.spec_from_file_location("build_portable_bla", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.bla = _load()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        native = self.root / "_internal" / "shipmblang" / "_compiler" / "native"
        native.mkdir(parents=True)
        (self.root / "shipmblang.exe").write_bytes(b"MZ-exe")
        (native / "shipmb_vision.dll").write_bytes(b"MZ-dll")
        (native / "llama-quantize.exe").write_bytes(b"MZ-quant")
        (self.root / "vcruntime140.dll").write_bytes(b"vc")
        (self.root / "vcruntime140_1.dll").write_bytes(b"vc1")
        (self.root / "_internal" / "python314.dll").write_bytes(b"py")
        (self.root / "vision").mkdir()
        (self.root / "vision" / "MiniCPM-V-4_6-Q4_K_M.gguf").write_bytes(b"GGUF-weights")
        (self.root / "extra.zip").write_bytes(b"PK")

    def test_selects_only_the_three_program_binaries(self):
        selected = self.bla.select_release_binaries(self.root)
        self.assertEqual(
            [path.name for path in selected],
            ["shipmblang.exe", "shipmb_vision.dll", "llama-quantize.exe"],
        )
        self.assertIn("_compiler", selected[1].parts)

    def test_missing_binary_is_an_error(self):
        (self.root / "shipmblang.exe").unlink()
        with self.assertRaises(self.bla.PortableBuildError) as raised:
            self.bla.select_release_binaries(self.root)
        self.assertIn("shipmblang.exe", str(raised.exception))

    def test_duplicate_binary_is_an_error(self):
        (self.root / "_internal" / "shipmb_vision.dll").write_bytes(b"MZ-dup")
        with self.assertRaises(self.bla.PortableBuildError) as raised:
            self.bla.select_release_binaries(self.root)
        self.assertIn("shipmb_vision.dll", str(raised.exception))


class HardenTreeTests(unittest.TestCase):
    def test_appends_a_trailer_and_leaves_other_files_unchanged(self):
        bla = _load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payloads = {
                "shipmblang.exe": b"MZ-exe",
                "shipmb_vision.dll": b"MZ-dll",
                "llama-quantize.exe": b"MZ-quant",
            }
            for name, payload in payloads.items():
                (root / name).write_bytes(payload)
            (root / "vcruntime140.dll").write_bytes(b"vc-runtime")
            (root / "model.gguf").write_bytes(b"weights-stay")
            calls = []

            def run_json(arguments):
                calls.append(list(arguments))
                if arguments[0] == "protect":
                    source = Path(arguments[1]).read_bytes()
                    Path(arguments[3]).write_bytes(source + b"TRAILER")
                    return {"intensity": arguments[arguments.index("--intensity") + 1]}
                if arguments[0] == "verify":
                    return {"overallPassed": True, "functionalIntegrityVerified": True}
                raise AssertionError(arguments)

            results = bla.harden_tree(root, run_json=run_json)
            self.assertEqual(sum(item["added_bytes"] for item in results), len(b"TRAILER") * 3)
            for name, payload in payloads.items():
                self.assertEqual((root / name).read_bytes(), payload + b"TRAILER")
            self.assertEqual((root / "vcruntime140.dll").read_bytes(), b"vc-runtime")
            self.assertEqual((root / "model.gguf").read_bytes(), b"weights-stay")
            protects = [call for call in calls if call[0] == "protect"]
            self.assertEqual(len(protects), 3)
            for call in protects:
                self.assertIn("--intensity", call)
                self.assertEqual(call[call.index("--intensity") + 1], "balanced")
                self.assertNotIn("bankrupt", call)
                self.assertEqual(call[call.index("--seed") + 1], "shipmblang-portable")
            self.assertEqual(len([call for call in calls if call[0] == "verify"]), 3)
            self.assertFalse(list(root.glob("*.bla-tmp")))

    def test_oversized_trailer_is_rejected_and_the_original_stays(self):
        bla = _load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "shipmblang.exe").write_bytes(b"MZ-exe")
            (root / "shipmb_vision.dll").write_bytes(b"MZ-dll")
            (root / "llama-quantize.exe").write_bytes(b"MZ-quant")

            def run_json(arguments):
                if arguments[0] == "protect":
                    Path(arguments[3]).write_bytes(b"MZ" + (b"x" * (bla.MAX_GROWTH_BYTES + 8)))
                    return {}
                raise AssertionError(arguments)

            with self.assertRaises(bla.PortableBuildError):
                bla.harden_tree(root, run_json=run_json)
            self.assertEqual((root / "shipmblang.exe").read_bytes(), b"MZ-exe")
            self.assertFalse(list(root.glob("*.bla-tmp")))

    def test_failed_verify_does_not_replace_the_binary(self):
        bla = _load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "shipmblang.exe").write_bytes(b"MZ-exe")
            (root / "shipmb_vision.dll").write_bytes(b"MZ-dll")
            (root / "llama-quantize.exe").write_bytes(b"MZ-quant")

            def run_json(arguments):
                if arguments[0] == "protect":
                    source = Path(arguments[1]).read_bytes()
                    Path(arguments[3]).write_bytes(source + b"TRAILER")
                    return {}
                return {"overallPassed": False, "functionalIntegrityVerified": True}

            with self.assertRaises(bla.PortableBuildError):
                bla.harden_tree(root, run_json=run_json)
            self.assertEqual((root / "shipmblang.exe").read_bytes(), b"MZ-exe")

    def test_rewritten_pe_is_rejected(self):
        bla = _load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "shipmblang.exe").write_bytes(b"MZ-exe")
            (root / "shipmb_vision.dll").write_bytes(b"MZ-dll")
            (root / "llama-quantize.exe").write_bytes(b"MZ-quant")

            def run_json(arguments):
                if arguments[0] == "protect":
                    Path(arguments[3]).write_bytes(b"MZ-replaced")
                    return {}
                raise AssertionError(arguments)

            with self.assertRaises(bla.PortableBuildError) as raised:
                bla.harden_tree(root, run_json=run_json)
            self.assertIn("rewritten", str(raised.exception))
            self.assertEqual((root / "shipmblang.exe").read_bytes(), b"MZ-exe")


class BuildOrderTests(unittest.TestCase):
    def test_both_folders_are_hardened_before_they_are_zipped(self):
        source = inspect.getsource(_load_builder().build)
        self.assertLess(source.index("harden_portable_tree(folder)"), source.index("write_portable_zip(folder"))
        self.assertLess(source.index("harden_portable_tree(stage)"), source.index("write_portable_zip(stage"))

    def test_readme_mentions_the_step_without_a_url(self):
        readme = Path(__file__).resolve().parents[1].joinpath("README.md").read_text(encoding="utf-8")
        start = readme.index("## Portable Windows zip")
        end = readme.index("\n## ", start + 1)
        section = readme[start:end]
        self.assertIn("bla-agents@latest", section)
        self.assertIn("balanced", section)
        self.assertNotIn("http://", section)
        self.assertNotIn("https://", section)


if __name__ == "__main__":
    unittest.main()
