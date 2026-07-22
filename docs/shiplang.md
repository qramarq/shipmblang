# ShipMBLang

ShipMBLang is the natural language programming layer for ShipMB: the way to
program ShipMB and its features on any given machine.

This first build is not a full standalone programming language yet. It is the
foundation for one: an installable Python package, command-line tool, editor
integration surface, and MCP server built around ShipMBLang's first language
primitive: `printurf()`.

`printurf()` is ShipMBLang's debugger function. It intakes code, project files,
raw errors, diagnostics, or stack traces, then returns a structured explanation
of what broke, why it broke, and what to try next.

## What ShipMBLang Is

ShipMBLang is currently five things:

- A Python module: `from shipmblang import printurf`
- A CLI path: `python -m shipmblang printurf ...`
- A natural sentence compiler: `python -m shipmblang compile ...`
- A local natural program runner: `python -m shipmblang run ...`
- An editor/MCP integration surface for code-aware debugging

The long-term goal is for ShipMBLang to become the small programming language and
developer runtime that exposes ShipMB capabilities consistently across local
machines, editors, automation clients, and future runtimes. Debugging is the
first feature because every real programming surface needs a way to explain what
went wrong.

## Natural Sentence Syntax

ShipMBLang can also treat regular sentences and paragraphs as source text. This is
the `shipmblang` writing model: type natural language syntax in a code editor,
then let ShipMBLang lower it through the pipeline:

```text
natural language syntax -> ShipMBLangCore -> ShipMBLang bytecode -> runtime/machine execution
```

The guiding ShipMBLang statement is:

```text
If the user can explain the program end to end in natural language syntax shipmb should be able to understand and convert that into machine code to run the programs.
```

For v0.1, "machine code" means the concrete ShipMBLang bytecode target executed
by the local ShipMBLang runtime. Native CPU code can come later.

For example, this paragraph:

```text
Use ShipMB. Open the current project and scan the codebase. When an error
happens, explain it with printurf, suggest a fix, and show the report.
```

compiles to:

```shiplang
use shipmb
project = open "."
project |> index
on error:
  error |> printurf |> suggest_fix |> show
```

From the terminal:

```bash
python -m shipmblang compile "Use ShipMB. Open the current project and scan the codebase. When an error happens, explain it with printurf and show the report."
```

To run the same natural program locally:

```bash
python -m shipmblang run "Use ShipMB. Open the current project and scan the codebase. When an error happens, explain it with printurf and show the report." \
  --error "NameError: name 'total' is not defined" \
  --path src/app.py
```

From Python:

```python
from shipmblang import compile_natural_program

program = compile_natural_program(
    "Use ShipMB. When an error happens, explain it with printurf and show me the fix."
)

print(program["core"])
print(program["bytecode"])
```

The first compiler is intentionally deterministic and small. It recognizes
sentences about using ShipMB, opening projects, indexing code, reacting to
errors, running `printurf()`, suggesting fixes, showing output, writing output,
and running named tasks. The Core language contract is stricter than scratchpad
prose: unknown declarations are hard errors, and diagnostics should identify the
phase, code, cause, and fix.

Under the hood, the public `shipmblang` package re-exports the implementation
that still lives in `driplm` for compatibility. `compile_natural_program()`
tokenizes the source, builds sentence nodes, lowers those nodes into semantic
operations, collects declarations for the whole compilation unit, resolves
references against that full declaration set, records symbols, emits IR,
normalizes and deduplicates the operation stream, then emits
`shipmblang-bytecode`. The readable ShipMBLangCore preview is rendered from the
same bytecode list, which keeps CLI output, JSON output, and runtime execution
aligned.

Declaration/name resolution is order-insensitive within a compilation unit, like
methods and declarations in C#, Java, and Go. A call or declaration may refer to
a function, class, method, property, variable, or constant written later. That
does not reorder effectful work: indexing, `printurf()`, `show`, `write`, and
`run` still execute in final bytecode order.

The first machine target is ShipMBLang bytecode, not native CPU assembly. That
is the right boundary for v0.1: paragraphs become deterministic instructions,
and the local ShipMBLang runtime executes the instructions that are already backed
by ShipMB features. See the dedicated ShipMBLang documentation in
[`shipmblang.md`](shipmblang.md).

Recent v0.1 updates broadened the natural syntax beyond the original debugging
flow. It can now model major-language structure such as target language,
imports, variables, constants, functions, classes, properties, methods, calls,
conditions, and loops. It can also model domain/device work such as ShipMBLang
libraries, Roku-like device targets, remote capabilities, runtime install
intent, voice/chat interfaces, and shared device-family resources.

The source contract is line-oriented, uses indentation for scope, uses `#` for
comments, maps ShipMB libraries and device-family dependencies to `use` and
`from`, and keeps ShipMBLang Core separate from emitted ShipMBLang bytecode. See
[`language-contract.md`](language-contract.md) for accepted/rejected syntax and
examples.

## What printurf() Does

`printurf()` turns this:

```text
raw error + nearby source code + project structure
```

into this:

```text
Error: [what failed]. Cause: [why it failed here]. Fix: [what to change].
```

It can also return structured data for editors, MCP clients, test runners, and
future ShipLang tools.

## Quick Examples

From the terminal:

```bash
python -m shipmblang printurf app.py --error "NameError: name 'total' is not defined"
python -m shipmblang printurf src/ --max-files 40
python -m shipmblang printurf src/ --error "TypeError: unsupported operand type(s)" --format json
```

From Python:

```python
from shipmblang import printurf

report = printurf(
    raw_error="NameError: name 'total' is not defined",
    paths=["src/app.py"],
    root=".",
)

print(report["diagnostics"][0]["suggestion"])
```

## Runtime Behavior

If a ShipMBLang-compatible checkpoint and tokenizer are available, `printurf()`
can use the local model to generate the explanation. If model weights are not available,
`printurf()` still works through a deterministic fallback that recognizes common
error families such as `NameError`, `ModuleNotFoundError`, `TypeError`,
`AttributeError`, `KeyError`, `IndexError`, and `SyntaxError`.

## MCP Integration

The MCP server exposes `printurf` as a tool. New clients should use:

```json
{
  "name": "shipmblang_index_codebase",
  "arguments": {
    "root_path": "C:/path/to/project",
    "max_files": 80
  }
}
```

Then call:

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

Legacy `shiplang_*` and `drip_*` aliases are still available for existing
integrations.

## First Build Definition

ShipMBLang v0.1.0 should be described as:

```text
The first public build of ShipMBLang, the natural language ShipMB programming layer,
introducing printurf(), ShipMB's codebase-aware debugging primitive for Python
modules, CLIs, editors, and MCP clients.
```
