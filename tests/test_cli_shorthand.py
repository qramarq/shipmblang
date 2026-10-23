"""Bare .shipmb invocation and standalone-only command behavior."""

import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from shipmblang import cli, editor
from shipmblang.providers import load_chat_provider

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "quoted_paragraph.shipmb"


class BareFileShorthandTests(unittest.TestCase):
    def test_shorthand_inserts_documented_defaults(self):
        self.assertEqual(
            cli.bare_file_argv(["notes/hello.shipmb"]),
            ["run", "--pipeline", "direct", "--profile", "general", "--memory", "off", "--file", "notes/hello.shipmb"],
        )

    def test_suffix_match_is_case_insensitive(self):
        self.assertEqual(
            cli.bare_file_argv([r"C:\programs\Hello.SHIPMB"]),
            ["run", "--pipeline", "direct", "--profile", "general", "--memory", "off", "--file", r"C:\programs\Hello.SHIPMB"],
        )

    def test_explicit_overrides_are_kept(self):
        self.assertEqual(
            cli.bare_file_argv(["hello.shipmb", "--memory", "on", "--pipeline", "legacy"]),
            ["run", "--file", "hello.shipmb", "--memory", "on", "--pipeline", "legacy"],
        )

    def test_profile_is_not_forced_onto_another_pipeline(self):
        self.assertEqual(
            cli.bare_file_argv(["hello.shipmb", "--pipeline", "ir"]),
            ["run", "--memory", "off", "--file", "hello.shipmb", "--pipeline", "ir"],
        )

    def test_commands_and_other_suffixes_are_unchanged(self):
        self.assertEqual(cli.bare_file_argv(["run", "hello.shipmb"]), ["run", "hello.shipmb"])
        self.assertEqual(cli.bare_file_argv(["compile"]), ["compile"])
        self.assertEqual(cli.bare_file_argv(["notes.shipmb.txt"]), ["notes.shipmb.txt"])
        self.assertEqual(cli.bare_file_argv(["--file", "hello.shipmb"]), ["--file", "hello.shipmb"])

    def test_file_and_file_flag_conflict(self):
        with patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                cli.bare_file_argv(["hello.shipmb", "--file", "other.shipmb"])
        self.assertEqual(raised.exception.code, 2)

    def test_main_dispatches_shorthand_as_run(self):
        seen = {}

        def capture():
            seen["argv"] = sys.argv.copy()
            return 0

        with patch.object(sys, "argv", ["shipmblang", "demo.shipmb", "--format", "text"]), patch("shipmblang.pipelines.run_main", capture):
            cli.main()
        self.assertEqual(
            seen["argv"],
            ["run", "--pipeline", "direct", "--profile", "general", "--memory", "off", "--file", "demo.shipmb", "--format", "text"],
        )

    def test_existing_run_command_is_not_rewritten(self):
        seen = {}

        def capture():
            seen["argv"] = sys.argv.copy()
            return 0

        with patch.object(sys, "argv", ["shipmblang", "run", "demo.shipmb"]), patch("shipmblang.pipelines.run_main", capture):
            cli.main()
        self.assertEqual(seen["argv"], ["run", "demo.shipmb"])

    def test_bare_file_runs_the_quoted_paragraph_example(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["shipmblang", str(EXAMPLE)]), patch("sys.stdout", output):
            cli.main()
        self.assertIn("12", output.getvalue())

    def test_bare_file_format_override_prints_runtime_text(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["shipmblang", str(EXAMPLE), "--format", "text"]), patch("sys.stdout", output):
            cli.main()
        self.assertEqual(output.getvalue(), "12\n")

    def test_help_mentions_the_shorthand(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["shipmblang", "--help"]), patch("sys.stdout", output):
            cli.main()
        text = output.getvalue()
        self.assertIn("program.shipmb", text)
        self.assertIn("memory off", text)
        self.assertIn("compile", text)
        self.assertIn("train", text)

    def test_unknown_command_is_unchanged(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["shipmblang", "nope"]), patch("sys.stdout", output):
            cli.main()
        self.assertIn("Unknown command: nope", output.getvalue())

    def test_python_dash_m_stays_an_unknown_command(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["shipmblang", "-m", "shipmblang.editor_bridge"]), patch("sys.stdout", output):
            cli.main()
        self.assertIn("Unknown command: -m", output.getvalue())


