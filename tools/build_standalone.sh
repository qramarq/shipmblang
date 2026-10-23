#!/bin/sh
# Build the self-contained shipmblang executable for this operating system.
set -eu
cd "$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
if command -v python3 >/dev/null 2>&1; then
    exec python3 tools/build_standalone.py "$@"
fi
exec python tools/build_standalone.py "$@"
