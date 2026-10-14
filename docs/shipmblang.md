# ShipMBLang

ShipMBLang is the natural language syntax layer for ShipMB programs. It lets a
user write a program as plain instructions in a code editor, then asks the
ShipMBLang compiler to lower those instructions into executable program form.

The guiding statement for ShipMBLang is:

```text
If the user can explain the program end to end in natural language syntax shipmb should be able to understand and convert that into machine code to run the programs.
```

In v0.1, the concrete machine target is ShipMBLang bytecode executed by the
local ShipMBLang runtime. Native CPU machine code can come later. The important
v0.1 boundary is that ordinary language becomes deterministic instructions that
a runtime can inspect, serialize, and execute.

## The Pipeline

ShipMBLang follows a compiler pipeline for English prose:

```text
English prose
-> lexical analysis
-> syntax analysis
-> semantic analysis
-> intermediate code generation
-> code optimization
-> target code generation
-> ShipMBLang bytecode
-> runtime/machine execution
```

1. Lexical analysis tokenizes the prose into words, numbers, strings,
   punctuation, sentence boundaries, and compiler keywords.
2. Syntax analysis groups tokens into statement nodes such as imports,
   functions, classes, loops, conditions, device operations, and output.
3. Semantic analysis collects declarations across the compilation unit, resolves
   references against that full declaration set, and emits symbols, diagnostics,
   and preliminary operations.
4. Intermediate code generation lowers semantics into ShipMBLang IR.
5. Code optimization normalizes the IR, inserts required runtime setup, and
   removes avoidable ambiguity.
6. Target code generation emits ShipMBLang bytecode.
7. Runtime/machine execution runs the supported bytecode operations locally.

That makes ShipMBLang feel like writing intent in English, while still keeping a
real compiler boundary between what the user wrote and what the runtime runs.

## Core Language Contract

ShipMBLang Core source is the readable layer between natural source and
ShipMBLang bytecode. It is line-oriented, blank lines are cosmetic, indentation
defines scope for OOP, functions, classes, methods, interfaces, types, and
device declarations, and comments use `#` only.

The canonical contract is maintained in
[`language-contract.md`](language-contract.md). It defines accepted and rejected
syntax for:

- `use` and `from` forms for ShipMB libraries, device families, and
  dependencies
- target-language imports used only inside program-model descriptions
- functions, classes, types, device functions, devices, and supported
  declarations
- identifiers, module access with dots, file paths with slashes, and
  kebab-case filenames or URLs
- quoted string literals, bare references, numbers, booleans, and lists without
  trailing commas
- deterministic flags that affect device families or user communication
- bidirectional bridges and validated protocols
- safety interlocks and policy expressions
- capability-provider mappings with explicit priority conflict resolution
- `architecture |> show` as compile/debug output rather than runtime bytecode
- multi-error diagnostics with distinct phases, codes, explanations, and fixes

Unknown declarations are hard errors. Exact declarations merge, unnecessary
duplicates warn, and syntax or compile errors fail compilation. Name resolution
is order-insensitive inside a compilation unit, but bytecode preserves runtime
effect order.

`python -m shipmblang compile ... --format json` exposes this full trace with
`tokens`, `syntax_tree`, `semantic_model` with `declaration_resolution`,
`intermediate_code`,
`optimized_intermediate_code`, `target_code`, `core`, and `bytecode`.

## How The Compiler Works

The compiler implementation is intentionally deterministic. It does not ask a
model to guess what the program means. The active implementation lives in
`driplm.natural_syntax`, with `shipmblang.natural_syntax` re-exporting that
module for the public package name.

Compilation proceeds in these concrete steps:

1. `lexical_analysis()` uses a single tokenizer regex to recognize quoted
   strings, numbers, identifiers, sentence boundaries, punctuation, and a fixed
   set of English compiler keywords. Each token keeps its source span so editors
   can relate compiler output back to prose.
