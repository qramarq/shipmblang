# ShipMBLang

ShipMBLang is the natural language programming layer for ShipMB. It lets users
write a program as ordinary instructions in a code editor, then compile those
instructions into a runnable bytecode form.

The guiding statement is:

```text
If the user can explain the program end to end in natural language syntax shipmb should be able to understand and convert that into machine code to run the programs.
```

For v0.1, the concrete machine target is ShipMBLang bytecode executed by the
local runtime. Native CPU code can come later.

## Pipeline

```text
English prose -> lexical analysis -> syntax analysis -> semantic analysis
-> intermediate code generation -> code optimization -> target code generation
-> ShipMBLangCore -> ShipMBLang bytecode -> runtime/machine execution
```

- English prose is the program text the user writes in a code editor.
- Lexical analysis tokenizes words, numbers, strings, punctuation, and compiler keywords.
- Syntax analysis groups tokens into natural-language statement nodes.
- Semantic analysis collects declarations, resolves references against the full
  declaration set, and emits program symbols and operations.
- Intermediate code generation emits ShipMBLang IR instructions.
- Code optimization normalizes and lightly rewrites IR before output.
- Target code generation emits ShipMBLang bytecode, the current machine target.
- The runtime executes the supported bytecode operations locally.

## Quick Start

Compile a natural program:

```bash
python -m shipmblang compile "Use ShipMB. Open the current project and scan the codebase. When an error happens, explain it with printurf and show the report."
```

Output:

```shiplang
use shipmb
project = open "."
project |> index
on error:
  error |> printurf |> show
```

Run a supported natural program:

```bash
python -m shipmblang run "Use ShipMB. Open the current project and scan the codebase. When an error happens, explain it with printurf and show the report." --error "NameError: name 'total' is not defined" --path app.py
```

Compile to JSON, including bytecode:

```bash
python -m shipmblang compile "Use ShipMB. Open the current project and scan the codebase." --format json
```

The JSON output includes the full compiler trace: `tokens`, `syntax_tree`,
`semantic_model` with `declaration_resolution`, `intermediate_code`,
`optimized_intermediate_code`, `target_code`, `core`, and `bytecode`.

## How It Works

ShipMBLang's current compiler is deterministic. The public
`shipmblang.natural_syntax` module re-exports the implementation in
`driplm.natural_syntax`, where the compiler:

1. tokenizes natural text with source spans
2. splits it into sentence-level statements
3. classifies and lowers statements into semantic operations
4. collects declarations for the whole compilation unit before resolving names,
   so references can point at declarations written later
5. records symbols for languages, imports, libraries, devices, variables,
   constants, functions, classes, capabilities, installs, and interfaces
6. wraps operations as IR, normalizes/deduplicates them, and inserts missing
   setup such as ShipMB usage, project opening, or error handling
7. emits `shipmblang-bytecode` with `native_machine_code: false`
8. renders the same bytecode as ShipMBLangCore for human review

The ShipMBLang Core contract is stricter than free-form note taking: unknown
declarations are hard errors, diagnostics should report multiple failures when
possible, and each diagnostic should name its phase, code, and fix.

Recent updates expanded the first `printurf()` workflow into a broader
program-model compiler: prose can now describe major-language declarations,
domain libraries, device targets, device capabilities, runtime install intent,
client interfaces, and device-family resources.

## Natural Programming Syntax

ShipMBLang now recognizes natural descriptions of the programming structure
used by major languages. A `.shipmb` file can read like an English design paper
while still listing libraries, variables, functions, classes, methods, control
flow, and output.

Core source is line-oriented, blank lines are cosmetic, indentation defines
scope for functions, classes, methods, interfaces, types, and device structures,
and comments use `#` only. See the canonical
[ShipMBLang Core language contract](docs/language-contract.md) for accepted and
rejected syntax across imports, declarations, identifiers, lists, deterministic
flags, bridges, safety interlocks, capability mappings, architecture debug
output, and diagnostics.

Within a compilation unit, declaration lookup is order-insensitive, like methods
in C#, Java, and Go. A call, return expression, method owner, property owner, or
base-class reference can resolve to a declaration written later in the file. The
compiler contract is to collect declarations first, then resolve references
against that full set. This does not reorder runtime work: effectful actions
such as `show`, `write`, `run`, indexing, and `printurf()` still execute in the
final bytecode order.

Supported language targets include Python, JavaScript, TypeScript, Java, C#,
C++, C, Go, Rust, Ruby, PHP, Swift, Kotlin, Scala, R, SQL, and shell scripts.
Common aliases such as `js`, `ts`, `golang`, `c sharp`, and `c plus plus` are
accepted.

Example:

The following `Cart` name is a target-language program-model name preserved
from the user's Python-oriented prose. Default Core identifiers use `snake_case`;
see the Core contract for pure Core examples.

```text
Use Python. Import math. Declare an integer variable total set to 0.
Define a function add_item that takes price and returns total plus price.
Create a class Cart with property items and method add_item that takes item and returns items.
For each item in items then call add_item with item. Show program.
```

Expected Core:

