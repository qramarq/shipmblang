"""Probe-and-show compilation and the natural VLC duration phrase."""
import subprocess
import unittest
from unittest.mock import patch

from shipmblang import compile_direct_program, run_direct_program


class MediaProbeTests(unittest.TestCase):
    def test_probe_compiles_without_ffprobe(self):
        with patch.object(subprocess, "run", side_effect=AssertionError("ffprobe")), patch.object(
            subprocess, "Popen", side_effect=AssertionError("ffprobe")
        ):
            result = compile_direct_program(
                'Probe "clip.mp4" and show the duration.', memory=False, model_provider=None
            )
        self.assertEqual(result["status"], "compiled", result)
        artifact = result["target_code"]
        self.assertEqual(artifact["version"], "0.4")
        self.assertIn("ffmpeg", artifact["runtime_contract"]["required_capabilities"])
        self.assertNotIn("vlc", artifact["runtime_contract"]["required_capabilities"])
        opcodes = [item["opcode"] for item in artifact["bytecode"]]
        self.assertIn("ffmpeg_probe", opcodes)
        self.assertIn("show", opcodes)

    def test_probe_runs_with_fake_executor(self):
        class FakeExecutor:
            def execute(self, job):
                raise AssertionError("execute is not used for probe")

            def probe(self, source):
                self.source = source
                return {"format": {"duration": "1.000000"}}

        executor = FakeExecutor()
        with patch.object(subprocess, "run", side_effect=AssertionError("ffprobe")), patch.object(
            subprocess, "Popen", side_effect=AssertionError("ffprobe")
        ):
            result = run_direct_program(
                'Probe "clip.mp4" and show the duration.',
                memory=False, model_provider=None, ffmpeg_executor=executor,
            )
        self.assertEqual(result["status"], "compiled", result)
        self.assertEqual(result["runtime"]["stdout"], "1.000000\n", result)
        self.assertEqual(executor.source, "clip.mp4")
        self.assertFalse(any(item.get("level") == "error" for item in result["diagnostics"]))

    def test_probe_without_executor_fails_before_media(self):
        result = run_direct_program(
            'Probe "clip.mp4" and show the duration.', memory=False, model_provider=None
        )
        self.assertTrue(any(
            item.get("level") == "error" and "FFmpeg executor" in item.get("message", "")
            for item in result["diagnostics"]
        ), result)
        self.assertEqual(result["runtime"]["stdout"], "")

    def test_natural_vlc_duration_phrase_compiles(self):
        with patch("ctypes.CDLL", side_effect=AssertionError("LibVLC")):
            natural = compile_direct_program(
                'Show the duration of vlc player "preview".', memory=False, model_provider=None
            )
            original = compile_direct_program(
                'Show the vlc duration of "preview".', memory=False, model_provider=None
            )
        for result in (natural, original):
            self.assertEqual(result["status"], "compiled", result)
            artifact = result["target_code"]
            self.assertIn("vlc", artifact["runtime_contract"]["required_capabilities"])
            self.assertEqual(artifact["version"], "0.5")
            query = next(item for item in artifact["bytecode"] if item["opcode"] == "vlc_query")
            self.assertEqual(query["operands"]["operation"], "duration")
            self.assertEqual(query["operands"]["return_type"], "integer")
            self.assertEqual(query["operands"]["argument_types"], ["text"])

    def test_and_show_still_splits_ordinary_addition(self):
        result = run_direct_program(
            "Let total be a mutable integer with value 1. Add 3 and show it.",
            memory=False, model_provider=None,
        )
        self.assertEqual(result["status"], "compiled", result)
        self.assertEqual(result["runtime"]["stdout"], "4\n", result)


if __name__ == "__main__":
    unittest.main()
