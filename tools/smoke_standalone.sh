#!/bin/sh
# Run the built executable with Python removed from PATH.
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
if [ -f "$root/dist/shipmblang.exe" ]; then
    bin="$root/dist/shipmblang.exe"
elif [ -f "$root/dist/shipmblang" ]; then
    bin="$root/dist/shipmblang"
else
    echo "No standalone executable in dist/. Run tools/build_standalone.py first." >&2
    exit 1
fi
empty=$(mktemp -d)
trap 'rm -rf "$empty"' EXIT

to_native() {
    if command -v cygpath >/dev/null 2>&1; then
        cygpath -w "$1"
    else
        printf '%s' "$1"
    fi
}

empty_path=$(to_native "$empty")
bin_native=$(to_native "$bin")
example=$(to_native "$root/examples/quoted_paragraph.shipmb")
database=$(to_native "$empty/notes.sqlite3")

hash -r 2>/dev/null || true
if PATH="$empty_path" command -v python >/dev/null 2>&1 || PATH="$empty_path" command -v python3 >/dev/null 2>&1; then
    echo "Python is still visible on the smoke-test PATH." >&2
    exit 1
fi

run_bin() {
    # MSYS_NO_PATHCONV keeps Git Bash from rewriting the Windows paths we already converted.
    env -u PYTHONPATH -u PYTHONHOME -u VIRTUAL_ENV MSYS_NO_PATHCONV=1 PATH="$empty_path" "$bin_native" "$@"
}

out=$(run_bin run --file "$example" --pipeline direct --profile general --memory off)
printf '%s\n' "$out"
printf '%s\n' "$out" | grep -q 12

run_bin --help >"$empty/help.out"
grep -q "program.shipmb" "$empty/help.out"

short=$(run_bin "$example")
printf '%s\n' "$short" | grep -q 12

set +e
run_bin train >"$empty/train.out" 2>"$empty/train.err"
code=$?
set -e
if [ "$code" -eq 0 ]; then
    echo "train should fail in the standalone executable." >&2
    exit 1
fi
grep -q "PyTorch" "$empty/train.err"

printf '%s\n' '{"action":"list","query":""}' | run_bin -X utf8 -m shipmblang.editor_bridge --database "$database" >"$empty/bridge.out"
grep -q '"ok": true' "$empty/bridge.out"

echo "standalone smoke test passed: $bin"
