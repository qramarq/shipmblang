# ShipMBLang

Natural-language programs in a `.shipmb` file, compiled and run on your machine.
Package 0.6.0. The bundled compiler snapshot is 0.6.0 from compiler commit
`4972b2f7ff69bc9f0f1105afc02ef4d3d59ef2f5`. It changes only when the compiler sync updates it.

## What's new in 0.6.0

- **Grammar `general-english-0.11`.** `Otherwise if`, `Repeat N times`,
  `Append ... to` a list, `#` comments, `divided by`, and `What is ...?` compile
  on the general profile. Save this as `grammar.shipmb`:

  ```text
  Let n be 2.
  If n is equal to 1 then:
  Show 1.
  Otherwise if n is equal to 2 then:
  Show 2.
  Otherwise:
  Show 0.
  End the condition.
  Repeat 2 times:
  Show 1.
  End the loop.
  Let numbers be a mutable list of integers.
  Append 4 to numbers. # keep 4
  Show numbers.
  What is 8 divided by 2?
  ```

  `shipmblang grammar.shipmb --format text` prints:

  ```text
  2
  1
  1
  [4]
  4
  ```

- **Media duration.** `Probe "clip.mp4" and show the duration.` compiles
  (`status` is `compiled`, and the program requires `ffmpeg`). Compilation does
  not read the file. Running it needs FFmpeg and ffprobe. See
  [media programs](docs/ffmpeg.md).
- **Standalone executable.** One file runs compile and run with no Python
  install. A build made with `--require-editor` already contains the notebook,
  so opening it does not need Rust or Cargo.
- **`shipmblang setup`.** Installs missing Rust, FFmpeg (with ffprobe), VLC,
  and Ollama from their official sources. Those tools are not copied into the
  executable.
