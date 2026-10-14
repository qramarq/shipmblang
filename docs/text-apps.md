# Terminals, Notepad, and notes

These workflows use the same Python runtime as the VS Code extension. Run
commands from the project directory containing `pyproject.toml`, or install it
with `python -m pip install .` to use it elsewhere (Python 3.11 or newer).

## Terminal

```powershell
python -m shipmblang run 'Pls show me the total of 2 and 3.' --format text --memory off
```

This prints `5`. Use `compile` instead of `run` to inspect bytecode, or use
`--format json` for the full source, interpretation, and diagnostics.

## Notepad and saved plain-text notes

Save this program as UTF-8 in `my notes.txt` or `my notes.shipmb`:

```text
Present the sum of 2 and 3.
Present "Keep this quotation exactly as written.".
```

```powershell
python -m shipmblang run --file "my notes.txt" --format text --memory off
```

The extension does not determine whether the file can run; its contents do.
Save edits before running the command again.

## Selected text from a note-taking app

Copy the program text, then explicitly run this in PowerShell:

```powershell
$OutputEncoding = [System.Text.UTF8Encoding]::new()
Get-Clipboard -Raw | python -X utf8 -m shipmblang run --file - --format text --memory off
```

`--file -` reads standard input, so other applications can pipe selected text
to the compiler without creating a temporary file. On a UTF-8 Unix terminal:

```bash
printf '%s\n' 'Present the sum of 2 and 3.' | python -m shipmblang run --file - --format text --memory off
```

Copy only program instructions, excluding Markdown fences, headings, and other
note content. This is a clipboard/file workflow, not an installed app plugin;
in-app Run buttons, highlighting, and inline diagnostics need separate adapters.

## Google Keep, NotebookLM, and Google Colab

For Google Keep and NotebookLM, copy the note's program instructions and use
the clipboard command above, or paste them into the Colab notebook below.
This does not sync your account or execute an entire notebook's sources.

Open [text_apps_colab.ipynb](../examples/text_apps_colab.ipynb) using Colab's
File > Upload notebook. ZIP the project folder containing `pyproject.toml`,
`shipmblang/`, and `driplm/`; upload that ZIP when the setup cell asks for it.
Run the setup cell, edit the program cell, and run the final cell to see output
or diagnostics. The notebook uses your current project build, with model
translation and memory capture disabled. Installation needs network access for
Python build tools. Files and text uploaded to Colab run in Google's environment.

See Google's [Colab FAQ](https://research.google.com/colaboratory/faq.html)
for notebook upload instructions.

## English, quotations, and slang

All these entry points share the existing compiler grammar and reviewed
contextual vocabulary. Quoted string data retains its wording. Supported prose
and abbreviations such as `Pls show me the total of 2 and 3.` work offline.
Arbitrary prose and slang are not guaranteed executable; unresolved wording can
use a configured model, or return diagnostics and clarification questions.
Use `--no-english-model` for deterministic-only parsing.

Successful general-profile runs with `--format text` print the program's output.
Unsuccessful compilations retain JSON diagnostics and a nonzero exit status;
profiles without textual stdout retain their JSON results. `--memory off`
disables local compiler capture for these examples.
