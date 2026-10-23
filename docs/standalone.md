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

`shipmblang editor` and `shipmblang notebook` open the Ratatui editor. In a
build made with `--require-editor`, the editor binary is inside the executable
and Cargo is not used. The editor calls back into the same executable for notes
and compilation. A build without that binary still asks for Rust and Cargo, as
a source install does on first launch. If Cargo is missing, the message tells
you to run `shipmblang setup`. The executable does not install anything by itself.

## Install Rust, FFmpeg, VLC, and Ollama

These tools are not inside the executable. Ollama is large, and this repository
is Apache-2.0, so it does not redistribute FFmpeg or VLC builds. `shipmblang setup`
installs whatever is missing from the official source for your system. The same
command works in the standalone executable and in `pip install shipmblang`.

The artifact from the standalone workflow includes the executable and a one-step
installer. The installer copies the executable onto your user PATH and then runs
`shipmblang setup`:

```sh
./install.sh
```

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

Pass setup flags through the installer, for example `./install.sh --yes --skip ollama`.
You can also copy the executable yourself and run `shipmblang setup`.

### What setup does

It looks for each tool on `PATH`, in the usual install directories, and in
`SHIPMB_FFMPEG_PATH`, `SHIPMB_FFPROBE_PATH`, and `SHIPMB_VLC_DIR` when those
variables already name a file or directory. It installs only the missing ones,
then writes the discovered paths to `tools.json` in the ShipMBLang data directory
(`%LOCALAPPDATA%\ShipMBLang` on Windows, `$XDG_DATA_HOME/ShipMBLang` or
`~/.local/share/ShipMBLang` otherwise). Later `compile` and `run` commands use
those paths when you do not pass a flag, the matching variable is unset, and the
tool is not already on `PATH`. A flag still wins, then an existing variable, then
`PATH`, then the recorded path.

| Flag | Effect |
| --- | --- |
| *(none)* | Show what will be installed and ask once. Enter accepts. |
| `--yes` | Install without asking. Does not download an Ollama model. |
| `--check` | Report each component and exit nonzero if one is missing. |
| `--dry-run` | Print the commands and do not run them. |
| `--only rust,ffmpeg` | Set up only these components. |
| `--skip ollama` | Leave these components untouched. |
| `--pull-models --model NAME` | After Ollama is available, run `ollama pull NAME`. |

Names are `rust`, `ffmpeg` (this includes ffprobe), `vlc`, and `ollama`.
`shipmblang setup --yes --pull-models` without `--model` does not download a
model. This repository does not define a default Ollama model. The interactive
setup can ask for a name; pressing Enter skips the download. MiniCPM-V and the
other documented model examples use an OpenAI-compatible endpoint, not an
`ollama pull` tag.

When a compile, run, or editor command needs a tool that is not installed, it
prints the original error and tells you to run `shipmblang setup`. It does not
start an installer.

### Linux

FFmpeg and VLC come from the distro, which also installs LibVLC:

- Debian and Ubuntu: `sudo apt-get install ffmpeg` and `sudo apt-get install vlc`
- Fedora and RHEL: `sudo dnf install ffmpeg` and `sudo dnf install vlc` (FFmpeg often needs [RPM Fusion](https://rpmfusion.org/) first)
- Arch: `sudo pacman -S ffmpeg` and `sudo pacman -S vlc`

Other distributions get a short manual instruction instead of a guessed package
command. Rust comes from the official rustup script,
<https://sh.rustup.rs>, with the minimal profile. Ollama comes from
<https://ollama.com/install.sh>. Setup then starts `ollama serve` if
<http://127.0.0.1:11434/api/version> is not already answering. Package installs
need `sudo` or a root shell. `--yes` uses `sudo --non-interactive` so a missing
password fails instead of waiting.

### macOS

Rust uses the same rustup script. FFmpeg is `brew install ffmpeg`. VLC is
`brew install --cask vlc`. Ollama uses <https://ollama.com/install.sh>, then the
local service is started if it is not already up. Install Homebrew from
<https://brew.sh> first. Setup does not install Homebrew. If `brew` is missing,
FFmpeg and VLC are reported with that link, and Rust and Ollama can still be
installed.

### Windows

Setup uses winget when it is on `PATH`:

- `Rustlang.Rustup`
- `Gyan.FFmpeg.Essentials` (includes ffprobe)
- `VideoLAN.VLC`
- `Ollama.Ollama`

If winget is missing or that install still leaves the tool undiscovered, setup
downloads the official fallback: `rustup-init.exe` from <https://win.rustup.rs>,
the LGPL FFmpeg essentials zip
`ffmpeg-master-latest-win64-lgpl.zip` from
[BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds/releases/latest),
the current VLC 3.x zip (or, if no zip is listed, the installer) from
<https://download.videolan.org/pub/videolan/vlc/last/>, and
`OllamaSetup.exe` from <https://ollama.com/download/OllamaSetup.exe>.
The zip is extracted for the current user. The VLC installer and the Ollama
installer may need an administrator account. A 32-bit VLC
is not used by a 64-bit ShipMBLang executable, and VLC 4 is not accepted.
LibVLC 3.x is `libvlc.dll` on Windows, `libvlc.so.5` on Linux, and
`libvlc.dylib` in the VLC 3 app on macOS.

### Licenses

ShipMBLang does not ship these programs. Installing them is your request to the
upstream project or your distro:

- **Rust** — rustup and the toolchain. Rust is dual-licensed MIT and Apache-2.0.
- **FFmpeg** — the distro package, the Homebrew formula, or on Windows the winget
  package `Gyan.FFmpeg.Essentials` (GPL-3.0) with the BtbN LGPL zip as the
  fallback. FFmpeg itself is LGPL-2.1 or later unless a build enables GPL
  components. Some distro and Homebrew builds do. The fallback Windows zip is
  the BtbN LGPL essentials build.
- **VLC** — the application is GPL-2.0. libVLC is LGPL-2.1.
- **Ollama** — the MIT-licensed installer from ollama.com.

### Rust is optional at runtime

`shipmblang editor` in a build made with `--require-editor` runs the packed
Ratatui binary and does not call Cargo. Setup still installs Rust because a
source checkout builds that editor, and the native editor sources, with Cargo.
Skip it with `shipmblang setup --skip rust`.

### Skipping components

```sh
shipmblang setup --only ffmpeg,vlc
shipmblang setup --skip ollama
shipmblang setup --check
shipmblang setup --dry-run
```

## What is not inside the executable

- **Local model extras.** PyTorch, tokenizers, and the training stack are not
  packed. `train`, `prepare`, `chat`, `download`, and
  `SHIPMB_MODEL_PROVIDER=drip` exit with a message that names
  `pip install "shipmblang[model]"`. Direct compilation does not need them.
  `SHIPMB_MODEL_PROVIDER=openai_compatible` still talks to an endpoint you
  configure; no extra Python packages are required for that HTTP client.
- **The private C++ compiler.** `docs/native.md` is unchanged. Nothing in this
  build downloads or replaces `shipmbc_cpp`.
- **External media tools are not packed.** FFmpeg, ffprobe, LibVLC, and Ollama
  stay outside the file. `shipmblang setup` installs them from the sources in
  the section above. Node.js is still separate. HyperFrames compilation writes
  a project with no Node process; rendering still needs Node.
- **The Tk sticky-note window.** `notebook` and `editor` open the terminal
  editor. The older Tk notes window is not packed.

Linux builds expect a glibc new enough for the Ubuntu runner that produced the
artifact. The executable does not look up a system Python.