2. `syntax_analysis()` splits the source into sentence-level statements on
   punctuation and newlines. Each statement is classified by checking the same
   extraction rules used by the compiler, such as target language, library,
   device, import, class, function, variable, loop, condition, error handler,
   output, run instruction, or diagnostic-worthy unsupported syntax.
3. `semantic_analysis()` compiles each statement into preliminary operations,
   collects declarations for the whole compilation unit, then resolves
   references against that full declaration set. The model stores symbols for
   languages, imports, libraries, devices, capabilities, installs, interfaces,
   variables, constants, functions, and classes. It also exposes
   `declaration_resolution`, which records the order-insensitive lookup
   strategy, resolved references, unresolved references, and the fact that
   effectful actions still run in bytecode order. Contract-invalid declarations
   must be surfaced as diagnostics instead of accepted as Core declarations.
4. `intermediate_code_generation()` wraps each semantic operation with a stable
   IR id such as `i0000`.
5. `code_optimization()` removes the IR wrapper, normalizes the operation
   stream, inserts required setup, and deduplicates obvious repeats. For example,
   it inserts ShipMB usage when the program omits it, inserts project-opening
   setup before project indexing if needed, and inserts error-handler setup
   before error actions if needed.
6. `target_code_generation()` removes optimizer ids and emits the current target
   object: `target: "shipmblang-bytecode"`,
   `native_machine_code: false`, and the final bytecode list.
7. `render_core_program()` renders that bytecode back into readable
   ShipMBLangCore for humans and editor previews.

The important consequence is that Core and bytecode come from the same final
operation list. If Core says `project |> index`, bytecode contains the matching
runtime instruction, but the exact lowercase operation spelling is generated
from English prose and may change. Contract-valid source must not rely on an
unknown declaration being preserved as runtime intent; declaration-shaped
unknowns are compiler errors.

The syntax-tree `role` field is an editor hint, not the source of truth for
execution. The semantic pass recompiles each statement and the optimized
bytecode is authoritative.

## Recent Language Updates

Recent v0.1 work expanded ShipMBLang from the original `printurf()`-centered
flow into a broader program-model compiler:

- Major-language structure can now be described in prose: target language,
  imports, variables, constants, functions, classes, properties, methods,
  returns, calls, conditions, loops, and model-oriented output.
- Domain/device prose can now describe libraries, device targets, capabilities,
  runtime install intent, client interfaces, and command error reporting.
- Device-family libraries are shared by the compiler, runtime, and MCP server.
  Built-ins currently cover `host`, `cuda`, `mps`, `browser`, and `embedded`.
- The runtime now records program declarations and domain/device declarations in
  a structured state object that `run --format json` can return.
- Public package names are ShipMBLang-first, while legacy `driplm`, `shiplang`,
  `shipmb`, and `driplang` paths remain compatibility shims.

## Natural Language Syntax

A `.shipmb` or `.shiplang` file can contain ordinary instructions:

```text
Use ShipMB. Open the current project and scan the codebase. When an error
happens, explain it with printurf, suggest a fix, and show the report.
```

The syntax is intentionally natural. A user should be able to describe the
program end to end: what capability to use, what input to open, what event to
react to, what work to perform, and what output to produce.

The first compiler recognizes sentences about:

- using ShipMB
- opening a project, folder, repo, or workspace
- scanning or indexing code
- reacting to errors
- explaining errors with `printurf()`
- suggesting fixes
- showing, writing, or exporting output
- recording a run instruction

Contract-valid programs use known declaration and operation families. Unknown
declarations are hard errors, and diagnostics should explain the phase, code,
cause, and fix instead of silently accepting unsupported syntax.

## Major Language Programming Syntax

ShipMBLang can also compile an English program specification that follows normal
programming principles. The user still declares the target language, imports or
libraries, variables, functions, classes, methods, control flow, calls, and
outputs, but the syntax can be prose instead of source-code punctuation.

Supported target languages and aliases:

