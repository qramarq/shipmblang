# ShipMBLang

Write English requests in a `.shipmb` file and run them locally. Broader English
translation is the default: supported grammar compiles directly, and other wording
uses your configured model to produce English that the existing compiler validates.
The bytecode formats and runtimes remain unchanged.

No model or API key is required for the deterministic grammar. Broader wording
requires a configured local or hosted model; unsupported operations and missing
information produce diagnostics or clarification questions, never placeholder code.

## Install

You need Python 3.11+ and Git. The language includes its compiler and runtime
internally; no separate compiler installation or compiler command is needed:

```sh
git clone https://github.com/qramarq/shipmblang.git
cd shipmblang
python -m pip install .
```

## Run a program

Save this as `hello.shipmb`:

```text
"Start with total at 4, then add 8 to total and show total."
```

Run it:

```sh
python -m shipmblang run --file hello.shipmb --memory off
```

The JSON result contains `runtime.stdout` with the value `"12\n"`.
`--memory off` disables saving your program to local compiler memory.
If an instruction is unsupported or needs clarification, revise it and run again.

## Broader English

Reviewed contextual wording also works offline: `Present the sum of 2 and 3.`,
`Could you add 2 and 3 together and tell me the result?`, and
`Compute the aggregate of 2 and 3.` each output `5`. Quoted text and variable
names retain their spelling; arithmetic `add` never becomes package installation.
See [contextual vocabulary](docs/contextual-vocabulary.md) for supported forms
and ambiguity limits. Broader requests sent to your configured model, including
Qwen, receive relevant reviewed vocabulary hints alongside the original request.

Configure an existing model endpoint once (PowerShell example):

```powershell
$env:SHIPMB_MODEL_PROVIDER = "openai_compatible"
$env:SHIPMB_MODEL_BASE_URL = "http://127.0.0.1:11434/v1"
$env:SHIPMB_MODEL_NAME = "your-installed-model"
python -m shipmblang run "Add the odd numbers in 2, 5, 8, and 11 and show the total." --memory off
```

Requests needing translation are sent to that endpoint. The compiler checks the
translation and compiles it by default. JSON retains the original request and the
interpretation; bytecode-only output prints the interpretation to stderr. Type
and syntax validation cannot prove that a model preserved the intended meaning.

Use `--review-model-interpretation` to review a proposal, then supply the intended
English with `--interpretation`. Use `--no-english-model` for deterministic-only
compilation. The default pipeline is `direct` with the `general` profile. Explicit
legacy pipelines remain available; Core output requires `--pipeline legacy`.

Python callers use `compile_direct_program(text)` or `run_direct_program(text)`
for the same defaults. Pass `model_provider=None` to disable translation, or
`accept_model_interpretation=False` to review it. The older
`compile_natural_program` / `run_natural_program` APIs retain their legacy schema.

See [examples](examples/), [VS Code setup](extensions/vscode-shipmblang/README.md),
and the [language guide](docs/shipmblang.md) for more.

## Multi-paragraph requests

Put the full request in one `.shipmb` file, separating paragraphs with blank lines.
ShipMBLang processes them as one program, so later paragraphs can refer to earlier
values and add constraints. Broader wording uses your configured model; the whole
translated program is validated before execution. Unsupported operations or
unresolved questions block execution of the entire program.

Run it with `python -m shipmblang run --file program.shipmb`. Use
`--review-model-interpretation` to review a model translation before compiling it.

## License

Copyright 2026 ZMachinery LLC (zmachinery).

Licensed under the [Apache License, Version 2.0](LICENSE).
ZMachinery LLC owns the original ShipMB / ShipMBLang code, compiler, runtime,
documentation, and other intellectual property it created or acquired.
Third-party materials remain the property of their respective owners.
This license grants usage rights without transferring ownership or granting
trademark rights except as expressly provided in the license. See [NOTICE](NOTICE).

## Compiler updates for maintainers

Compiler changes are developed and pushed in the compiler repository; language
changes are developed and pushed in this language repository. Each language
release bundles a selected compiler snapshot so users install only ShipMBLang.
See [the bundle update and verification workflow](docs/bundled-compiler.md).
