#!/bin/sh
cd "$(dirname "$0")" || exit 1
PY=python3
command -v "$PY" >/dev/null 2>&1 || PY=python
"$PY" tools/try_language.py "$@"
status=$?
[ $status -ne 0 ] && echo "Tester exited with an error. See the message above." >&2
exit $status
