"""Real installed-binary checks; set SHIPMB_FFMPEG_PATH/SHIPMB_FFPROBE_PATH."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


FFMPEG = os.environ.get("SHIPMB_FFMPEG_PATH") or shutil.which("ffmpeg")
FFPROBE = os.environ.get("SHIPMB_FFPROBE_PATH") or shutil.which("ffprobe")
ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(FFMPEG and FFPROBE, "Install FFmpeg/ffprobe or configure their executable paths")
class FFmpegEndToEndTests(unittest.TestCase):
    def invoke(self, *args, expected=0):
        process = subprocess.run(
            [sys.executable, "-m", "shipmblang", *args, "--memory", "off", "--no-english-model"],
            cwd=ROOT, capture_output=True, text=True, timeout=45,
        )
        self.assertEqual(process.returncode, expected, process.stdout + process.stderr)
        return json.loads(process.stdout)

    def test_compile_then_run_function_and_loop_with_source_relative_paths(self):
        with tempfile.TemporaryDirectory(prefix="shipmb media ") as folder:
            directory = Path(folder)
            fixture = subprocess.run(
                [FFMPEG, "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                 "color=c=blue:s=32x24:r=2", "-t", "1", "-c:v", "mpeg4", str(directory / "input.mp4")],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(fixture.returncode, 0, fixture.stderr)
            source = directory / "program.shipmb"
            source.write_text('''Define a function transcode with text parameter destination returning integer:
Run FFmpeg:
Input clip from "input.mp4".
Output result to destination.
Output option "-c:v" for result with "mpeg4".
End FFmpeg.
Return 1.
End the function.
Let destinations be the list of texts "first.mp4", "second.mp4".
For each destination in destinations:
Show the result of transcode with destination.
End the loop.
''', encoding="utf-8")
            result = self.invoke("compile", "--file", str(source), "--format", "json",
                                 "--ffmpeg-path", "nonexistent-compile-only.exe")
            self.assertEqual(result["status"], "compiled")
            self.assertEqual(result["target_code"]["version"], "0.4")
            self.assertFalse((directory / "first.mp4").exists())
            self.assertFalse((directory / "second.mp4").exists())
            result = self.invoke("compile", "--file", str(source), "--run", "--ffmpeg-path", FFMPEG,
                                 "--ffprobe-path", FFPROBE, "--ffmpeg-timeout", "30")
            self.assertEqual(result["runtime"]["stdout"], "1\n1\n")
            for name in ("first.mp4", "second.mp4"):
                probe = subprocess.run(
                    [FFPROBE, "-v", "error", "-show_streams", "-of", "json", str(directory / name)],
                    capture_output=True, text=True, timeout=15,
                )
                self.assertEqual(probe.returncode, 0, probe.stderr)
                stream = json.loads(probe.stdout)["streams"][0]
                self.assertEqual((stream["width"], stream["height"]), (32, 24))
            before = (directory / "first.mp4").read_bytes()
            failed = self.invoke("run", "--file", str(source), "--ffmpeg-path", FFMPEG,
                                 "--ffprobe-path", FFPROBE, "--ffmpeg-timeout", "30", expected=1)
            self.assertTrue(any(d["level"] == "error" for d in failed["diagnostics"]))
            self.assertEqual((directory / "first.mp4").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
