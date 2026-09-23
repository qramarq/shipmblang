"""Language-side execution opt-in and compiler configuration forwarding."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from shipmblang import pipelines


class FFmpegAdapterTests(unittest.TestCase):
    def setUp(self):
        self.result = {"status": "compiled", "diagnostics": [],
                       "target_code": {"version": "0.4", "bytecode": [],
                                       "runtime_contract": {"required_capabilities": ["ffmpeg"]}}}
        self.runtime = types.ModuleType("shipmblang._compiler.runtime")
        self.runtime.run_artifact = Mock(return_value=({"stdout": ""}, []))
        self.media = types.ModuleType("shipmblang._compiler.ffmpeg")
        self.media.FFmpegExecutor = Mock()

    def invoke(self, *args):
        output = io.StringIO()
        with patch.object(sys, "argv", ["compile", *args]), contextlib.redirect_stdout(output):
            pipelines.main()
        return json.loads(output.getvalue())

    def test_compile_does_not_import_executor_even_with_paths(self):
        with patch.object(pipelines, "compile_direct_program", return_value=self.result), patch.dict(
            sys.modules, {"shipmblang._compiler.ffmpeg": None, "shipmblang._compiler.runtime": None}
        ):
            result = self.invoke("media source", "--ffmpeg-path", "missing.exe")
        self.assertEqual(result, self.result["target_code"])

    def test_cli_run_resolves_source_parent_and_forwards_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "media.shipmb"
            source.write_text("media source", encoding="utf-8")
            with patch.object(pipelines, "compile_direct_program", return_value=self.result), patch.dict(
                sys.modules, {"shipmblang._compiler.ffmpeg": self.media,
                              "shipmblang._compiler.runtime": self.runtime}
            ):
                self.invoke("--file", str(source), "--run", "--ffmpeg-path", "tools/ffmpeg",
                            "--ffprobe-path", "tools/ffprobe", "--ffmpeg-timeout", "12.5")
            self.media.FFmpegExecutor.assert_called_once_with(
                ffmpeg_path="tools/ffmpeg", ffprobe_path="tools/ffprobe", timeout=12.5,
                base_dir=source.resolve().parent)
        self.runtime.run_artifact.assert_called_once_with(
            self.result["target_code"], ffmpeg_executor=self.media.FFmpegExecutor.return_value)

    def test_unresolved_source_never_creates_executor(self):
        with patch.object(pipelines, "compile_direct_program", return_value={
            "status": "needs_clarification", "target_code": None, "diagnostics": []
        }), patch.dict(sys.modules, {"shipmblang._compiler.ffmpeg": None}):
            with self.assertRaises(SystemExit) as failure:
                self.invoke("unclear", "--run")
        self.assertEqual(failure.exception.code, 1)

    def test_api_executor_is_not_sent_to_compiler(self):
        executor = object()
        with patch.object(pipelines, "compile_direct_program", return_value=self.result) as compile_program, patch.dict(
            sys.modules, {"shipmblang._compiler.runtime": self.runtime}
        ):
            pipelines.run_direct_program("media source", memory=False, ffmpeg_executor=executor)
        compile_program.assert_called_once_with("media source", memory=False)
        self.runtime.run_artifact.assert_called_once_with(self.result["target_code"], ffmpeg_executor=executor)

    def test_catalog_is_forwarded_unchanged(self):
        compiler = types.SimpleNamespace(compile_direct_program=Mock(return_value=self.result))
        catalog = {"version": "fixture"}
        with patch.object(pipelines, "_compiler", return_value=compiler):
            result = pipelines.compile_direct_program(
                "media source", memory=False, model_provider=None, ffmpeg_catalog=catalog)
        self.assertIs(result, self.result)
        self.assertIs(compiler.compile_direct_program.call_args.kwargs["ffmpeg_catalog"], catalog)

    def test_configured_frontend_receives_catalog(self):
        frontend = types.ModuleType("shipmblang._compiler.english_model")
        frontend.EnglishModelFrontend = Mock(return_value=lambda source: {"paraphrase": source})
        catalog = {"version": "fixture"}
        provider = object()
        with patch.dict(sys.modules, {"shipmblang._compiler.english_model": frontend}), patch(
            "shipmblang.providers.load_chat_provider", return_value=provider
        ):
            pipelines._english_model("general", catalog)("media source")
        frontend.EnglishModelFrontend.assert_called_once_with(provider, profile="general", ffmpeg_catalog=catalog)

    def test_explicit_executable_catalog_lookup_is_lazy_and_injection_wins(self):
        frontend = types.ModuleType("shipmblang._compiler.english_model")
        frontend.EnglishModelFrontend = Mock(return_value=lambda source: {"paraphrase": source})
        catalog_module = types.ModuleType("shipmblang._compiler.ffmpeg_catalog")
        catalog_module.available_catalog = Mock(return_value={"version": "installed"})
        with patch.dict(sys.modules, {"shipmblang._compiler.english_model": frontend,
                                      "shipmblang._compiler.ffmpeg_catalog": catalog_module}), patch(
            "shipmblang.providers.load_chat_provider", return_value=object()
        ):
            propose = pipelines._english_model("general", ffmpeg_path="custom/ffmpeg")
            catalog_module.available_catalog.assert_not_called()
            propose("media source")
            catalog_module.available_catalog.assert_called_once_with("media source", "custom/ffmpeg")
            catalog_module.available_catalog.reset_mock()
            pipelines._english_model("general", {"version": "injected"}, "custom/ffmpeg")("media source")
            catalog_module.available_catalog.assert_not_called()

    def test_invalid_configuration_fails_before_compilation(self):
        cases = [("--ffmpeg-timeout", value) for value in ("0", "-1", "nan", "inf", "bad")]
        cases += [("--pipeline", "legacy", "--ffmpeg-path", "ffmpeg"),
                  ("--profile", "roku", "--ffprobe-path", "ffprobe")]
        for args in cases:
            with self.subTest(args=args), patch.object(pipelines, "compile_direct_program") as compile_program:
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as failure:
                    self.invoke("source", *args)
                self.assertEqual(failure.exception.code, 2)
                compile_program.assert_not_called()


if __name__ == "__main__":
    unittest.main()
