"""NumPy reference for the MiniCPM-V 4.6 vision tower used by the parity fixture.

The graph follows tools/mtmd/models/minicpmv.cpp (clip_graph_minicpmv4_6) and the
position buckets hardcoded in tools/mtmd/clip.cpp: floor(70 * i / n). Tower and
window MLPs use tanh GELU. The final 2x2 merger uses erf GELU and has no
residual. Fast-mode resizing is outside this tower; the fixture image is already
one slice, which is what detailed mode passes through.
"""
from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

import numpy as np

# CPU F32 agreement with mtmd on the committed fixture. The measured max
# absolute error on this host is about 8.5e-3 (cosine 0.994). The gate is
# wider so -march=native on the three CI machines still agrees.
EMBEDDING_ATOL = 2e-2
EMBEDDING_RTOL = 1e-2


def read_png_rgb(path):
    data = Path(path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} is not a PNG")
    pos = 8
    width = height = None
    compressed = []
    while pos + 8 <= len(data):
        size = int.from_bytes(data[pos:pos + 4], "big")
        tag = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + size]
        if tag == b"IHDR":
            width, height = struct.unpack(">II", chunk[:8])
            if chunk[8] != 8 or chunk[9] != 2:
                raise ValueError("the parity PNG must be 8-bit RGB")
        elif tag == b"IDAT":
            compressed.append(chunk)
        elif tag == b"IEND":
            break
        pos += 12 + size
    raw = zlib.decompress(b"".join(compressed))
    stride = width * 3
    rows = []
    cursor = 0
    for _ in range(height):
        if raw[cursor] != 0:
            raise ValueError("the parity PNG must use filter None")
        cursor += 1
        rows.append(raw[cursor:cursor + stride])
        cursor += stride
    return np.frombuffer(b"".join(rows), dtype=np.uint8).reshape(height, width, 3).copy()


def _layer_norm(x, weight, bias, eps):
    mean = x.mean(axis=-1, keepdims=True)
    var = ((x - mean) ** 2).mean(axis=-1, keepdims=True)
    return (x - mean) / np.sqrt(var + eps) * weight + bias


def _gelu_tanh(x):
    inner = math.sqrt(2.0 / math.pi) * (x + 0.044715 * x ** 3)
    return 0.5 * x * (1.0 + np.tanh(inner))


def _gelu_erf(x):
    values = np.asarray(x)
    erf = np.vectorize(math.erf, otypes=[np.float64])
    return (0.5 * values * (1.0 + erf(values.astype(np.float64)))).astype(values.dtype, copy=False)


def _linear(x, weight):
    return x @ weight.T


def _attention(x, q_weight, k_weight, v_weight, o_weight, n_heads, mask=None):
    n_tokens, width = x.shape
    head = width // n_heads
    def project(weight):
        return _linear(x, weight).reshape(n_tokens, n_heads, head)
    query = project(q_weight)
    key = project(k_weight)
    value = project(v_weight)
    scores = np.einsum("qhd,khd->hqk", query, key) / math.sqrt(head)
    if mask is not None:
        scores = scores + mask
    scores = scores - scores.max(axis=-1, keepdims=True)
    weights = np.exp(scores)
    weights /= weights.sum(axis=-1, keepdims=True)
    mixed = np.einsum("hqk,khd->qhd", weights, value).reshape(n_tokens, width)
    return _linear(mixed, o_weight)


def _mlp(x, up, down, gelu):
    return _linear(gelu(_linear(x, up)), down)


def _conv_patches(image, weight):
    # ggml conv2d is cross-correlation. Output tokens are row-major, x fastest.
    out_channels, in_channels, kernel_h, kernel_w = weight.shape
    channels, height, width = image.shape
    if channels != in_channels:
        raise ValueError("patch embedding channel count does not match the image")
    rows = height // kernel_h
    cols = width // kernel_w
    tokens = np.empty((rows * cols, out_channels), dtype=weight.dtype)
    for y in range(rows):
        for x in range(cols):
            patch = image[:, y * kernel_h:(y + 1) * kernel_h, x * kernel_w:(x + 1) * kernel_w]
            tokens[y * cols + x] = np.tensordot(weight, patch, axes=([1, 2, 3], [0, 1, 2]))
    return tokens, rows, cols


def _buckets(count):
    return [math.floor(70.0 * i / count) for i in range(count)]


