# Native vision

`shipmblang setup --vision` installs everything a vision program needs:

- the pinned MiniCPM-V 4.6 language model and f16 projector
- `mmproj-model-q8_0.gguf`, quantized locally from that f16 file
- `libshipmb_vision`, built from the vendored sources when the machine has a toolchain

Save this as `photo.shipmb`, using the path of a PNG, JPEG, GIF, or BMP:

```text
Look at "photo.png" and tell me what is in it.
```

```sh
shipmblang setup --vision
shipmblang photo.shipmb --format text
```

That sentence is the `describe` operation. The bundled runtime asks "What is in
this image?" and stops after 16 tokens. `VisionEngine` in
`shipmblang/_compiler/vision.py` sends that budget when the engine is created,
and `VisionExecutor.invoke` does not pass a larger `max_tokens` for `describe`.
Sixteen tokens is a short phrase. A model that starts a longer sentence stops
mid-sentence. The same budget covers yes/no and count answers, and it is the
budget the 2-second latency check measures. This repository does not edit
`shipmblang/_compiler`, so the program path keeps 16 tokens. Compile-time
image prose is a different call and may use 64 or 256 tokens.

The first run asks before it downloads. `shipmblang setup --vision --yes` skips the
question. Compilation does not load the library. Running a vision program does.
If the library is missing, the run exits 2 and tells you to run
`shipmblang setup --vision`.

Linux is verified. Windows x64 is supported with Visual Studio 2022 and the
static C runtime. The Windows section below is the procedure for that platform.
macOS comes later. The commands in the first half of this page were run on Linux.

## Weights

The pins live in `native/shipmb_vision/weight_pins.json` and
`native/shipmb_vision/pins.json`. Setup downloads these two files from
`huggingface.co/openbmb/MiniCPM-V-4.6-gguf` at revision
`afe9accb78d2995d214cd912920c9c92f4015faa`:

| File | Bytes | SHA-256 |
| --- | --- | --- |
| `MiniCPM-V-4_6-Q4_K_M.gguf` | 529101504 | `6b0c74962c44bc6bf4b655b9b02c13eda9d5a0491543ae976d1ac18e4b7892e2` |
| `mmproj-model-f16.gguf` | 1108746944 | `ca931d861d0801d9003e50697cd764721a334107c0e0415a51168ee1938462de` |

`mmproj-model-q8_0.gguf` is not on Hugging Face. Setup builds `llama-quantize`
from llama.cpp tag `b11846` (commit `1a24df163920a4744a95373d178d790b72a9bb2f`)
and runs it as `llama-quantize mmproj-model-f16.gguf mmproj-model-q8_0.gguf Q8_0`
with no extra flags. The result must be 726599744 bytes and SHA-256
`cc6e95b117ade93ca9dfc5a81998d14a19b9ae8ce4eb44658a20b55407a7d54f`.
Twenty-seven `ffn_down` tensors stay F16 because their dimension 4304 is not
divisible by 32.

Downloads show progress and resume from a `.partial` file. Each finished file
is checked against its size and SHA-256. A file that already matches is left
alone, so a second `setup --vision` does not download or quantize again.
`--offline` refuses to use the network and names that fact when a pinned file
is missing. A dropped connection leaves the partial file in place and tells
you to run the same command again.

The library reads `SHIPMB_VISION_MODEL_DIR` when it is set. Otherwise it uses:

| System | Directory |
| --- | --- |
| Linux | `$XDG_CACHE_HOME/shipmblang/vision`, or `~/.cache/shipmblang/vision`. An empty `HOME` is `./.cache/shipmblang/vision`. |
| macOS | `~/Library/Caches/shipmblang/vision` |
| Windows | `%LOCALAPPDATA%\shipmblang\vision`, then `%USERPROFILE%\AppData\Local\shipmblang\vision`, then `shipmblang\vision` |

The runtime opens `MiniCPM-V-4_6-Q4_K_M.gguf` and `mmproj-model-q8_0.gguf` in
that directory. The f16 file stays there so quantization can be repeated
without another download.

## Build the library