- Python: `python`, `py`
- JavaScript and TypeScript: `javascript`, `js`, `typescript`, `ts`
- JVM and CLR languages: `java`, `kotlin`, `scala`, `c#`, `c sharp`
- C-family systems languages: `c`, `c++`, `cpp`, `c plus plus`
- Go and Rust: `go`, `golang`, `rust`
- Web and scripting languages: `ruby`, `php`, `swift`, `r`, `sql`, `shell`, `bash`

Recognized programming declarations include:

These declaration examples describe a target-language program model, so names
such as `Cart` and `BaseCart` are preserved as model names from the user's
target-language prose. Pure Core identifiers default to `snake_case`.

- Target language: `Use Python`, `Create a C++ program`, `Write in TypeScript`
- Imports/libraries: `Import math`, `From collections import Counter`, `Include iostream`, `Use the express library`
- Variables/constants: `Declare an integer variable total set to 0`, `Const limit equals 10`
- Functions: `Define a function add_item that takes price and returns total plus price`
- Classes: `Create a class Cart`, `Class Cart extends BaseCart`
- Properties: `Class Cart with property items`, `Property total on class Cart`
- Methods: `Class Cart with method add_item that takes item and returns items`
- Returns and calls: `Return total`, `Call add_item with item`
- Conditions and loops: `If total is empty then return error`, `For each item in items then call add_item with item`
- Output: `Show program`, `Show imports`, `Show variables`, `Show functions`, `Show classes`
- Device programs: `Use the tv pack library in ShipMBLang to control this Roku TV like a remote would`
- Device capabilities: `Use the resources a Roku remote controller would have and search, open, close apps`
- Client interfaces: `Give me voice and chat bot access if able`
- Runtime install intent: `Install shipmb on the tv`

### Declaration And Name Resolution

ShipMBLangCore treats declarations in the same compilation unit as
order-insensitive for name resolution, following the familiar model used for
methods and declarations in C#, Java, and Go. A declaration or reference can
mention a class, method, function, property, variable, or constant that is
written later in the source text.

The compiler contract is:

1. Parse and lower the source into preliminary operations without executing
   them.
2. Collect all declarations visible to the compilation unit or scope.
3. Resolve references against the full declaration set.
4. Emit Core and bytecode in the source-preserving operation order.

This is only a declaration/name-resolution rule. It does not move effectful
actions. Runtime work such as project indexing, `printurf`, `show`, `write`,
and `run` follows the final bytecode order.

For example, this is valid:

```text
Use Python. Call helper with total.
Define a function helper that takes value and returns total.
Declare an integer variable total set to 0. Show program.
```

The semantic model resolves `helper` to the later function declaration and
`total` to the later variable declaration. The rendered Core still keeps
`call helper(total)` before the `fn helper(...)` and `let total...` declarations,
so tools can distinguish name resolution from runtime action order.

Example natural program:

The following `Cart` name is a target-language program-model name preserved from
the user's Python-oriented prose. Default Core identifiers use `snake_case`; see
the Core contract for pure Core examples.

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

An illustrative bytecode trace keeps these constructs structured. Operation
names are lowercase canonical names generated from English prose and may change:

```json
[
  { "op": "target_language", "language": "python" },
  { "op": "import", "module": "math", "symbols": [], "kind": "import" },
  { "op": "declare_variable", "name": "total", "type": "int", "value": "0", "constant": false },
  { "op": "define_function", "name": "add_item", "parameters": ["price"], "returns": "total plus price" },
  { "op": "define_class", "name": "Cart" },
  { "op": "define_property", "class": "Cart", "name": "items" },
  { "op": "define_method", "class": "Cart", "name": "add_item", "parameters": ["item"], "returns": "items" },
  { "op": "loop", "iterator": "item", "source": "items", "action": "call add_item with item" },
  { "op": "show", "value": "program" }
]
```

This does not make ShipMBLang a native Python, JavaScript, C++, or Rust compiler
yet. It means ShipMBLang can understand major-language program structure from
natural syntax, lower it to ShipMBLangCore, emit deterministic bytecode, and
expose that model to the runtime and tooling.

