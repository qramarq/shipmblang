# ShipMBLang for VS Code

Compile/run `.shipmb`, `.shiplang`, and `.smb` prose from the active editor, including unsaved text or a selection. Compiler errors and clarification questions appear in Problems. General programs print captured output in the ShipMBLang output channel. Existing printurf explanations and command aliases remain available.

## Setup

1. Install ShipMBLang and the optional shipmbcompiler package into the same Python environment. Direct compilation requires Python 3.11+ and shipmbcompiler >=0.2.3,<0.3. For local private checkouts, install the compiler checkout first, then the language checkout with `python -m pip install -e .` in each package root.
2. Install the local VSIX through **Extensions: Install from VSIX**, or launch this folder with an Extension Development Host.
3. Set `shipmblang.pythonPath` to that environment's Python executable (not a command with arguments). Use a full path when necessary.
4. For general programs, set `shipmblang.pipeline` to `direct` and `shipmblang.profile` to `general`. Extension 0.3.0 defaults to `direct`/`general`; existing explicit settings take precedence. The profile setting only applies to `direct`.
5. Open `examples/general_functions.shipmb`, then run **ShipMBLang: Run Natural Program**. The output should be `720`.

```json
{
  "shipmblang.pythonPath": "C:/path/to/venv/Scripts/python.exe",
  "shipmblang.pipeline": "direct",
  "shipmblang.profile": "general",
  "shipmblang.memory": false
}
```

Use `shipmblang.projectRoot` only to select a source checkout when the package is not installed. Workspace configuration is resolved for the active document, including multi-root workspaces. An installed environment works from unrelated project folders. In SSH/WSL/container sessions, install Python packages on the workspace host and configure its interpreter path.

## Commands and behavior

- **Compile Natural Program** displays structured compiler output without running it.
- **Run Natural Program** compiles and runs the selected snapshot; general runtime output appears in the output channel.
- **Explain Current Diagnostic / Explain Pasted Error** run the existing printurf workflow.

A clarification or unsupported program is shown as feedback, not treated as runnable code. Source changes clear stale Problems; results from superseded snapshots are discarded. Operations can be cancelled and default to a 30-second timeout (`shipmblang.timeoutMs`). Output is bounded to 4 MiB. Editor source memory is off unless explicitly enabled. These commands require a trusted, filesystem-backed workspace; they do not grant host/device permissions.

Basic highlighting and bracket/string pairing are included. This extension does not yet provide completion, rename, debugging, or a language server. Other IDEs can use the same CLI documented in `docs/terminal-and-ides.md`.

## Development and verification

```text
npm test
npm run lint
```

`test/host/index.js` is an actual VS Code extension-host test. The repository's `tools/check_compiler_coinstall.py` can run it using an installed VS Code executable specified by `SHIPMB_CODE_EXE`; it builds both distributions in temporary folders and uses a disposable VS Code profile. It does not modify normal editor settings. Packaging is local only; publishing is a separate action.

## Write a quoted English paragraph

With shipmblang 0.2.0, shipmbcompiler 0.2.2+, and VS Code extension 0.3.0,
create a `.shipmb` file and write:

```text
"Start with total at 4, then add 8 to total and show total."
```

Run **ShipMBLang: Run Natural Program**, or click the Run button in the editor
title bar. The ShipMBLang Output channel prints `12`. **ShipMBLang: New Prose
Program** opens this example in a new editor. Save it anywhere in your workspace.
Straight double quotes (`"..."`) and smart double quotes (`“...”`) can surround
the program. The quotes belong in the file; the editor sends them unchanged.
The paragraph can span lines, and diagnostics refer to your original text.

VS Code now defaults to the `direct` pipeline and `general` profile. Existing
explicit settings take precedence: change an old `legacy` setting to `direct`
for prose. Terminal defaults remain compatible, so select the pipeline explicitly:

```powershell
& .venv/Scripts/python.exe -X utf8 -m shipmblang run --file examples/quoted_paragraph.shipmb --pipeline direct --profile general --memory off
```

The interpreter supports the documented computation grammar and everyday
arithmetic instructions, including named mutable values and add/subtract/multiply/
divide updates. Recognized instructions can be joined with `then` and `and`.
Existing functions, explicit condition/loop blocks, and text literals remain
available. Unsupported instructions are reported; they are not silently omitted.
This does not yet turn arbitrary application descriptions into websites, database
systems, or other programs requiring unimplemented capabilities.

If the compiler asks for clarification, edit the paragraph and run again, or use
**ShipMBLang: Clarify and Run** to restate the complete intended program. The
compiler checks that answer against the original source; an unrelated replacement
is not automatically accepted. An edit while entering an answer cancels that
submission. No cloud model is automatically invoked.

To upgrade an existing setup, pull both repositories, reinstall each package in
the same Python environment, rebuild/install `shipmblang-0.3.1.vsix`, then reload
VS Code. Keep `shipmblang.projectRoot` pointed at the current checkout; an old
source-path override can shadow the upgraded package. See Setup above.

## Multi-paragraph programs

With compiler 0.2.3+ and language 0.2.1+, paragraphs can share values and functions,
contain nested conditions/loops, and use separate double-quote wrappers separated
by blank lines. Paragraphs do not implicitly close blocks. The complete program
is checked before execution; invalid later paragraphs are not skipped.

See [multi-paragraph rules, examples, and regression checks](../../docs/multi-paragraph-programs.md) for the
precise contract, source-location guarantees, and supported complexity.
