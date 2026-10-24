"""Vision programs compile without numpy and fail closed when the library is absent."""
import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from shipmblang import run_direct_program
from shipmblang.notebook import execute_program
from shipmblang.pipelines import VISION_LIBRARY_REQUIRED


ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'Look at "photo.jpg" and tell me what is in it.'


class VisionGuardTests(unittest.TestCase):
    def test_import_and_compile_do_not_need_numpy(self):
        script = textwrap.dedent(
            """
            import sys

            class Block:
                def find_spec(self, fullname, path, target=None):
                    if fullname == "numpy" or fullname.startswith("numpy."):
                        raise ModuleNotFoundError("numpy blocked")
                    return None

            sys.meta_path.insert(0, Block())
            import shipmblang._compiler
            from shipmblang._compiler.direct import compile_direct_program
            result = compile_direct_program(
                'Look at "photo.jpg" and tell me what is in it.',
                memory=False,
                model_provider=None,
            )
            if result.get("status") != "compiled":
                raise SystemExit(result)
            capabilities = result["target_code"]["runtime_contract"]["required_capabilities"]
            if "vision" not in capabilities:
                raise SystemExit(capabilities)
            """
        )
        completed = subprocess.run(
            [sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)

    def test_missing_library_is_a_clear_error(self):
        missing = ROOT / "missing-shipmb-vision.so"
        with patch.dict(os.environ, {"SHIPMB_VISION_BRIDGE": str(missing)}):
            with self.assertRaises(ValueError) as raised:
                run_direct_program(SOURCE, memory=False, model_provider=None)
        self.assertIn("requires the shipmb_vision library / run shipmblang setup --vision", str(raised.exception))
        self.assertEqual(str(raised.exception), VISION_LIBRARY_REQUIRED)

    def test_cli_missing_library_exits_without_traceback(self):
        missing = ROOT / "missing-shipmb-vision.so"
        env = os.environ.copy()
        env["SHIPMB_VISION_BRIDGE"] = str(missing)
        env["SHIPMB_MEMORY"] = "off"
        completed = subprocess.run(
            [sys.executable, "-m", "shipmblang", "run", "--pipeline", "direct", "--profile", "general",
             "--memory", "off", "--no-english-model", SOURCE],
            cwd=ROOT, env=env, capture_output=True, text=True, check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("requires the shipmb_vision library / run shipmblang setup --vision", completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)
        self.assertNotIn("Traceback", completed.stdout)

    def test_supplied_executor_runs_without_the_library(self):
        class Executor:
            def invoke(self, operation, values):
                self.operation = operation
                self.values = values
                return "a cat"

        executor = Executor()
        missing = ROOT / "missing-shipmb-vision.so"
        with patch.dict(os.environ, {"SHIPMB_VISION_BRIDGE": str(missing)}):
            result = run_direct_program(
                SOURCE, memory=False, model_provider=None, vision_executor=executor,
            )
        self.assertEqual(executor.operation, "describe")
        self.assertEqual(result["runtime"]["stdout"], "a cat\n")
        self.assertFalse(any(item.get("level") == "error" for item in result["diagnostics"]))

    def test_notes_refuse_vision_without_running_it(self):
        code, result = execute_program(SOURCE, "run")
        self.assertEqual(code, 2)
        self.assertNotIn("runtime", result)
        self.assertIn("cannot run the native vision engine", result["diagnostics"][0]["message"])


if __name__ == "__main__":
    unittest.main()
