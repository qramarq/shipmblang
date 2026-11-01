# ShipMBLang for OpenIDEA

[OpenIDEA](https://github.com/l0ng-ai/openidea) plugin that associates
`.shipmb`, `.smb`, and `.shiplang` with the `shipmblang` language server.
The package is contribution-only: `plugin.toml` points at
`languages/shipmblang.toml`, and there is no plugin code to build.

OpenIDEA copies the manifest and the language file it references. This README
stays in the source tree for install instructions.

## Install from disk

1. Install ShipMBLang so `shipmblang` is on `PATH` (`pip install shipmblang`,
   `pip install -e .` from this repository, or the standalone executable).
2. In OpenIDEA, choose **Settings › Plugins › Install Plugin from Disk…**
   (or the **Install Plugin from Disk…** action).
3. Select the `extensions/openidea-shipmblang` folder.
4. Open a `.shipmb`, `.smb`, or `.shiplang` file.

The language id is `shipmblang`. Indentation is 2 spaces. Line comments are
`#`, which is the comment delimiter the compiler accepts.

## Install into one project

Symlink or copy this folder to `<project>/.openidea/plugins/shipmblang/` and
reopen the project. OpenIDEA lists that copy with a dev tag. **Reload Plugins**
picks up edits to `languages/shipmblang.toml`.

```sh
mkdir -p /path/to/project/.openidea/plugins
ln -s /path/to/shipmblang/extensions/openidea-shipmblang /path/to/project/.openidea/plugins/shipmblang
```

## Language server

The plugin starts `shipmblang lsp` on standard input and output. The workspace
root is the outermost directory inside the project that contains `.git`, or
the project directory when that marker is absent.

When `shipmblang` is not on `PATH`, OpenIDEA uses the fallback server
`python -X utf8 -m shipmblang lsp` if `python` is installed. Prefer the
`shipmblang` executable when you have one.

Other layouts:

- Standalone executable, or a console script, that is not named `shipmblang`
  on `PATH`: **Settings › Languages & Frameworks › Language Servers**, select
  **shipmblang**, and set the executable path. Leave the command arguments as
  `lsp`.
- The interpreter is `python3` rather than `python`: on that same page, add a
  language server with command `python3 -X utf8 -m shipmblang lsp` and
  language ShipMBLang. Turn off **shipmblang** and **shipmblang-python** so
  only one server runs.
- The plugin cannot be installed: add the same custom server for **Plain Text**,
  then under **Settings › Editor › File Types** add `*.shipmb`, `*.smb`, and
  `*.shiplang` to Plain Text. That server also attaches to other Plain Text
  files. Installing this plugin is the way to get a ShipMBLang file type.

`shipmblang lsp --check` prints `lsp ok` when the server can start.

The server publishes compiler diagnostics (clarification questions are
warnings), hover text for the bytecode operations on the current line, and
`workspace/executeCommand` commands `shipmblang.compile` and `shipmblang.run`.
It does not advertise completion, rename, formatting, or a debugger. The
server uses the Python standard library only.

## Highlighting

`ui-mode` is `Properties files`, a CodeMirror mode OpenIDEA already ships.
It colors `#` comments. It is not a ShipMBLang grammar.

Plugin manifests contribute languages, themes, and commands. They have no
TextMate entry, so
`extensions/vscode-shipmblang/syntaxes/shipmblang.tmLanguage.json`
(`scopeName` `source.shipmblang`) is not loaded. This repository does not
ship a tree-sitter grammar, and the language file does not set `tree-sitter`.
Diagnostics and hover still come from `shipmblang lsp`.
