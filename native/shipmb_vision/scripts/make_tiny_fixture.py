#!/usr/bin/env python3
"""Build the committed MiniCPM-V 4.6 parity fixture.

The checkpoint is a fixed-seed random vision tower plus a language head biased
so greedy decoding of the question "cat" emits one token. Conversion uses the
pinned llama.cpp convert_hf_to_gguf.py (plain F32 and --mmproj). The output is
a few megabytes and is what CI runs; this script is the reproducer.
"""
from __future__ import annotations

import argparse
import json
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

import numpy as np

SEED = 46
HIDDEN = 32
HEADS = 4
HEAD_DIM = 8
FFN = 64
LAYERS = 2
INSERT_LAYER = 0
PATCH = 14
SCALE = 56
POS_SIDE = 70
MERGER_FFN = 64
TEXT_HEADS = 4
TEXT_KV = 2
YES_ID = 7

# mtmd looks these up by piece for MiniCPM-V 4.6 and inserts the ids into
# the text batch. A missing piece becomes LLAMA_TOKEN_NULL and aborts prefill.
IMAGE_MARKERS = [
    "<image>",
    "</image>",
    "<slice>",
    "</slice>",
    "<image_id>",
    "</image_id>",
]
TOKENS = [
    "<unk>",
    "<|end|>",
    "<|im_start|>",
    "<|im_end|>",
    "<think>",
    "</think>",
    "\n",
    "yes",
    "a", "c", "e", "i", "n", "r", "s", "t", "u", "z",
    *IMAGE_MARKERS,
    "0",
]
# gguf TokenType: UNKNOWN=2, CONTROL=3, NORMAL=1
TOKEN_TYPES = (
    [2]
    + [3] * 5
    + [1, 1]
    + [1] * 10
    + [3] * len(IMAGE_MARKERS)
    + [1]
)


def write_png(path, rgb):
    height, width, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[y].tobytes() for y in range(height))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def sample_image():
    y, x = np.mgrid[0:SCALE, 0:SCALE]
    rgb = np.stack([
        (x * 4 + 3) % 256,
        (y * 5 + 7) % 256,
        ((x + 2 * y) * 3 + 11) % 256,
    ], axis=-1).astype(np.uint8)
    return rgb


def vision_tensors(rng):
    tensors = {}

    def add(name, array):
        tensors[name] = np.ascontiguousarray(array, dtype=np.float32)

    def normal(shape):
        return rng.normal(0.0, 0.02, size=shape).astype(np.float32)

    def ones(n):
        return np.ones((n,), dtype=np.float32)

    def zeros(n):
        return np.zeros((n,), dtype=np.float32)

    add("model.vision_tower.embeddings.patch_embedding.weight", normal((HIDDEN, 3, PATCH, PATCH)))
    add("model.vision_tower.embeddings.position_embedding.weight", normal((POS_SIDE * POS_SIDE, HIDDEN)))
    for layer in range(LAYERS):
        prefix = f"model.vision_tower.encoder.layers.{layer}."
        add(prefix + "layer_norm1.weight", ones(HIDDEN))
        add(prefix + "layer_norm1.bias", zeros(HIDDEN))
        add(prefix + "layer_norm2.weight", ones(HIDDEN))
        add(prefix + "layer_norm2.bias", zeros(HIDDEN))
        for name in ("q_proj", "k_proj", "v_proj", "out_proj"):
            add(prefix + f"self_attn.{name}.weight", normal((HIDDEN, HIDDEN)))
        add(prefix + "mlp.fc1.weight", normal((FFN, HIDDEN)))
        add(prefix + "mlp.fc2.weight", normal((HIDDEN, FFN)))
    add("model.vision_tower.post_layernorm.weight", ones(HIDDEN))
    add("model.vision_tower.post_layernorm.bias", zeros(HIDDEN))

    add("model.vision_tower.vit_merger.layer_norm1.weight", ones(HIDDEN))
    add("model.vision_tower.vit_merger.layer_norm1.bias", zeros(HIDDEN))
    for name in ("q_proj", "k_proj", "v_proj", "out_proj"):
        add(f"model.vision_tower.vit_merger.self_attn.{name}.weight", normal((HIDDEN, HIDDEN)))
    joined = HIDDEN * 4
    add("model.vision_tower.vit_merger.pre_norm.weight", ones(joined))
    add("model.vision_tower.vit_merger.pre_norm.bias", zeros(joined))
    add("model.vision_tower.vit_merger.linear_1.weight", normal((MERGER_FFN, joined)))
    add("model.vision_tower.vit_merger.linear_2.weight", normal((HIDDEN, MERGER_FFN)))

    add("model.merger.mlp.0.pre_norm.weight", ones(joined))
    add("model.merger.mlp.0.pre_norm.bias", zeros(joined))
    add("model.merger.mlp.0.linear_1.weight", normal((joined, joined)))
    add("model.merger.mlp.0.linear_2.weight", normal((HIDDEN, joined)))
    return tensors


