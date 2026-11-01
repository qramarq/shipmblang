# ShipMBLang in any editor

Two interfaces work from a source install and from the standalone executable:

- `shipmblang lsp` speaks Language Server Protocol on standard input and output.
- `shipmblang compile` and `shipmblang run` stay the stable JSON command line,
  including programs piped on stdin.

`.shipmb` and `.smb` are the file extensions to associate. The VS Code extension
also accepts `.shiplang`. Its TextMate grammar lives at
`extensions/vscode-shipmblang/syntaxes/shipmblang.tmLanguage.json`
(`scopeName` `source.shipmblang`) and can be reused by editors that load a
TextMate grammar. OpenIDEA 0.1.33 uses that same language file only after
it is copied into the IDE's user languages directory. The plugin folder
alone does not start the language server. See [OpenIDEA](#openidea).

There is no document formatter in ShipMBLang. The language server does not
advertise formatting.

## Version, stdin, and exit codes

```text
shipmblang --version
shipmblang lsp --check
```

`--version` prints `shipmblang` and the package version. `lsp --check` prints
`lsp ok` without reading a document.

Pipe a buffer when the editor has not saved the file. `--file -` reads the
program from standard input:

```text
shipmblang compile --file - --pipeline direct --profile general --format json --memory off
shipmblang run --file - --pipeline direct --profile general --memory off
```

Exit 0 means success. Exit 1 reports a failed, unsupported, or clarification
result, or a runtime diagnostic. Exit 2 reports invocation and setup errors on
the direct path. JSON diagnostics keep source spans in Unicode code points.
The language server converts those spans to UTF-16 positions. General run JSON
includes `runtime.stdout` and `runtime.output`. See
[terminals and IDEs](terminal-and-ides.md) for the rest of the command contract.

Replace `shipmblang` below with the full path of the standalone executable when
that file is not on `PATH`. A source install uses the same arguments after
`python -m shipmblang`, with `-X utf8` when the terminal is not UTF-8:

```text
python -X utf8 -m shipmblang lsp
```

## What the language server provides

- Diagnostics from the bundled compiler, published as the document changes.
  Clarification questions are warnings.
- Hover text for the bytecode operations that cover the current line.
- `workspace/executeCommand` commands `shipmblang.compile` and
  `shipmblang.run`. Pass the open document URI, the raw program text, or
  `{"text": "...", "uri": "file:///..."}`. The result includes `status`,
  `exitCode`, `stdout`, `output`, `diagnostics`, and `clarifications`.

The server uses only the Python standard library.

## VS Code and Cursor

Open `extensions/vscode-shipmblang` and press F5, or install the folder as an
extension. File associations and the TextMate grammar are already registered.

Set `shipmblang.executablePath` to the standalone executable when you do not
want the extension to launch Python. When that setting is empty, the extension
uses `shipmblang` on `PATH` if it finds one, and otherwise
`shipmblang.pythonPath`. `shipmblang.lsp` defaults to on and starts
`shipmblang lsp` for diagnostics and hover. Compile, Run, Clarify and Run, and
the printurf explanation commands keep working either way.

```json
{
  "shipmblang.executablePath": "/absolute/path/to/shipmblang",
  "shipmblang.lsp": true,
  "shipmblang.pipeline": "direct",
  "shipmblang.profile": "general",
  "shipmblang.memory": false
}
```

Cursor reads the same settings. Details are in the
[extension README](../extensions/vscode-shipmblang/README.md).

## Neovim

With [nvim-lspconfig](https://github.com/neovim/nvim-lspconfig):

```lua
vim.filetype.add({
  extension = { shipmb = "shipmblang", smb = "shipmblang", shiplang = "shipmblang" },
})
local configs = require("lspconfig.configs")
local util = require("lspconfig.util")
if not configs.shipmblang then
  configs.shipmblang = {
    default_config = {
      cmd = { "shipmblang", "lsp" },
      filetypes = { "shipmblang" },
      root_dir = util.find_git_ancestor,
      single_file_support = true,
    },
  }
end
require("lspconfig").shipmblang.setup({})
vim.api.nvim_create_user_command("ShipmbRun", function()
  vim.lsp.buf.execute_command({
    command = "shipmblang.run",
    arguments = { vim.uri_from_bufnr(0) },
  })
end, {})
```

Point `cmd` at the standalone executable if it is not named `shipmblang` on
`PATH`.

## Vim

Vim 8 can speak to a stdio language server through a client such as
[vim-lsp](https://github.com/prabirshrestha/vim-lsp). Register the executable
and the file types:

```vim
autocmd BufNewFile,BufRead *.shipmb,*.smb,*.shiplang setfiletype shipmblang
if executable('shipmblang')
  autocmd User lsp_setup call lsp#register_server({
    \ 'name': 'shipmblang',
    \ 'cmd': {server_info -> ['shipmblang', 'lsp']},
    \ 'allowlist': ['shipmblang'],
    \ })
endif
```

Without a language-client plugin, a buffer can still be piped to the CLI:

```vim
command! ShipmbRun execute '%write !shipmblang run --file - --pipeline direct --profile general --memory off'
```

## Emacs

[Eglot](https://www.gnu.org/software/emacs/manual/html_mono/eglot.html) is
built into Emacs 29:

```elisp
(add-to-list 'auto-mode-alist '("\\.\\(shipmb\\|smb\\|shiplang\\)\\'" . text-mode))
(with-eval-after-load 'eglot
  (add-to-list 'eglot-server-programs
               '((text-mode) . ("shipmblang" "lsp"))))
```

Use a dedicated major mode instead of `text-mode` if you already have one, and
put that mode in `eglot-server-programs`. `M-x eglot` starts the server.

## Helix

`~/.config/helix/languages.toml`:

```toml
[[language]]
name = "shipmblang"
scope = "source.shipmblang"
file-types = ["shipmb", "smb", "shiplang"]
roots = []
indent = { tab-width = 2, unit = "  " }
language-servers = ["shipmblang"]

[language-server.shipmblang]
command = "shipmblang"
args = ["lsp"]
```

The grammar file in this repository can be dropped into a Helix grammar
checkout if you want highlighting beyond the language server.

## Zed

In Zed settings:

```json
{
  "languages": {
    "ShipMBLang": {
      "language_servers": ["shipmblang"]
    }
  },
  "lsp": {
    "shipmblang": {
      "command": "shipmblang",
      "args": ["lsp"]
    }
  },
  "file_types": {
    "ShipMBLang": ["shipmb", "smb", "shiplang"]
  }
}
```

If Zed does not load that grammar automatically, add
`syntaxes/shipmblang.tmLanguage.json` as a language extension and keep the
`source.shipmblang` scope.

## Sublime Text

Install the [LSP package](https://packagecontrol.io/packages/LSP), then add
this to LSP's user settings:

```json
{
  "clients": {
    "shipmblang": {
      "enabled": true,
      "command": ["shipmblang", "lsp"],
      "selector": "source.shipmblang"
    }
  }
}
```

Associate the extensions and the TextMate grammar with
`Preferences > Browse Packages` by copying
`extensions/vscode-shipmblang/syntaxes/shipmblang.tmLanguage.json` into a
`ShipMBLang` package, and add:

```json
{
  "extensions": ["shipmb", "smb", "shiplang"]
}
```

to that package's `ShipMBLang.sublime-settings` if the grammar does not already
name them.

## JetBrains IDEs

Install [LSP4IJ](https://plugins.jetbrains.com/plugin/23257-lsp4ij). Add a
user-defined language server:

- Command: `shipmblang`
- Arguments: `lsp`
- Filename patterns: `*.shipmb`, `*.smb`, `*.shiplang`

For a one-shot compile without LSP4IJ, add an External Tool:

- Program: `shipmblang`
- Arguments: `run --file $FilePath$ --pipeline direct --profile general --memory off --plain`
- Working directory: `$ProjectFileDir$`

Use `compile` instead of `run` for a compile-only tool. Save the file first.

## Notepad++

Associate `.shipmb` and `.smb` with whatever highlighting you prefer. Under
`Run > Run...`:

```text
shipmblang run --file "$(FULL_CURRENT_PATH)" --pipeline direct --profile general --memory off
```

Save the file before running. To send the unsaved buffer, a plugin that can
pipe the current text can call:

```text
shipmblang run --file - --pipeline direct --profile general --memory off
```

## Kate

In `Settings > Configure Kate > LSP Client > User Server Settings`:

```json
{
  "servers": {
    "shipmblang": {
      "command": ["shipmblang", "lsp"],
      "url": "https://github.com/qramarq/shipmblang",
      "highlightingModeRegex": "^ShipMBLang$"
    }
  }
}
```

In the file-type configuration, map `*.shipmb`, `*.smb`, and `*.shiplang` to a
mode named `ShipMBLang`. Kate can also run an external tool with
`shipmblang compile --file %{Document:FileName} --pipeline direct --profile general --format json --memory off`.

## OpenIDEA

OpenIDEA 0.1.33 lists the plugin in
[`extensions/openidea-shipmblang`](../extensions/openidea-shipmblang/README.md)
and does not start `shipmblang lsp` from that listing. Document detection
and language-server startup read built-in languages plus
`<config>/languages/*.toml`, loaded at startup. Plugin languages are not
in that registry, so a `.shipmb` file stays Plain Text: no `shipmblang`
process, no hover, and only the spell checker. A `tree-sitter` key is not
required for a language server (OpenIDEA's Dockerfile language has a
server and no `tree-sitter` entry). Full steps, the stale-`PATH`
executable, and a draft upstream patch are in the plugin README.

1. `shipmblang lsp --check` prints `lsp ok` for the first `shipmblang` on
   the `PATH` OpenIDEA will see. On Windows, `where.exe shipmblang` shows
   every match. An older `shipmblang.exe` without `lsp` is still launched,
   then exits, and the `python` fallback does not run. Restart OpenIDEA
   after changing `PATH`.
2. Copy `extensions/openidea-shipmblang/languages/shipmblang.toml` to the
   user languages directory and restart. This is not the log folder.
   - Windows: `%APPDATA%\ai.l0ng.openidea\languages\shipmblang.toml`
   - Linux: `~/.config/ai.l0ng.openidea/languages/shipmblang.toml`
     (`$XDG_CONFIG_HOME` when that is set)
   - macOS: `~/Library/Application Support/ai.l0ng.openidea/languages/shipmblang.toml`
3. Trust the project when OpenIDEA shows Restricted Mode. An untrusted
   project detects the language and starts no server.

Open a `.shipmb` file. Hover and compiler diagnostics come from
`shipmblang lsp`. `#` is the line comment. Indentation is 2 spaces.
Highlighting borrows the CodeMirror mode `Properties files`. The file
icon stays the unknown-file icon; the UI icon map has no plugin entry.

To run the focused file, add an External Tool (**Settings › Tools ›
External Tools**): program `shipmblang`, arguments
`run --file $FilePath$ --pipeline direct --profile general --memory off --plain`,
working directory `$ProjectFileDir$`. Output is in the Run tool window: the
program text on standard output, and failures as `file:line:col: message` on
standard error. Without `--plain` the result is verbose JSON.
The Run button's Current File action has no `.shipmb` producer. A fixed
file can be a shell configuration in `.openidea/run.toml`:

```toml
[[configurations]]
id = "user:shipmblang-run"
name = "Run ShipMBLang"
kind = "shell"
command = "shipmblang"
args = ["run", "--file", "program.shipmb", "--pipeline", "direct", "--profile", "general", "--memory", "off", "--plain"]
```

Choose that configuration in the run widget. It does not follow the
active file. The plugin API cannot start a process, so the package does
not add a Run command.

If `shipmblang` is missing and `python` exists, the language file's
fallback is `python -X utf8 -m shipmblang lsp`. For `python3`, add that
command on the Language Servers page and turn the other ShipMBLang
servers off. A custom server attached to Plain Text also runs on other
Plain Text files; the user language file is what creates the ShipMBLang
file type on 0.1.33.

## Terminal fallback

Any editor that can only start a process should use the commands in
[terminals and IDEs](terminal-and-ides.md). Pass the saved path as one
`--file` argument, or pipe the buffer with `--file -`.
