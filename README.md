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

## What distinguishes ShipMB's approach

ShipMB keeps the user's supported English prose as the maintained program and
combines direct compilation with source-bound clarification, contextual memory,
and explicit guarded execution. These are architectural features, not a claim
that ShipMB is the first or only language to provide them.

- **Direct compilation:** English -> typed syntax and resolved names -> final
  ShipMB bytecode. No Core source, generated Python/JavaScript, TAC, or separate
  intermediate instruction list is produced by this path. The syntax tree is
  still an internal representation; `target_code` contains the final VM artifact,
  not native CPU code or another source-language compilation step.
- **Clarification tied to source:** focused API answers identify a question and
  source revision. Stale answers cannot silently apply to changed prose; the
  revised program is validated before bytecode is emitted.
- **Meaning remembered in context:** confirmed interpretations are reused only
  after compatibility and project/binding checks. Similar wording is a suggestion,
  not confirmation. Memory does not autonomously rewrite grammar or train models.
- **Ability checked at execution:** guarded actions check current ability through
  an injected checker, skip with a reason when unable, and continue independent
  actions. This is verified with simulated outcomes in the Roku profile; it is
  not a claim of completed general device control.
- **Explicit outcomes:** supported meaning compiles; ambiguity requests
  clarification; unsupported meaning gets an explanation. There is no silent
  fallback to a different compilation pipeline.

The current frontend recognizes a defined English grammar, not arbitrary prose.
Broader understanding requires reviewed grammar changes and regression tests.
Remembering meaning never grants execution permission or proves current device
availability. General app, messaging, camera and cross-device integrations remain
planned work. The intended distinction is how these features work together;
historical uniqueness has not been established.

## Multi-paragraph programs

With compiler 0.2.3+ and language 0.2.1+, paragraphs can share values and functions,
contain nested conditions/loops, and use separate double-quote wrappers separated
by blank lines. Paragraphs do not implicitly close blocks. The complete program
is checked before execution; invalid later paragraphs are not skipped.

See [multi-paragraph rules, examples, and regression checks](docs/multi-paragraph-programs.md) for the
precise contract, source-location guarantees, and supported complexity.


## Compilation pipelines

The opt-in direct pipeline uses the optional `shipmbcompiler` package:

```text
English prose -> syntax tree and resolved names -> ShipMB bytecode -> runtime
```

```powershell
python -m shipmblang compile --file program.smb --pipeline direct --profile general --memory off
```

`shipmblangcore` remains a specification and compatibility project, not an
installation or translation dependency of this direct path. Direct compilation
requires Python 3.11+. The default remains `legacy`, using this language package's
existing compiler and output formats. Explicit `ir` selects shipmbcompiler's
separate IR pipeline. Neither compatibility path is an automatic fallback after
an unresolved direct compilation. Later Core examples describe compatibility
behavior, not an obligatory stage of direct compilation.

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


## Standalone and general compilation

Compile directly to the existing bytecode envelope without rendering Core:

```bash
python -m shipmblang compile "Use ShipMB. Open the current project and scan the codebase." --format bytecode
```

This outputs `target`, `native_machine_code`, and `bytecode`. Core text and the
shipmblangcore specification repository are not required. Python callers can use
`compile_natural_program(text, include_core=False)` to keep the full compiler
trace with `core` set to `None`, without calling the Core renderer. Existing
Core/JSON defaults and run behavior are unchanged. This remains the local
ShipMBLang bytecode format, not native code or the separate shipmbcompiler format.
Compile-only imports also avoid the error-reporting, project-indexing, provider,
and runtime-context modules. Public helpers remain available through lazy exports;
execution loads its runtime helpers when requested.

### Optional direct English compiler

On Python 3.11 or newer, install the separately named compiler distribution with
`python -m pip install "shipmblang[direct]"`. Both distributions can coexist;
the basic language package still has no required dependencies.

```bash
python -m shipmblang compile "Use the tv pack library in shipmblang to control this Roku TV like a remote." --pipeline direct --memory off
python -m shipmblang compile "Use the tv pack library in shipmblang to control this Roku TV like a remote." --pipeline direct --format json --memory off
python -m shipmblang compile "Use the tv pack library in shipmblang to control this Roku TV like a remote." --pipeline ir --memory off
```

`legacy` remains the default and uses the existing language compiler. `direct`
delegates English interpretation and bytecode generation to shipmbcompiler;
`ir` explicitly selects that compiler's older IR pipeline. There is no automatic
fallback. Direct/IR output defaults to compiler bytecode; JSON includes diagnostics
and clarification questions. Core output is available through `legacy`. A direct
result needing clarification or reporting unsupported behavior exits unsuccessfully
and prints its full explanation, even when bytecode output was requested.

Answer a clarification by keeping the original source and supplying explicit
English with `--interpretation`:

```bash
python -m shipmblang compile "Control it like a remote." --pipeline direct --interpretation "Use the tv pack library in shipmblang to control this Roku TV like a remote." --format json --memory off
```

The compiler validates that interpretation before generating bytecode. It does
not silently substitute a guessed meaning. With memory enabled, confirmed meaning
can be recorded by the compiler. This flag is supported only by the direct pipeline.

Python callers can use `shipmblang.compile_direct_program(...)`. Its result keeps
the compiler schema, including `status`, `clarifications`, and `target_code`.
It accepts explicit bindings, clarification answers and an optional model-provider
callback; no model is selected automatically. Compiler bytecode is not passed to
the legacy language runtime. `run --pipeline direct` uses the compiler's validated
artifact runner. Its Roku profile is an event sandbox, not a live-device controller.

