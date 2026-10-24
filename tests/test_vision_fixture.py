"""Tiny-fixture vision checks. Real MiniCPM-V weights stay behind SHIPMB_VISION_WEIGHTS=1."""

import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import time
import unittest
import zlib

from shipmblang._compiler.vision import LLM_FILENAME, MMPROJ_FILENAME, MODEL_SHA256
from shipmblang.vision_build import existing_library, library_filename, package_library_path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "native" / "shipmb_vision" / "fixtures" / "minicpmv46-tiny"


def _png(path: Path, width: int, height: int) -> None:
    rows = []
    for y in range(height):
        pixel = bytes((y % 256, 48, 96))
        rows.append(b"\x00" + pixel * width)
    raw = b"".join(rows)

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _nearest_rank_p95(samples):
    ordered = sorted(samples)
    index = max(0, round(0.95 * len(ordered) + 0.5) - 1)
    return ordered[index], index


class TinyFixtureTests(unittest.TestCase):
    def test_fixture_files_match_the_parity_contract(self):
        golden = json.loads((FIXTURE / "golden.json").read_text(encoding="utf-8"))
        self.assertEqual(golden["text"], "yes")
        self.assertEqual(golden["question"], "cat")
        self.assertEqual(golden["image_tokens"], 1)
        self.assertEqual(golden["max_tokens"], 1)
        self.assertTrue((FIXTURE / "sample.png").read_bytes().startswith(b"\x89PNG"))
        for name in ("model.gguf", "mmproj.gguf", "weights.npz"):
            self.assertGreater((FIXTURE / name).stat().st_size, 0, name)
        self.assertEqual(MODEL_SHA256, "6b0c74962c44bc6bf4b655b9b02c13eda9d5a0491543ae976d1ac18e4b7892e2")
        self.assertEqual(LLM_FILENAME, "MiniCPM-V-4_6-Q4_K_M.gguf")
        self.assertEqual(MMPROJ_FILENAME, "mmproj-model-q8_0.gguf")

    def test_library_answers_the_tiny_fixture(self):
        library = existing_library() or (package_library_path() if package_library_path().is_file() else None)
        if library is None:
            build = ROOT / "native" / "shipmb_vision" / "build" / library_filename()
            library = build if build.is_file() else None
        if library is None:
            self.skipTest("libshipmb_vision is not built. Run python tools/build_vision.py.")
        from shipmblang._compiler.vision import VisionEngine

        golden = json.loads((FIXTURE / "golden.json").read_text(encoding="utf-8"))
        engine = VisionEngine(
            model_path=FIXTURE / "model.gguf",
            mmproj_path=FIXTURE / "mmproj.gguf",
            bridge_path=library,
            n_threads=1,
            n_ctx=2048,
            max_tokens=golden["max_tokens"],
            flash_attn=False,
            detailed=True,
            use_gpu=False,
            warmup=True,
        )
        self.addCleanup(engine.close)
        payload = engine.query(
            FIXTURE / "sample.png",
            golden["question"],
            detailed=True,
            max_tokens=golden["max_tokens"],
        )
        self.assertTrue(payload.get("ok"), payload)
        self.assertEqual(payload.get("text"), golden["text"])
        self.assertEqual(payload.get("image_tokens"), golden["image_tokens"])


@unittest.skipUnless(os.environ.get("SHIPMB_VISION_WEIGHTS") == "1", "set SHIPMB_VISION_WEIGHTS=1 to use the real MiniCPM-V weights")
class RealWeightTests(unittest.TestCase):
    def test_end_to_end_program_and_warm_latency(self):
        from shipmblang import run_direct_program
        from shipmblang._compiler.vision import VisionEngine

        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "sample.png"
            _png(image, 448, 448)
            source = f'Look at "{image}" and tell me what is in it.'
            result = run_direct_program(source, memory=False, model_provider=None)
            self.assertEqual(result.get("status"), "compiled", result.get("diagnostics"))
            stdout = result.get("runtime", {}).get("stdout", "")
            self.assertTrue(stdout.strip(), result)
            engine = VisionEngine(n_threads=0, max_tokens=16, flash_attn=True, warmup=True, use_gpu=False)
            self.addCleanup(engine.close)
            question = "What is the main object in this image? Answer in one or two words."
            rows = []
            for _ in range(11):
                started = time.perf_counter()
                payload = engine.query(image, question, max_tokens=16)
                wall_ms = (time.perf_counter() - started) * 1000
                self.assertTrue(payload.get("ok"), payload)
                rows.append((payload.get("elapsed_ms"), wall_ms, payload.get("text")))
            warm = [row[0] for row in rows[1:]]
            ordered = sorted(warm)
            if len(ordered) % 2:
                median = ordered[len(ordered) // 2]
            else:
                median = (ordered[len(ordered) // 2 - 1] + ordered[len(ordered) // 2]) / 2
            p95, index = _nearest_rank_p95(warm)
            print(
                f"warm elapsed_ms median={median} p95={p95} index={index} n={len(warm)} "
                f"cold={rows[0][0]} cpu_count={os.cpu_count()} text={rows[-1][2]!r}",
                file=sys.stderr,
            )
            self.assertLess(p95, 2000, rows)


if __name__ == "__main__":
    unittest.main()
