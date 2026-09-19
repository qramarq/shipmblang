"""Private-repository behavior retained by the compiler integration."""
import contextlib
import io
import sys
import unittest
from unittest.mock import patch

import shipmblang
from shipmblang import cli


class RemoteCompatibilityTests(unittest.TestCase):
    def test_onboarding_public_api_remains_available(self):
        from driplm.onboarding import build_onboarding_manifest, run_onboarding_checks
        self.assertIs(shipmblang.build_onboarding_manifest, build_onboarding_manifest)
        self.assertIs(shipmblang.run_onboarding_checks, run_onboarding_checks)

    def test_onboarding_cli_still_dispatches(self):
        with patch.object(sys, "argv", ["shipmblang", "onboarding"]), patch("driplm.onboarding.main", return_value=0) as onboarding:
            with self.assertRaises(SystemExit) as result:
                cli.main()
        self.assertEqual(result.exception.code, 0)
        onboarding.assert_called_once_with()

    def test_legacy_command_catalog_remains_available(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["shipmblang"]), contextlib.redirect_stdout(output):
            cli.main()
        for command in ("onboarding", "train", "prepare", "chat", "download"):
            self.assertIn(command, output.getvalue())


if __name__ == "__main__":
    unittest.main()
