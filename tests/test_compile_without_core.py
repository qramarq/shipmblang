"""Core is an optional review output, never an input to bytecode compilation."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import contextlib
import io
import tempfile
import unittest
from unittest.mock import patch

from driplm import natural_syntax
from shipmblang import compile_natural_program


ROKU_PROSE = "let's use the tv pack library in shipmblang to control this roku tv like a remote would. being able to agenticallly call and use the resources a roku remote controller would have and be able to search/open/close apps and show me any errors that happen when we execute commands. install shipmb on the tv and give me voice and chat bot access if able."


def fail_renderer(*args, **kwargs):
    raise AssertionError("Core rendering must not run")


def check_bytecode_and_trace_are_identical_without_core():
    legacy = compile_natural_program(ROKU_PROSE)
    assert isinstance(legacy["core"], str)
    with patch.object(natural_syntax, "render_core_program", fail_renderer):
        direct = compile_natural_program(ROKU_PROSE, include_core=False)
    assert direct == {**legacy, "core": None}
    assert direct["target_code"]["native_machine_code"] is False


def check_bytecode_cli_skips_renderer():
    expected = compile_natural_program(ROKU_PROSE, include_core=False)["target_code"]
    with patch.object(natural_syntax, "render_core_program", fail_renderer):
        assert json.loads(capture_cli(["compile", ROKU_PROSE, "--format", "bytecode"])) == expected


def check_legacy_cli_formats():
    expected = compile_natural_program(ROKU_PROSE)
    assert capture_cli(["compile", ROKU_PROSE]).strip() == expected["core"].strip()
    assert json.loads(capture_cli(["compile", ROKU_PROSE, "--format", "json"])) == expected


def check_isolated_compile_without_sibling_projects(tmp_path):
    # Copy only the two distribution packages, with no sibling source or site packages.
    root = Path(__file__).resolve().parents[1]
    for package in ("shipmblang", "driplm"):
        shutil.copytree(root / package, tmp_path / package, ignore=shutil.ignore_patterns("__pycache__"))
    for relative in ("driplm/error_explainer.py", "driplm/project_context.py",
                     "shipmblang/providers.py", "shipmblang/runtime_context.py"):
        (tmp_path / relative).unlink(missing_ok=True)
    script = """
import importlib.abc
import runpy
import sys
class BlockExternal(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if (fullname.split('.')[0] in {'shipmblangcore', 'shipmbcompiler', 'torch', 'tokenizers'}
                or fullname in {'driplm.error_explainer', 'driplm.project_context',
                                'driplm.model', 'driplm.inference', 'shipmblang.providers',
                                'shipmblang.runtime_context', 'shipmblang.multimodal'}):
            raise AssertionError('Forbidden compile dependency: ' + fullname)
sys.meta_path.insert(0, BlockExternal())
sys.path.insert(0, sys.argv.pop(1))
from shipmblang import compile_natural_program
assert compile_natural_program(sys.argv[1], include_core=False)['core'] is None
sys.argv = ['shipmblang', 'compile', sys.argv[1], '--format', 'bytecode']
runpy.run_module('shipmblang', run_name='__main__')
"""
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", script, str(tmp_path), ROKU_PROSE],
        cwd=tmp_path, capture_output=True, text=True, check=True,
    )
    emitted = json.loads(result.stdout)
    assert emitted["target"] == "shipmblang-bytecode"
    assert emitted["bytecode"]
    assert "core" not in emitted


def capture_cli(argv):
    output = io.StringIO()
    with patch.object(sys, "argv", argv), contextlib.redirect_stdout(output):
        natural_syntax.main()
    return output.getvalue()


class CompileWithoutCoreTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"SHIPMB_MEMORY": "off"})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_public_exports_remain_available(self):
        import driplm
        import shipmblang
        for package in (driplm, shipmblang):
            for name in package.__all__:
                self.assertIn(name, dir(package))
                self.assertIsNotNone(getattr(package, name))
        self.assertIs(driplm.drip, driplm.drip_printf)
        self.assertIs(shipmblang.compile_natural_program, natural_syntax.compile_natural_program)

    def test_run_retains_core_output(self):
        result = natural_syntax.run_natural_program("Use ShipMB.")
        self.assertEqual(result["program"]["core"], "use shipmb")

    def test_bytecode_and_trace(self):
        check_bytecode_and_trace_are_identical_without_core()

    def test_cli_without_renderer(self):
        check_bytecode_cli_skips_renderer()

    def test_legacy_formats(self):
        check_legacy_cli_formats()

    def test_isolated_compile(self):
        with tempfile.TemporaryDirectory() as directory:
            check_isolated_compile_without_sibling_projects(Path(directory))


if __name__ == "__main__":
    unittest.main()