def language_tensors():
    vocab = len(TOKENS)
    tensors = {}

    def add(name, array):
        tensors[name] = np.ascontiguousarray(array, dtype=np.float32)

    def zeros(shape):
        return np.zeros(shape, dtype=np.float32)

    # Qwen3Next adds 1 to every norm.weight except linear_attn.norm, so a stored 0
    # is a runtime gamma of 1. Projections are zero, so each block's residual
    # keeps the token embedding and the biased head emits "yes".
    add("model.language_model.embed_tokens.weight", np.ones((vocab, HIDDEN), dtype=np.float32))
    add("model.language_model.norm.weight", zeros((HIDDEN,)))
    head = np.full((vocab, HIDDEN), -100.0, dtype=np.float32)
    head[YES_ID] = 100.0
    add("lm_head.weight", head)
    n_v_heads = 2
    key_dim = HEAD_DIM * n_v_heads
    value_dim = HEAD_DIM * n_v_heads
    conv_dim = key_dim * 2 + value_dim
    q_out = TEXT_HEADS * HEAD_DIM * 2
    kv_out = TEXT_KV * HEAD_DIM
    for layer, kind in enumerate(("linear_attention", "full_attention")):
        prefix = f"model.language_model.layers.{layer}."
        add(prefix + "input_layernorm.weight", zeros((HIDDEN,)))
        add(prefix + "post_attention_layernorm.weight", zeros((HIDDEN,)))
        if kind == "linear_attention":
            add(prefix + "linear_attn.in_proj_qkv.weight", zeros((key_dim * 2 + value_dim, HIDDEN)))
            add(prefix + "linear_attn.in_proj_z.weight", zeros((value_dim, HIDDEN)))
            add(prefix + "linear_attn.in_proj_a.weight", zeros((n_v_heads, HIDDEN)))
            add(prefix + "linear_attn.in_proj_b.weight", zeros((n_v_heads, HIDDEN)))
            add(prefix + "linear_attn.conv1d.weight", zeros((conv_dim, 1, 4)))
            add(prefix + "linear_attn.dt_bias", np.full((n_v_heads,), -30.0, dtype=np.float32))
            add(prefix + "linear_attn.A_log", np.full((n_v_heads,), -20.0, dtype=np.float32))
            add(prefix + "linear_attn.norm.weight", np.ones((HEAD_DIM,), dtype=np.float32))
            add(prefix + "linear_attn.out_proj.weight", zeros((HIDDEN, value_dim)))
        else:
            add(prefix + "self_attn.q_proj.weight", zeros((q_out, HIDDEN)))
            add(prefix + "self_attn.k_proj.weight", zeros((kv_out, HIDDEN)))
            add(prefix + "self_attn.v_proj.weight", zeros((kv_out, HIDDEN)))
            add(prefix + "self_attn.o_proj.weight", zeros((HIDDEN, TEXT_HEADS * HEAD_DIM)))
            add(prefix + "self_attn.q_norm.weight", zeros((HEAD_DIM,)))
            add(prefix + "self_attn.k_norm.weight", zeros((HEAD_DIM,)))
        add(prefix + "mlp.gate_proj.weight", zeros((FFN, HIDDEN)))
        add(prefix + "mlp.up_proj.weight", zeros((FFN, HIDDEN)))
        add(prefix + "mlp.down_proj.weight", zeros((HIDDEN, FFN)))
    return tensors


