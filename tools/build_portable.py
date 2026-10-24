#!/usr/bin/env python3
"""Build a Windows x64 folder zip of shipmblang.

The default zip contains the executable, the vision library, llama-quantize,
and the Visual C++ runtime DLLs the executable needs. It does not contain
model weights. The first ``shipmblang setup --vision`` downloads those.

``--with-weights`` also writes a second zip with the language model and the
q8 projector, after checking them against the pins. The f16 projector is not
packed. ``--check-weights`` only checks the cache and prints the weight sizes.
It does not run PyInstaller and it does not deflate the weights.

This command produces the exe zip on Windows x64. On any other system it
exits 2 unless ``--check-weights`` is set.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shipmblang.portable import (  # noqa: E402
    PortableBuildError,
    discover_vc_dlls,
    not_built_weight_lines,
    package_version,
    pinned_size_lines,
    portable_dir_name,
    pyinstaller_argv,
    report_zip,
    require_size_keys,
    repo_root,
    vc_search_roots,
    verify_runtime_weights,
    with_weights_archive_lines,
    zip_filename,
)


def _emit(lines: list[str]) -> None:
    require_size_keys(lines)
    for line in lines:
        print(line, flush=True)


def check_weights() -> int:
    from shipmblang.vision_setup import vision_model_dir

    cache = vision_model_dir()
    try:
        verify_runtime_weights(cache)
    except PortableBuildError as error:
        print(str(error), file=sys.stderr)
        return 1
    for line in pinned_size_lines():
        print(line, flush=True)
    for line in not_built_weight_lines():
        print(line, flush=True)
    print(f"weights_ok {cache}", flush=True)
    return 0


def _build_onedir(dist: Path, work: Path) -> Path:
    from shipmblang.vision_build import configure_and_build, existing_library, standalone_datas

    if existing_library() is None:
        configure_and_build()
    try:
        import PyInstaller  # noqa: F401
    except ImportError as error:
        raise PortableBuildError(
            "PyInstaller is required. Install it with: python -m pip install pyinstaller"
        ) from error
    datas = standalone_datas()
    names = {path.name.lower() for path, _destination in datas}
    if "shipmb_vision.dll" not in names:
        raise PortableBuildError("shipmb_vision.dll was not found. Build the vision library first.")
    if "llama-quantize.exe" not in names:
        raise PortableBuildError("llama-quantize.exe was not found. Build the vision library first.")
    if shutil.which("strip"):
        print("strip is on PATH; PyInstaller will strip debug symbols.", flush=True)
    command = pyinstaller_argv(
        repo_root() / "tools" / "standalone_entry.py",
        dist,
        work,
        datas,
        strip=shutil.which("strip") is not None,
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(repo_root()) + os.pathsep + environment.get("PYTHONPATH", "")
    print("PyInstaller onedir (UPX off, Release vision library).", flush=True)
    subprocess.run(command, check=True, cwd=repo_root(), env=environment)
    produced = dist / "shipmblang"
    if not produced.is_dir():
        raise PortableBuildError(f"PyInstaller finished without producing {produced}")
    return produced


def build(dist: Path, *, with_weights: bool) -> None:
    from shipmblang.portable import assemble_portable_tree, write_portable_zip

    dist.mkdir(parents=True, exist_ok=True)
    onedir = _build_onedir(dist / "pyinstaller", repo_root() / "build" / "pyinstaller-portable")
    vc_dlls = discover_vc_dlls(vc_search_roots(), onedir)
    version = package_version()
    folder_name = portable_dir_name(version)
    folder = dist / folder_name
    assemble_portable_tree(onedir, folder, with_weights=False, vc_dlls=vc_dlls, version=version)
    archive = dist / zip_filename(version)
    write_portable_zip(folder, archive, root_name=folder_name)
    lines = report_zip(archive, "default")
    if with_weights:
        stage = dist / f"{folder_name}-with-weights-stage"
        assemble_portable_tree(onedir, stage, with_weights=True, vc_dlls=vc_dlls, version=version)
        heavy = dist / zip_filename(version, with_weights=True)
        write_portable_zip(stage, heavy, root_name=folder_name)
        shutil.rmtree(stage)
        lines.extend(with_weights_archive_lines(heavy))
        print(f"with_weights_zip {heavy}", flush=True)
    else:
        lines.extend(not_built_weight_lines())
    print(f"portable_zip {archive}", flush=True)
    _emit(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--with-weights",
        action="store_true",
        help="Also write shipmblang-<version>-windows-x64-with-weights.zip. The default zip is still written.",
    )
    parser.add_argument(
        "--check-weights",
        action="store_true",
        help="Check the cached language model and q8 projector, print their sizes, and do not build a zip.",
    )
    parser.add_argument("--dist", type=Path, default=ROOT / "dist", help="Directory for the zip (default: dist/).")
    args = parser.parse_args(argv)
    if args.check_weights and args.with_weights:
        parser.error("--check-weights does not build a zip, so it cannot be combined with --with-weights.")
    if args.check_weights:
        return check_weights()
    if sys.platform != "win32":
        print(
            f"The portable exe zip is built on Windows x64. This machine is {sys.platform}. "
            "On Windows, run: python tools\\build_portable.py",
            file=sys.stderr,
        )
        return 2
    try:
        build(args.dist, with_weights=args.with_weights)
    except PortableBuildError as error:
        print(str(error), file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as error:
        print(f"The portable build failed (exit {error.returncode}).", file=sys.stderr)
        return error.returncode or 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
