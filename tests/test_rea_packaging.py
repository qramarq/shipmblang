"""tools/rea stays out of the runtime, the wheel, and the Windows zip."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile

from shipmblang.portable import (
    PortableBuildError,
    assemble_portable_tree,
    pyinstaller_argv,
    pyinstaller_excludes,
    reject_dev_only_data,
    write_portable_zip,
)
from shipmblang.vision_setup import VisionPins

from test_portable import _pin


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PACKAGES = ("shipmblang", "driplm", "shiplang", "shipmb", "driplang")


class ReaPackagingTests(unittest.TestCase):
    def test_pyinstaller_excludes_the_dev_tool_module(self):
        self.assertIn("tools.rea", pyinstaller_excludes())
        command = pyinstaller_argv(Path("entry.py"), Path("dist"), Path("work"), [])
        self.assertIn("tools.rea", command)
        self.assertNotIn("tools/rea", command)

    def test_pyinstaller_refuses_tools_rea_data(self):
        with self.assertRaises(PortableBuildError):
            reject_dev_only_data(Path("tools/rea/build-from-text/cli.mjs"), "shipmblang")
        with self.assertRaises(PortableBuildError):
            pyinstaller_argv(
                Path("entry.py"),
                Path("dist"),
                Path("work"),
                [(Path("native/shipmb_vision/pins.json"), "tools/rea")],
            )

    def test_portable_tree_drops_a_planted_tools_rea_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            onedir = root / "onedir"
            onedir.mkdir()
            (onedir / "shipmblang.exe").write_bytes(b"exe")
            planted = onedir / "tools" / "rea" / "build-from-text" / "cli.mjs"
            planted.parent.mkdir(parents=True)
            planted.write_bytes(b"x" * 10000)
            real = __import__("shipmblang.vision_setup", fromlist=["load_pins"]).load_pins()
            pins = VisionPins(
                llm=_pin("MiniCPM-V-4_6-Q4_K_M.gguf", b"llm"),
                f16=_pin("mmproj-model-f16.gguf", b"f16"),
                q8=_pin("mmproj-model-q8_0.gguf", b"q8"),
                source=real.source,
            )
            destination = root / "out"
            assemble_portable_tree(onedir, destination, with_weights=False, pins=pins, version="0.6.0")
            self.assertFalse((destination / "tools").exists())
            archive = root / "out.zip"
            write_portable_zip(destination, archive, root_name="shipmblang-0.6.0-windows-x64")
            with zipfile.ZipFile(archive) as opened:
                names = opened.namelist()
                payloads = [opened.read(name) for name in names]
            self.assertTrue(names)
            self.assertFalse(any("tools/rea" in name for name in names))
            self.assertNotIn(b"x" * 10000, payloads)

    def test_runtime_cli_lsp_and_compiler_do_not_reference_tools_rea(self):
        paths = [
            ROOT / "shipmblang" / "cli.py",
            ROOT / "shipmblang" / "lsp.py",
        ]
        compiler = ROOT / "shipmblang" / "_compiler"
        paths.extend(path for path in compiler.rglob("*.py"))
        for package in RUNTIME_PACKAGES:
            if package == "shipmblang":
                continue
            paths.extend(path for path in (ROOT / package).rglob("*.py"))
        for path in (ROOT / "shipmblang").rglob("*.py"):
            if path.name == "portable.py":
                continue
            paths.append(path)
        for path in paths:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("tools/rea", text, path)
            self.assertNotIn("tools.rea", text, path)
            self.assertNotIn("rea-forge", text, path)

    def test_manifest_prunes_tools_rea_and_dependencies_are_unchanged(self):
        manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
        self.assertIn("prune tools/rea", manifest)
        project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('exclude = ["tools", "tools.*"]', project)
        self.assertIn("dependencies = []", project)
        self.assertNotIn("vitest", project)
        self.assertNotIn("rea-forge", project)

    def test_standalone_bundle_excludes_tools_rea(self):
        path = ROOT / "tools" / "build_standalone.py"
        spec = importlib.util.spec_from_file_location("build_standalone_rea", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertIn("tools.rea", module.EXCLUDES)


if __name__ == "__main__":
    unittest.main()
