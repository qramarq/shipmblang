#!/bin/sh
# Place the ShipMBLang executable on PATH, then run shipmblang setup.
# Arguments are passed through, for example: ./install.sh --yes --skip ollama
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -x "$script_dir/shipmblang" ]; then
    source=$script_dir/shipmblang
elif [ -x "$script_dir/dist/shipmblang" ]; then
    source=$script_dir/dist/shipmblang
else
    echo "Could not find the shipmblang executable next to install.sh." >&2
    exit 1
fi

dest_dir=${HOME}/.local/bin
mkdir -p "$dest_dir"
cp "$source" "$dest_dir/shipmblang"
chmod 755 "$dest_dir/shipmblang"

path_line='export PATH="$HOME/.local/bin:$PATH" # ShipMBLang'
ensure_line() {
    file=$1
    if [ -f "$file" ] && grep -q '# ShipMBLang' "$file"; then
        return 0
    fi
    printf '\n%s\n' "$path_line" >> "$file"
}
ensure_line "${HOME}/.profile"
if [ "$(uname -s)" = "Darwin" ]; then
    ensure_line "${HOME}/.zprofile"
fi

export PATH="$dest_dir:$PATH"
echo "Installed $dest_dir/shipmblang"
echo "Open a new terminal, or run: export PATH=\"\$HOME/.local/bin:\$PATH\""
exec "$dest_dir/shipmblang" setup "$@"
