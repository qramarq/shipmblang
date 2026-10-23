"""Direct failures name --pipeline legacy only when legacy emits real Core."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUIDE = "Use ShipMB. Open the current project and scan the codebase."


class LegacyPipelineHintTests(unittest.TestCase):
    def invoke(self, source):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT)
        env["SHIPMB_MEMORY"] = "off"
        return subprocess.run(
            [sys.executable, "-m", "shipmblang", "compile",
             "--no-english-model", "--memory", "off", source],
            cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
        )

    def test_unsupported_core_sentence_names_legacy_pipeline(self):
        result = self.invoke(GUIDE)
        self.assertNotEqual(result.returncode, 0, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["pipeline"], "direct")
        self.assertEqual(payload["status"], "unsupported")
        self.assertIsNone(payload["target_code"])
        codes = [item.get("code") for item in payload["diagnostics"]]
        self.assertIn("SMBG100", codes)
        self.assertIn("SMBL002", codes)
        hint = next(item for item in payload["diagnostics"] if item.get("code") == "SMBL002")
        self.assertIn("--pipeline legacy", hint["message"])
        self.assertIn("--pipeline legacy", result.stdout)
        original = next(item for item in payload["diagnostics"] if item.get("code") == "SMBG100")
        self.assertIn("not implemented by the general computation grammar", original["message"])

    def test_intent_only_legacy_core_does_not_hint(self):
        result = self.invoke("Hello world.")
        self.assertNotEqual(result.returncode, 0, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["pipeline"], "direct")
        self.assertEqual(payload["status"], "unsupported")
        codes = [item.get("code") for item in payload.get("diagnostics", [])]
        self.assertNotIn("SMBL002", codes)
        self.assertNotIn("--pipeline legacy", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