def config():
    text = {
        "hidden_size": HIDDEN,
        "num_hidden_layers": LAYERS,
        "num_attention_heads": TEXT_HEADS,
        "num_key_value_heads": TEXT_KV,
        "head_dim": HEAD_DIM,
        "intermediate_size": FFN,
        "rms_norm_eps": 1e-6,
        "vocab_size": len(TOKENS),
        "max_position_embeddings": 2048,
        "rope_theta": 10000.0,
        "tie_word_embeddings": False,
        # Qwen3.5 always builds a hybrid graph. The recurrent-state copy is
        # unallocated when every layer is full attention, and the KV index
        # tensor is unallocated when every layer is linear attention.
        "layer_types": ["linear_attention", "full_attention"],
        "full_attention_interval": 4,
        "linear_conv_kernel_dim": 4,
        "linear_key_head_dim": HEAD_DIM,
        "linear_num_key_heads": 2,
        "linear_num_value_heads": 2,
        "linear_value_head_dim": HEAD_DIM,
        "rope_parameters": {
            "rope_theta": 10000.0,
            "partial_rotary_factor": 1.0,
            "mrope_section": [2, 2, 0, 0],
        },
    }
    vision = {
        "hidden_size": HIDDEN,
        "num_hidden_layers": LAYERS,
        "num_attention_heads": HEADS,
        "intermediate_size": FFN,
        "patch_size": PATCH,
        "image_size": POS_SIDE,
        "layer_norm_eps": 1e-6,
        "insert_layer_id": INSERT_LAYER,
    }
    return {
        "architectures": ["MiniCPMV4_6ForConditionalGeneration"],
        "model_type": "minicpmv",
        "torch_dtype": "float32",
        "shipmb_vision_fixture": True,
        "shipmb_vision_tokens": TOKENS,
        "shipmb_vision_token_types": TOKEN_TYPES,
        "bos_token_id": 0,
        "eos_token_id": 1,
        "unk_token_id": 0,
        "insert_layer_id": INSERT_LAYER,
        "text_config": text,
        "vision_config": vision,
    }


def preprocessor():
    return {
        "image_mean": [0.5, 0.5, 0.5],
        "image_std": [0.5, 0.5, 0.5],
        "scale_resolution": SCALE,
        "downsample_mode": "16x",
    }


def convert(convert_py, model_dir, outfile, mmproj):
    command = [sys.executable, str(convert_py), str(model_dir), "--outtype", "f32", "--outfile", str(outfile)]
    if mmproj:
        command.append("--mmproj")
    else:
        command.append("--no-mtp")
    subprocess.run(command, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if len(TOKENS) != len(TOKEN_TYPES):
        raise SystemExit("token list and types diverged")
    if YES_ID >= len(TOKENS) or TOKENS[YES_ID] != "yes":
        raise SystemExit("YES_ID does not name the yes token")
    if 2 * (2 + 2 + 0) != HEAD_DIM:
        raise SystemExit("mrope sections do not cover head_dim")
    if LAYERS != 2:
        raise SystemExit("the fixture language stack is one linear layer and one full-attention layer")

    root = Path(__file__).resolve().parents[1]
    convert_py = root / "third_party" / "llama.cpp" / "convert_hf_to_gguf.py"
    out = args.out
    out.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(SEED)
    tensors = {}
    tensors.update(vision_tensors(rng))
    tensors.update(language_tensors())
    image = sample_image()
    write_png(out / "sample.png", image)
    np.savez_compressed(out / "weights.npz", **tensors)

    from safetensors.numpy import save_file
    with tempfile.TemporaryDirectory(prefix="shipmb-vision-fixture-") as tmp:
        model_dir = Path(tmp)
        save_file(tensors, model_dir / "model.safetensors")
        (model_dir / "config.json").write_text(json.dumps(config()), encoding="utf-8")
        (model_dir / "preprocessor_config.json").write_text(json.dumps(preprocessor()), encoding="utf-8")
        convert(convert_py, model_dir, out / "model.gguf", mmproj=False)
        convert(convert_py, model_dir, out / "mmproj.gguf", mmproj=True)

    golden = {
        "question": "cat",
        "detailed": True,
        "flash_attn": False,
        "n_threads": 1,
        "use_gpu": False,
        "max_tokens": 1,
        "image_tokens": 1,
        "text": "yes",
        "embedding_atol": 2e-2,
        "embedding_rtol": 1e-2,
        "seed": SEED,
        "insert_layer_id": INSERT_LAYER,
        "vision_heads": HEADS,
        "scale_resolution": SCALE,
        "patch_size": PATCH,
    }
    (out / "golden.json").write_text(json.dumps(golden, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
