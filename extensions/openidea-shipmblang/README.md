# ShipMBLang for OpenIDEA

Language definition for `.shipmb`, `.smb`, and `.shiplang` on
[OpenIDEA](https://github.com/l0ng-ai/openidea) 0.1.33. The folder is a
contribution plugin (`plugin.toml` plus `languages/shipmblang.toml`). It has
no WASM component.

On OpenIDEA 0.1.33, installing this plugin does not start `shipmblang lsp`.
The steps below copy the same language file into the directory the IDE
actually loads, then add a way to run a program. A draft of the OpenIDEA
change that would make the plugin sufficient is in
[`upstream/`](upstream/README.md).

## Why the plugin list is not enough

OpenIDEA shows this package as an enabled plugin and lists the three
extensions. That list comes from the plugin host. The process that opens a
file uses a different registry: built-in languages, plus every `*.toml` file
in the user languages directory, loaded once at startup
(`LanguageRegistry::load` in `crates/ide-language`). Plugin languages are
added only to the `languages` IPC reply that fills Settings. They are not
inserted into the registry that detects the file and starts language servers
(`LspManager` in `crates/ide-lsp`, built from the project fork of that
registry).

A `.shipmb` file is therefore Plain Text. Plain Text has no language server,
so no `shipmblang` process starts and the log has no line about one. The
spell checker still marks words. Hover stays empty. A `tree-sitter` key is
not what is missing: OpenIDEA's `languages/dockerfile.toml` defines a
language server and has no `tree-sitter` entry. Trust is a separate gate
(below). It was not the reason a listed dev plugin produced no server: an
enabled dev plugin means the project was already trusted, and trusted
projects still do not launch servers for plugin-only languages.

Checked with the `openidea-server` 0.1.33 binary (`--stdio`, protocol 2),
which loads the same registry and does not load plugins:

- With no user language file, opening `program.shipmb` in a trusted project
  reported language `plaintext` and `lsp_servers` was empty. No `shipmblang`
  process existed.
- After copying `languages/shipmblang.toml` into that server's
  `config/languages/` and restarting, the same open reported language
  `shipmblang`. The server status became `ready`, the process was
  `python3 -m shipmblang lsp` (a `shipmblang` wrapper on `PATH`), and hover
  on the example line returned the bytecode (`const 4`, `binary add`,
  `show`, …). A file whose first line was `// not a comment` published one
  `shipmblang` diagnostic (`SMBG100`).
- The same language file in an untrusted project still reported
  `shipmblang` and started no server (`lsp_servers` empty).
- A `shipmblang` executable that exits on `lsp`, placed ahead of a working
  one, left the server `crashed`. The `python` fallback did not start.

The desktop app was not clicked. Its document open and language-server
startup go through this same backend.

## Check the executable before installing

`shipmblang lsp --check` must print `lsp ok` for the executable OpenIDEA
will launch. On Windows, run that in the same environment the IDE sees
(the user and system `PATH` of a program started from the shell or Start
menu, not only a terminal you opened later). Restart OpenIDEA after
changing `PATH`. Windows builds do not re-read a login shell; macOS and
Linux builds take `PATH` from the login shell and may use a cached value
until the next launch.

```text
where.exe shipmblang
shipmblang lsp --check
```

`where.exe` lists every match. OpenIDEA runs the first one it finds. An
older `shipmblang.exe` that has no `lsp` subcommand is still "found", so
the IDE starts it, the process exits, and the `python` fallback does not
run. Remove that older file from `PATH`, or put the current executable
ahead of it, until `shipmblang lsp --check` prints `lsp ok` for the first
hit. Then restart OpenIDEA.

If `shipmblang` is not installed and `python` is, the language file's
fallback server is `python -X utf8 -m shipmblang lsp`. On a machine where
the interpreter is `python3`, add that command under
**Settings › Languages & Frameworks › Language Servers** for ShipMBLang
and turn off **shipmblang** and **shipmblang-python**.

## Install the language file (OpenIDEA 0.1.33)

Copy `languages/shipmblang.toml` into the user languages directory and
restart OpenIDEA. This is not the log folder.

| System | Directory |
| --- | --- |
| Windows | `%APPDATA%\ai.l0ng.openidea\languages` |
| Linux | `$XDG_CONFIG_HOME/ai.l0ng.openidea/languages` or `~/.config/ai.l0ng.openidea/languages` |
| macOS | `~/Library/Application Support/ai.l0ng.openidea/languages` |

Logs stay under `%LOCALAPPDATA%\ai.l0ng.openidea\logs` on Windows (and the
matching local data directory elsewhere). A debug build from a worktree
uses the identifier `ai.l0ng.openidea.dev.w` plus a hash of that worktree,
not `ai.l0ng.openidea`. The release whose log path is
`%LOCALAPPDATA%\ai.l0ng.openidea\logs` uses the table above.

Windows:

```powershell
$dir = Join-Path $env:APPDATA "ai.l0ng.openidea\languages"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
Copy-Item languages\shipmblang.toml (Join-Path $dir "shipmblang.toml")
```

Linux and macOS, from this folder:

```sh
dir="${XDG_CONFIG_HOME:-$HOME/.config}/ai.l0ng.openidea/languages"
# macOS: dir="$HOME/Library/Application Support/ai.l0ng.openidea/languages"
mkdir -p "$dir"
cp languages/shipmblang.toml "$dir/shipmblang.toml"
```

Restart OpenIDEA. The registry reads that directory only at startup.

The plugin can still be installed (**Settings › Plugins › Install Plugin
from Disk…**, or a symlink at
`<project>/.openidea/plugins/shipmblang/`). On 0.1.33 it does not start
the server. If both the copy and the plugin define `shipmblang`, the copy
wins, including after the upstream patch. Delete the copy when you no
longer want it to shadow the plugin file.

If the window says the project is in Restricted Mode, trust the project.
Restricted Mode loads no dev plugins and starts no language servers.

Open a `.shipmb` file. The editor language is ShipMBLang. A `shipmblang`
process is running. Hover shows the bytecode for that line. A `//` line
is a compiler diagnostic. `#` is the comment the compiler accepts.
Indentation is 2 spaces. Highlighting uses the bundled CodeMirror mode
`Properties files`, which colors `#` comments. There is no tree-sitter
grammar in this repository, and the language file does not set
`tree-sitter`.

File icons stay the unknown-file icon. OpenIDEA picks icons from a fixed
extension map in the UI (`file-unknown` for an extension it does not
list). Plugin manifests cannot contribute an icon.

## Run a program

The Run button's Current File action only knows the languages hard-coded
in OpenIDEA's run producers. `.shipmb` is not one of them, so Current File
reports that the active file has no runnable element. `wit/plugin.wit`
gives a plugin log, notifications, editor text, and language registration.
It cannot start a process, so this package does not add a Run command.

Two ways do run `shipmblang` and show the output in the Run tool window.

**Active file.** Settings › Tools › External Tools. Add a tool:

- Name: `Run ShipMBLang`
- Program: `shipmblang` (or the full path of the executable that passes
  `lsp --check`)
- Arguments: `run --file $FilePath$ --pipeline direct --profile general --memory off`
- Working directory: `$ProjectFileDir$`

Save the file first. Run the tool from Find Action (`Run ShipMBLang`).
The arguments are one command line; `$FilePath$` is the focused file.
Output opens in the Run tool window. This tool is an IDE setting. It is
not stored in the plugin.

**A chosen file, from the Run button.** In the project,
`.openidea/run.toml`:

```toml
[[configurations]]
id = "user:shipmblang-run"
name = "Run ShipMBLang"
kind = "shell"
command = "shipmblang"
args = ["run", "--file", "program.shipmb", "--pipeline", "direct", "--profile", "general", "--memory", "off"]
```

Replace `program.shipmb` with the path relative to the project. Restart
or reopen the project, choose **Run ShipMBLang** in the run widget, and
press Run. The configuration does not follow whichever file is focused.
`openidea-server` 0.1.33, project trusted, listed this configuration from
`run_configs` and `run_start` launched it. The same command's JSON
`runtime.stdout` for `examples/quoted_paragraph.shipmb` is `12`.

`shipmblang compile --file <file> --pipeline direct --profile general --run`
is the compile command with execution. `run --file` is the same pipeline
and profile without asking `compile` to execute. Both need the direct
pipeline when the program should run.

## Language server, once it is running

Diagnostics come from the bundled compiler. Clarification questions are
warnings. Hover is the bytecode for the current line. The server also
answers `workspace/executeCommand` for `shipmblang.compile` and
`shipmblang.run`. OpenIDEA calls that only as a follow-up to a completion
item, and it does not show the command's JSON in the Run tool window.
Use the external tool or the run configuration to see output.

The server does not advertise completion, rename, formatting, or a
debugger. It uses the Python standard library only.
`extensions/vscode-shipmblang/syntaxes/shipmblang.tmLanguage.json` is not
loaded: plugin manifests have no TextMate entry.
