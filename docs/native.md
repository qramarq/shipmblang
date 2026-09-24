# Use a privately supplied native compiler

The public ShipMBLang repository provides a Windows launcher, build helper and
integration check for the native C++17 compiler. The compiler source and binary
are supplied separately and privately. They are not included in this repository
or its public source ZIP. Existing Python integrations remain unchanged.

## Use an existing executable

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

## Build local compiler sources

Install CMake 3.20+ and a C++17 toolchain, such as Visual Studio 2022 Build Tools
with the Desktop C++ workload. Supply the compiler source folder containing
`cpp/CMakeLists.txt`:

```powershell
powershell -ExecutionPolicy Bypass -File native/build.ps1 -CompilerRoot C:\private-sources\shipmbcompiler
```

The helper builds and tests the local sources, then installs the executable into
the ignored `native/bin` folder. The launcher uses that executable when
`SHIPMB_NATIVE_COMPILER` is not set. No compiler is downloaded automatically.

## Contract and checks

Use native compiler 0.5.0 or newer, matching the current language snapshot
provenance (`125c12ef57973bad3d9e0270b295cf6cda8e5402`). Its deterministic general
grammar supports variables, expressions, typed lists, conditions, loops and
functions. It emits interpreted ShipMB bytecode, not a new machine-code executable
for each program. JSON results contain `target_code` and, after execution,
`runtime.stdout`. General artifacts use bytecode 0.3 and VLC artifacts use 0.5.
Unsupported grammar returns diagnostics rather than falling back to Python or a
model. The current native revision also supports explicitly configured model
interpretation and shared persistent meaning memory; these are not required for
deterministic local programs.

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
and Windows host-window embedding. Windows x64 is the verified platform.

Editor tasks and terminals may invoke the launcher on a `.shipmb` file. Existing
VS Code extension commands continue to use the Python integration.
