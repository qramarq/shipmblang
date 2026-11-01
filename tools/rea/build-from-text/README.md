# build-from-text

Local plaintext-to-build mode for this fork of [morluto/rea](https://github.com/morluto/rea).

It extracts a JSON Schema, a plan file, and a vitest skeleton from plain text. It does not use the network, emit telemetry, compile a binary, or run the skeleton.

The user-facing description is [docs/build-from-text.md](../docs/build-from-text.md). An example input is [fixtures/checksum.txt](fixtures/checksum.txt).

```bash
node scripts/rea.mjs build-from-text --text build-from-text/fixtures/checksum.txt --out /tmp/checksum-spec
```

Upstream [SECURITY.md](../SECURITY.md) and [DISCLAIMER.md](../DISCLAIMER.md) are unchanged and still apply. The MIT license and copyright remain in [LICENSE](../LICENSE).