- **Native vision.** In-process MiniCPM-V 4.6. `shipmblang setup --vision`
  installs it. See [Native vision](#native-vision) and
  [the vision guide](docs/native.md). Linux is verified. Windows x64 build,
  setup, and run steps are in that section. macOS comes later.
- **Chat-room notebook.** `shipmblang notebook` and `shipmblang editor` open
  saved notes as rooms.
- **`shipmblang lsp` and editors.** Diagnostics, hover, and compile/run over
  stdio. Configs are in [editors](docs/editors.md). In VS Code or Cursor, set
  `shipmblang.executablePath` to the standalone executable.
- **Compiler sync.** Pull requests keep `shipmblang/_compiler/` aligned with
  shipmblang-compiler. See [compiler sync](docs/compiler-sync.md).

## Native vision

Native vision runs MiniCPM-V 4.6 inside the `shipmblang` process. There is no
separate server. After setup, a vision program does not use the network.
Paths, pins, and the build are in [the vision guide](docs/native.md).

### Install

```sh
shipmblang setup --vision
```

That command downloads two files from
`huggingface.co/openbmb/MiniCPM-V-4.6-gguf` at revision
`afe9accb78d2995d214cd912920c9c92f4015faa`, checks each size and SHA-256, then
builds the runtime projector locally:

| File | Bytes | Where it comes from |
| --- | --- | --- |
| `MiniCPM-V-4_6-Q4_K_M.gguf` | 529101504 | Hugging Face |
| `mmproj-model-f16.gguf` | 1108746944 | Hugging Face |
| `mmproj-model-q8_0.gguf` | 726599744 | `llama-quantize` of the f16 file, type `Q8_0`, no extra flags |

The q8 file is not on Hugging Face. Setup checks its size and SHA-256
(`cc6e95b117ade93ca9dfc5a81998d14a19b9ae8ce4eb44658a20b55407a7d54f`) after
quantizing. On Linux the three files go in `$XDG_CACHE_HOME/shipmblang/vision`
when that variable is set, otherwise `~/.cache/shipmblang/vision`.
`SHIPMB_VISION_MODEL_DIR` overrides the directory. A second run that already
matches the pins does not download or quantize again.

`shipmblang setup --vision --yes` skips the prompt. A terminal without `--yes`
asks first. A non-interactive run that still has work to do exits 2 and tells
you to add `--yes`. `--check` prints the cache and the library, does not
download or build, and exits 1 when the library, the language model, or the
q8 projector is missing. `--dry-run` prints the plan and changes nothing.
`--offline` does not use the network: it reuses weights already in the cache
and fails if one is missing. `--offline` is valid only together with
`--vision`. `--vision` does not accept `--only`, `--skip`, `--pull-models`,
or `--model`.

Setup uses a library already next to the program or packed in the executable.
Otherwise it builds `native/shipmb_vision` when CMake, git, and a C++ compiler
are installed. `SHIPMB_VISION_BRIDGE`, when set, is the shared library
`vision.py` loads. When it is unset, the loader uses
`libshipmb_vision.so` beside `vision.py` (`libshipmb_vision.dylib` on macOS,
`shipmb_vision.dll` on Windows).

### Build the library

The sources are `native/shipmb_vision/`. You need CMake, git, and a compiler.
The script uses gcc and g++ when both are on `PATH`, because `/usr/bin/c++`
is Clang on some machines and then cannot link libstdc++. Pass `--cc` and
`--cxx` together to choose another pair. The first configure clones llama.cpp
tag `b11846` and needs the network for that clone.

```sh
python tools/build_vision.py
```

The shared library is copied to `shipmblang/_compiler/native/`, which is where
`vision.py` looks.

### Run a program

Save this as `photo.shipmb`. The path is a PNG, JPEG, GIF, or BMP:

```text
Look at "photo.png" and tell me what is in it.
```

```sh
shipmblang photo.shipmb --format text
```

Compilation does not load the library. Running the program does. If the
library is missing, the run exits 2 and tells you to run
`shipmblang setup --vision`. The printed answer uses at most 16 tokens, so a
longer sentence can stop mid-sentence.

### Standalone executable

`python tools/build_standalone.py` packs the CPU library, `llama-quantize`,
and the vision license files when the library has already been built. The
weights stay outside the executable. Run `shipmblang setup --vision` on the
machine that will run vision programs.

### Latency

The target is a warm nearest-rank 95th percentile under 2 seconds. Repeating
one image can set `cached` and skip the image encode; that faster number is
not the target. Ten different 448×448 images, each with `cached` false, on
the 4-core Linux machine used here: median 1582.58 ms, nearest-rank p95
1665.45 ms. On a Windows laptop (Ryzen AI 7 350, 8 cores / 16 threads) the
same uncached check was median 1222 ms and nearest-rank p95 1247 ms.

### Windows

Windows x64 uses Visual Studio 2022 or Build Tools with the MSVC x64 toolset.
`cl` does not need to be on `PATH`. `python tools\build_vision.py` asks
`vswhere` for that install, configures the Visual Studio generator with
`-A x64`, and builds Release. A Developer shell that already has `cl`,
`ninja`, and `VSCMD_VER` or `VCToolsInstallDir` uses Ninja. The script copies
`shipmb_vision.dll` to `shipmblang\_compiler\native\` and `llama-quantize.exe`
to `shipmblang\_compiler\native\bin\`. Both link the static C runtime.

```powershell
python tools\build_vision.py
ctest --test-dir native\shipmb_vision\build -C Release --output-on-failure
shipmblang setup --vision
```

Setup writes the three weight files to `%LOCALAPPDATA%\shipmblang\vision`,
then `%USERPROFILE%\AppData\Local\shipmblang\vision`. Write image paths in
the program with forward slashes. A backslash inside quotes is an escape.

```text
Look at "C:/Users/me/photo.png" and tell me what is in it.
```

```powershell
shipmblang photo.shipmb --format text
python tools\build_standalone.py
```

`dist\shipmblang.exe` packs the DLL, `llama-quantize.exe`, and the license
files. The weights stay in the cache. Run `shipmblang setup --vision` on the
machine that will run vision programs.

### Platforms and licenses

Linux is verified. Windows x64 is supported with Visual Studio 2022 and the
static C runtime. macOS comes later.

The MiniCPM-V weights are Apache-2.0. llama.cpp is MIT
(`native/shipmb_vision/licenses/llama.cpp-MIT.txt`). Other notices are in
`native/shipmb_vision/NOTICE`.

## Standalone executable

Download `shipmblang` for Linux or macOS, or `shipmblang.exe` for Windows, from
the [Standalone executable workflow](https://github.com/qramarq/shipmblang/actions/workflows/standalone.yml).
Open a successful run and save the artifact for your system. These are Actions
artifacts, not a GitHub Release. No Python install is required.

Unpack the artifact and run the installer. It copies the executable onto your
user `PATH` and then runs `shipmblang setup`, which installs Rust, FFmpeg (with
ffprobe), VLC, and Ollama when they are missing. Those tools are not copied
into the executable. A build made after `python tools/build_vision.py` also
packs the CPU vision library, `llama-quantize`, and the vision license files.
The weights stay outside the executable. Run `shipmblang setup --vision` for
them. Linux vision is verified. Windows x64 vision is built from this
repository with Visual Studio 2022; see [Native vision](#native-vision).
macOS vision comes later.

On Windows, from the unpacked artifact:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

On macOS or Linux:

```sh
./install.sh
```

The installer asks once before it installs anything. Pass setup flags through
it, for example `./install.sh --yes --skip ollama`. `shipmblang setup --check`
only reports what is missing. Rust is optional while you use the packed editor;
it is installed because a source checkout builds that editor with Cargo. See
[the standalone guide](docs/standalone.md) for each operating system, where each
tool comes from, and the licenses.

```sh
shipmblang examples/quoted_paragraph.shipmb --format text
```

That prints:

```text
12
```

Without `--format text`, the same file prints JSON whose `runtime.stdout` is
`"12\n"`. The shorthand uses the direct pipeline, the general profile, and
memory off.

### Build it yourself

From a checkout, on the machine where you want to build:

```sh
python -m pip install pyinstaller
python tools/build_standalone.py --require-editor
```

On Windows: `powershell -ExecutionPolicy Bypass -File tools\build_standalone.ps1 --require-editor`

The build writes `dist/shipmblang` (`dist/shipmblang.exe` on Windows).
`--require-editor` fails the build if Cargo cannot produce the Ratatui binary.
The same `install.sh` or `install.ps1` in `tools/` can install that binary.

## Standalone commands

Flags below are the ones the CLI accepts. `run` defaults to `--format json`.
`compile` defaults to `--format bytecode`. `--pipeline` defaults to `direct`.
`--memory` defaults to `on` unless the bare `program.shipmb` shorthand adds
`--memory off`.

| Command | What it does |
| --- | --- |
| `shipmblang program.shipmb` | Run that file: direct pipeline, general profile, memory off. |
| `shipmblang examples/quoted_paragraph.shipmb --format text` | Same shorthand. `--format text` prints runtime stdout only (`12`). |
| `shipmblang run --file examples/quoted_paragraph.shipmb --pipeline direct --profile general --memory off` | Explicit run. JSON includes `runtime.stdout`. |
| `shipmblang compile --file examples/quoted_paragraph.shipmb --format json --memory off` | Compile to JSON. This example's `status` is `compiled`. |
| `shipmblang run --file - --pipeline direct --profile general --memory off --format text` | Read the program from stdin. `compile --file -` compiles stdin. A bare `shipmblang --file -` is not a command. |
| `shipmblang notebook` | Open the chat-room notebook. `shipmblang editor` is the same UI. |
| `shipmblang editor --theme dark --database notes.sqlite3` | `--theme` is `dark` or `light`. `--ascii` uses plain borders. `--database` selects the SQLite file. `--smoke` prints one frame and exits. `--demo` renders the sample room. `--version` prints the editor version. |
| `shipmblang setup` | Detect Rust, FFmpeg, VLC, and Ollama, and install any that are missing. |
| `shipmblang setup --check` | Report each component. Exit nonzero if a selected tool is absent. |
| `shipmblang setup --dry-run` | Print the install commands and do not run them. |
| `shipmblang setup --yes --skip ollama` | Install without asking. `--skip` leaves components untouched. `--yes` does not download an Ollama model. |
| `shipmblang setup --only rust,ffmpeg` | Limit the command to those components. Names are `rust`, `ffmpeg` (includes ffprobe), `vlc`, and `ollama`. |
| `shipmblang setup --pull-models --model NAME` | After Ollama is available, run `ollama pull NAME`. There is no default model. |
| `shipmblang setup --vision` | Install native MiniCPM-V 4.6. See [Native vision](#native-vision). `--yes` skips the prompt. `--check` and `--dry-run` do not download. `--offline` does not use the network. |
| `shipmblang lsp` | Language server on stdin/stdout. `shipmblang lsp --check` prints `lsp ok`. |
| `shipmblang --version` | Print `shipmblang 0.6.0`. `-V` is the same flag. |
| `shipmblang --help` | Print the command list. `-h` is the same flag. |
| `shipmblang printurf --error-file error.txt` | Explain a raw error. `--error` passes the text directly. |
| `shipmblang mcp` | MCP server on stdin/stdout. It takes no flags. |
| `shipmblang onboarding --check` | Print the onboarding contract. `--check` runs readiness checks. `--format` is `text` or `json`. |
| `shipmblang hyperframes compile examples/hyperframes-title.shipmb --out output/title` | Write an HTML video project. `hyperframes render output/title --out output/title.mp4` renders it. |
| `shipmblang train` | Train the local model. `prepare`, `chat`, and `download` are the other model commands. The standalone executable rejects these and tells you to `pip install "shipmblang[model]"`. |

`ship` is an alias of `compile`. `ship-run` is an alias of `run`.

## Notebook

`shipmblang notebook` and `shipmblang editor` open the same Ratatui chat room.
The sidebar lists each saved note: title, last activity, a one-line preview,
and a status badge. The center is the conversation. Your program is on the
right; ShipMB replies on the left with stdout, diagnostics, and a collapsible
bytecode line. Clarification questions are indented under the message. The
composer is at the bottom. Dark is the default. `--theme light` and Alt+T
switch themes. `--ascii` (also `SHIPMB_ASCII=1` or `TERM=dumb`) draws
`+`/`-`/`|` borders. The packed executable does not need Rust to open this UI.
A source install builds it with Cargo on first launch. Older SQLite notes are
kept; see [the notebook guide](docs/notebook.md).

| Key | Action |
| --- | --- |
| Enter, F5 | Compile and run |
| Ctrl+Enter, Alt+C | Compile only |
| Shift+Enter, Alt+Enter, Ctrl+J | New line in the composer |
| Up | When the composer is empty, load the last program you sent |
| Ctrl+I | Attach an image (`[[image:N]]` stays in the text) |
| Ctrl+N | New chat |
| Ctrl+O | Focus search |
| Ctrl+S | Save the draft |
| Ctrl+B | Back up the SQLite file |
| Ctrl+D | Delete the open chat after you type `DELETE` |
| Ctrl+R | Remove unplaced attachments after you type `REMOVE` |
| Ctrl+P | Pin or unpin the open chat |
| Ctrl+E | Show or hide bytecode on the latest reply |
| Alt+T | Toggle dark and light |
| Ctrl+Q | Save and quit |

`shipmblang editor --smoke --demo` prints `shipmblang editor smoke ok` and one
frame without a terminal. The start of the dark sample frame:

```text
shipmblang editor smoke ok
 ShipMB   Sum of 2 and 3  ?  Ready  dark
╭ Chats ───────────────────╮ ╭ Conversation ───────────────────────────────────────────────────────╮
│ Search chats             │ │                                Today                                │
│  ◆ Sum of 2 and 3        │ │                                                                  You│
│  Which declared value do…│ │                                           ▌ Show the sum of 2 and 3.│
│  09:16  ?                │ │                                                                09:14│
│● Café receipt            │ │                                                                     │
│  café                    │ │ShipMB                                                               │
│  08:02  ✓                │ │▌ Ran successfully.                                                  │
│  Park photo              │ │▌ 5                                                                  │
│  Could not compile this …│ │▸ bytecode                                                           │
│  Yesterday 18:02  ✕      │ │09:14                                                                │
```

## Editors

Point any editor at the same executable. VS Code and Cursor use the extension in
`extensions/vscode-shipmblang`: set `shipmblang.executablePath` to the standalone
file, or leave it empty to use `shipmblang` on `PATH` and then
`shipmblang.pythonPath`. `shipmblang.lsp` starts the language server for
diagnostics and hover. Neovim, Vim, Emacs (eglot), Helix, Zed, Sublime Text,
JetBrains (LSP4IJ or an external tool), Notepad++, and Kate snippets are in
[editors](docs/editors.md). File extensions are `.shipmb`, `.smb`, and
`.shiplang`. The TextMate grammar is
`extensions/vscode-shipmblang/syntaxes/shipmblang.tmLanguage.json`.

## Install with Python

Use this path for development, model extras, and a source checkout. Install
Python 3.11+ and Git.

```sh
git clone https://github.com/qramarq/shipmblang.git
cd shipmblang
python -m pip install .
```

Create `hello.shipmb`:

```text
"Start with total at 4, then add 8 to total and show total."
```

```sh
python -m shipmblang run --file hello.shipmb --memory off --format text
```

That prints `12`. `python -m shipmblang program.shipmb` is the same shorthand
as the executable. The first `python -m shipmblang editor` on a source install
needs Rust and Cargo. The standalone executable already contains that binary.

### Try it without git

1. Download the ZIP (the latest [GitHub Release](https://github.com/qramarq/shipmblang/releases/latest), or **Code → Download ZIP**) and unzip it.
2. Install Python 3.11+.
3. Double-click `try-language.cmd` (Windows) or run `./try-language.sh` (macOS/Linux).

## VS Code

From a source checkout with ShipMBLang installed in the Python environment you
want the extension to use:

1. Open `extensions/vscode-shipmblang` in VS Code 1.92 or newer.
2. Press **F5** to open the Extension Development Host.
3. Run **ShipMBLang: New Prose Program**, then **ShipMBLang: Run Natural Program**.

Set `shipmblang.executablePath` when the extension should launch the standalone
executable instead of Python. See the
[VS Code guide](extensions/vscode-shipmblang/README.md).

On Windows, `vscode-workspace.cmd [folder]` creates `hello.shipmb`, `hello.smb`,
and `hello.shiplang` in a `workspace` folder and opens them in VS Code.

## Documentation

- [Standalone executable](docs/standalone.md)
- [Notebook](docs/notebook.md)
- [Editors](docs/editors.md)
- [Terminals and IDEs](docs/terminal-and-ides.md)
- [Language guide](docs/shipmblang.md)
- [Grammar and contextual vocabulary](docs/contextual-vocabulary.md)
- [Media programs](docs/ffmpeg.md) and [media setup](docs/media-parity.md)
- [HyperFrames](docs/hyperframes.md)
- [Compiler sync](docs/compiler-sync.md) and [bundled compiler](docs/bundled-compiler.md)
- [MiniCPM-V](docs/minicpmv.md) and [Notes media](docs/notes-media.md)
- [Text apps](docs/text-apps.md) and the [Colab notebook](examples/text_apps_colab.ipynb)
- [Examples](examples/)

## Optional native runtime

Use the [native Windows launcher](docs/native.md) with a privately supplied
ShipMBCompiler C++17 source folder or executable. Native compilation and execution
run without Python. This public repository and its
[source ZIP](https://github.com/qramarq/shipmblang/archive/refs/heads/main.zip)
include the launcher and build helper; **compiler source and binaries are supplied
separately and privately**.

```powershell
$env:SHIPMB_NATIVE_COMPILER = 'C:\private-tools\shipmbc_cpp.exe'
.\shipmblang-native.cmd native/examples/general.shipmb --run
```

## Media integrations

FFmpeg, HyperFrames, and VLC are available through the Python package and the
separately supplied native compiler. The bundled Python compiler snapshot is
0.5.0. See [media setup](docs/media-parity.md). Python VLC execution uses the
optional native `shipmb_vlc.dll` adapter and an installed matching LibVLC 3.x;
compilation needs neither. `shipmblang setup` can install FFmpeg, ffprobe, and
VLC. Model-assisted English and persistent memory remain Python features.

Supported grammar compiles directly. Other wording uses your configured model
to produce English that the compiler validates. Computation programs keep
bytecode 0.3. Media programs use bytecode 0.4. No model or API key is required
for the deterministic grammar. Unsupported operations and missing information
produce diagnostics or clarification questions.

### FFmpeg media jobs

Compile a media program without processing its inputs:

```powershell
shipmblang compile --file examples/ffmpeg-transcode.shipmb --memory off --no-english-model
```

The example converts `input.mp4` to `output.mp4`. Put the input beside the source
file, then opt into execution:

```powershell
shipmblang compile --file examples/ffmpeg-transcode.shipmb --run --ffmpeg-path C:/tools/ffmpeg/bin/ffmpeg.exe --ffprobe-path C:/tools/ffmpeg/bin/ffprobe.exe --ffmpeg-timeout 120 --memory off --no-english-model
```

`--run` on `compile` requires the direct pipeline. Relative media paths resolve
from the source file's directory. Existing outputs are protected unless the
program says `Overwrite outputs.` See [media programs](docs/ffmpeg.md).

`Probe "clip.mp4" and show the duration.` compiles to a program whose required
capability is `ffmpeg`. The shown duration is the probed `format.duration`
text. Compilation does not run ffprobe.

### HyperFrames video projects

```powershell
shipmblang hyperframes compile examples/hyperframes-title.shipmb --out output/title
```

This writes the project without a model, Node, or a render process. To produce
an MP4, install Node.js 22+, FFmpeg/ffprobe, and the pinned renderer
dependencies as described in the [HyperFrames guide](docs/hyperframes.md), then:

```powershell
shipmblang hyperframes render output/title --out output/title.mp4 --timeout 300
```

Compilation refuses an existing project directory. Rendering refuses an existing
output file.

## Broader English

Reviewed contextual wording also works offline: `Present the sum of 2 and 3.`,
`Could you add 2 and 3 together and tell me the result?`, and
`Compute the aggregate of 2 and 3.` each output `5`. See
[contextual vocabulary](docs/contextual-vocabulary.md).

```powershell
$env:SHIPMB_MODEL_PROVIDER = "openai_compatible"
$env:SHIPMB_MODEL_BASE_URL = "http://127.0.0.1:11434/v1"
$env:SHIPMB_MODEL_NAME = "your-installed-model"
shipmblang run "Add the odd numbers in 2, 5, 8, and 11 and show the total." --memory off
```

Use `--review-model-interpretation` to review a proposal, then supply the
intended English with `--interpretation`. Use `--no-english-model` for
deterministic-only compilation. The default pipeline is `direct` with the
`general` profile. Core output requires `--pipeline legacy`.

Python callers use `compile_direct_program(text)` or `run_direct_program(text)`.
Pass `model_provider=None` to disable translation.

## Multi-paragraph requests

Put the full request in one `.shipmb` file, separating paragraphs with blank
lines. Later paragraphs can refer to earlier values. Unsupported operations or
unresolved questions block execution of the entire program. See
[multi-paragraph programs](docs/multi-paragraph-programs.md).

```sh
shipmblang run --file program.shipmb --memory off
```

## Text apps and terminals

Run saved Notepad files or pipe copied program text from Google Keep and
NotebookLM through the same runtime. See [text-app workflows](docs/text-apps.md)
and the [Colab notebook](examples/text_apps_colab.ipynb). Stdin is:

```sh
shipmblang run --file - --pipeline direct --profile general --memory off --format text
```

## iOS and Android

The [mobile app](apps/mobile/README.md) provides executable sticky notes with
local saving and Run/Terminal controls. It connects to the authenticated
ShipMBLang service using the current pinned compiler snapshot. Optional media
import, conversion, composition, preview, and export are described in
[Notes media setup](docs/notes-media.md).

Image attachments in the notebook use `[[image:N]]` in document order. The
[MiniCPM-V guide](docs/minicpmv.md) documents the image provider. No fine-tuned
weights are included in this package.

## Compiler updates for maintainers

Compiler changes are developed in the compiler repository. Language changes are
developed here. Each language release bundles a selected compiler snapshot.
Package 0.6.0 does not replace that snapshot. See
[the bundle workflow](docs/bundled-compiler.md) and
[compiler sync](docs/compiler-sync.md).

## License

Copyright 2026 ZMachinery LLC (zmachinery).

Licensed under the [Apache License, Version 2.0](LICENSE).
ZMachinery LLC owns the original ShipMB / ShipMBLang code, compiler, runtime,
documentation, and other intellectual property it created or acquired.
Third-party materials remain the property of their respective owners.
This license grants usage rights without transferring ownership or granting
trademark rights except as expressly provided in the license. See [NOTICE](NOTICE).
