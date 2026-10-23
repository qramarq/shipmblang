"""Launch the native Ratatui chat-room notebook while keeping notes in SQLite."""
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
    source_dir = destination / "src"
    source_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / "Cargo.toml", destination / "Cargo.toml")
    for path in (source / "src").glob("*.rs"):
        shutil.copy2(path, source_dir / path.name)
    if (source / "Cargo.lock").is_file():
        shutil.copy2(source / "Cargo.lock", destination / "Cargo.lock")
    return destination / "Cargo.toml"


def find_cargo() -> str | None:
    found = shutil.which("cargo")
    if found:
        return found
    home = Path(os.environ.get("CARGO_HOME") or Path.home() / ".cargo")
    for name in ("cargo.exe", "cargo"):
        candidate = home / "bin" / name
        if candidate.is_file():
            return str(candidate)
    return None


EDITOR_BINARY_NAMES = ("shipmblang-editor.exe", "shipmblang-editor")
_CARGO_MESSAGE = "ShipMBLang Editor needs Rust and Cargo. Install Rust from https://rustup.rs, then rerun this command."


class EditorLaunchError(RuntimeError):
    """The editor command could not be constructed."""


def bundled_editor_executable() -> Path | None:
    """Return the prebuilt editor packed into a standalone executable."""
    if not getattr(sys, "frozen", False):
        return None
    roots: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))
    roots.append(Path(sys.executable).resolve().parent)
    relative = Path("shipmblang") / "native" / "ratatui-editor"
    for root in roots:
        for name in EDITOR_BINARY_NAMES:
            for candidate in (root / relative / name, root / name):
                if candidate.is_file():
                    return candidate
    return None


def _editor_workdir() -> str:
    if getattr(sys, "frozen", False):
        return str(Path.cwd())
    return str(Path(__file__).resolve().parents[1])


def _missing_editor_message() -> str:
    if getattr(sys, "frozen", False):
        return "This standalone build does not include the Ratatui editor binary. " + _CARGO_MESSAGE
    return _CARGO_MESSAGE


def editor_launch_plan(database: Path, extra: list[str] | None = None) -> tuple[list[str], Path, dict[str, str]]:
    """Return the editor command, working directory, and environment.

    A standalone build runs the prebuilt binary and points it back at this
    executable. A source install still builds the bundled sources with Cargo.
    ``extra`` is appended for theme, smoke, and version flags.
    """
    database = database.expanduser().resolve()
    tail = [item for item in (extra or []) if item]
    bundled = bundled_editor_executable()
    if bundled is not None:
        if os.name != "nt":
            bundled.chmod(bundled.stat().st_mode | 0o755)
        command = [str(bundled), "--database", str(database), "--python", sys.executable,
                   "--workdir", _editor_workdir(), "--startdir", str(Path.cwd()), *tail]
        return command, Path.cwd(), os.environ.copy()
    cargo = find_cargo()
    if cargo is None:
        raise EditorLaunchError(_missing_editor_message())
    data_dir = database.parent / "ratatui-editor"
    target_dir = database.parent / "ratatui-target"
    manifest = _install_editor_sources(data_dir)
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(target_dir)
    env["PATH"] = str(Path(cargo).parent) + os.pathsep + env.get("PATH", "")
    command = [cargo, "run", "--release", "--quiet", "--manifest-path", str(manifest), "--",
               "--database", str(database), "--python", sys.executable,
               "--workdir", _editor_workdir(), "--startdir", str(Path.cwd()), *tail]
    return command, data_dir, env


def _editor_extra(args) -> list[str]:
    extra: list[str] = []
    if args.version:
        extra.append("--version")
    if args.smoke:
        extra.append("--smoke")
    if args.demo:
        extra.append("--demo")
    if args.theme:
        extra.extend(["--theme", args.theme])
    if args.ascii:
        extra.append("--ascii")
    if args.dump:
        extra.extend(["--dump", str(args.dump)])
    if args.select is not None:
        extra.extend(["--select", str(args.select)])
    return extra


def main() -> None:
    parser = argparse.ArgumentParser(description="Open the ShipMBLang chat-room notebook.")
    parser.add_argument("--database", type=Path, default=default_database(),
                        help="Notes SQLite file (also opens a backup).")
    parser.add_argument("--theme", choices=["dark", "light"], default=None,
                        help="Start in the dark or light theme. Alt+T toggles it later.")
    parser.add_argument("--ascii", action="store_true",
                        help="Draw borders and badges with ASCII instead of Unicode.")
    parser.add_argument("--smoke", action="store_true",
                        help="Render one frame without a terminal and exit.")
    parser.add_argument("--demo", action="store_true",
                        help="Render the sample chat room instead of the saved notebook.")
    parser.add_argument("--dump", type=Path, default=None,
                        help="Write the rendered frame to this path as text and JSON cells.")
    parser.add_argument("--select", type=int, default=None,
                        help="Sample room to show with --demo.")
    parser.add_argument("--version", action="store_true",
                        help="Print the editor version and exit.")
    args = parser.parse_args()
    if not args.version:
        try:
            compiler_snapshot()
        except (OSError, ValueError, KeyError) as error:
            parser.exit(2, f"The bundled compiler snapshot failed its integrity check: {error}\n")
    try:
        command, cwd, env = editor_launch_plan(args.database, _editor_extra(args))
        completed = subprocess.run(command, cwd=cwd, env=env, check=False)
    except EditorLaunchError as error:
        parser.exit(2, f"{error}\n")
    except OSError as error:
        parser.exit(2, f"Could not start the Ratatui editor: {error}\n")
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
