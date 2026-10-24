# Compiler sync

ShipMBLang vendors the compiler under `shipmblang/_compiler/`. The compiler
repository is private:
[qramarq/shipmblang-compiler](https://github.com/qramarq/shipmblang-compiler).
Its project directory is `shipmbcompiler/` and the import package is
`shipmbcompiler/shipmbcompiler/`. `tools/bundle_compiler.py` is pointed at that
project.

The two-way sync opens pull requests so those trees stay aligned. It does not
push to `main` and it does not force-push.

- Outbound copies `shipmblang/_compiler/**` into
  `shipmbcompiler/shipmbcompiler/` and opens a pull request on the compiler
  repository.
- Inbound adopts compiler changes that this snapshot has not edited and opens
  a pull request here. When both sides changed the same file, the sync stops
  and does not overwrite either side.

`shipmblang/_compiler/BUNDLED.json` records `source_commit` for the snapshot
that is already vendored. Staging a snapshot by hand is described in
[the bundle workflow](bundled-compiler.md).