The current compiler does not emit target-language source files. `Use Python`,
`Use TypeScript`, or `Create a C++ program` selects a language in the program
model; it does not switch the bytecode backend away from
`shipmblang-bytecode`.

Device-control prose compiles into the same compiler pipeline. For example:

```text
Let's use the tv pack library in shipmblang to control this roku tv like a remote would.
Being able to agentically call and use the resources a roku remote controller would have
and be able to search, open, close apps and show me any errors that happen when we execute commands.
Install shipmb on the tv and give me voice and chat bot access if able.
```

Expected Core:

```shiplang
use shipmb
library "tv_pack" from "shipmblang" for "control this roku tv like a remote would"
device_target = tv platform "roku" as tv
remote |> capability "remote_control" agentic
device_target = remote_controller platform "roku" as remote_controller
remote |> capability "list_resources" agentic
remote |> capability "search_apps" agentic
remote |> capability "open_app" agentic
remote |> capability "close_app" agentic
remote |> capability "execute_command" agentic
on error:
  error |> printurf |> show
run "commands"
install "shipmb" on tv
interface "voice" mode "client"
interface "chat_bot" mode "client"
```

## ShipMBLangCore

ShipMBLangCore is the readable intermediate representation. It is not the prose
the user wrote, and it is not the final runtime format. It is the small
functional form that shows what the compiler understood.

The natural program above compiles to:

```shiplang
use shipmb
project = open "."
project |> index
on error:
  error |> printurf |> suggest_fix |> show
```

Core is useful because it gives users and editor tools a compact preview before
running anything.

## ShipMBLang Bytecode

ShipMBLang bytecode is the v0.1 machine target. It is represented as structured
instructions that the local runtime can execute:

The following trace is illustrative. Bytecode operation names are lowercase
canonical names generated from English prose, and spellings may change across
compiler revisions.

```json
[
  { "op": "use", "module": "shipmb" },
  { "op": "open_project", "target": "." },
  { "op": "index_project" },
  { "op": "on_error" },
  { "op": "printurf" },
  { "op": "suggest_fix" },
  { "op": "show", "value": "report" }
]
```

This bytecode is the current concrete answer to "machine code" for ShipMBLang:
it is the executable machine-facing instruction stream for the ShipMBLang runtime.
It is not native CPU assembly in v0.1.

The target-code object reports this explicitly:

```json
{
  "target": "shipmblang-bytecode",
  "native_machine_code": false,
  "bytecode": []
}
```

## Runtime And Machine Execution

`python -m shipmblang run` compiles natural language syntax, produces the same Core
and bytecode internally, then executes the supported bytecode operations.

Today the runtime can:

- load the ShipMB module marker
- open and index a project
- build a program model from natural declarations of target language, imports,
  variables, constants, functions, classes, properties, methods, calls,
  conditionals, and loops
- build a `printurf()` report from an error, source context, and project files
- suggest a fix through the `printurf()` report path
- show output in the terminal or editor output pane
- write output to a safe path under the project root
- record run instructions that are not enabled for native execution yet

The last point is the v0.1 distinction: ShipMBLang has a real bytecode target
now, while native process execution and native CPU code generation can evolve
later behind the same pipeline.

## Device Family Libraries

ShipMBLang models device targets as libraries of resources. Selecting a device
family makes that family's resources available to the runtime and MCP clients.
The built-in families are:

- `host`: filesystem, process, environment, and clock resources
- `cuda`: tensors, GPU memory, kernels, and streams
- `mps`: tensors, unified memory, and Metal kernels
- `browser`: DOM, viewport, storage, and network resources
- `embedded`: GPIO, serial, I2C, SPI, and flash resources

Family names and aliases are syntax keywords. That means a user can write the
formal phrase:

```text
Use the embedded device family. Expose the gpio resource. Show device resources.
```

