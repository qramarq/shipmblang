# ShipMBLang printurf VS Code extension

Editor-native ShipMBLang `printurf()` error explanations for ShipMB projects.
Also supports natural ShipMBLang programs in `.shiplang` and `.shipmb` files.

## Features

- CodeLens above diagnostics: `ShipMBLang: explain`
- Quick Fix: `Explain with ShipMBLang`
- Hover link on diagnostics
- Command palette:
  - `ShipMBLang: Explain Current Diagnostic`
  - `ShipMBLang: Explain Pasted Error`
  - `ShipMBLang: Compile Natural Program`
  - `ShipMBLang: Run Natural Program`

Every response is forced into:

```text
Error: [Simple Explanation]. Cause: [Specific Reason]. Fix: [Solution].
```

## Local development

1. Open this folder in VS Code.
2. Press `F5` to launch an Extension Development Host.
3. Open a codebase with diagnostics.
4. Run `ShipMBLang: Explain Current Diagnostic`.

The extension calls `python -m shipmblang printurf` locally. Configure
`shipmblang.projectRoot` if the extension cannot auto-detect the ShipMBLang
repo.

Natural programs are selected text or the full active document. The compile
command lowers regular sentences to ShipMBLangCore; the run command executes the
supported ShipMBLang bytecode instructions through the local runtime.

Pipeline:

```text
natural language syntax -> ShipMBLangCore -> ShipMBLang bytecode -> runtime/machine execution
```

For v0.1, ShipMBLang bytecode is the concrete machine target; native CPU code can
come later. See `docs/shipmblang.md` from the repo root for the full docs.

The compiler is deterministic: it tokenizes natural text, splits it into
sentence statements, lowers recognized statements into semantic operations,
collects declarations for the whole compilation unit, resolves references
against that full declaration set, normalizes the operation stream, emits
`shipmblang-bytecode`, and renders the same bytecode as ShipMBLangCore for
preview. Contract-valid source uses known declaration and operation families;
unknown declarations should surface as hard compiler diagnostics.

Declaration/name resolution is order-insensitive, so a natural program may refer
to declarations written later. Runtime actions still run in final bytecode
order.

Recent runtime support includes natural declarations for major-language program
models, device-family resources, domain libraries, device targets, remote-style
capabilities, install intent, and voice/chat interfaces. The extension keeps
legacy `shiplang.*` command IDs available for older integrations, but new
visible commands and settings use `shipmblang.*`.

Core source is line-oriented, uses indentation for scope, uses `#` for comments,
and keeps ShipMBLang Core separate from emitted ShipMBLang bytecode. See
`docs/language-contract.md` from the repo root for accepted and rejected syntax.
