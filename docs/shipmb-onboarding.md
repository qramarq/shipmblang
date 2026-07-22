# ShipMB onboarding integration

ShipMB should treat ShipMBLang as a local Python package with a stable readiness
command. The onboarding flow does not need to download model weights or run
training; the compiler, local bytecode runtime, `printurf`, and MCP entrypoint
are usable from the source checkout.

## Contract

From a ShipMB onboarding process, resolve the ShipMBLang checkout and install it
into the Python environment ShipMB will use:

```bash
python -m pip install -e C:/path/to/shipmblang
```

Then verify readiness:

```bash
python -m shipmblang onboarding --format json --check --root C:/path/to/shipmb-project
```

The command exits with code `0` only when all required checks pass. Its JSON
output includes:

- `status`: `ready`, `blocked`, or `metadata`
- `install.argv`: the exact editable-install command for this checkout
- `verify.argv`: the exact readiness command for this checkout
- `commands.compile`, `commands.run`, `commands.printurf`, `commands.mcp`
- `compiler_contract`, including the bytecode target, ShipMBLangCore naming,
  declaration/name-resolution rule, declaration pass, and runtime action order
- `mcp.command` and `mcp.args` for stdio MCP clients
- `environment` values ShipMB can record for later discovery
- `checks[]` with pass/fail details for import, compiler, runtime, printurf, and MCP

ShipMB can also read `shipmblang-onboarding.json` before installation if it
needs a static discovery file. The CLI manifest is authoritative after Python is
available.

The compiler contract exposed through onboarding is:

- target code is `shipmblang-bytecode`
- the readable Core surface is ShipMBLangCore
- declarations are resolved order-insensitively within a compilation unit
- compilers collect declarations before resolving references
- effectful runtime actions execute in final bytecode order

## Recommended ShipMB flow

1. Locate or clone ShipMBLang beside ShipMB, or accept an explicit
   `SHIPMBLANG_HOME`.
2. Choose the Python executable that ShipMB uses for local tooling.
3. Run `python -m pip install -e <shipmblang_root>`.
4. Run `python -m shipmblang onboarding --format json --check --root <shipmb_project_root>`.
5. Store `SHIPMBLANG_HOME`, `SHIPMBLANG_PYTHON`, and the MCP command from the
   manifest.
6. Register the MCP server with:

```json
{
  "command": "<python>",
  "args": ["-m", "shipmblang", "mcp"],
  "env": {
    "SHIPMBLANG_HOME": "<shipmblang_root>",
    "SHIPLANG_DEVICE": "cpu"
  }
}
```

New ShipMB callers should use these MCP tools:

- `printurf`
- `shipmblang_explain_error`
- `shipmblang_index_codebase`
- `shipmblang_list_device_families`
- `shipmblang_select_device_family`
- `shipmblang_get_device_resource`

## Local smoke test

Run this from the ShipMBLang repo root:

```bash
python tools/smoke_onboarding.py --python .venv/Scripts/python.exe --cwd .
```

The smoke test shells out to the same command ShipMB should call and validates
the manifest schema, readiness status, command contract, and check results.
