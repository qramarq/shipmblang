"""Language execution routing for VLC and mixed media artifacts."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, Mock, patch

from shipmblang import pipelines


class VLCAdapterTests(unittest.TestCase):
    def setUp(self):
        self.result = {"status": "compiled", "diagnostics": [], "target_code": {
            "version": "0.5", "bytecode": [],
            "runtime_contract": {"required_capabilities": ["vlc", "ffmpeg"]}}}
        self.runtime = types.ModuleType("shipmblang._compiler.runtime")
        self.runtime.run_artifact = Mock(return_value=({"stdout": ""}, []))
        self.vlc = types.ModuleType("shipmblang._compiler.vlc")
        self.vlc.VLCExecutor = MagicMock()
        self.ffmpeg = types.ModuleType("shipmblang._compiler.ffmpeg")
        self.ffmpeg.FFmpegExecutor = Mock()

    def invoke(self, *args):
        with patch.object(sys, "argv", ["compile", *args]), contextlib.redirect_stdout(io.StringIO()) as output:
            pipelines.main()
        return json.loads(output.getvalue())

    def test_compile_does_not_import_runtime_adapters(self):
        with patch.object(pipelines, "compile_direct_program", return_value=self.result), patch.dict(sys.modules, {
            "shipmblang._compiler.vlc": None, "shipmblang._compiler.ffmpeg": None,
            "shipmblang._compiler.runtime": None,
        }):
            self.assertEqual(self.invoke("source", "--vlc-bridge", "not-installed.dll"), self.result["target_code"])

    def test_mixed_artifact_uses_both_adapters_and_closes_vlc(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "media program.shipmb"
            source.write_text("source", encoding="utf-8")
            with patch.object(pipelines, "compile_direct_program", return_value=self.result), patch.dict(sys.modules, {
                "shipmblang._compiler.vlc": self.vlc, "shipmblang._compiler.ffmpeg": self.ffmpeg,
                "shipmblang._compiler.runtime": self.runtime,
            }):
                self.invoke("--file", str(source), "--run", "--vlc-dir", "vlc", "--vlc-bridge", "bridge.dll",
                            "--vlc-startup-timeout", "2.5", "--headless", "--ffmpeg-path", "ffmpeg")
            self.vlc.VLCExecutor.assert_called_once_with(vlc_dir="vlc", bridge_path="bridge.dll",
                base_dir=source.resolve().parent, startup_timeout_ms=2500, headless=True)
            self.vlc.VLCExecutor.return_value.__exit__.assert_called_once()
            self.runtime.run_artifact.assert_called_once_with(self.result["target_code"],
                ffmpeg_executor=self.ffmpeg.FFmpegExecutor.return_value,
                vlc_executor=self.vlc.VLCExecutor.return_value.__enter__.return_value)

    def test_rejected_program_never_loads_adapter(self):
        with patch.object(pipelines, "compile_direct_program", return_value={
            "status": "needs_clarification", "target_code": None, "diagnostics": []
        }), patch.dict(sys.modules, {"shipmblang._compiler.vlc": None}):
            with self.assertRaises(SystemExit) as failure:
                self.invoke("ambiguous", "--run", "--headless")
            self.assertEqual(failure.exception.code, 1)

    def test_explicit_public_api_adapter_is_forwarded(self):
        executor = object()
        with patch.object(pipelines, "compile_direct_program", return_value=self.result), patch.dict(sys.modules, {
            "shipmblang._compiler.runtime": self.runtime,
        }):
            pipelines.run_direct_program("source", vlc_executor=executor)
        self.runtime.run_artifact.assert_called_once_with(self.result["target_code"], vlc_executor=executor)

    def test_invalid_configuration_rejected_before_compilation(self):
        for args in [("--vlc-startup-timeout", value) for value in ("nan", "inf", "0", "0.0001", "2147484")]+[
            ("--pipeline", "legacy", "--headless"), ("--profile", "roku", "--vlc-dir", "vlc")]:
            with self.subTest(args=args), patch.object(pipelines, "compile_direct_program") as compile_program:
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as failure:
                    self.invoke("source", *args)
                self.assertEqual(failure.exception.code, 2)
                compile_program.assert_not_called()


if __name__ == "__main__":
    unittest.main()
