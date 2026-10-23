# Standalone executable

ShipMBLang can run as one executable, with no Python installation on the machine
that uses it. The executable is the public Python package packed with
[PyInstaller](https://pyinstaller.org/), including the bundled compiler snapshot,
HyperFrames vendor files, note starters, and editor sources. It is not the
private native C++ compiler. That compiler stays out of this repository; see
[the native launcher](native.md) if you already have it.

PyInstaller is used instead of compiling the package to C. The language loads
compiler modules on demand and reads package data from the installed tree.
Packing that tree keeps the same import and file layout the Python CLI uses.

## Download

The [Standalone executable workflow](https://github.com/qramarq/shipmblang/actions/workflows/standalone.yml)
builds `shipmblang` on Linux and macOS and `shipmblang.exe` on Windows, smoke-tests
each binary, and uploads it as an Actions artifact. Those artifacts are not a
GitHub Release. Each file matches the operating system and CPU of the runner
that built it (`ubuntu-latest` and `windows-latest` are x64; `macos-latest` is
Apple Silicon).

On macOS, if Gatekeeper refuses the downloaded file, clear the quarantine flag
from the executable you saved: `xattr -d com.apple.quarantine shipmblang`.

## Build

Install Python 3.11+ only on the build machine, plus a current stable Rust
toolchain from [rustup](https://rustup.rs) when you want the editor packed in.
The locked editor crates use Rust edition 2024. From the repository root:

```sh
python -m pip install pyinstaller
python tools/build_standalone.py --require-editor
```

```powershell
python -m pip install pyinstaller
powershell -ExecutionPolicy Bypass -File tools\build_standalone.ps1 --require-editor
```

`tools/build_standalone.sh` is the same entry on Linux and macOS. The result is
`dist/shipmblang` or `dist/shipmblang.exe`. `--require-editor` fails the build
if Cargo cannot produce the Ratatui binary. Omit it and the script still builds
the executable, then warns that `shipmblang editor` will need Cargo at launch.
`--skip-editor` never tries to compile the editor.

## Use

The executable accepts the same commands as `python -m shipmblang`:

```sh
./dist/shipmblang run --file examples/quoted_paragraph.shipmb --pipeline direct --profile general --memory off
./dist/shipmblang --help
./dist/shipmblang examples/quoted_paragraph.shipmb
```

The last form runs a `.shipmb` file with the direct pipeline, the general
profile, and memory off. Flags after the filename override those defaults, for
example `shipmblang program.shipmb --format text`. The same shorthand works in
the installed Python console script. `compile`, `run`, `editor`, `notebook`,
`hyperframes`, and the older commands keep their previous parsing.

`shipmblang editor` and `shipmblang notebook` open the Ratatui chat-room
notebook. In a build made with `--require-editor`, the editor binary is inside
the executable and Cargo is not used. The editor calls back into the same
executable for notes and compilation. A build without that binary still asks
for Rust and Cargo, as a source install does on first launch.

```sh
./dist/shipmblang --version
./dist/shipmblang editor --version
./dist/shipmblang editor --smoke --demo
./dist/shipmblang lsp --check
```

`--smoke` prints `shipmblang editor smoke ok` and one frame, then exits. The
same executable is the language server (`shipmblang lsp`) and the compile/run
fallback for other editors. See [editors](editors.md).

## What is not inside the executable

- **Local model extras.** PyTorch, tokenizers, and the training stack are not
  packed. `train`, `prepare`, `chat`, `download`, and
  `SHIPMB_MODEL_PROVIDER=drip` exit with a message that names
  `pip install "shipmblang[model]"`. Direct compilation does not need them.
  `SHIPMB_MODEL_PROVIDER=openai_compatible` still talks to an endpoint you
  configure; no extra Python packages are required for that HTTP client.
- **The private C++ compiler.** `docs/native.md` is unchanged. Nothing in this
  build downloads or replaces `shipmbc_cpp`.
- **External media tools.** FFmpeg, ffprobe, LibVLC, and Node.js are still
  installed separately when a program actually uses them. HyperFrames
  compilation writes a project with no Node process; rendering still needs Node.
- **The Tk sticky-note window.** `notebook` and `editor` open the terminal
  editor. The older Tk notes window is not packed.

Linux builds expect a glibc new enough for the Ubuntu runner that produced the
artifact. The executable does not look up a system Python.
