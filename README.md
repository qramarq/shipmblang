# ShipMBLang

Write supported English instructions in a `.shipmb` file and run them locally.
No AI model or API key is required. ShipMBLang currently supports a defined
programming grammar, not arbitrary English requests.

## Install

You need Python 3.11+ and Git. The language includes its compiler and runtime:

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
python -m shipmblang run --file hello.shipmb --pipeline direct --profile general --memory off
```

The JSON result contains `runtime.stdout` with the value `"12\n"`.
`--memory off` disables saving your program to local compiler memory.
If an instruction is unsupported or needs clarification, revise it and run again.

See [examples](examples/), [VS Code setup](extensions/vscode-shipmblang/README.md),
and the [language guide](docs/shipmblang.md) for more.

## License

Copyright 2026 ZMachinery LLC (zmachinery).

Licensed under the [Apache License, Version 2.0](LICENSE).
ZMachinery LLC owns the original ShipMB / ShipMBLang code, compiler, runtime,
documentation, and other intellectual property it created or acquired.
Third-party materials remain the property of their respective owners.
This license grants usage rights without transferring ownership or granting
trademark rights except as expressly provided in the license. See [NOTICE](NOTICE).