The opt-in `general` profile requires a profile-capable `shipmbcompiler>=0.2.1,<0.3`
build. It compiles supported pure computation into version 0.3 compiler bytecode.
For example, [general_sum.shipmb](examples/general_sum.shipmb) adds the values above
10 in the list 3, 12, 15 and captures `27` followed by a newline:

```bash
python -m shipmblang run --file examples/general_sum.shipmb --pipeline direct --profile general --memory off
```

The JSON result contains `runtime.stdout` and `runtime.output`. Python callers use
`compile_direct_program(source, profile="general", memory=False)` to compile.
The [function example](examples/general_functions.shipmb) uses a typed recursive
factorial function and produces `720`:

```bash
python -m shipmblang run --file examples/general_functions.shipmb --pipeline direct --profile general --memory off
```

`--profile` is only valid with `--pipeline direct`; the default direct profile
remains `roku`, and existing legacy/IR defaults are unchanged. General artifacts
run through the compiler's version-aware loader, not the legacy language runtime.
This initial profile supports its implemented computation subset; it does not
provide arbitrary prose interpretation or live storage, API, UI, or device effects.

Source submissions and outcomes are captured locally when compiler memory is
installed. This includes unsuccessful interpretations and original source text.
`--memory off` or API `memory=False` always disables capture. Otherwise an explicit
`memory_path` or `--memory-path` (also `--memory-db`) enables that database even
when `SHIPMB_MEMORY=off`. Without an explicit path, `SHIPMB_MEMORY=off` disables
capture; `SHIPMB_MEMORY_DB` selects the default database when capture is enabled.
Otherwise the compiler's local user-data location is used. Legacy capture failures, including a missing
optional compiler, warn without discarding the compilation result. Use a disposable
database or disable memory for tests and sensitive inputs.


## Terminal and IDE integration

See [terminal and IDE setup](docs/terminal-and-ides.md) and the [VS Code extension](extensions/vscode-shipmblang/README.md) for interpreter configuration, general compilation, diagnostics, and local verification.


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
source-path override can shadow the upgraded package. See the setup below.

## Test ShipMBLang in VS Code (Windows)

You need Python 3.11 or newer, VS Code 1.92 or newer, access to both private
repositories, and the ShipMBLang VSIX extension. ShipMBLangCore is not required
for this direct/general workflow. The extension is currently installed manually.

1. Clone both repositories into the same parent directory (or use your existing
   current checkouts):

   ```powershell
   git clone https://github.com/qramarq/shipmblang.git
   git clone https://github.com/qramarq/shipmblang-compiler.git
   cd shipmblang
   ```

2. In VS Code, use **File > Open Folder** to open the `shipmblang` checkout and
   trust your workspace. Open **Terminal > New Terminal** with PowerShell.
   Confirm `python --version` is 3.11 or newer, then install both packages into
   the same environment:

   ```powershell
   python -m venv .venv
   & .venv/Scripts/python.exe -m pip install -e ../shipmblang-compiler/shipmbcompiler
   & .venv/Scripts/python.exe -m pip install -e .
   ```

   These commands assume sibling clones with the names above. Adjust paths for
   existing checkouts. Environment activation is not required.

3. Obtain `shipmblang-0.3.1.vsix` from the project maintainer, or build it from
   the language checkout with Node.js 22+ and npm installed:

   ```powershell
   cd extensions/vscode-shipmblang
   npx --yes @vscode/vsce package --no-dependencies --out shipmblang-0.3.1.vsix
   cd ../..
   ```

   Press **Ctrl+Shift+P**, select **Extensions: Install from VSIX**, select that
   file, and reload VS Code if prompted. The generated VSIX is not committed to
   the repository or published to the Marketplace.

4. Press **Ctrl+Shift+P** and choose **Preferences: Open Workspace Settings
   (JSON)**. Merge these entries into the existing settings object, replacing
   `C:/path/to/shipmblang` with your actual language checkout path:

   ```json
   {
     "shipmblang.pythonPath": "C:/path/to/shipmblang/.venv/Scripts/python.exe",
     "shipmblang.projectRoot": "C:/path/to/shipmblang",
     "shipmblang.pipeline": "direct",
     "shipmblang.profile": "general",
     "shipmblang.memory": false
   }
   ```

   Use a full executable path, not a command with arguments. An old
   `shipmblang.projectRoot` setting can load an outdated source checkout even
   when the Python environment is correct. Override it here with the current
   checkout; remove obsolete user-level settings when no longer needed.

5. Press **Ctrl+Shift+E** to open Explorer on the left. Expand `examples` and
   open `general_functions.shipmb`. With no text selected, press
   **Ctrl+Shift+P** and run **ShipMBLang: Run Natural Program**. Open
   **View > Output** and select **ShipMBLang** in the dropdown. Expect `720`.
   **ShipMBLang: Compile Natural Program** shows compiler output without running.
   If text is selected, only the selection is submitted.

6. To test diagnostics, create `test.smb` containing `Show missing.` and run
   **ShipMBLang: Compile Natural Program**. Press **Ctrl+Shift+M** to see the
   undefined-name diagnostic in Problems.

For a terminal check from the language checkout:

```powershell
& .venv/Scripts/python.exe -X utf8 -m shipmblang run --file examples/general_functions.shipmb --pipeline direct --profile general --memory off
```

The terminal returns JSON whose `runtime.stdout` is `720\n`. If you see
`No module named shipmblang`, check the selected interpreter and installation.
If options such as `--pipeline` or `--memory` are unrecognized, check for an old
`projectRoot` override. If commands are unavailable, check workspace trust and
that the extension is enabled.

Current VS Code support includes compile/run commands, basic syntax highlighting,
and Problems diagnostics. Autocomplete, rename, debugging, and a language server
are not implemented. General programs must use the implemented grammar; arbitrary
English is not guaranteed to compile. Other IDEs can invoke the installed CLI.
