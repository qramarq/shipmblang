"""Launch the native Ratatui document editor while keeping notes in SQLite."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

from .notebook_store import default_database
from .notebook_runtime import compiler_snapshot


def _install_editor_sources(destination: Path) -> Path:
    source = Path(__file__).parent / "native" / "ratatui-editor"
    if not (source / "Cargo.toml").is_file():
        raise FileNotFoundError("The bundled Ratatui editor sources are missing. Reinstall ShipMBLang.")
    (destination / "src").mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / "Cargo.toml", destination / "Cargo.toml")
    shutil.copy2(source / "src" / "main.rs", destination / "src" / "main.rs")
    return destination / "Cargo.toml"


def main() -> None:
    parser = argparse.ArgumentParser(description="Open the ShipMBLang Ratatui document editor.")
    parser.add_argument("--database", type=Path, default=default_database(),
                        help="Notes SQLite file (also opens a backup).")
    args = parser.parse_args()
    try:
        compiler_snapshot()
    except (OSError, ValueError, KeyError) as error:
        parser.exit(2, f"The bundled compiler snapshot failed its integrity check: {error}\n")
    cargo = shutil.which("cargo")
    if cargo is None:
        parser.exit(2, "ShipMBLang Editor needs Rust and Cargo. Install Rust from https://rustup.rs, then rerun this command.\n")

    database = args.database.expanduser().resolve()
    data_dir = database.parent / "ratatui-editor"
    target_dir = database.parent / "ratatui-target"
    try:
        manifest = _install_editor_sources(data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["CARGO_TARGET_DIR"] = str(target_dir)
        command = [cargo, "run", "--release", "--quiet", "--manifest-path", str(manifest), "--",
                   "--database", str(database), "--python", sys.executable,
                   "--workdir", str(Path(__file__).resolve().parents[1]),
                   "--startdir", str(Path.cwd())]
        completed = subprocess.run(command, cwd=data_dir, env=env, check=False)
    except OSError as error:
        parser.exit(2, f"Could not start the Ratatui editor: {error}\n")
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
