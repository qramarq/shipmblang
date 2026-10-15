# ShipMBLang

## Quick start (Python)

Install Python 3.11+ and Git. In a terminal, run:

```sh
git clone https://github.com/qramarq/shipmblang.git
cd shipmblang
python -m pip install .
```

Create `hello.shipmb` in the `shipmblang` folder with this text:

```text
"Start with total at 4, then add 8 to total and show total."
```

Run it:

```sh
python -m shipmblang run --file hello.shipmb --memory off
```

The result includes `runtime.stdout` with `"12\n"`. No separate compiler, model, or
API key is needed for this example.

## Notebook and editor

After installing ShipMBLang, run either command to open the same terminal notebook:

```sh
python -m shipmblang notebook
# or
python -m shipmblang editor
```

Rust and Cargo are needed for the first launch. See the [editor guide](docs/notebook.md)
for writing, saving, and running notes.

## VS Code

To try the included extension, install ShipMBLang from this checkout as above, then:

1. Open `extensions/vscode-shipmblang` in VS Code 1.92 or newer.
2. Press **F5** to open the Extension Development Host.
3. In that window, open the Command Palette, choose **ShipMBLang: New Prose Program**,
   then choose **ShipMBLang: Run Natural Program**.

The extension uses the same Python environment where ShipMBLang is installed. See
the [VS Code guide](extensions/vscode-shipmblang/README.md) if you need to select a
different interpreter.

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

## ShipMBLang document editor

Run `python -m shipmblang editor` (or `python -m shipmblang notebook`) to open
the Ratatui terminal document editor. Write English instructions, insert local
images inline with Ctrl+I, then compile with Ctrl+Enter or run with F5. Rust and
Cargo are required for the bundled terminal UI. The bundled 0.5.0 compiler
supports ordered `[[image:N]]` anchors through the v2 image prose contract. See
the [editor guide](docs/notebook.md).
The [MiniCPM-V 4.6 guide](docs/minicpmv.md) documents the image provider,
train-only QLoRA/CPU-offload preflight, and held-out compiler evaluation. No
fine-tuned weights or upstream vision-benchmark scores are included in this
release.

## 0.5.0 multimodal verification

ShipMBLang Python suite: **139 passed, 1 skipped, 61 subtests passed**. The
ShipMBCompiler Python 0.5.0 suite: **235 passed, 3 skipped**. The shipped
language bundle uses compiler 0.5.0 and the `shipmb-image-prose-v2` contract:
the editor inserts local images inline, the adapter sends image paths with
numbered anchors in document order, and the compiler asks for clarification
when attachments or visual details are missing. The editor also keeps notes in
the existing SQLite store. This update applies to the bundled Python compiler;
the native C++ compiler remains a separate distribution. The Ratatui crate was
not built here because Cargo is not installed on this machine.

These are software test results, not MiniCPM-V benchmark scores. No fine-tune
has run yet; DocVQA, MMBench, OCRBench, and held-out compiler-model evaluations
remain unmeasured. See the [training and evaluation guide](docs/minicpmv.md)
before preparing licensed train-only data or reporting model metrics.

### MiniCPM-V training and evaluation progress

Progress is reported in stages so software support is not confused with model
quality measurements:

1. **Integration complete:** ShipMBLang 0.5.0 bundles the compiler's ordered
   image-and-prose contract. The editor can attach local images in document
   order, and missing image context produces a clarification request.
2. **Local verification complete:** the recorded 0.5.0 suites above cover the
   language and compiler integration. Hosted CI caught a cross-platform
   line-ending mismatch in the compiler snapshot hashes. The bundle now uses
   committed LF blob hashes, and the mobile pin uses the canonical manifest
   digest. Focused integrity/notebook tests passed locally; the latest hosted CI
   caught the stale mobile pin, so this correction still needs a push and CI run.
3. **Training preparation documented:** the [MiniCPM-V guide](docs/minicpmv.md)
   describes train-only data preparation, QLoRA with CPU offload, and held-out
   compiler evaluation. The selected first model is MiniCPM-V 4.6 at 1.3B
   parameters, with an 8 GiB GPU as the local target.
4. **Training and benchmark measurements pending:** no fine-tune has run and no
   DocVQA, MMBench, OCRBench, or compiler-translation score is available yet.
   The plan is to compare both documented training approaches, train only on
   available training splits, and keep official evaluation splits held out.
5. **Smaller-model follow-up pending:** after the 1.3B run is successfully
   published, evaluate a model at or below 1B parameters against the same
   held-out tasks. Add scores here only after reproducible evaluation runs.

## iOS and Android

The [mobile app](apps/mobile/README.md) provides executable sticky notes with
local saving and Run/Terminal controls. It connects to the authenticated
ShipMBLang service using the current pinned compiler snapshot. Expo development,
preview, and production build profiles are included; signed device builds and
store submissions require your release accounts and a hosted HTTPS service.

Executable Notes now includes optional media import, conversion, composition rendering,
preview and export. See [Notes media setup](docs/notes-media.md).