class StandaloneCommandTests(unittest.TestCase):
    def test_frozen_train_explains_missing_model_extras(self):
        stderr = io.StringIO()
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "argv", ["shipmblang", "train"]), patch("sys.stderr", stderr):
            with patch("driplm.__main__.main") as legacy:
                with self.assertRaises(SystemExit) as raised:
                    cli.main()
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("PyTorch", stderr.getvalue())
        self.assertIn("shipmblang[model]", stderr.getvalue())
        legacy.assert_not_called()

    def test_python_train_still_dispatches(self):
        with patch.object(sys, "frozen", False, create=True), patch.object(sys, "argv", ["shipmblang", "train"]):
            with patch("driplm.__main__.main") as legacy:
                cli.main()
        legacy.assert_called_once_with()

    def test_frozen_drip_provider_is_rejected(self):
        with patch.object(sys, "frozen", True, create=True), patch.dict(os.environ, {"SHIPMB_MODEL_PROVIDER": "drip"}, clear=False):
            with self.assertRaises(ValueError) as raised:
                load_chat_provider()
        self.assertIn("PyTorch", str(raised.exception))

    def test_frozen_openai_compatible_provider_still_loads(self):
        env = {
            "SHIPMB_MODEL_PROVIDER": "openai_compatible",
            "SHIPMB_MODEL_BASE_URL": "http://127.0.0.1:9/v1",
            "SHIPMB_MODEL_NAME": "demo",
        }
        with patch.object(sys, "frozen", True, create=True), patch.dict(os.environ, env, clear=False):
            provider = load_chat_provider()
        self.assertEqual(provider.model, "demo")

    def test_frozen_module_flag_reaches_editor_bridge_help(self):
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "argv", ["shipmblang", "-X", "utf8", "-m", "shipmblang.editor_bridge", "--help"]), patch("sys.stdout", io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                cli.main()
        self.assertEqual(raised.exception.code, 0)

    def test_frozen_module_flag_preserves_normal_cli(self):
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "argv", ["shipmblang", "-Xutf8", "-m", "shipmblang", "compile", "--help"]), patch("sys.stdout", io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                cli.main()
        self.assertEqual(raised.exception.code, 0)


class BundledEditorTests(unittest.TestCase):
    def test_python_package_does_not_use_a_packed_editor(self):
        with patch.object(sys, "frozen", False, create=True):
            self.assertIsNone(editor.bundled_editor_executable())

    def test_frozen_launch_uses_the_packed_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "shipmblang" / "native" / "ratatui-editor" / "shipmblang-editor"
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b"#!/bin/sh\n")
            binary.chmod(0o644)
            with patch.object(sys, "frozen", True, create=True), patch.object(sys, "_MEIPASS", str(root), create=True), patch.object(editor, "find_cargo", side_effect=AssertionError("cargo")):
                command, _cwd, _env = editor.editor_launch_plan(Path(directory) / "notes.sqlite3")
            self.assertEqual(command[0], str(binary))
            self.assertIn("--python", command)
            self.assertIn(sys.executable, command)
            self.assertTrue(os.access(binary, os.X_OK))

    def test_missing_cargo_message_is_unchanged_for_python(self):
        with patch.object(sys, "frozen", False, create=True), patch.object(editor, "find_cargo", return_value=None):
            with self.assertRaises(editor.EditorLaunchError) as raised:
                editor.editor_launch_plan(Path("notes.sqlite3"))
        self.assertEqual(
            str(raised.exception),
            "ShipMBLang Editor needs Rust and Cargo. Install Rust from https://rustup.rs, then rerun this command.",
        )

    def test_frozen_build_without_editor_names_cargo(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(sys, "frozen", True, create=True), patch.object(sys, "_MEIPASS", directory, create=True), patch.object(editor, "find_cargo", return_value=None):
                with self.assertRaises(editor.EditorLaunchError) as raised:
                    editor.editor_launch_plan(Path(directory) / "notes.sqlite3")
        self.assertIn("does not include the Ratatui editor binary", str(raised.exception))
        self.assertIn("https://rustup.rs", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