The C++ sources are `native/shipmb_vision/`. llama.cpp is not vendored. CMake
fetches tag `b11846`, checks commit `1a24df163920a4744a95373d178d790b72a9bb2f`,
and applies `patches/llama.cpp-b11846-shipmb.patch`. See `VENDOR.md` and
`BUILD.md` in that directory. `vendor/json.hpp` is nlohmann/json 3.11.3. The
llama.cpp license is `licenses/llama.cpp-MIT.txt`.

```sh
python tools/build_vision.py
ctest --test-dir native/shipmb_vision/build --output-on-failure
```

The script configures with gcc and g++ when both are on `PATH`. On some
machines `/usr/bin/c++` is Clang and cannot link libstdc++, so the script does
not leave the compiler to CMake's default. Pass `--cc` and `--cxx` together to
choose a different pair. `CC` and `CXX`, or `SHIPMB_VISION_CC` and
`SHIPMB_VISION_CXX`, do the same when both are set.

The shared library is installed at `shipmblang/_compiler/native/`, which is
where `vision.py` looks when `SHIPMB_VISION_BRIDGE` is unset
(`libshipmb_vision.so`, `libshipmb_vision.dylib`, or `shipmb_vision.dll`).
That directory is build output and is not committed. The same step copies
`LICENSE`, `NOTICE`, and `licenses/llama.cpp-MIT.txt` beside the library.

`setup --vision` uses a library already packed in the wheel or the standalone
executable. If none is packed, it builds `native/shipmb_vision` when CMake,
git, and a compiler are installed. Otherwise it stops and says what to install.

`ctest` runs `shipmb_vision_smoke`, `shipmb_vision_sha_test`, and
`shipmb_vision_parity`. The parity test uses `fixtures/minicpmv46-tiny/` and
does not download the real weights. `shipmb_vision_bench` is built but not
run by `ctest`. It needs the real weights.

## Standalone executable

`python tools/build_standalone.py` packs the CPU library, the weight pins,
`llama-quantize`, and the license files when the library has already been built. The frozen
`vision.py` finds that library: the executable sets `SHIPMB_VISION_BRIDGE` to
`shipmblang/_compiler/native/<library>` inside the PyInstaller bundle when the
variable is unset. Weights are not packed. Run `shipmblang setup --vision` on
the machine that will execute vision programs.

## Tests

`python -m unittest discover -s tests` includes the tiny-fixture checks and the
setup tests. Those tests use a fake downloader. They do not fetch the real
weights. A built library makes the tiny-fixture query run; without it, that
one test is skipped and the file checks still run.

Real-weight checks are opt-in:

```sh
SHIPMB_VISION_WEIGHTS=1 python -m unittest tests.test_vision_fixture.RealWeightTests
```

The latency target is a warm nearest-rank 95th percentile under 2000 ms.
`elapsed_ms` is the library clock from bitmap creation through the answer,
after the weights are loaded. Nearest rank uses
`index = max(0, round(0.95 * len(samples) + 0.5) - 1)` on the sorted samples.

The library keeps prefixes for the last few images. A repeat of one of those
images sets `cached` to true and skips the image encode, so that repeat is
not this measurement. Use a different image for every sample and keep rows
whose `cached` flag is false.

On the 4-core Linux machine used for this check (Intel Xeon, KVM, one thread
per core), ten different 448×448 PNGs, the same short question, `max_tokens`
16, and `cached` false on every row:

| | |
| --- | --- |
| median | 1582.58 ms |
| nearest-rank p95 | 1665.45 ms (index 9) |

## Windows x64

The Windows build uses the Visual Studio generator. `cl` does not need to be
on `PATH`. `python tools/build_vision.py` asks `vswhere` for the newest Visual
Studio or Build Tools install that has the MSVC x64 toolset and configures
with `-G "Visual Studio 17 2022" -A x64` (the year and major version come from
vswhere). A Developer shell that already has both `cl` and `ninja` on `PATH`
(`VSCMD_VER` or `VCToolsInstallDir` is set) uses the Ninja generator instead.

