#!/usr/bin/env python3
"""Harden the shipped program binaries in a portable folder.

``tools/build_portable.py`` calls this after the folder is assembled and
before the zip is written. BLA's directory mode only rewrites JavaScript, and
its archive mode rewrites a zip without Zip64, so this step protects three
files in place:

- ``shipmblang.exe``
- ``shipmb_vision.dll``
- ``llama-quantize.exe``

The Visual C++ runtime DLLs, pinned weight files, and every other file stay
byte-for-byte. The preset is ``balanced``. A trailer larger than 256 KiB is
rejected so the lightweight zip cannot grow by a large step. On Windows PE
files the original bytes must remain a prefix.

The build machine needs Node.js 22.13+ or 24.x and npm. The unzipped folder
does not.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shipmblang.portable import PortableBuildError  # noqa: E402


INTENSITY = "balanced"
SEED = "shipmblang-portable"
MAX_GROWTH_BYTES = 256 * 1024
RELEASE_BINARIES = (
    "shipmblang.exe",
    "shipmb_vision.dll",
    "llama-quantize.exe",
)
JsonRunner = Callable[[list[str]], dict]


def select_release_binaries(root: Path) -> list[Path]:
    """Return the three program binaries, or raise if the set is not exact."""
    if not root.is_dir():
        raise PortableBuildError(f"{root} is not a directory.")
    found: dict[str, list[Path]] = {name: [] for name in RELEASE_BINARIES}
    for path in root.rglob("*"):
        if path.is_file() and path.name in found:
            found[path.name].append(path)
    missing = [name for name, paths in found.items() if not paths]
    if missing:
        raise PortableBuildError(
            "The portable folder is missing "
            + ", ".join(missing)
            + ". BLA harden runs only after those files are in the folder."
        )
    duplicates = [name for name, paths in found.items() if len(paths) > 1]
    if duplicates:
        raise PortableBuildError(
            "Expected one copy of " + ", ".join(duplicates) + " before BLA harden."
        )
    return [found[name][0] for name in RELEASE_BINARIES]


def _npx() -> str:
    found = shutil.which("npx")
    if found is None:
        raise PortableBuildError(
            "npx was not found. The portable build machine needs Node.js 22.13+ or 24.x "
            "so BLA can harden the release binaries. The unzipped folder does not need Node."
        )
    return found


def _run_bla_json(arguments: list[str]) -> dict:
    command = [_npx(), "--yes", "bla-agents@latest", *arguments, "--json"]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise PortableBuildError(
            f"BLA failed (exit {completed.returncode}): {' '.join(command)}\n{detail}"
        )
    text = completed.stdout
    start = text.find("{")
    if start < 0:
        raise PortableBuildError(f"BLA did not return JSON for: {' '.join(arguments)}")
    try:
        return json.loads(text[start:])
    except json.JSONDecodeError as error:
        raise PortableBuildError(f"BLA returned invalid JSON for: {' '.join(arguments)}") from error


def _harden_one(path: Path, run_json: JsonRunner) -> dict:
    original = path.read_bytes()
    temporary = path.with_name(path.name + ".bla-tmp")
    if temporary.exists():
        temporary.unlink()
    try:
        run_json(
            [
                "protect",
                str(path),
                "-o",
                str(temporary),
                "--intensity",
                INTENSITY,
                "--seed",
                SEED,
            ]
        )
        if not temporary.is_file():
            raise PortableBuildError(f"BLA protect did not write {temporary.name}.")
        protected = temporary.read_bytes()
        growth = len(protected) - len(original)
        if growth < 0 or growth > MAX_GROWTH_BYTES:
            raise PortableBuildError(
                f"{path.name} grew by {growth} bytes. The limit is {MAX_GROWTH_BYTES} bytes."
            )
        if original.startswith(b"MZ") and not protected.startswith(original):
            raise PortableBuildError(
                f"{path.name} was rewritten. The portable build only accepts a trailer on PE files."
            )
        verification = run_json(["verify", str(temporary), str(path)])
        if not verification.get("overallPassed") or not verification.get("functionalIntegrityVerified"):
            raise PortableBuildError(f"BLA verify did not pass for {path.name}.")
        mode = path.stat().st_mode
        os.replace(temporary, path)
        os.chmod(path, mode)
    finally:
        if temporary.exists():
            temporary.unlink()
    print(
        f"bla_harden {path.name} bytes={len(original)}->{len(protected)} "
        f"added={growth} intensity={INTENSITY} verify=passed",
        flush=True,
    )
    return {
        "name": path.name,
        "original_bytes": len(original),
        "protected_bytes": len(protected),
        "added_bytes": growth,
    }


def _fingerprint(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def harden_tree(root: Path, *, run_json: JsonRunner | None = None) -> list[dict]:
    """Protect the three release binaries and leave every other file untouched."""
    runner = run_json or _run_bla_json
    selected = select_release_binaries(root)
    selected_set = set(selected)
    before = {
        path: _fingerprint(path)
        for path in root.rglob("*")
        if path.is_file() and path not in selected_set
    }
    results = [_harden_one(path, runner) for path in selected]
    for path, fingerprint in before.items():
        if not path.is_file() or _fingerprint(path) != fingerprint:
            raise PortableBuildError(
                f"BLA harden changed {path.relative_to(root)}, which is not a release binary."
            )
    added = sum(item["added_bytes"] for item in results)
    print(f"bla_harden files={len(results)} added_bytes={added} intensity={INTENSITY}", flush=True)
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Assembled portable folder (not the zip).")
    args = parser.parse_args(argv)
    try:
        harden_tree(args.root)
    except PortableBuildError as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
