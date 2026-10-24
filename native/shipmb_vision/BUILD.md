# Build `shipmb_vision`

These commands build the shared library from this directory on a clean Linux machine. They fetch llama.cpp; they do not expect it to be vendored here.

Install the tools once:

```bash
sudo apt-get update
sudo apt-get install -y build-essential cmake git ca-certificates
```

From this directory:

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DGGML_CCACHE=OFF -DCMAKE_C_COMPILER=gcc -DCMAKE_CXX_COMPILER=g++
cmake --build build --parallel
ctest --test-dir build --output-on-failure
```

Configure clones `https://github.com/ggml-org/llama.cpp.git` tag `b11846` (`git clone --depth 1`) and checks that `HEAD` is `1a24df163920a4744a95373d178d790b72a9bb2f`. It then applies `patches/llama.cpp-b11846-shipmb.patch`. The build needs network access for that clone.

## Output

On Linux the library is `build/libshipmb_vision.so`.

`vision.py` loads that file with ctypes. The names it resolves are:

- `smb_vision_create`
- `smb_vision_query`
- `smb_vision_query_stream`
- `smb_vision_free`
- `smb_vision_last_error`

The header also exports `smb_vision_runtime`. `vision.py` does not load that symbol.

`vision.py` opens `SHIPMB_VISION_BRIDGE` when that variable is set. Otherwise it opens `native/libshipmb_vision.so` next to `vision.py` (`libshipmb_vision.dylib` on macOS, `shipmb_vision.dll` on Windows).

## Tests

`ctest` runs three tests:

- `shipmb_vision_smoke` checks the CPU backend string and the missing-weights error. It does not load model files.
- `shipmb_vision_sha_test` checks the SHA-256 helper.
- `shipmb_vision_parity` runs the tiny MiniCPM-V 4.6 fixture in `fixtures/minicpmv46-tiny/` and checks the greedy token and the image-token count.

`shipmb_vision_bench` is built with the library. It is the warm-latency harness. `ctest` does not run it, and it needs the real weights.

## What is not in this tree

llama.cpp itself is not included. The real MiniCPM-V GGUF weights are not included. `scripts/make_tiny_fixture.py` regenerates the tiny fixture; it looks for `third_party/llama.cpp/convert_hf_to_gguf.py` and needs NumPy. The library build does not run that script. The committed fixture is already in `fixtures/minicpmv46-tiny/` (about 1.8 MB).

To also build `llama-quantize` (the tool that reproduces `mmproj-model-q8_0.gguf` from the f16 projector), configure with `-DSHIPMB_VISION_QUANTIZE=ON`.
