# ShipMBLang printurf editor integrations

printurf has two integration layers:

1. `python -m shipmblang mcp` exposes `printurf` as a local MCP server.
2. `extensions/vscode-shipmblang` makes `printurf` editor-native in VS Code.
3. `.shiplang` and `.shipmb` files can contain natural ShipMBLang programs.

The editor contract is always:

```text
Error: [Simple Explanation]. Cause: [Specific Reason]. Fix: [Solution].
```

## VS Code extension

Open `extensions/vscode-shipmblang` in VS Code and press `F5` to launch an Extension
Development Host.

The extension contributes:

- CodeLens above diagnostics: `ShipMBLang: explain`
- Quick Fix: `Explain with ShipMBLang`
- Diagnostic hover link
- Command palette actions:
  - `ShipMBLang: Explain Current Diagnostic`
  - `ShipMBLang: Explain Pasted Error`
  - `ShipMBLang: Compile Natural Program`
  - `ShipMBLang: Run Natural Program`

For natural programs, type ordinary language in a `.shiplang` or `.shipmb` file,
select the paragraph you want to compile or run, and use the command palette. If
nothing is selected, the extension sends the whole document.

Example:

```text
Use ShipMB. Open the current project and scan the codebase. When an error
happens, explain it with printurf, suggest a fix, and show the report.
```

The compile command returns ShipMBLangCore. The run command sends the same text
through `python -m shipmblang run` and shows the local runtime output. The natural
program pipeline is:

```text
natural language syntax -> ShipMBLangCore -> ShipMBLang bytecode -> runtime/machine execution
```

In v0.1, the concrete machine target is ShipMBLang bytecode. Native CPU code can
come later. See [`shipmblang.md`](shipmblang.md) for the full workflow.

For editor previews, declaration/name resolution is order-insensitive within the
selected compilation unit. The compiler collects declarations first, so a call,
method, property, or return expression can resolve to a declaration written later
in the file. The extension still sends the original text to the CLI, and runtime
actions execute in final bytecode order.

Configuration:

```json
{
  "shipmblang.pythonPath": "C:/path/to/shipmblang/.venv/Scripts/python.exe",
  "shipmblang.projectRoot": "C:/path/to/shipmblang",
  "shipmblang.checkpoint": "checkpoints/best_model.pt",
  "shipmblang.tokenizer": "data/tokenizer.json",
  "shipmblang.device": "cpu"
}
```

## MCP configuration

For IDEs or AI clients that support MCP, add a local stdio server config like:

```json
{
  "servers": {
    "shipmblang": {
      "command": "C:/path/to/shipmblang/.venv/Scripts/python.exe",
      "args": ["-m", "shipmblang", "mcp"],
      "env": {
        "SHIPLANG_CHECKPOINT": "checkpoints/best_model.pt",
        "SHIPLANG_TOKENIZER": "data/tokenizer.json",
        "SHIPLANG_DEVICE": "cpu"
      }
    }
  }
}
```

The MCP server exposes:

- `printurf(raw_error?, code_context?, paths?, root_path?, file_path?, line?, format?)`
- `shipmblang_explain_error(raw_error?, code_context?, paths?, root_path?, file_path?, line?, format?)`
- `shipmblang_index_codebase(root_path, max_files?)`
- `shipmblang_list_device_families(family?, format?)`
- `shipmblang_select_device_family(family, format?)`
- `shipmblang_get_device_resource(family?, resource, format?)`

`shiplang_*` and `drip_*` tools are kept as compatibility aliases. New clients
should call `printurf` and `shipmblang_index_codebase`.

Recommended client flow:

```json
{
  "name": "shipmblang_index_codebase",
  "arguments": {
    "root_path": "C:/path/to/project",
    "max_files": 80
  }
}
```

Then call `printurf` with an error plus either explicit context or files to
inspect:

```json
{
  "name": "printurf",
  "arguments": {
    "raw_error": "NameError: name 'total' is not defined",
    "paths": ["src/app.py"],
    "root_path": "C:/path/to/project",
    "format": "json"
  }
}
```

The JSON response includes `diagnostics[]` with `error`, `file`, `line`,
`context`, `cause`, `suggestion`, and the one-line `explanation`, plus a
`project` index with source files, languages, imports, and top-level symbols.

Device-family resources are available through MCP too. The active family starts
as `host`; clients can select another family and then read family or resource
descriptions:

```json
{
  "name": "shipmblang_select_device_family",
  "arguments": {
    "family": "embedded"
  }
}
```

Resource URIs include:

- `shipmblang://device-families`
- `shipmblang://active-device`
- `shipmblang://device-family/<family>`
- `shipmblang://device-family/<family>/resource/<resource>`

The current built-in families are `host`, `cuda`, `mps`, `browser`, and
`embedded`.

## Standalone MCP smoke test

Run this from the ShipMBLang repo root:

```bash
python tools/smoke_mcp.py --python .venv/Scripts/python.exe --cwd .
```

The smoke test launches `python -m shipmblang mcp`, performs MCP initialization,
sends the `notifications/initialized` notification, lists tools, calls
`printurf`, and validates that the response is a strict
`Error: ... Cause: ... Fix: ...` paragraph.

The VS Code extension does not require MCP to function; it calls the local
`python -m shipmblang printurf`, `python -m shipmblang compile`, and
`python -m shipmblang run` commands directly for lower latency and simpler setup.
