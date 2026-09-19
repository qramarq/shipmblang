# Terminals and IDEs

The supported command boundary is the installed Python package. Use the same interpreter in your terminal and editor. Legacy compilation supports Python 3.10+; direct/general requires Python 3.11+ and the separately installed shipmbcompiler >=0.2.1,<0.3 package. Install from the two private checkouts, preserving their package roots and licenses; neither requires the Core repository at compilation time.

## Terminal

From any project directory after installation:

```text
python -m shipmblang compile --file "program with spaces.smb" --pipeline direct --profile general --format json --memory off
python -m shipmblang run --file "program with spaces.smb" --pipeline direct --profile general --memory off
```

The console commands `shipmblang`, `shipmb`, `shipmblang-compile`, `shipmb-compile`, and `shiplang-compile` use the same package. The corresponding run aliases also remain available. Use `python -m shipmblang` if console scripts are not on PATH. For an interpreter path containing spaces, PowerShell needs its call operator:

```powershell
& "C:/path to/venv/Scripts/python.exe" -X utf8 -m shipmblang run --file "program.shipmb" --pipeline direct --profile general --memory off
```

General run output is JSON with `runtime.stdout` and `runtime.output`; it is not a claim of native-machine-code generation. Exit 0 means success, exit 1 reports failed/unsupported/clarification or runtime diagnostics, and exit 2 reports invocation/setup errors on the direct path. JSON compiler diagnostics retain source spans in Unicode code-point offsets. Existing legacy output/defaults remain compatible. File-based input avoids shell quoting changes to prose. `-X utf8` is useful for non-ASCII terminal environments.

## Other IDEs

Configure an external tool with the interpreter as the executable and arguments `-m shipmblang compile --file <current-file> --pipeline direct --profile general --format json --memory off`. Set the working directory to the project's root; pass the filename as one argument, using your IDE's current-file variable. A second tool replaces `compile` with `run`. Save the file before invoking file-based tools.

Any IDE that can invoke a process can use this boundary. Native Problems, completion and debugging depend on that editor's integration; no cross-editor language-server support is claimed.

## VS Code

See [extension setup](../extensions/vscode-shipmblang/README.md). The extension reads the current editor buffer directly, handles paths with spaces, maps compiler spans into Problems, and keeps existing printurf commands.

## Validation

Python regression tests: `python -m unittest discover -s tests`. Extension process tests: `node --test extensions/vscode-shipmblang/test/runner.test.js`. `tools/check_compiler_coinstall.py <compiler-package-root>` verifies installed distributions from unrelated directories, aliases, Unicode source, paths with spaces and general/function execution. Set `SHIPMB_CODE_EXE` to an installed VS Code executable to include the real extension-host test in a temporary editor profile. CI covers Windows, Linux and macOS; a configured CI matrix is not evidence that every platform has already run.
