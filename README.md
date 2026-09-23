# ShipMBLang

## Optional native runtime

Use the [native Windows launcher](docs/native.md) with a privately supplied
ShipMBCompiler C++17 source folder or executable. Native compilation and execution
run without Python. This public repository and its
[source ZIP](https://github.com/qramarq/shipmblang/archive/refs/heads/main.zip)
include the launcher and build helper; **compiler source and binaries are supplied
separately and privately**. Existing Python integrations below remain available.

```powershell
$env:SHIPMB_NATIVE_COMPILER = 'C:\private-tools\shipmbc_cpp.exe'
.\shipmblang-native.cmd native/examples/general.shipmb --run
```

## Media integrations in 0.5.0

FFmpeg, HyperFrames and VLC are available through both the Python-based language
and the separately supplied native compiler 0.5.0. See [media setup](docs/media-parity.md).
Python VLC execution uses the optional native `shipmb_vlc.dll` adapter and an
installed matching LibVLC 3.x; compilation needs neither. Native FFmpeg and
HyperFrames run without Python, with their external media/render tools installed
when execution is requested. Model-assisted English and persistent memory remain
Python features; this release aligns media capabilities rather than every API.

## Python integrations

Version 0.5.0 bundles ShipMBCompiler 0.5.0 and includes the FFmpeg media and
HyperFrames video commands documented below.

Write English requests in a `.shipmb` file and run them locally. Broader English
translation is the default: supported grammar compiles directly, and other wording
uses your configured model to produce English that the existing compiler validates.
Computation programs retain their existing bytecode format; media programs use the explicit FFmpeg runtime.

No model or API key is required for the deterministic grammar. Broader wording
requires a configured local or hosted model; unsupported operations and missing
information produce diagnostics or clarification questions, never placeholder code.

## Install

You need Python 3.11+ and Git. The language includes its compiler and runtime
internally; no separate compiler installation or compiler command is needed:

```sh
git clone https://github.com/qramarq/shipmblang.git
cd shipmblang
python -m pip install .
```

## Run a program

Save this as `hello.shipmb`:

```text
"Start with total at 4, then add 8 to total and show total."
```

Run it:

```sh
python -m shipmblang run --file hello.shipmb --memory off
```

The JSON result contains `runtime.stdout` with the value `"12\n"`.
`--memory off` disables saving your program to local compiler memory.
If an instruction is unsupported or needs clarification, revise it and run again.

## FFmpeg media jobs

Compile a media program without processing its inputs:

```powershell
python -m shipmblang compile --file examples/ffmpeg-transcode.shipmb --memory off --no-english-model
```

The example converts `input.mp4` to `output.mp4`. Put the input beside the source
file, then opt into execution using your separately installed FFmpeg and ffprobe:

```powershell
python -m shipmblang compile --file examples/ffmpeg-transcode.shipmb --run --ffmpeg-path C:/tools/ffmpeg/bin/ffmpeg.exe --ffprobe-path C:/tools/ffmpeg/bin/ffprobe.exe --ffmpeg-timeout 120 --memory off --no-english-model
```

Media blocks support variables, loops and functions, scoped input/output options,
stream mapping and filter graphs. They use bytecode 0.4; computation-only programs
keep bytecode 0.3. Relative media paths resolve from the source file's directory.
Existing outputs are protected unless the program says `Overwrite outputs.`
Python callers explicitly supply `FFmpegExecutor` to `run_direct_program`.

Deterministic media grammar needs no model or executable to compile. Broader
wording uses the configured model and can consult installed FFmpeg help without
processing media. Available codecs and filters depend on the installed build.
See [media programs](docs/ffmpeg.md) for the grammar, Python API and environment
variables for executable paths.

## HyperFrames video projects

Compile supported video instructions into a standalone HTML project:

```powershell
python -m shipmblang hyperframes compile examples/hyperframes-title.shipmb --out output/title
```

This deterministic command writes the project without a model, Node or a render
process. To produce an MP4, first install Node.js 22+, FFmpeg/ffprobe and the pinned
renderer dependencies as described in the [HyperFrames guide](docs/hyperframes.md),
then explicitly render:

```powershell
python -m shipmblang hyperframes render output/title --out output/title.mp4 --timeout 300
```

Compilation refuses an existing project directory; rendering refuses an existing
output file. The Python API provides `compile_hyperframes`,
`write_hyperframes_project` and `render_hyperframes_project`.

## Broader English

Reviewed contextual wording also works offline: `Present the sum of 2 and 3.`,
`Could you add 2 and 3 together and tell me the result?`, and
`Compute the aggregate of 2 and 3.` each output `5`. Quoted text and variable
names retain their spelling; arithmetic `add` never becomes package installation.
See [contextual vocabulary](docs/contextual-vocabulary.md) for supported forms
and ambiguity limits. Broader requests sent to your configured model, including
Qwen, receive relevant reviewed vocabulary hints alongside the original request.

Configure an existing model endpoint once (PowerShell example):

```powershell
$env:SHIPMB_MODEL_PROVIDER = "openai_compatible"
$env:SHIPMB_MODEL_BASE_URL = "http://127.0.0.1:11434/v1"
$env:SHIPMB_MODEL_NAME = "your-installed-model"
python -m shipmblang run "Add the odd numbers in 2, 5, 8, and 11 and show the total." --memory off
```

Requests needing translation are sent to that endpoint. The compiler checks the
translation and compiles it by default. JSON retains the original request and the
interpretation; bytecode-only output prints the interpretation to stderr. Type
and syntax validation cannot prove that a model preserved the intended meaning.

Use `--review-model-interpretation` to review a proposal, then supply the intended
English with `--interpretation`. Use `--no-english-model` for deterministic-only
compilation. The default pipeline is `direct` with the `general` profile. Explicit
legacy pipelines remain available; Core output requires `--pipeline legacy`.

Python callers use `compile_direct_program(text)` or `run_direct_program(text)`
for the same defaults. Pass `model_provider=None` to disable translation, or
`accept_model_interpretation=False` to review it. The older
`compile_natural_program` / `run_natural_program` APIs retain their legacy schema.

See [examples](examples/), [VS Code setup](extensions/vscode-shipmblang/README.md),
and the [language guide](docs/shipmblang.md) for more.

## Multi-paragraph requests

Put the full request in one `.shipmb` file, separating paragraphs with blank lines.
ShipMBLang processes them as one program, so later paragraphs can refer to earlier
values and add constraints. Broader wording uses your configured model; the whole
translated program is validated before execution. Unsupported operations or
unresolved questions block execution of the entire program.

Run it with `python -m shipmblang run --file program.shipmb`. Use
`--review-model-interpretation` to review a model translation before compiling it.

## License

Copyright 2026 ZMachinery LLC (zmachinery).

Licensed under the [Apache License, Version 2.0](LICENSE).
ZMachinery LLC owns the original ShipMB / ShipMBLang code, compiler, runtime,
documentation, and other intellectual property it created or acquired.
Third-party materials remain the property of their respective owners.
This license grants usage rights without transferring ownership or granting
trademark rights except as expressly provided in the license. See [NOTICE](NOTICE).

## Compiler updates for maintainers

Compiler changes are developed and pushed in the compiler repository; language
changes are developed and pushed in this language repository. Each language
release bundles a selected compiler snapshot so users install only ShipMBLang.
See [the bundle update and verification workflow](docs/bundled-compiler.md).

## Text apps and terminals

Run saved Notepad files or pipe copied program text from Google Keep and NotebookLM
through the same runtime as VS Code. See [text-app workflows](docs/text-apps.md)
and the [Colab notebook](examples/text_apps_colab.ipynb).

## ShipMB executable sticky notes

Run `python -m shipmblang notebook`, or double-click `notebook.cmd` on Windows.
Write English directly on a small sticky note. **Run** executes it; **Terminal**
shows or hides output. Notes autosave locally. Right-click for new notes, search,
and backups. See the [notes guide](docs/notebook.md).

## iOS and Android

The [mobile app](apps/mobile/README.md) provides executable sticky notes with
local saving and Run/Terminal controls. It connects to the authenticated
ShipMBLang service using the current pinned compiler snapshot. Expo development,
preview, and production build profiles are included; signed device builds and
store submissions require your release accounts and a hosted HTTPS service.
