# tools/rea

Dev-only copy of `rea build-from-text` from the private fork
[qramarq/rea-forge](https://github.com/qramarq/rea-forge), a fork of
[morluto/rea](https://github.com/morluto/rea). The license is MIT. Copyright
(c) 2026 morluto. See [LICENSE](LICENSE).

Nothing in the shipmblang runtime, CLI, LSP, or compiler imports this
directory. It is not a package dependency. `MANIFEST.in` prunes it from the
sdist. PyInstaller is told to exclude `tools.rea`, and the Windows zip copy
skips any `tools/rea` path. Node and vitest run from this directory only.

## Pins

| Source | SHA |
| --- | --- |
| rea-forge pull request 11 head (`cursor/build-from-text-0dd8`) | `efefede93b934c5cd72bd2abe54a8ac827b50119` |
| rea-forge `main`, the pull request base | `7dd38664efa0db7bf075bfd58d08e580479ce245` |
| upstream morluto/rea | `1d343a88e53af51101a408d437641c60b7bb34e4` |

[SOURCE.txt](SOURCE.txt) is the fetch record. [FORK.md](FORK.md) is the fork
note from that tree. [SECURITY.md](SECURITY.md) and [DISCLAIMER.md](DISCLAIMER.md)
are the upstream texts.

`scripts/rea.mjs` here is a small standalone entry. It implements
`build-from-text` and does not load the rest of the REA CLI. The command
itself is [build-from-text/](build-from-text/). The user-facing description is
[docs/build-from-text.md](docs/build-from-text.md). An example spec is
[specs/textseg-frame.txt](specs/textseg-frame.txt).

## Run

From this directory, with Node.js:

```bash
node scripts/rea.mjs build-from-text --text build-from-text/fixtures/checksum.txt --out /tmp/checksum-spec
node scripts/rea.mjs build-from-text --text specs/textseg-frame.txt --out /tmp/textseg-spec
```

The mode's tests live in `build-from-text/*.test.ts`. From this directory,
with vitest available to Node:

```bash
npx vitest run --config build-from-text/vitest.config.ts
```

Paths in the copied docs are relative to this directory, not the shipmblang
repository root. The command does not use the network, emit telemetry, install
packages, or compile a binary.
