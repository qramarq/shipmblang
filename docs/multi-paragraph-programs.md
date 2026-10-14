# Multi-paragraph programs

Requires shipmblang 0.2.1+, shipmbcompiler 0.2.3+ (below 0.3), Python 3.11+,
and the direct/general pipeline. VS Code extension 0.3.1 includes the matching
integration tests. Core is not required.

## Structure and scope

A program is one complete source document. Paragraph breaks organize that
program; they do not reset variables, start a new process, or close a scope.
Use either one pair of double quotes around the entire document, including its
blank lines, or a pair around each block with a blank line between blocks.
Straight double quotes and smart double quotes are supported. Text strings inside
instructions remain text, including words such as `then` or `and`.

```text
“Start with total at 4.”

“Add 8 to total.”

“Show total.”
```

This prints `12`. The value declared in the first paragraph remains available in
the following paragraphs. Ordinary unquoted supported syntax remains valid.

Use explicit names when more than one value could match `it` or `the result`.
Ambiguous references require clarification; paragraph order is not permission to
guess which value you meant.

## Conditions, loops, and functions

Paragraph boundaries do not replace `End the condition.`, `End the loop.`, or
`End the function.`. Blocks can continue into later paragraphs until their
explicit closing statement. Their normal variable visibility rules still apply;
paragraph breaks do not make a function's local variables global.

[The nested example](../examples/multiple_paragraphs.shipmb) declares a list and
an accumulator in one paragraph, uses an `If` inside a `For each` in the next,
and displays the accumulated `27` in the final paragraph.

[The function example](../examples/paragraph_functions.shipmb) defines a recursive
factorial function in one paragraph and invokes it in another, producing `720`.
Recursion and loops remain subject to compiler/runtime resource limits.

Complexity means combining supported operations, types, control flow, and
functions. It does not imply that any free-form paragraph can synthesize an
arbitrary website, database, network service, or other unimplemented capability.

## Whole-program validation and diagnostics

The compiler validates the complete submitted program before producing a runnable
artifact. A missing value, ambiguous reference, malformed quote/block, or
unsupported instruction in a later paragraph prevents successful compilation.
The language runner does not execute the valid prefix of a rejected program.
A runtime failure in an otherwise valid artifact is a different case; compilation
validation does not promise transactional rollback of execution.

The language/editor boundary preserves the original Unicode text, blank lines,
and LF or CRLF line endings. Diagnostic offsets therefore refer to the submitted
source rather than a rewritten paragraph. VS Code maps those offsets into its
UTF-16 editor positions. Editing clears old diagnostics. Clarification answers
are tied to the selected source snapshot; changing the document while entering
an answer requires another clarification submission.

In VS Code, run the whole file with no selection to include earlier definitions.
Selecting only a later paragraph submits just that selection, so values from
unselected paragraphs will not exist in that submission. **Clarify and Run**
requires a complete restatement, including the definitions and operations you
want preserved across paragraphs.

## Verify changes to either project

These are durable regression requirements for both repositories:

- Shared values across paragraphs and functions called from later paragraphs.
- A condition nested inside a loop, including blocks crossing quote boundaries.
- Both quote layouts and both LF/CRLF line endings.
- Exact original Unicode source and later-paragraph diagnostic locations.
- Ambiguity and unsupported later instructions reject the whole compilation.
- VS Code submits the same source as the API/CLI, including unsaved buffers.

From the language checkout, after installing both packages:

```powershell
& .venv/Scripts/python.exe -X utf8 -I tools/check_paragraphs.py .
```

The check uses installed packages from temporary working directories, tests API
and CLI execution and failures, and needs no network, device access, or model.
The broader `tools/check_compiler_coinstall.py <compiler-package-root>` builds
and tests both installation orders and invokes the paragraph checks. Supply
`SHIPMB_CODE_EXE` to also run the real VS Code extension-host suite, which checks
multi-paragraph execution, clarification, and later-paragraph Problems locations.
The compiler repository maintains parser, scope, and CLI regression tests for
the same contract.