```shiplang
use shipmb
target language "python"
import "math"
let total: int = 0
fn add_item(price) -> total plus price:
  pass
class Cart:
property Cart.items
method Cart.add_item(item) -> items:
  pass
for item in items:
  call add_item with item
program |> show
```

Forward references are valid for declaration resolution:

```text
Use Python. Call helper with total.
Define a function helper that takes value and returns total.
Declare an integer variable total set to 0. Show program.
```

The `call helper` and `returns total` references resolve after declaration
collection, even though `helper` and `total` are declared later. The rendered
Core and bytecode still keep the call before the later declarations.

The runtime stores these declarations in the program model and can return them
with `run --format json`. Native process execution remains opt-in future work;
v0.1 records and exposes the compiled bytecode safely. Selecting a target such
as Python or Rust updates the program model; it does not yet emit native source
or switch away from the ShipMBLang bytecode backend.

## Python API

```python
from shipmblang import compile_natural_program, printurf

program = compile_natural_program(
    "Use ShipMB. When an error happens, explain it with printurf and show the report."
)

print(program["tokens"])
print(program["syntax_tree"])
print(program["semantic_model"])
print(program["core"])
print(program["bytecode"])

report = printurf(
    raw_error="NameError: name 'total' is not defined",
    paths=["src/app.py"],
    root=".",
)

print(report["diagnostics"][0]["suggestion"])
```

## printurf

`printurf()` is ShipMBLang's codebase-aware debugging primitive. It accepts raw
errors, diagnostics, stack traces, source context, or project files, then returns
a structured explanation:

```text
Error: [what failed]. Cause: [why it failed here]. Fix: [what to change].
```

CLI examples:

```bash
python -m shipmblang printurf app.py --error "NameError: name 'total' is not defined"
python -m shipmblang printurf src/ --max-files 40
python -m shipmblang printurf src/ --error "TypeError: unsupported operand type(s)" --format json
```

## Device Families

ShipMBLang includes device-family libraries so a program or MCP client can set
the current device target and inspect the resources available on that target.
The first built-in families are `host`, `cuda`, `mps`, `browser`, and
`embedded`. Family names and aliases are syntax keywords, so `cuda`, `gpu`,
`browser`, `web`, `embedded`, and `raspberry pi` can be used directly in natural
programs.

Natural syntax can select a family and resource:

```bash
python -m shipmblang run "Use the embedded device family. Expose the gpio resource. Show device resources."
python -m shipmblang run "Use raspberry pi. Read gpio. Show resources."
```

Python callers can inspect the same library:

```python
from shipmblang.libraries.device_families import get_device_family, list_device_resources

embedded = get_device_family("raspberry pi")
resources = list_device_resources("embedded")
```

## Editor Workflow

ShipMBLang is designed to be written in a normal code editor.

1. Create a `.shipmb` or `.shiplang` file.
2. Write the program in natural language syntax.
3. Run `ShipMBLang: Compile Natural Program` to inspect ShipMBLangCore.
4. Run `ShipMBLang: Run Natural Program` to execute supported bytecode through
   the local runtime.

The VS Code extension lives in `extensions/vscode-shipmblang` and calls
`python -m shipmblang` locally.

## MCP

Run the local MCP server:

```bash
python -m shipmblang mcp
```

New clients should call:

- `printurf`
- `shipmblang_explain_error`
- `shipmblang_index_codebase`
- `shipmblang_list_device_families`
- `shipmblang_select_device_family`
- `shipmblang_get_device_resource`

Device resources are also exposed through MCP resources:

- `shipmblang://device-families`
- `shipmblang://active-device`
- `shipmblang://device-family/embedded/resource/gpio`

## ShipMB Onboarding

ShipMB setup should install this checkout into the Python environment it uses
for local tools, then call the readiness command:

```bash
python -m pip install -e C:/path/to/shipmblang
python -m shipmblang onboarding --format json --check --root C:/path/to/shipmb-project
```

The onboarding command returns a machine-readable manifest with install,
verify, CLI, MCP, environment, and smoke-check metadata. A static discovery
manifest is also available at `shipmblang-onboarding.json`; after Python is
available, the CLI manifest is authoritative.

## Documentation

- [ShipMBLang language guide](docs/shipmblang.md)
- [ShipMBLang Core language contract](docs/language-contract.md)
- [ShipMBLang and printurf overview](docs/shiplang.md)
- [Editor and MCP setup](docs/shipmblang-ide.md)
- [ShipMB onboarding integration](docs/shipmb-onboarding.md)

## v0.1 Scope

ShipMBLang v0.1 is:

- a natural language syntax for describing programs end to end
- a deterministic compiler from natural syntax to ShipMBLangCore
- a bytecode emitter for ShipMBLang runtime instructions
- a local runtime for supported bytecode operations
- a foundation for later native execution targets

It is not a full native compiler yet. The current concrete machine target is
ShipMBLang bytecode.

## Compatibility

The public project name and recommended command surface are ShipMBLang. Some
legacy internal module names and aliases remain so older integrations continue
to run while new docs and examples use `shipmblang`.

## License

Proprietary. ShipMBLang, including ShipMBLang Core, the compiler, runtime
components, developer tooling, and `printurf()` functionality, is the
intellectual and proprietary property of ZMachinery LLC by way of SHIPMB. All
rights reserved.