The generator is multi-config, so the build passes `--config Release`. The
products are `build\Release\shipmb_vision.dll` and
`build\bin\Release\llama-quantize.exe` or
`build\_deps\llamacpp-build\tools\quantize\Release\llama-quantize.exe`. The
script copies `shipmb_vision.dll` to `shipmblang\_compiler\native\`, which is
the path `vision.py` opens, and copies `llama-quantize.exe` to
`shipmblang\_compiler\native\bin\`. License files and the weight pins are
copied beside the DLL. That directory is build output and is not committed.

```powershell
python tools\build_vision.py
ctest --test-dir native\shipmb_vision\build -C Release --output-on-failure
```

CMake fetches llama.cpp with `core.autocrlf=false` and applies
`patches/llama.cpp-b11846-shipmb.patch` from `cmake/pin-llama.cmake` before it
adds the subdirectory. That replaces the single-argument `FetchContent_Populate`
call, which current CMake warns about under CMP0169. `.gitattributes` keeps the
patch and the files under `fixtures/` byte-for-byte on a checkout with
`core.autocrlf=true`, and it keeps the C++ sources LF.

The library and `llama-quantize.exe` link the static multithreaded CRT
(`/MT`, CMake `MultiThreaded`). ggml and llama are already static libraries.
A static CRT is the right choice here for three reasons. The DLL is loaded
with `ctypes` by an absolute path, and Windows does not search that directory
for dependent DLLs, so dropping `VCRUNTIME140.dll` next to it does not help
unless every host calls `os.add_dll_directory`. The quantize tool is a
separate process spawned from the source tree and from the frozen executable,
and it would otherwise need a matching copy of the redistributable beside the
exe. The C ABI does not free memory across the Python/DLL boundary, so the
DLL's static CRT can live inside the process that Python built with the
dynamic CRT. `dumpbin /dependents` on `shipmb_vision.dll` and
`llama-quantize.exe` should not list `MSVCP140.dll`, `VCRUNTIME140.dll`, or
`VCRUNTIME140_1.dll`. `api-ms-win-crt-*.dll` or `KERNEL32.dll` are Windows
components, not the Visual C++ redistributable. The frozen `shipmblang.exe`
still depends on the VC runtime because the PyInstaller bootloader and Python
do. That is separate from the vision library.

`shipmblang setup --vision` writes the cache to `%LOCALAPPDATA%\shipmblang\vision`
(then `%USERPROFILE%\AppData\Local\shipmblang\vision`, then `shipmblang\vision`),
the same directories the native library reads. Downloads and quantization take
an exclusive lock file so a second setup stops instead of appending to the
same partial. The partial is published with `os.replace` after it is closed,
which is atomic on NTFS, and a sharing violation from a scanner is retried.
Paths use the `\\?\` prefix so a cache directory longer than `MAX_PATH` still
opens. Ctrl+C flushes the partial download and leaves it in place. Ctrl+C
during quantization terminates `llama-quantize.exe` and deletes that partial,
because a half-written GGUF is not resumed. The quantize tool is always run
as `llama-quantize.exe` by its full path.

`python tools\build_standalone.py` packs `shipmb_vision.dll`,
`llama-quantize.exe`, the pins, and the license files into `dist\shipmblang.exe`.
On startup the frozen program sets `SHIPMB_VISION_BRIDGE` to the DLL under
`_MEIPASS` and calls `os.add_dll_directory` on that directory before
`vision.py` loads it. Weights are not packed. `shipmblang setup --vision` on
the target machine fills the cache.

## Portable Windows zip

On Windows x64, `python tools/build_portable.py` writes
`dist/shipmblang-<version>-windows-x64.zip`. The default zip has the
executable, `shipmb_vision.dll`, `llama-quantize.exe`, and the VC runtime
DLLs next to the executable. It has no model weights. The first
`shipmblang setup --vision` downloads them into the normal cache.
`--with-weights` also writes
`dist/shipmblang-<version>-windows-x64-with-weights.zip` with the language
model and the q8 projector, after checking those files against the pins.
The f16 projector is not packed. `--check-weights` checks the cache and
prints the weight sizes. It does not deflate a zip.

The folder inside the zip is a PyInstaller onedir tree. `--onefile` would
extract the interpreter to a temporary directory on every launch. The vision
DLL and `llama-quantize.exe` stay Release builds. MinSizeRel (`/O1`) is not
used: it can slow the ggml kernels, and the warm p95 under 2 seconds was
measured for the Release library. UPX is not used. The archive is deflate
level 9, with a Zip64 local header on every member so a multi-gigabyte
`--with-weights` archive still extracts. User steps and the size table are
in the README section
[Portable Windows zip](../README.md#portable-windows-zip). The from-source
Windows build above is unchanged.

The laptop check is `tools/win_verify_portable.ps1`. It builds the default
zip, extracts it, clears `PATH` down to `C:\Windows\System32` and
`C:\Windows`, and points `LOCALAPPDATA` at an empty directory. It then runs
`--version`, `examples/general_sum.shipmb`, and `setup --vision --check`
(weights must be missing). It copies the three cached weight files into that
empty cache, runs `setup --vision --yes` so the same hash checks run, then
runs one vision program. Warm latency is measured in-process with the
absolute Python, because each launch of the executable loads the model again.
`-WithWeights` also builds the heavy zip. The default run does not.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\admin\shipmb-worker\shipmblang\tools\win_verify_portable.ps1
```

