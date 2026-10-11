"""Preflight or fine-tune MiniCPM-V 4.6 with ms-swift QLoRA."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


MODEL = "OpenBMB/MiniCPM-V-4.6"


def read_dataset(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    count = 0
    with path.open("rb") as stream:
        for line_number, raw in enumerate(stream, 1):
            digest.update(raw)
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid JSONL at line {line_number}: {error}") from error
            if row.get("split", "train") != "train":
                raise ValueError(f"Training data contains non-train split at line {line_number}.")
            if not isinstance(row.get("query"), str) or not row["query"].strip():
                raise ValueError(f"Missing query at line {line_number}.")
            if not isinstance(row.get("response"), str) or not row["response"].strip():
                raise ValueError(f"Missing response at line {line_number}.")
            images = row.get("images", [])
            if not isinstance(images, list):
                raise ValueError(f"images must be a list at line {line_number}.")
            for image in images:
                image_path = Path(image)
                if not image_path.is_file():
                    raise ValueError(f"Image does not exist at line {line_number}: {image}")
            count += 1
    if not count:
        raise ValueError("Training data has no examples.")
    return count, digest.hexdigest()


def gpu_summary() -> dict[str, object]:
    try:
        import torch
    except ImportError as error:
        raise RuntimeError("PyTorch with CUDA is required for the local training preflight.") from error
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable; local MiniCPM-V QLoRA needs a CUDA GPU.")
    device = torch.cuda.get_device_properties(0)
    return {
        "name": device.name,
        "vram_gib": round(device.total_memory / (1024 ** 3), 2),
        "capability": list(torch.cuda.get_device_capability(0)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path, help="Train-only ms-swift JSONL dataset.")
    parser.add_argument("--output-dir", type=Path, default=Path("output/minicpmv46"))
    parser.add_argument("--max-steps", type=int, default=-1, help="Use -1 for one epoch.")
    parser.add_argument("--preflight", action="store_true", help="Check data, CUDA, and SWIFT installation without starting training.")
    parser.add_argument("--pilot", action="store_true", help="Run a one-step QLoRA pilot to measure actual memory fit.")
    args = parser.parse_args()

    if not (3, 10) <= sys.version_info[:2] < (3, 14):
        raise SystemExit("Use Python 3.10–3.13 for the SWIFT training environment.")
    dataset = args.dataset.resolve(strict=True)
    if not dataset.is_file():
        raise SystemExit(f"Training dataset is not a file: {dataset}")
    count, digest = read_dataset(dataset)
    gpu = gpu_summary()
    swift = shutil.which("swift")
    if not swift:
        raise SystemExit("ms-swift is not installed in this environment; install it in the model-training environment first.")

    manifest = {
        "base_model": MODEL,
        "method": "QLoRA (bitsandbytes NF4), DeepSpeed ZeRO-3 CPU offload",
        "dataset": str(dataset),
        "dataset_sha256": digest,
        "train_examples": count,
        "gpu": gpu,
    }
    if args.preflight and not args.pilot:
        print(json.dumps(manifest, indent=2))
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=True)
    deepspeed = args.output_dir / "zero3-cpu-offload.json"
    deepspeed.write_text(json.dumps({
        "bf16": {"enabled": "auto"},
        "fp16": {"enabled": "auto"},
        "zero_optimization": {
            "stage": 3,
            "offload_optimizer": {"device": "cpu", "pin_memory": True},
            "offload_param": {"device": "cpu", "pin_memory": True},
            "overlap_comm": False,
            "contiguous_gradients": True,
        },
        "gradient_accumulation_steps": "auto",
        "train_batch_size": "auto",
        "train_micro_batch_size_per_gpu": "auto",
    }, indent=2) + "\n", encoding="utf-8")
    manifest_path = args.output_dir / "run-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    command = [swift, "sft", "--model", MODEL, "--model_type", "minicpmv4_6",
               "--dataset", str(dataset), "--tuner_type", "lora", "--quant_method", "bnb",
               "--quant_bits", "4", "--bnb_4bit_quant_type", "nf4",
               "--bnb_4bit_use_double_quant", "true", "--torch_dtype", "bfloat16",
               "--bnb_4bit_compute_dtype", "bfloat16", "--per_device_train_batch_size", "1",
               "--gradient_checkpointing", "true", "--deepspeed", str(deepspeed),
               "--output_dir", str(args.output_dir), "--dataset_num_proc", "1"]
    command.extend(["--max_steps", "1"] if args.pilot else ["--max_steps", str(args.max_steps)])
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as error:
        print("MiniCPM-V training stopped. Review the SWIFT output and GPU/host memory before retrying.", file=sys.stderr)
        return error.returncode or 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