or a shorter keyword-oriented form:

```text
Use raspberry pi. Read gpio. Show resources.
```

Natural syntax can select a family and use one of its resources:

```text
Use the embedded device family. Expose the gpio resource. Show device resources.
```

Expected Core:

```shiplang
use shipmb
device = family "embedded"
device |> resource "gpio"
device_resources |> show
```

An illustrative bytecode trace for this example includes:

```json
[
  { "op": "use", "module": "shipmb" },
  { "op": "use_device_family", "family": "embedded" },
  { "op": "use_device_resource", "resource": "gpio" },
  { "op": "show", "value": "device_resources" }
]
```

MCP clients can list, select, and read device resources with:

- `shipmblang_list_device_families`
- `shipmblang_select_device_family`
- `shipmblang_get_device_resource`
- `shipmblang://device-families`
- `shipmblang://active-device`
- `shipmblang://device-family/<family>/resource/<resource>`

Python callers can import the library from ShipMBLang:

```python
from shipmblang.libraries.device_families import get_device_family

family = get_device_family("gpu")
```

## CLI Workflow

Compile a natural program to ShipMBLangCore:

```bash
python -m shipmblang compile "Use ShipMB. Open the current project and scan the codebase. When an error happens, explain it with printurf, suggest a fix, and show the report."
```

Compile the same program to structured output, including bytecode:

```bash
python -m shipmblang compile "Use ShipMB. Open the current project and scan the codebase. When an error happens, explain it with printurf, suggest a fix, and show the report." --format json
```

Read source from a file:

```bash
python -m shipmblang compile --file program.shipmb
```

Compile a natural major-language program model:

```bash
python -m shipmblang compile "Use Python. Import math. Declare an integer variable total set to 0. Define a function add_item that takes price and returns total plus price. Show program."
```

Run a natural program through the local runtime:

```bash
python -m shipmblang run "Use ShipMB. Open the current project and scan the codebase. When an error happens, explain it with printurf, suggest a fix, and show the report." --error "NameError: name 'total' is not defined" --path app.py
```

Run a file and return JSON:

```bash
python -m shipmblang run --file program.shipmb --error-file traceback.txt --path src/ --format json
```

## Editor Workflow

ShipMBLang is designed to be written in a normal code editor.

1. Create a `.shipmb` or `.shiplang` file.
2. Write the program as natural language syntax.
3. Select the paragraph to compile or run, or leave nothing selected to use the
   whole document.
4. Run `ShipMBLang: Compile Natural Program` to inspect ShipMBLangCore.
5. Run `ShipMBLang: Run Natural Program` to execute the supported bytecode through
   the local runtime.

The VS Code extension in `extensions/vscode-shipmblang` calls the same local CLI
commands as the terminal workflow. Compile is preview-oriented. Run is
execution-oriented.

## More Examples

Open and index the current project:

```text
Use ShipMB. Open the current project and scan the codebase.
```

Expected Core:

```shiplang
use shipmb
project = open "."
project |> index
```

Explain an error and write the report:

```text
Use ShipMB. When an error happens, explain it with printurf and write the report.
```

Expected Core:

```shiplang
use shipmb
on error:
  error |> printurf
  write report to "shipmb-output.json"
```

Record a future run intent:

```text
Use ShipMB. Execute tests.
```

Expected Core:

```shiplang
use shipmb
run "tests"
```

In v0.1, the runtime records the run instruction as planned instead of launching
native commands by default.

## v0.1 Scope

ShipMBLang v0.1 should be understood as:

- a natural language syntax for describing programs end to end
- a deterministic compiler from natural syntax to ShipMBLangCore
- a deterministic bytecode emitter for ShipMBLang runtime instructions
- a local runtime for the supported bytecode operations
- a foundation for later native execution targets

It should not be described as a full native compiler yet. The current concrete
target is ShipMBLang bytecode. Native CPU code, OS process execution, or other
machine backends can come after the bytecode contract is stable.