def _window_index(rows, cols):
    order = []
    for window_y in range(rows // 2):
        for window_x in range(cols // 2):
            order.append((2 * window_y) * cols + (2 * window_x))
            order.append((2 * window_y) * cols + (2 * window_x + 1))
            order.append((2 * window_y + 1) * cols + (2 * window_x))
            order.append((2 * window_y + 1) * cols + (2 * window_x + 1))
    return np.asarray(order, dtype=np.int64)


def _downsample_index(offset_row, offset_col, rows, cols, stride):
    index = []
    for y in range(rows):
        for x in range(cols):
            index.append((2 * y + offset_row) * stride + (2 * x + offset_col))
    return np.asarray(index, dtype=np.int64)


def _block_mask(n_tokens, dtype):
    mask = np.full((n_tokens, n_tokens), np.finfo(np.float32).min, dtype=dtype)
    for window in range(n_tokens // 4):
        start = window * 4
        mask[start:start + 4, start:start + 4] = 0.0
    return mask


def image_embeddings(weights, image_hwc, n_heads, insert_layer_id=0, eps=1e-6, dtype=np.float64):
    """Return projector embeddings with shape (image_tokens, text_hidden)."""
    arrays = {key: np.asarray(value, dtype=dtype) for key, value in weights.items()}
    pixels = np.asarray(image_hwc, dtype=dtype)
    normalized = (pixels / 255.0 - 0.5) / 0.5
    planar = np.transpose(normalized, (2, 0, 1))
    tokens, rows, cols = _conv_patches(planar, arrays["model.vision_tower.embeddings.patch_embedding.weight"])
    buckets_y = _buckets(rows)
    buckets_x = _buckets(cols)
    positions = [buckets_y[y] * 70 + buckets_x[x] for y in range(rows) for x in range(cols)]
    tokens = tokens + arrays["model.vision_tower.embeddings.position_embedding.weight"][positions]

    hidden = tokens.shape[-1]
    if hidden % n_heads != 0:
        raise ValueError("vision hidden size is not divisible by n_heads")
    n_layers = sum(1 for key in arrays if key.startswith("model.vision_tower.encoder.layers.") and key.endswith("layer_norm1.weight"))

    def vit(x, layer):
        prefix = f"model.vision_tower.encoder.layers.{layer}."
        attended = _attention(
            _layer_norm(x, arrays[prefix + "layer_norm1.weight"], arrays[prefix + "layer_norm1.bias"], eps),
            arrays[prefix + "self_attn.q_proj.weight"],
            arrays[prefix + "self_attn.k_proj.weight"],
            arrays[prefix + "self_attn.v_proj.weight"],
            arrays[prefix + "self_attn.out_proj.weight"],
            n_heads,
        )
        x = x + attended
        fed = _mlp(
            _layer_norm(x, arrays[prefix + "layer_norm2.weight"], arrays[prefix + "layer_norm2.bias"], eps),
            arrays[prefix + "mlp.fc1.weight"],
            arrays[prefix + "mlp.fc2.weight"],
            _gelu_tanh,
        )
        return x + fed

    for layer in range(insert_layer_id + 1):
        tokens = vit(tokens, layer)

    window = _window_index(rows, cols)
    inverse = np.empty_like(window)
    inverse[window] = np.arange(window.shape[0])
    residual = tokens
    merged = _attention(
        _layer_norm(tokens, arrays["model.vision_tower.vit_merger.layer_norm1.weight"], arrays["model.vision_tower.vit_merger.layer_norm1.bias"], eps)[window],
        arrays["model.vision_tower.vit_merger.self_attn.q_proj.weight"],
        arrays["model.vision_tower.vit_merger.self_attn.k_proj.weight"],
        arrays["model.vision_tower.vit_merger.self_attn.v_proj.weight"],
        arrays["model.vision_tower.vit_merger.self_attn.out_proj.weight"],
        n_heads,
        _block_mask(window.shape[0], tokens.dtype),
    )
    tokens = merged[inverse] + residual

    half_rows = rows // 2
    half_cols = cols // 2
    groups = [
        _downsample_index(row, col, half_rows, half_cols, cols)
        for row, col in ((0, 0), (0, 1), (1, 0), (1, 1))
    ]
    pieces = [tokens[index] for index in groups]
    mean = 0.25 * sum(pieces)
    joined = np.concatenate(pieces, axis=-1)
    reduced = _mlp(
        _layer_norm(joined, arrays["model.vision_tower.vit_merger.pre_norm.weight"], arrays["model.vision_tower.vit_merger.pre_norm.bias"], eps),
        arrays["model.vision_tower.vit_merger.linear_1.weight"],
        arrays["model.vision_tower.vit_merger.linear_2.weight"],
        _gelu_tanh,
    )
    tokens = reduced + mean

    for layer in range(insert_layer_id + 1, n_layers):
        tokens = vit(tokens, layer)

    if "model.vision_tower.post_layernorm.weight" in arrays:
        tokens = _layer_norm(
            tokens,
            arrays["model.vision_tower.post_layernorm.weight"],
            arrays["model.vision_tower.post_layernorm.bias"],
            eps,
        )

    merger_rows = half_rows
    merger_cols = half_cols
    groups = [
        _downsample_index(row, col, merger_rows // 2, merger_cols // 2, merger_cols)
        for row, col in ((0, 0), (0, 1), (1, 0), (1, 1))
    ]
    pieces = [tokens[index] for index in groups]
    joined = np.concatenate(pieces, axis=-1)
    projected = _mlp(
        _layer_norm(joined, arrays["model.merger.mlp.0.pre_norm.weight"], arrays["model.merger.mlp.0.pre_norm.bias"], eps),
        arrays["model.merger.mlp.0.linear_1.weight"],
        arrays["model.merger.mlp.0.linear_2.weight"],
        _gelu_erf,
    )
    return projected.astype(np.float32)
