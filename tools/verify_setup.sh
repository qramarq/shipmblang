#!/bin/sh
# Exercise shipmblang setup on a built standalone executable.
# Smoke-testing the quoted paragraph stays in tools/smoke_standalone.sh and must run first.
set -eu

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
if [ -f "$root/dist/shipmblang.exe" ]; then
    bin="$root/dist/shipmblang.exe"
elif [ -f "$root/dist/shipmblang" ]; then
    bin="$root/dist/shipmblang"
else
    echo "No standalone executable in dist/." >&2
    exit 1
fi

to_native() {
    if command -v cygpath >/dev/null 2>&1; then
        cygpath -w "$1"
    else
        printf '%s' "$1"
    fi
}

bin_native=$(to_native "$bin")
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

run_setup() {
    # shellcheck disable=SC2086
    MSYS_NO_PATHCONV=1 "$bin_native" setup "$@"
}

os_name=$(uname -s)
case "$os_name" in
    Linux) family=linux ;;
    Darwin) family=darwin ;;
    MINGW*|MSYS*|CYGWIN*) family=windows ;;
    *)
        echo "Unsupported OS for setup verification: $os_name" >&2
        exit 1
        ;;
esac

echo "== setup --check =="
set +e
run_setup --check >"$tmp/check.out" 2>&1
check_code=$?
set -e
cat "$tmp/check.out"
for name in rust ffmpeg vlc ollama; do
    if ! grep -q "$name" "$tmp/check.out"; then
        echo "setup --check did not mention $name" >&2
        exit 1
    fi
done
if grep -q ': missing' "$tmp/check.out"; then
    if [ "$check_code" -eq 0 ]; then
        echo "setup --check reported a missing tool but exited 0." >&2
        exit 1
    fi
fi

echo "== setup --dry-run =="
run_setup --dry-run >"$tmp/dry.out" 2>&1
cat "$tmp/dry.out"

require_if_missing() {
    label=$1
    pattern=$2
    if grep -q "^${label}: missing" "$tmp/check.out"; then
        if ! grep -E -q "$pattern" "$tmp/dry.out"; then
            echo "dry-run for missing $label did not match: $pattern" >&2
            exit 1
        fi
    fi
}

case "$family" in
    linux)
        require_if_missing rust 'sh.rustup.rs'
        require_if_missing ffmpeg 'apt-get'
        require_if_missing vlc 'apt-get'
        require_if_missing ollama 'ollama.com/install.sh'
        ;;
    darwin)
        require_if_missing rust 'sh.rustup.rs'
        require_if_missing ffmpeg 'brew install ffmpeg'
        require_if_missing vlc 'cask vlc'
        require_if_missing ollama 'ollama.com/install.sh'
        ;;
    windows)
        require_if_missing rust 'Rustlang.Rustup|win.rustup.rs'
        require_if_missing ffmpeg 'Gyan.FFmpeg.Essentials|ffmpeg-master-latest-win64-lgpl'
        require_if_missing vlc 'VideoLAN.VLC|download.videolan.org'
        require_if_missing ollama 'Ollama.Ollama|OllamaSetup.exe'
        ;;
esac

echo "== setup --yes --skip ollama =="
run_setup --yes --skip ollama

echo "== verify ffmpeg, ffprobe, vlc, and cargo =="
run_setup --check --only ffmpeg
run_setup --check --only vlc
run_setup --check --only rust

python - <<'PY'
import json, os, pathlib, subprocess, sys
if os.name == "nt":
    path = pathlib.Path(os.environ["LOCALAPPDATA"]) / "ShipMBLang" / "tools.json"
else:
    root = pathlib.Path(os.environ.get("XDG_DATA_HOME", pathlib.Path.home() / ".local" / "share"))
    path = root / "ShipMBLang" / "tools.json"
data = json.loads(path.read_text(encoding="utf-8"))
for key, args in (("ffmpeg", ["-version"]), ("ffprobe", ["-version"]), ("cargo", ["--version"])):
    binary = data.get(key) or ""
    if not binary:
        sys.exit(f"missing {key} in {path}")
    print(f"== {binary} {' '.join(args)} ==")
    completed = subprocess.run([binary, *args], check=False)
    if completed.returncode != 0:
        sys.exit(completed.returncode)
vlc_dir = pathlib.Path(data.get("vlc_dir") or "")
names = ("libvlc.so.5", "libvlc.dll", "libvlc.dylib", "libvlc.5.dylib")
if not vlc_dir.is_dir() or not any((vlc_dir / name).is_file() for name in names):
    sys.exit(f"No LibVLC 3.x library in {vlc_dir}")
print(f"LibVLC directory: {vlc_dir}")
PY

if [ "$family" = "linux" ]; then
    echo "== ollama dry-run and install =="
    run_setup --dry-run --only ollama >"$tmp/ollama-dry.out"
    cat "$tmp/ollama-dry.out"
    grep -q 'ollama.com/install.sh' "$tmp/ollama-dry.out"
    run_setup --yes --only ollama
    python - <<'PY'
import json, os, pathlib, subprocess, sys
root = pathlib.Path(os.environ.get("XDG_DATA_HOME", pathlib.Path.home() / ".local" / "share"))
data = json.loads((root / "ShipMBLang" / "tools.json").read_text(encoding="utf-8"))
binary = data.get("ollama") or ""
if not binary:
    sys.exit("missing ollama in tools.json")
print(f"== {binary} --version ==")
subprocess.run([binary, "--version"], check=False)
PY
    ok=0
    attempt=0
    while [ "$attempt" -lt 15 ]; do
        if curl -fsS http://127.0.0.1:11434/api/version; then
            ok=1
            break
        fi
        attempt=$((attempt + 1))
        sleep 2
    done
    if [ "$ok" -ne 1 ]; then
        echo "Ollama did not answer on http://127.0.0.1:11434/api/version" >&2
        exit 1
    fi
fi

echo "setup verification passed"
