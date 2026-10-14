"""Exercise the real bundled compiler rather than mocked integration APIs."""
from pathlib import Path
import sys
import unittest


@unittest.skipIf(sys.version_info < (3, 11), "Direct compilation requires Python 3.11+")
class BundledCompilerTests(unittest.TestCase):
    def test_general_examples_compile_and_run(self):
        from shipmblang import run_direct_program

        examples = Path(__file__).resolve().parents[1] / "examples"
        for name, expected in (("general_sum.shipmb", "27\n"),
                               ("general_functions.shipmb", "720\n"),
                               ("quoted_paragraph.shipmb", "12\n")):
            with self.subTest(example=name):
                result = run_direct_program((examples / name).read_text(encoding="utf-8"),
                                            profile="general", memory=False)
                self.assertEqual(result["status"], "compiled", result)
                self.assertEqual(result["runtime"]["stdout"], expected)

    def test_ir_pipeline_is_available(self):
        from shipmblang._compiler import compile_source

        result = compile_source(
            "Use the tv pack library in shipmblang to control this Roku TV like a remote.",
            include_core=False, memory=False)
        self.assertTrue(result["target_code"]["bytecode"])


if __name__ == "__main__":
    unittest.main()
