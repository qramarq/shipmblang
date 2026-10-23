# Compiler sync

ShipMBLang vendors the compiler under `shipmblang/_compiler/`. The compiler
repository is private: [qramarq/shipmblang-compiler](https://github.com/qramarq/shipmblang-compiler).
Its git root contains the project directory `shipmbcompiler/` (`pyproject.toml`),
and the import package is `shipmbcompiler/shipmbcompiler/`. `tools/bundle_compiler.py`
is pointed at that project. Bundle path `X` is `shipmbcompiler/shipmbcompiler/X`
from the compiler git root.

Two workflows in this repository keep those trees aligned. They open pull
requests. They do not push to `main` and they do not force-push.

```text
shipmblang main                         shipmblang-compiler default branch
shipmblang/_compiler/**  --outbound-->  shipmbcompiler/shipmbcompiler/**
shipmblang/_compiler/**  <--inbound--   default-branch HEAD
```

## What you add once

### Secret

Name: `SHIPMBLANG_COMPILER_TOKEN`

Where: this repository → Settings → Secrets and variables → Actions → Secrets.

Token: a fine-grained personal access token.

- Resource owner: `qramarq`
- Repository access: `qramarq/shipmblang-compiler`
- Permissions:
  - Metadata: Read (required on every fine-grained token)
  - Contents: Read and write
  - Pull requests: Read and write

Optional, so pull requests opened in this repository run CI: also grant that
same token access to `qramarq/shipmblang` with Contents read/write and Pull
requests read/write. If you do not, the workflows fall back to the default
`GITHUB_TOKEN`. GitHub does not start `pull_request` workflows for a pull
request that `GITHUB_TOKEN` opened. Push an empty commit, or reopen the pull
request with your own account, to start CI. Inbound auto-merge is skipped in
that case because the checks would never start.

The workflows never run on `pull_request` or `pull_request_target`, so a fork
cannot read this secret.

### Variables

Same settings page, Variables tab. Both are optional.

| Name | Default when unset | Meaning |
| --- | --- | --- |
| `COMPILER_SYNC_AUTOMERGE` | enabled | Set to `false` to leave the compiler pull request open. Any other value, including empty, enables squash auto-merge. |
| `COMPILER_SYNC_INBOUND_AUTOMERGE` | disabled | Set to `true` to squash-merge the ShipMBLang pull request after checks. Any other value leaves it for review. |

Auto-merge also needs Settings → General → Allow auto-merge on the target
repository. If branch protection requires a review the token cannot supply, the
pull request stays open until that review lands. When the API refuses
auto-merge, the workflow leaves the pull request open and writes the reason in
the job summary.

### Optional instant inbound

Copy [compiler-sync/notify-shipmblang.yml](compiler-sync/notify-shipmblang.yml)
into the compiler repository as `.github/workflows/notify-shipmblang.yml`.
Create secret `SHIPMBLANG_DISPATCH_TOKEN` there (not in this repository): a
fine-grained PAT with Contents read/write on `qramarq/shipmblang` only. A push
to the compiler's default branch then sends `repository_dispatch`
`compiler-updated`. Without that file, inbound sync still runs every 30 minutes.

## How a change moves

Outbound (`.github/workflows/sync-compiler-upstream.yml`) runs on a push to
`main` that touches `shipmblang/_compiler/**`, and from Actions → Sync compiler
upstream → Run workflow.

It checks out `shipmblang-compiler`, copies bundle files back to
`shipmbcompiler/shipmbcompiler/`, and if normalized content differs, pushes
`sync/shipmblang-<shortsha>` and opens or updates a pull request titled
`Sync compiler changes from shipmblang@<shortsha>`. The body links the
ShipMBLang commit and any pull requests attached to it. Squash auto-merge is
requested unless `COMPILER_SYNC_AUTOMERGE` is `false`.

If `local_patches` does not list the files whose normalized content differs
from `source_commit`, it also opens or updates `sync/local-patches` in this
repository. That pull request changes only `BUNDLED.json` and
`apps/mobile/src/compiler-snapshot.json`.

Inbound (`.github/workflows/sync-compiler-downstream.yml`) runs every 30
minutes, on Run workflow, and on `repository_dispatch` type `compiler-updated`.
It plans a three-way merge of the snapshot, `source_commit`, and the compiler
default-branch HEAD:

- Same normalized text: keep the bytes already in the snapshot. `source_commit`
  advances and `local_patches` becomes `[]`. This is the usual result right
  after an outbound sync merges, including when only the manifest was stale.
- Upstream changed a file this snapshot did not: take the bundled form of the
  upstream file. Remaining hand edits stay in `local_patches`.
- This snapshot has edits upstream has not touched: do not overwrite them and
  do not move `source_commit`. Update `local_patches` if the list is wrong.
- Both sides changed the same file: fail the job and do not open a pull request.

A real adopt pushes `sync/compiler-<shortsha>` titled
`Sync compiler from shipmblang-compiler@<shortsha>`. A patch-list correction
reuses `sync/local-patches`. Before either pull request is pushed, the job runs
`tools/check_bundled_install.py --snapshot` and the unit tests against the
swapped tree.

## Line endings

`shipmblang/.gitattributes` marks `shipmblang/_compiler/**` as `-text`, then
forces LF for Python and for `BUNDLED.json`. The six HyperFrames text resources
(`bridge.mjs`, `package.json`, `package-lock.json`, `INTER-LICENSE.txt`,
`THIRD-PARTY.md`, `gsap.min.js`) are stored CRLF, and `BUNDLED.json` hashes
those CRLF bytes. `tools/bundle_compiler.py` LF-normalizes `.py` only. Upstream
stores five Python blobs as CRLF (`compiler.py`, `core.py`, `general_runtime.py`,
`runtime.py`, `source_format.py`) and the text resources as LF.

Copy-back compares LF-normalized text (binaries such as `.woff2` are compared
raw). An unchanged blob is not rewritten. A real edit is staged with Git
filters disabled, using the upstream blob's newline style, so the pull request
does not turn a line-ending difference into a full-file diff. Inbound keeps the
snapshot's bytes whenever normalized text matches, so those six resource hashes
do not change on every run.

## Loops

1. Neither workflow triggers on `pull_request` or `pull_request_target`.
2. Both use the concurrency group `shipmblang-compiler-sync` with
   `cancel-in-progress: false`. An in-progress sync finishes; a newer waiting
   run replaces an older one that has not started.
3. Outbound skips a push whose non-merge commits are downstream syncs or
   `local_patches` records. The marker lines are `Compiler-Sync: downstream`
   and `Compiler-Sync: local-patches`. The commit subjects
   `Sync compiler from shipmblang-compiler@…` and
   `Record compiler local_patches` count even when a squash merge drops the body.
4. Outbound also skips a push that only changes `BUNDLED.json` and
   `apps/mobile/src/compiler-snapshot.json`.
5. `workflow_dispatch` does not use that skip. It still opens a pull request
   only when normalized content differs.
6. Copy-back and the inbound plan compare normalized content, so a sync that
   only carried line endings does not bounce back.
7. Inbound will not replace local edits with older upstream bytes. After those
   edits merge upstream, the next inbound run is metadata only: `source_commit`
   becomes that HEAD and `local_patches` is cleared.
8. Branch names stay under `sync/`. The push refspec is explicit. A rejected
   push fails the job instead of force-pushing.

## First run

Merging the workflow does not touch `shipmblang/_compiler/**`, so outbound does
not run by itself. The eleven files from the general-english-0.10 edits are
already on `main`, and `local_patches` is still `[]` while `source_commit` is
`ecaf8078aa7507c2c4df44959adba6032aa65c80`. Run **Sync compiler upstream** once
from the Actions tab. The compiler pull request should contain only those
content edits:

- `core.py`
- `general_codegen.py`
- `general_english.py`
- `general_runtime.py`
- `hyperframes/compiler.py`
- `ir.py`
- `media_english.py`
- `runtime.py`
- `semantics.py`
- `target.py`
- `vlc_english.py`

The same run, or the next inbound schedule, records that list in
`local_patches` without rewriting the compiler bytes. After the compiler pull
request merges, inbound opens a ShipMBLang pull request that advances
`source_commit` and clears `local_patches`. Review that pull request
(`COMPILER_SYNC_INBOUND_AUTOMERGE` defaults off).

## How to disable

Actions → the workflow → ⋯ → Disable workflow. Removing the secret makes the
jobs fail, and the inbound schedule will fail every 30 minutes until the
workflow is disabled. Set `COMPILER_SYNC_AUTOMERGE` to `false` to keep opening
compiler pull requests without merging them.

## Manual equivalent

`tools/compiler_sync.py` is what the workflows call.

```powershell
python tools/compiler_sync.py locate C:\path\to\shipmblang-compiler
python tools/compiler_sync.py copy-back --snapshot shipmblang/_compiler --project C:\path\to\shipmblang-compiler
python tools/compiler_sync.py local-patches --snapshot shipmblang/_compiler --project C:\path\to\shipmblang-compiler --apply --pin apps/mobile/src/compiler-snapshot.json
python tools/compiler_sync.py plan-inbound --snapshot shipmblang/_compiler --project C:\path\to\shipmblang-compiler --commit <40-hex-head> --output C:\path\to\empty-dir
```

`copy-back` prints the git paths it changed. Stage those with
`python tools/compiler_sync.py stage-exact` so Git does not renormalize
newlines. `plan-inbound` writes `plan.json` and, unless the trees are already
reconciled, a `candidate/` directory. Install that candidate only after
`python tools/check_bundled_install.py --snapshot` and the test suite pass.
