"""Optional compiler routing and legacy compatibility without installed extras."""

import contextlib
import io
import json
import os
import sys
import types
import unittest
import warnings
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import Mock, patch

from shipmblang import pipelines


@unittest.skipIf(sys.version_info < (3, 11), "Direct compiler requires Python 3.11+")
class PipelineTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"SHIPMB_MEMORY": "off"})
        environment.start()
        self.addCleanup(environment.stop)
        self.artifact = {"producer": "shipmbcompiler", "version": "0.2", "bytecode": []}
        self.result = {"status": "compiled", "pipeline": "direct", "diagnostics": [],
                       "target_code": self.artifact, "core_source": None}
        self.compiler = types.ModuleType("shipmbcompiler")
        self.compiler.compile_direct_program = Mock(return_value=self.result)
        self.compiler.compile_source = Mock(return_value=self.result)

    def invoke(self, *args, run=False):
        output = io.StringIO()
        with patch.object(sys, "argv", ["compile", *args]), contextlib.redirect_stdout(output):
            (pipelines.run_main if run else pipelines.main)()
        return json.loads(output.getvalue())

    def test_adapter_retains_contract_and_disables_memory_by_env(self):
        provider = Mock()
        with patch.dict(sys.modules, {"shipmbcompiler": self.compiler}), patch.dict(os.environ, {"SHIPMB_MEMORY": "off", "SHIPMB_MEMORY_DB": "custom.sqlite"}):
            result = pipelines.compile_direct_program("exact source", model_provider=provider, bindings={"tv": "roku"})
        self.assertIs(result, self.result)
        call = self.compiler.compile_direct_program.call_args
        self.assertEqual(call.args, ("exact source",))
        self.assertFalse(call.kwargs["memory"])
        self.assertEqual(call.kwargs["memory_path"], "custom.sqlite")
        self.assertIs(call.kwargs["model_provider"], provider)
        self.assertEqual(call.kwargs["profile"], "general")
        self.assertTrue(call.kwargs["accept_model_interpretation"])
        self.compiler.compile_source.assert_not_called()

    def test_direct_defaults_to_bytecode(self):
        with patch.dict(sys.modules, {"shipmbcompiler": self.compiler}):
            self.assertEqual(self.invoke("--pipeline", "direct", "--memory", "off", "Use ShipMB."), self.artifact)

    def test_quoted_paragraph_file_is_forwarded_verbatim(self):
        source = '\u201cStart with 12.\nAdd 15 and show the result.\u201d\n'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quoted paragraph.smb"
            path.write_bytes(source.encode("utf-8"))
            with patch.dict(sys.modules, {"shipmbcompiler": self.compiler}):
                self.invoke("--pipeline", "direct", "--profile", "general", "--file", str(path))
        self.assertEqual(self.compiler.compile_direct_program.call_args.args, (source,))

    def test_multiple_paragraphs_preserve_crlf_and_unicode(self):
        source = '“Show "😀".”\r\n\r\n“Show missing.”\r\n'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "multiple paragraphs.smb"
            path.write_bytes(source.encode("utf-8"))
            with patch.dict(sys.modules, {"shipmbcompiler": self.compiler}):
                self.invoke("--pipeline", "direct", "--profile", "general", "--file", str(path))
        self.assertEqual(self.compiler.compile_direct_program.call_args.args, (source,))

    def test_general_profile_is_forwarded_without_artifact_rewriting(self):
        self.artifact.update(version="0.3", profile="general")
        with patch.dict(sys.modules, {"shipmbcompiler": self.compiler}):
            result = self.invoke("--pipeline", "direct", "--profile", "general", "Show 27.")
        self.assertEqual(result, self.artifact)
        self.assertEqual(self.compiler.compile_direct_program.call_args.kwargs["profile"], "general")
        self.compiler.compile_source.assert_not_called()

    def test_general_run_uses_validated_compiler_runtime(self):
        self.artifact.update(version="0.3", profile="general")
        runtime = types.ModuleType("shipmbcompiler.runtime")
        runtime.run_artifact = Mock(return_value=({"output": ["27"]}, []))
        with patch.dict(sys.modules, {"shipmbcompiler": self.compiler, "shipmbcompiler.runtime": runtime}):
            result = self.invoke("--pipeline", "direct", "--profile", "general", "Show 27.", run=True)
        self.assertEqual(result["runtime"]["output"], ["27"])
        runtime.run_artifact.assert_called_once_with(self.artifact)
        self.assertEqual(self.compiler.compile_direct_program.call_args.kwargs["profile"], "general")

    def test_compile_only_general_never_loads_runtime(self):
        with patch.dict(sys.modules, {"shipmbcompiler": self.compiler, "shipmbcompiler.runtime": None}):
            self.assertEqual(self.invoke("--pipeline", "direct", "--profile", "general", "Show 27."), self.artifact)

    def test_clarification_prevents_host_creation_and_execution(self):
        self.compiler.compile_direct_program.return_value = {**self.result, "status": "needs_clarification", "target_code": None}
        with patch.dict(sys.modules, {"shipmbcompiler": self.compiler, "shipmbcompiler.runtime": None}):
            with self.assertRaises(SystemExit) as failure:
                self.invoke("--pipeline", "direct", "--profile", "general", "Show 27.", run=True)
        self.assertEqual(failure.exception.code, 1)

    def test_run_api_forwards_only_supplied_host(self):
        runtime = types.ModuleType("shipmbcompiler.runtime")
        runtime.run_artifact = Mock(return_value=({"output": []}, []))
        host = object()
        with patch.dict(sys.modules, {"shipmbcompiler": self.compiler, "shipmbcompiler.runtime": runtime}):
            pipelines.run_direct_program("Show 27.", profile="general", memory=False, host=host)
            runtime.run_artifact.assert_called_with(self.artifact, host=host)
            pipelines.run_direct_program("Show 27.", profile="general", memory=False)
            runtime.run_artifact.assert_called_with(self.artifact)

    def test_profile_requires_direct_pipeline_before_loading_any_compiler(self):
        for args in (("--pipeline", "legacy", "--profile", "roku"), ("--pipeline", "ir", "--profile", "general")):
            with self.subTest(args=args), patch.object(pipelines, "_compiler") as compiler, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as failure:
                    self.invoke(*args, "Use ShipMB.")
                self.assertEqual(failure.exception.code, 2)
                compiler.assert_not_called()

    def test_api_rejects_unknown_profile(self):
        with patch.object(pipelines, "_compiler") as compiler:
            with self.assertRaisesRegex(ValueError, "profile"):
                pipelines.compile_direct_program("Show 27.", profile="unknown")
        compiler.assert_not_called()

    def test_older_compiler_keeps_roku_default_and_rejects_general_clearly(self):
        def old_compile(source, *, memory, memory_path, project, bindings, clarification_answers, model_provider):
            return self.result
        self.compiler.compile_direct_program = old_compile
        with patch.dict(sys.modules, {"shipmbcompiler": self.compiler}):
            self.assertIs(pipelines.compile_direct_program("Use ShipMB.", profile="roku", model_provider=None), self.result)
            with self.assertRaisesRegex(pipelines.CompilerUnavailableError, "profile-capable"):
                pipelines.compile_direct_program("Show 27.", profile="general")

    def test_cli_forwards_explicit_interpretation_with_original_source(self):
        with patch.dict(sys.modules, {"shipmbcompiler": self.compiler}):
            self.invoke("--pipeline", "direct", "--interpretation", "Use ShipMB.", "Use it.")
        call = self.compiler.compile_direct_program.call_args
        self.assertEqual(call.args, ("Use it.",))
        self.assertEqual(call.kwargs["clarification_answers"], {"interpretation": "Use ShipMB."})
        self.compiler.compile_source.assert_not_called()

    def test_ir_rejects_interpretation(self):
        with patch.object(pipelines, "_compiler") as compiler, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.invoke("--pipeline", "ir", "--interpretation", "Use ShipMB.", "Use it.")
        compiler.assert_not_called()

    def test_explicit_database_overrides_env_but_not_memory_false(self):
        with patch.dict(sys.modules, {"shipmbcompiler": self.compiler}):
            pipelines.compile_direct_program("Use ShipMB.", memory_path="explicit.sqlite")
            self.assertTrue(self.compiler.compile_direct_program.call_args.kwargs["memory"])
            pipelines.compile_direct_program("Use ShipMB.", memory=False, memory_path="explicit.sqlite")
            self.assertFalse(self.compiler.compile_direct_program.call_args.kwargs["memory"])
            self.invoke("--pipeline", "direct", "--memory-db", "explicit.sqlite", "Use ShipMB.")
            self.assertTrue(self.compiler.compile_direct_program.call_args.kwargs["memory"])
            self.invoke("--pipeline", "direct", "--memory", "off", "--memory-db", "explicit.sqlite", "Use ShipMB.")
            self.assertFalse(self.compiler.compile_direct_program.call_args.kwargs["memory"])

    def test_legacy_explicit_database_precedence(self):
        from shipmblang import compile_natural_program
        memory = types.ModuleType("shipmbcompiler.memory")
        memory.MemoryStore = Mock()
        with patch.dict(sys.modules, {"shipmbcompiler.memory": memory}):
            compile_natural_program("Use ShipMB.", memory_path="explicit.sqlite")
            memory.MemoryStore.assert_called_once_with("explicit.sqlite")
            memory.MemoryStore.reset_mock()
            compile_natural_program("Use ShipMB.", memory=False, memory_path="explicit.sqlite")
            memory.MemoryStore.assert_not_called()

    def test_ir_is_explicit(self):
        with patch.dict(sys.modules, {"shipmbcompiler": self.compiler}):
            self.assertEqual(self.invoke("--pipeline", "ir", "--memory", "off", "Use ShipMB."), self.artifact)
        self.compiler.compile_source.assert_called_once()
        self.compiler.compile_direct_program.assert_not_called()

    def test_ir_run_stays_with_its_compiler(self):
        self.compiler.compile_source.return_value = {**self.result, "runtime": {"events": []}}
        with patch.dict(sys.modules, {"shipmbcompiler": self.compiler, "shipmbcompiler.runtime": None}):
            result = self.invoke("--pipeline", "ir", "--memory", "off", "Use ShipMB.", run=True)
        self.assertEqual(result["runtime"], {"events": []})
        self.assertTrue(self.compiler.compile_source.call_args.kwargs["run"])
        self.compiler.compile_direct_program.assert_not_called()

    def test_clarification_is_visible_and_never_falls_back(self):
        self.compiler.compile_direct_program.return_value = {
            **self.result, "status": "needs_clarification", "target_code": None,
            "clarifications": [{"question": "Which device?"}],
        }
        output = io.StringIO()
        with patch.dict(sys.modules, {"shipmbcompiler": self.compiler}), patch.object(sys, "argv", ["compile", "--pipeline", "direct", "Use it."]), contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as failure:
                pipelines.main()
        self.assertEqual(failure.exception.code, 1)
        self.assertEqual(json.loads(output.getvalue())["clarifications"][0]["question"], "Which device?")
        self.compiler.compile_source.assert_not_called()

    def test_missing_extra_has_actionable_error(self):
        with patch.dict(sys.modules, {"shipmbcompiler": None}):
            with self.assertRaisesRegex(pipelines.CompilerUnavailableError, r"shipmblang\[direct\]"):
                pipelines.compile_direct_program("Use ShipMB.")

    def test_python_310_explains_optional_requirement(self):
        with patch.object(sys, "version_info", (3, 10)):
            with self.assertRaisesRegex(pipelines.CompilerUnavailableError, "Python 3.11"):
                pipelines.compile_direct_program("Use ShipMB.")

    def test_bytecode_output_keeps_warnings_visible(self):
        self.result["diagnostics"] = [{"level": "warning", "code": "SMBM001", "message": "Memory unavailable"}]
        stderr = io.StringIO()
        with patch.dict(sys.modules, {"shipmbcompiler": self.compiler}), contextlib.redirect_stderr(stderr):
            self.assertEqual(self.invoke("--pipeline", "direct", "Use ShipMB."), self.artifact)
        self.assertIn("Memory unavailable", stderr.getvalue())

    def test_core_rejected_before_compiler_load(self):
        with patch.object(pipelines, "_compiler") as compiler, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.invoke("--pipeline", "direct", "--format", "core", "Use ShipMB.")
        compiler.assert_not_called()

    def test_run_uses_compiler_runtime_only(self):
        runtime = types.ModuleType("shipmbcompiler.runtime")
        runtime.run_artifact = Mock(return_value=({"events": []}, []))
        with patch.dict(sys.modules, {"shipmbcompiler": self.compiler, "shipmbcompiler.runtime": runtime}):
            result = self.invoke("--pipeline", "direct", "--memory", "off", "Use ShipMB.", run=True)
        runtime.run_artifact.assert_called_once_with(self.artifact)
        self.assertEqual(result["runtime"], {"events": []})

    def test_explicit_legacy_output_unchanged(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["compile", "--pipeline", "legacy", "Use ShipMB."]), contextlib.redirect_stdout(output):
            pipelines.main()
        self.assertEqual(output.getvalue().strip(), "use shipmb")

    def test_default_compiles_broader_english_with_general_profile(self):
        with patch.dict(sys.modules, {"shipmbcompiler": self.compiler}), patch.dict(os.environ, {"SHIPMB_MODEL_PROVIDER": "openai_compatible"}):
            self.assertEqual(self.invoke("Add up the odd scores."), self.artifact)
        options = self.compiler.compile_direct_program.call_args.kwargs
        self.assertEqual(options["profile"], "general")
        self.assertTrue(options["accept_model_interpretation"])
        self.assertTrue(callable(options["model_provider"]))

    def test_model_can_be_disabled_or_reviewed(self):
        with patch.dict(sys.modules, {"shipmbcompiler": self.compiler}):
            self.invoke("--no-english-model", "Show 7.")
            self.assertIsNone(self.compiler.compile_direct_program.call_args.kwargs["model_provider"])
            self.invoke("--review-model-interpretation", "Add up the odd scores.")
            self.assertFalse(self.compiler.compile_direct_program.call_args.kwargs["accept_model_interpretation"])

    def test_model_options_require_direct(self):
        for flag in ("--no-english-model", "--review-model-interpretation"):
            with patch.object(pipelines, "_compiler") as compiler, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as failure:
                    self.invoke("--pipeline", "legacy", flag, "Show 7.")
                self.assertEqual(failure.exception.code, 2)
                compiler.assert_not_called()

    def test_model_frontend_is_lazy_and_uses_existing_chat_provider(self):
        frontend_module = types.ModuleType("shipmbcompiler.english_model")
        frontend_module.EnglishModelFrontend = Mock(return_value=lambda source: {"paraphrase": "Show 9."})
        provider = object()
        with patch.dict(sys.modules, {"shipmbcompiler.english_model": frontend_module}), patch("shipmblang.providers.load_chat_provider", return_value=provider) as load:
            proposal = pipelines._english_model("general")
            load.assert_not_called()
            self.assertEqual(proposal("What is three squared?"), {"paraphrase": "Show 9."})
        frontend_module.EnglishModelFrontend.assert_called_once_with(provider, profile="general")

    def test_missing_model_returns_actionable_question(self):
        frontend_module = types.ModuleType("shipmbcompiler.english_model")
        frontend_module.EnglishModelFrontend = Mock()
        with patch.dict(sys.modules, {"shipmbcompiler.english_model": frontend_module}), patch("shipmblang.providers.load_chat_provider", return_value=None):
            proposal = pipelines._english_model("general")("Do something new.")
        self.assertIn("SHIPMB_MODEL_BASE_URL", proposal["question"])
        frontend_module.EnglishModelFrontend.assert_not_called()

    def test_bytecode_output_exposes_translation_on_stderr(self):
        self.result["interpretation_source"] = "Show 9."
        stderr = io.StringIO()
        with patch.dict(sys.modules, {"shipmbcompiler": self.compiler}), contextlib.redirect_stderr(stderr):
            self.assertEqual(self.invoke("What is three squared?"), self.artifact)
        self.assertIn("Show 9.", stderr.getvalue())

    def test_legacy_captures_original_text_and_result(self):
        from shipmblang import compile_natural_program
        memory = types.ModuleType("shipmbcompiler.memory")
        memory.MemoryStore = Mock()
        source = "  Use ShipMB.\n"
        with patch.dict(sys.modules, {"shipmbcompiler.memory": memory}), patch.dict(os.environ, {"SHIPMB_MEMORY": "on"}):
            result = compile_natural_program(source, root="project", memory_path="disposable.sqlite")
        memory.MemoryStore.assert_called_once_with("disposable.sqlite")
        memory.MemoryStore.return_value.record_submission.assert_called_once_with(source, "project", "legacy", result)

    def test_legacy_failed_compile_is_captured(self):
        from driplm import natural_syntax
        memory = types.ModuleType("shipmbcompiler.memory")
        memory.MemoryStore = Mock()
        with patch.dict(sys.modules, {"shipmbcompiler.memory": memory}), patch.dict(os.environ, {"SHIPMB_MEMORY": "on"}), patch.object(natural_syntax, "_compile_natural_program", side_effect=ValueError("bad source")):
            with self.assertRaisesRegex(ValueError, "bad source"):
                natural_syntax.compile_natural_program("bad", memory_path="disposable.sqlite")
        call = memory.MemoryStore.return_value.record_submission.call_args.args
        self.assertEqual(call[0], "bad")
        self.assertEqual(call[3]["status"], "failed")

    def test_memory_failure_does_not_discard_compile(self):
        from shipmblang import compile_natural_program
        with patch.dict(sys.modules, {"shipmbcompiler.memory": None}), patch.dict(os.environ, {"SHIPMB_MEMORY": "on"}), warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = compile_natural_program("Use ShipMB.")
        self.assertEqual(result["core"], "use shipmb")
        self.assertIn("memory capture failed", str(caught[0].message))

    def test_direct_dispatch_does_not_import_legacy_or_runtime(self):
        script = """
import importlib.abc, sys, types, runpy
sys.path.insert(0, sys.argv[1])
class BlockLegacy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'driplm' or fullname.startswith('driplm.') or fullname in {
            'shipmblang.providers', 'shipmblang.runtime_context', 'shipmbcompiler.runtime',
            'shipmbcompiler.ir', 'shipmbcompiler.optimizer', 'shipmbcompiler.core'
        }:
            raise AssertionError(fullname)
sys.meta_path.insert(0, BlockLegacy())
compiler = types.ModuleType('shipmbcompiler')
compiler.compile_direct_program = lambda source, **kwargs: {
    'status': 'compiled', 'diagnostics': [],
    'target_code': {'producer': 'shipmbcompiler', 'bytecode': []}
}
sys.modules['shipmbcompiler'] = compiler
from shipmblang import compile_direct_program
assert compile_direct_program('Use ShipMB.', memory=False)['status'] == 'compiled'
sys.argv = ['shipmblang', 'compile', 'Use ShipMB.', '--pipeline', 'direct', '--memory', 'off']
runpy.run_module('shipmblang', run_name='__main__')
"""
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, "-I", "-S", "-c", script, str(Path(__file__).resolve().parents[1])], cwd=directory, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)["producer"], "shipmbcompiler")


if __name__ == "__main__":
    unittest.main()
