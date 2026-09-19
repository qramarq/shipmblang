# ShipMBLang for VS Code

Compile/run `.shipmb`, `.shiplang`, and `.smb` prose from the active editor, including unsaved text or a selection. Compiler errors and clarification questions appear in Problems. General programs print captured output in the ShipMBLang output channel. Existing printurf explanations and command aliases remain available.

## Setup

1. Install ShipMBLang and the optional shipmbcompiler package into the same Python environment. Direct compilation requires Python 3.11+ and shipmbcompiler >=0.2.1,<0.3. For local private checkouts, install the compiler checkout first, then the language checkout with `python -m pip install -e .` in each package root.
2. Install the local VSIX through **Extensions: Install from VSIX**, or launch this folder with an Extension Development Host.
3. Set `shipmblang.pythonPath` to that environment's Python executable (not a command with arguments). Use a full path when necessary.
4. For general programs, set `shipmblang.pipeline` to `direct` and `shipmblang.profile` to `general`. Pipeline defaults remain `legacy`; the profile setting only applies to `direct`.
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
