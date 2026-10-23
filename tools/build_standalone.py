#!/usr/bin/env python3
"""Build a self-contained shipmblang executable for this operating system.

PyInstaller packs the existing Python package, including compiler data files,
into one executable. When Cargo is available it also builds the Ratatui editor
and stores that binary inside the executable so ``shipmblang editor`` does not
need Rust at runtime. Optional model packages (PyTorch, tokenizers) are left out.

The native C++ compiler described in docs/native.md is a separate private
distribution and is not part of this build.
"""

from __future__ import annotations

import argparse
import importlib.metadata as metadata
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
EDITOR_MANIFEST = ROOT / "shipmblang" / "native" / "ratatui-editor" / "Cargo.toml"
PACKAGES = ("shipmblang", "driplm", "shiplang", "shipmb", "driplang")
EXCLUDES = (
    "torch",
    "torchvision",
    "torchaudio",
    "numpy",
    "tokenizers",
    "datasets",
    "tqdm",
    "tkinter",
    "driplm.model",
    "driplm.train",
    "driplm.dataset",
    "driplm.inference",
    "driplm.generate_data",
    "driplm.prepare_data",
)


def _editor_name() -> str:
    return "shipmblang-editor.exe" if os.name == "nt" else "shipmblang-editor"


def _cargo_argv() -> list[str] | None:
    rustup = shutil.which("rustup")
    if rustup:
        probe = subprocess.run([rustup, "run", "stable", "cargo", "--version"], capture_output=True, text=True)
        if probe.returncode != 0:
            subprocess.run([rustup, "toolchain", "install", "stable", "--profile", "minimal"], check=True)
        return [rustup, "run", "stable", "cargo"]
    cargo = shutil.which("cargo")
    if cargo:
        return [cargo]
    home = Path(os.environ.get("CARGO_HOME") or Path.home() / ".cargo")
    for name in ("cargo.exe", "cargo"):
        candidate = home / "bin" / name
        if candidate.is_file():
            return [str(candidate)]
    return None


def build_editor(target_dir: Path) -> Path | None:
    cargo = _cargo_argv()
    if cargo is None:
        return None
    target_dir.mkdir(parents=True, exist_ok=True)
    command = [*cargo, "build", "--release", "--locked", "--manifest-path", str(EDITOR_MANIFEST),
               "--target-dir", str(target_dir)]
    subprocess.run(command, check=True, cwd=EDITOR_MANIFEST.parent)
    binary = target_dir / "release" / _editor_name()
    if not binary.is_file():
        raise SystemExit(f"Cargo finished without producing {binary}")
    if os.name != "nt":
        binary.chmod(binary.stat().st_mode | 0o755)
    probe = subprocess.run([str(binary)], capture_output=True, text=True)
    detail = (probe.stderr or "") + (probe.stdout or "")
    if probe.returncode == 0 or "Missing" not in detail:
        raise SystemExit(f"The editor binary did not start:\n{detail}")
    return binary


def _metadata_args() -> list[str]:
    try:
        metadata.version("shipmblang")
    except metadata.PackageNotFoundError:
        return []
    return ["--copy-metadata", "shipmblang"]


def build_executable(editor: Path | None, dist: Path) -> Path:
    try:
        import PyInstaller  # noqa: F401
    except ImportError as error:
        raise SystemExit(
            "PyInstaller is required. Install it with: python -m pip install pyinstaller"
        ) from error
    work = ROOT / "build" / "pyinstaller"
    dist.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile", "--console",
        "--name", "shipmblang",
        "--distpath", str(dist),
        "--workpath", str(work),
        "--specpath", str(work),
        "--paths", str(ROOT),
        *sum((["--collect-all", package] for package in PACKAGES), []),
        *sum((["--exclude-module", name] for name in EXCLUDES), []),
        *_metadata_args(),
    ]
    if editor is not None:
        command.extend(["--add-data", f"{editor}{os.pathsep}shipmblang/native/ratatui-editor"])
    command.append(str(ROOT / "tools" / "standalone_entry.py"))
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT) + os.pathsep + environment.get("PYTHONPATH", "")
    subprocess.run(command, check=True, cwd=ROOT, env=environment)
    produced = dist / ("shipmblang.exe" if os.name == "nt" else "shipmblang")
    if not produced.is_file():
        raise SystemExit(f"PyInstaller finished without producing {produced}")
    return produced


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-editor", action="store_true",
                        help="Fail if the Ratatui editor binary cannot be built and packed.")
    parser.add_argument("--skip-editor", action="store_true",
                        help="Do not build or pack the Ratatui editor. Cargo remains required at launch.")
    parser.add_argument("--dist", type=Path, default=ROOT / "dist",
                        help="Directory for the finished executable (default: dist/).")
    args = parser.parse_args()
    if args.skip_editor and args.require_editor:
        parser.error("--skip-editor and --require-editor cannot be combined.")
    editor = None
    if not args.skip_editor:
        try:
            editor = build_editor(ROOT / "build" / "ratatui-editor")
        except subprocess.CalledProcessError as error:
            print("Could not build the Ratatui editor. Rust 1.85+ (edition 2024) is required.", file=sys.stderr)
            raise SystemExit(error.returncode) from error
        if editor is None:
            message = "Cargo was not found, so the editor was not bundled. Install Rust from https://rustup.rs."
            if args.require_editor:
                raise SystemExit(message)
            print(f"warning: {message}", file=sys.stderr)
        else:
            print(f"editor bundled: {editor} ({editor.stat().st_size} bytes)", flush=True)
    produced = build_executable(editor, args.dist)
    print(f"standalone executable: {produced} ({produced.stat().st_size} bytes)", flush=True)


if __name__ == "__main__":
    main()
