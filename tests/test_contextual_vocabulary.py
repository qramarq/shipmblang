"""Public language integration gates for the reviewed compiler vocabulary."""
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from shipmblang import compile_direct_program, run_direct_program
from shipmblang._compiler import compile_direct_program as compile_snapshot


class ContextualVocabularyTests(unittest.TestCase):
    def test_equivalent_requests_remain_offline_and_preserve_source(self):
        sources = (
            "Show the sum of 2 and 3.",
            "Present the sum of 2 and 3.",
            "Please show me the sum of 2 and 3.",
            "Start with 2. Add 3. Show it.",
            "Could you add 2 and 3 together and tell me the result?",
            "Compute the aggregate of 2 and 3.",
            "Pls show me the total of 2 and 3.",
            "I want you to calculate the total of 2 and 3.",
        )
        with patch("shipmblang.providers.load_chat_provider", side_effect=AssertionError("Unexpected model call")):
            for source in sources:
                with self.subTest(source=source):
                    result = run_direct_program(source, memory=False)
                    self.assertEqual(result["status"], "compiled", result)
                    self.assertEqual(result["source"], source)
                    self.assertEqual(result["runtime"]["stdout"], "5\n")

    def test_literal_and_identifier_senses_are_unchanged(self):
        for source, expected in (
            ('Present "present add install aggregate do not change".', "present add install aggregate do not change\n"),
            ('Let present be 8. Let aggregate be 3. Show present minus aggregate.', "5\n"),
            ('Let install be a mutable integer with value 2. Add 3 to install. Present install.', "5\n"),
            ('Show the difference of 2 and 9.', "-7\n"),
        ):
            with self.subTest(source=source):
                result = run_direct_program(source, memory=False, model_provider=None)
                self.assertEqual(result["status"], "compiled", result)
                self.assertEqual(result["runtime"]["stdout"], expected)

    def test_constraints_and_ambiguous_senses_never_partially_execute(self):
        for source in (
            "Do not present the sum of 2 and 3.",
            "Present the sum of 2 and 3 unless I say otherwise.",
            "Present the sum of 2 and 3. Then install a package.",
            "Add the package requests.",
            "Add 3.",
            "Present it.",
            "Compute the aggregate.",
            "Yo, hook me up with the aggregate.",
            "Could you add 2 and 3 together and tell me the result except 3?",
        ):
            with self.subTest(source=source):
                result = run_direct_program(source, memory=False, model_provider=None)
                self.assertNotEqual(result["status"], "compiled", result)
                self.assertIsNone(result["target_code"])
                self.assertNotIn("runtime", result)
                self.assertEqual(result["source"], source)

    def test_public_adapter_matches_exact_bundled_compiler(self):
        for source in ("Present the total of 2 and 3.", "Present it.", "Add requests."):
            options = dict(memory=False, model_provider=None, profile="general", accept_model_interpretation=True)
            self.assertEqual(compile_direct_program(source, **options), compile_snapshot(source, **options))

    def test_manifest_covers_every_compiler_module(self):
        root = Path(__file__).resolve().parents[1] / "shipmblang/_compiler"
        manifest = json.loads((root / "BUNDLED.json").read_text())
        modules = {path.relative_to(root).as_posix() for path in root.rglob("*.py")}
        self.assertLessEqual(modules, manifest["sha256"].keys())
        self.assertIn("general_vocabulary.py", modules)
        for name, digest in manifest["sha256"].items():
            self.assertEqual(hashlib.sha256((root / name).read_bytes()).hexdigest(), digest, name)
