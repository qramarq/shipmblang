# One installation, separate development

## HyperFrames integration (2026-09-23)

The HyperFrames compiler was added as an independently verified component from
the compiler's 0.3.0 working source. This integration adds only the 11 files under
`hyperframes/`: four Python modules, the Node bridge and its two package manifests,
and four browser/vendor resources. It does not replace bytecode compiler modules.
`BUNDLED.json` records every resource hash and `components.hyperframes` records
the component's source version and file list. A concurrent FFmpeg integration
owns any separate base-compiler update.

Nested JS/MJS, fonts and third-party notices are included in language wheels.
Node dependencies and Python caches are excluded from snapshot staging. Renderer
dependencies are an explicit user installation, never a compilation side effect.
See [HyperFrames usage](hyperframes.md) for commands and setup.

The clean-wheel checker compiles a video source through the installed language
CLI, writes the standalone project without Node dependencies, and verifies every
manifest hash in the wheel. Real renderer/media checks are compiler-owned; the
language tests check delegation, diagnostics, source-relative media roots, error
exit codes and the explicit compile/render boundary.

## Development workflow

Users install only ShipMBLang (Python 3.11+). Every language wheel contains its
compiler and runtime under `shipmblang._compiler`. There is no dependency on the
separate compiler distribution, top-level `shipmbcompiler` package, or `shipmbc`
command. The internal namespace is an implementation detail, not a supported
public API. Python source remains inspectable.

Develop and push compiler changes in the compiler repository. Develop and push
language changes in the language repository. Do not edit the bundled snapshot as
the source of truth. After user approval of a tested compiler snapshot,
run these commands from the language project (the folder with pyproject.toml):

```powershell
python tools/bundle_compiler.py C:/path/to/shipmbcompiler --output C:/path/to/new-candidate
python tools/check_bundled_install.py --snapshot C:/path/to/new-candidate
python -m unittest discover -s tests
python tools/check_bundled_install.py
```

The packaging check needs setuptools, wheel, and pip in the development Python.
It builds a wheel in a temporary folder, installs only that wheel into a clean
environment without network access, and checks public API and CLI execution.
It also checks that no public compiler package or compiler launcher is installed.

The staging tool copies compiler modules without changing their relative imports
or bytecode formats. `shipmblang/_compiler/BUNDLED.json` records the upstream
version and SHA-256 of each source file. Review the snapshot and manifest diff,
then commit them with the language release. Language and compiler versions can
advance independently; a language release keeps its selected snapshot until the
next explicit update. Runtime never downloads or upgrades the compiler.

Build and distribute the language wheel from this project after verification.
Older `output/*publish` directories are historical staging copies; they do not
automatically receive changes made here.

## English understanding integration gates (2026-09-23)

Compiler owns grammar, contextual senses, semantic validation, clarification
protocol, provenance, canonical conformance corpus, and the Buzz review queue.
Language owns presentation, provider forwarding, packaging and snapshot parity.
Do not implement a second interpretation engine or edit the vendored compiler.
Prefer offline parsing, with configured local Qwen as fallback. The intended
ambiguity policy is a focused question plus a validated suggested interpretation
when available; unresolved meaning produces no runnable artifact. Answers must
be source-revision-bound, preserve original prose/history, and be recompiled.
Confirmation of meaning does not authorize execution. These protocol changes
remain compiler-owned work, not claims about the current 0.2.4 snapshot.

Dictionary facts, reviewed executable phrase rules, confirmed memory and model
training are distinct. No fine-tuning is planned. New phrasing for an existing
operation is separate from introducing a new runtime capability.

Prepare proposed updates in a new candidate directory using mandatory `--output`.
The bundle tool rejects existing destinations and the approved snapshot. Include
each compiler-owned data/license file using repeated `--resource package/path`.
The install checker accepts `--snapshot` and substitutes it only in a temporary
build copy. Keep the approved checkout intact. User
approval gates integration and releases; do not merge, publish, or auto-upgrade.

The future understanding bundle must include compiler source, reviewed aliases,
pinned Open English Wordnet 2025 SQLite data, attribution/license, protocol and
matching compiler-owned corpus identities. Compilation must never fetch data.
The bundler copies Python plus explicitly selected package-relative resources;
wheel patterns cover nested JSON, SQLite, text, LICENSE and NOTICE files.
The final resource selection and vocabulary/protocol identities still need the
compiler's contract. Do not treat fixture packaging as dictionary integration.
Hash all resources and verify their presence in the wheel; an unrecognized file
extension will fail that gate until package-data explicitly supports it.

Current verification commands (no snapshot replacement):

```powershell
python tools/verify_bundle.py shipmblang/_compiler
python -m unittest discover -s tests -p test_snapshot_conformance.py
python tools/check_bundled_install.py
```

The adapter fixtures compare the public API with a separately imported copy of
the exact bundled bytes, using memory off, models disabled or identical injected
proposals. They compare full results including spans and diagnostics. They are
integration fixtures, not a competing semantic corpus or evidence of broad prose
readiness. Consume the matching compiler-owned corpus when available. Test
memory/project isolation and invalidation separately when that contract lands.

Verified baseline: compiler 0.2.4, 26 files, manifest SHA-256
`8f65b32d78a711c1bf5ee01f1457192dceb29f18b93957c661ad81a7734bb8da`.
“Show the sum of 2 and 3.” compiles; “Present the sum of 2 and 3.” is unsupported;
“Show it.” requires clarification. Quoted words remain literal. Do not compare
this selected snapshot to moving compiler HEAD as an equality requirement.