## Private native compiler

The public repository also has a Windows launcher, build helper, and
integration check for a separate native C++17 compiler. That compiler's source
and binary are supplied privately. They are not the vision library above, and
they are not in this repository. `native/build.ps1` and `native/verify.ps1`
belong to that launcher.

### Use an existing executable

Point the launcher at your local executable:

```powershell
$env:SHIPMB_NATIVE_COMPILER = 'C:\private-tools\shipmbc_cpp.exe'
.\shipmblang-native.cmd native/examples/general.shipmb
.\shipmblang-native.cmd native/examples/general.shipmb --run
```

Compilation is separate from execution. The first command returns JSON without
running the program; `--run` opts into execution. Native compilation and runtime
do not require Python, Node.js or a model. The existing Python CLI remains the
entry point for model translation, FFmpeg, HyperFrames, notebook, MCP and printurf.

### Build local compiler sources

Install CMake 3.20+ and a C++17 toolchain, such as Visual Studio 2022 Build Tools
with the Desktop C++ workload. Supply the compiler source folder containing
`cpp/CMakeLists.txt`:

```powershell
powershell -ExecutionPolicy Bypass -File native/build.ps1 -CompilerRoot C:\private-sources\shipmbcompiler
```

The helper builds and tests the local sources, then installs the executable into
the ignored `native/bin` folder. The launcher uses that executable when
`SHIPMB_NATIVE_COMPILER` is not set. No compiler is downloaded automatically.

### Contract and checks

The native C++ compiler is a separate distribution and is not pinned by the
bundled Python compiler snapshot. The current Python snapshot is 0.6.0 from
compiler commit `4972b2f7ff69bc9f0f1105afc02ef4d3d59ef2f5`. Vision programs use
the library documented above. The native launcher remains available for
deterministic compilation and execution of its supported instructions.

The native compiler emits interpreted ShipMB bytecode, not a new machine-code
executable for each program. JSON results contain `target_code` and, after
execution, `runtime.stdout`. General artifacts use bytecode 0.3 and VLC artifacts
use 0.5. Unsupported grammar returns diagnostics rather than falling back to
Python or a model. Native model interpretation and persistent memory are separate
features of the supplied native compiler build.

```powershell
powershell -ExecutionPolicy Bypass -File native/verify.ps1
.\shipmblang-native.cmd --run-artifact C:\programs\compiled-program.json
```

`--run-artifact` accepts a saved compiler JSON result or its `target_code` object.
Keep JSON integer literals intact when saving artifacts with large integers.
Relative media paths resolve from the source or artifact directory.

For VLC programs, install matching-architecture VLC 3.x separately and pass
`--vlc-dir "C:\Program Files\VideoLAN\VLC"` during execution if needed.
Compilation does not load VLC. See the privately supplied compiler's VLC guide
for playback, playlists, metadata, tracks, subtitles, waits, streaming/transcoding
and Windows host-window embedding. Windows x64 is the verified platform for
that private compiler. It was not re-checked for the vision library.

Editor tasks and terminals may invoke the launcher on a `.shipmb` file. Existing
VS Code extension commands continue to use the Python integration.
