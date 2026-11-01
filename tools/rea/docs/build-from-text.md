# Build from plain text

`build-from-text` is a local mode of this fork. It reads a plain-text description of a binary or feature and writes three files:

| File               | What it is                                     |
| ------------------ | ---------------------------------------------- |
| `spec.schema.json` | A JSON Schema document extracted from the text |
| `PLAN.md`          | A build plan                                   |
| `skeleton.test.ts` | A vitest skeleton                              |

The mode is dispatched by `rea build-from-text` before the compiled analysis runtime. It uses only the local filesystem and the Node.js standard library.

## What this mode does not do

- It does not open a network connection or download the schema dialect.
- It does not emit telemetry.
- It does not install packages or compile a binary.
- It does not check that a declared entry file exists.
- It does not run `skeleton.test.ts`. Every generated case is `it.todo`.
- It does not change `SECURITY.md` or `DISCLAIMER.md`. Those upstream texts still apply.

`PLAN.md` says the plan has not been executed and that the acceptance tests have not been run. `$schema` in `spec.schema.json` is the JSON Schema draft 2020-12 dialect identifier. The command does not fetch that URL.

## Usage

```bash
node scripts/rea.mjs build-from-text --text path/to/spec.txt --out path/to/out
node build-from-text/cli.mjs --text path/to/spec.txt --out path/to/out
node build-from-text/cli.mjs --text - --out path/to/out < path/to/spec.txt
```

`--text -` reads stdin. `--help` prints usage and exits 0.

Exit status:

| Status | Meaning                                                         |
| ------ | --------------------------------------------------------------- |
| 0      | Help, or the three files were written                           |
| 1      | The text could not be extracted, or a file could not be written |
| 2      | The arguments were incomplete or unknown                        |

On success, stdout is a JSON object with `executed: false`, `network: false`, and `telemetry: false`. A failed extraction does not create the output directory.

## Plain text

Fields and sections are line-oriented. Blank lines are ignored. A leading BOM is ignored, and CRLF newlines are accepted. The text must be at most 1 MiB, each line at most 4000 characters, and the name at most 200 characters.

Scalar fields:

```text
Name: checksum
Kind: binary
Language: typescript
Entry: src/checksum.ts
Summary: Print a lowercase hex digest of a file.
```

`Title` is a synonym for `Name`. `Description` is a synonym for `Summary`. `Lang` is a synonym for `Language`. `Entrypoint` and `Entry point` are synonyms for `Entry`.

`Kind` is `binary`, `feature`, `library`, `module`, or `service`. When it is omitted, the spec records `unspecified`.

A level-one heading sets the name when `Name` is absent:

```text
# widget

A small feature.
```

Prose before the first section becomes the summary when `Summary` is absent.

Sections start with a heading or a label followed by a colon:

```text
Behavior:
- Read the first argument as a file path

Constraints:
- no network
- no telemetry

Inputs:
- path: string, required

Outputs:
- digest: string, required

Tests:
- missing path exits 2
```

`Behaviors`, `Constraints`, `Inputs`, `Outputs`, `Notes`, and `Acceptance` are accepted names. Markdown headings such as `## Behavior` start the same sections.

A typed field is `name: type` or `name: type, required`. A trailing `?` or the word `optional` makes it optional. Otherwise it is required. Types are `string`, `number`, `integer`, `boolean`, `object`, `array`, and `null`. Aliases: `str`, `text`, `float`, `double`, `int`, `bool`, and `list`.

`network` and `telemetry` are `forbidden`, `allowed`, or `unspecified`. Inside `Constraints`, phrases such as `no network`, `offline`, `no telemetry`, and `allow network` set the same values. A second, different value is an error. When the text does not say, the recorded value is `unspecified`, and the plan says to leave that channel out.

An example input is `build-from-text/fixtures/checksum.txt`.

## JSON Schema

When the text declares both inputs and outputs, the schema root is an object with required `input` and `output` objects. When it declares only one side, that side is the root. When it declares neither, the root is an object with no properties and `additionalProperties: false`.

Extracted behaviors, constraints, acceptance tests, kind, language, and entry are stored in the `x-build-from-text` annotation. `language` and `entry` are JSON `null` when the text did not set them.

## Plan and skeleton

`PLAN.md` repeats the extracted spec and lists local steps. It does not claim that a binary was produced or that tests passed.

`skeleton.test.ts` imports `describe` and `it` from `vitest` and emits one `it.todo` per acceptance test. If the text lists none, it emits a single placeholder todo. The file is source text for a later test run. This command does not execute it.

## Tests for this mode

The mode's own tests are in `build-from-text/*.test.ts`. From the repository root:

```bash
npx vitest run --config build-from-text/vitest.config.ts
```

Those tests cover extraction, schema shape, plan wording, the skeleton, the CLI, the `rea build-from-text` entry, and a source scan that rejects network client imports. They do not run generated skeletons and they do not claim upstream REA's full suite was run.