For each proposed snapshot, report before/after behavior, distinguishing inputs,
counterexamples, test evidence, limitations and exact bundle identity. Report
semantic outcomes, clarification behavior, attempted model calls (including
failures), and offline/model latency. Live model evaluation must record settings;
do not claim measured performance from injected proposals. Broad prose readiness
requires the reviewed compiler corpus and independently authored human examples;
generated fixtures are not human evidence. Buzz work remains a bounded approved
queue; no scheduled service is authorized by this integration groundwork.

First review item: manifest integrity and approved-snapshot adapter parity.
Owned files are `tools/verify_bundle.py`, `tools/check_bundled_install.py`,
`tests/test_snapshot_conformance.py`, and this document. Five focused tests pass.
The clean offline wheel installation, API and CLI check passes using the bundled
development Python. Default-Python unittest discovery ran 71 entries with one
skip and one import error: existing `test_slang.py` requires pytest, which is
absent from both available runtimes. Therefore the complete suite is not claimed
green. Remaining dependencies are the compiler's canonical corpus and resource/
provenance contract. No approved snapshot bytes were replaced.

Second review item: isolated candidate staging and explicit resource packaging.
Additional owned files are `tools/bundle_compiler.py`, `pyproject.toml`, and
`tests/test_bundle_staging.py`. Four staging tests pass (nine focused tests total).
A temporary copy of the approved snapshot plus three clearly synthetic nested
resources (`data/words.sqlite`, `data/LICENSE`, `data/corpus.json`) passed wheel
hash verification, clean offline installation, and API/CLI execution. This tests
resource transport, not SQLite contents or dictionary semantics. The temporary
candidate was discarded; the approved 26-file manifest remains unchanged.

## Contextual vocabulary integration (2026-09-23)

The selected compiler snapshot now includes grammar `general-english-0.6` and
vocabulary `contextual-general-2` from tested compiler commit
`db568cee173f9e74da9a07936022f75c935cedfc`. The 27-module manifest SHA-256 is
`aa2a44dbd86c277affe80f6506d790f12448a0b6bf60d1e1866b4f855f668da1`.
Python snapshot bytes use LF before hashing so Git checkout does not invalidate
integrity records. New [contextual vocabulary](contextual-vocabulary.md) describes
the bounded executable senses and examples.

The three reported forms now execute offline and output 5. Public API/CLI tests
cover source preservation, literal data, identifier senses, ambiguous targets,
negation and constraints. A local fixture endpoint verifies relevant reviewed
hints and the unchanged request reach the configured provider. These are
transport tests, not evidence of live Qwen semantic accuracy.

Verification: 65 tests pass in the publish checkout. The active source's existing
virtual environment runs 88 tests successfully, with 3 skips and 51 successful
subtests. Both clean offline wheel installations pass. The publish-wheel check
also verifies every manifest hash and runs the new vocabulary through installed
API and CLI entry points. Earlier baseline results above describe the previous
snapshot; they are not the behavior of this integrated snapshot.

## FFmpeg integration (2026-09-23)

The selected base is compiler 0.3.0, grammar `general-english-0.7`, from the tested
compiler working tree. It adds `ffmpeg.py`, `ffmpeg_catalog.py`, and
`media_english.py`; no non-Python FFmpeg resources are required. The concurrent
HyperFrames component's 11 files, hashes and `components.hyperframes` provenance
were preserved. The combined 41-file manifest SHA-256 is
`32bfd591cc3145fbe17f66e1a8812994a0856fb27af956698a974775da86475e`.
The preceding commit identity describes the older vocabulary snapshot, not this
uncommitted compiler working tree. File hashes identify the selected bytes.

Media statements now compile through the default general pipeline as bytecode
0.4; computation remains bytecode 0.3. The language CLI supports
`--ffmpeg-path`, `--ffprobe-path`, and `--ffmpeg-timeout`. `compile` processes no
media; `--run` or `run` opts into execution. Python callers supply the public
`FFmpegExecutor` explicitly. See [media programs](ffmpeg.md).

Validation: 8 language adapter tests and 35 existing pipeline tests pass. The
real installed-binary test compiles with a nonexistent executable without writing
outputs, then runs a function inside a loop to produce two source-relative media
files. ffprobe confirms their dimensions. Repeating the run fails with exit code
1 and leaves existing output bytes unchanged. The documented transcode example
compiles deterministically with no diagnostics. The combined candidate passes
the isolated offline wheel gate, including media API/CLI compilation, missing
executor rejection, computation execution, every bundle hash, and the installed
HyperFrames CLI. No release was published.

Final combined live-package verification: 120 tests passed, 10 skipped, and 63
subtests passed, with both executable environment variables set so the real
FFmpeg test ran. The final clean offline wheel gate also passed against the live
41-file snapshot, including the installed HyperFrames CLI and all manifest hashes.

Broader English uses reference FFmpeg knowledge and may lazily query installed
help when model translation is needed. These integration checks do not claim
live-model semantic accuracy or support for every codec in every FFmpeg build.

## Published snapshot compatibility

The manifest records the upstream compiler commit in `source_commit`; Python
files are normalized to LF before hashing. When refreshing the snapshot, update
`apps/mobile/src/compiler-snapshot.json` with its version, commit and the SHA-256
of `json.dumps(manifest, sort_keys=True)`. The authenticated mobile service
verifies these pins before execution. Keep the mobile client and service on the
same snapshot.
