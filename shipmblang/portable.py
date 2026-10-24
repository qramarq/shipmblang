"""Windows portable zip: the executable and its runtime, without model weights.

``tools/build_portable.py`` is the command. This module is the part that can
be tested on Linux: the manifest, the pin check, the weight-directory choice,
and the zip itself.

The vision DLL and ``llama-quantize.exe`` stay Release builds. MinSizeRel
asks MSVC for ``/O1``. That can slow the ggml kernels, and a warm p95 under
2 seconds was measured for the Release library. This tree does not switch the
build to MinSizeRel.

The archive uses deflate level 9 and Zip64. UPX is not used.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import sys
import zipfile

from shipmblang.vision_setup import VisionPins, extended_path, load_pins


VISION_BUILD_CONFIG = "Release"
COMPRESS_LEVEL = 9
ZIP_NAME_TEMPLATE = "shipmblang-{version}-windows-x64.zip"

# sqlite3 stays. notebook_store.py and _compiler/memory.py import it.
# tkinter is imported only by the notebook window. Tcl/Tk is left out of this zip.
# torch, numpy, and the training stack are already excluded from the standalone exe.
PYINSTALLER_EXCLUDES = (
    "tkinter",
    "_tkinter",
    "test",
    "unittest",
    "pydoc",
    "pydoc_data",
    "lib2to3",
    "distutils",
    "ensurepip",
    "idlelib",
    "venv",
    "turtle",
    "turtledemo",
    "xmlrpc",
    "doctest",
    "pdb",
    "bdb",
    "curses",
    "readline",
    "rlcompleter",
    "antigravity",
    "ctypes.test",
    "sqlite3.test",
    "torch",
    "torchvision",
    "torchaudio",
    "numpy",
    "tokenizers",
    "datasets",
    "tqdm",
    "driplm.model",
    "driplm.train",
    "driplm.dataset",
    "driplm.inference",
    "driplm.generate_data",
    "driplm.prepare_data",
)

COLLECT_PACKAGES = ("shipmblang", "driplm", "shiplang", "shipmb", "driplang")
VC_RUNTIME_DLLS = ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll")
REQUIRED_VC_DLLS = ("vcruntime140.dll", "vcruntime140_1.dll")
SKIP_SUFFIXES = {".pdb", ".lib", ".exp"}
SKIP_PARTS = {"fixtures", "__pycache__", "tests"}


class PortableBuildError(RuntimeError):
    """The portable zip cannot be assembled."""


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def package_version() -> str:
    from shipmblang.lsp import shipmblang_version

    return shipmblang_version()


def zip_filename(version: str | None = None, *, with_weights: bool = False) -> str:
    name = ZIP_NAME_TEMPLATE.format(version=version or package_version())
    if with_weights:
        return name.replace(".zip", "-with-weights.zip")
    return name


def portable_dir_name(version: str | None = None) -> str:
    """Folder name inside both zips. Unzipping creates this directory."""
    return zip_filename(version).removesuffix(".zip")


def runtime_weights(pins: VisionPins | None = None) -> tuple:
    """Language model and q8 projector. The f16 file is only a quantize input."""
    loaded = pins if pins is not None else load_pins()
    return (loaded.llm, loaded.q8)


def pinned_size_lines(pins: VisionPins | None = None) -> list[str]:
    loaded = pins if pins is not None else load_pins()
    download = loaded.llm.size + loaded.f16.size
    on_disk = download + loaded.q8.size
    return [
        f"SIZE weight_llm_bytes={loaded.llm.size}",
        f"SIZE weight_f16_bytes={loaded.f16.size}",
        f"SIZE weight_q8_bytes={loaded.q8.size}",
        f"SIZE download_bytes={download}",
        f"SIZE weights_on_disk_bytes={on_disk}",
    ]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(extended_path(path), "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_weight_file(path: Path, pin) -> None:
    if not path.is_file():
        raise PortableBuildError(
            f"Missing {pin.filename} at {path}. Run `shipmblang setup --vision` before --with-weights."
        )
    size = path.stat().st_size
    digest = _sha256(path)
    if size != pin.size or digest != pin.sha256:
        raise PortableBuildError(
            f"{pin.filename} does not match the pin. Expected {pin.size} bytes and sha256 {pin.sha256}; "
            f"found {size} bytes and sha256 {digest}."
        )


def verify_runtime_weights(cache: Path, pins: VisionPins | None = None) -> None:
    for pin in runtime_weights(pins):
        verify_weight_file(cache / pin.filename, pin)


def pyinstaller_excludes() -> tuple[str, ...]:
    if "sqlite3" in PYINSTALLER_EXCLUDES:
        raise PortableBuildError("sqlite3 is imported by the notebook store and the memory database.")
    return PYINSTALLER_EXCLUDES


def pyinstaller_argv(
    entry: Path,
    dist: Path,
    work: Path,
    datas: list[tuple[Path, str]],
    *,
    strip: bool = False,
) -> list[str]:
    """Onedir PyInstaller command. UPX is off. ``--strip`` is used only when requested."""
    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onedir", "--console", "--noupx",
        "--name", "shipmblang",
        "--distpath", str(dist),
        "--workpath", str(work),
        "--specpath", str(work),
        "--paths", str(repo_root()),
    ]
    if strip:
        command.append("--strip")
    for package in COLLECT_PACKAGES:
        command.extend(["--collect-all", package])
    for name in pyinstaller_excludes():
        command.extend(["--exclude-module", name])
    command.extend(_metadata_args())
    for origin, destination in datas:
        command.extend(["--add-data", f"{origin}{os.pathsep}{destination}"])
    command.append(str(entry))
    if "--onefile" in command or "--upx-dir" in command:
        raise PortableBuildError("The portable build must not use onefile or UPX.")
    return command


def _metadata_args() -> list[str]:
    import importlib.metadata as metadata

    try:
        metadata.version("shipmblang")
    except metadata.PackageNotFoundError:
        return []
    return ["--copy-metadata", "shipmblang"]


def vc_search_roots() -> list[Path]:
    """Directories that may hold the app-local VC runtime. System32 is not one of them."""
    base = Path(getattr(sys, "base_prefix", sys.prefix))
    return [base, base / "DLLs", Path(sys.executable).resolve().parent]


def discover_vc_dlls(roots: list[Path], onedir: Path | None = None) -> dict[str, Path]:
    """Find vcruntime140.dll and vcruntime140_1.dll. msvcp140.dll is included when present.

    Search the given directories for a file of that exact name, then the onedir
    tree. Do not pass System32: a DLL installed there is not a substitute for
    shipping one inside the zip.
    """
    found: dict[str, Path] = {}
    for root in roots:
        directory = Path(root)
        if not directory.is_dir():
            continue
        for name in VC_RUNTIME_DLLS:
            if name in found:
                continue
            candidate = directory / name
            if candidate.is_file():
                found[name] = candidate
    if onedir is not None and Path(onedir).is_dir():
        for name in VC_RUNTIME_DLLS:
            if name in found:
                continue
            matches = [path for path in Path(onedir).rglob(name) if path.is_file()]
            if matches:
                found[name] = matches[0]
    missing = [name for name in REQUIRED_VC_DLLS if name not in found]
    if missing:
        raise PortableBuildError(
            "VC runtime DLLs were not found next to Python or in the PyInstaller folder: "
            + ", ".join(missing)
            + ". This build does not copy them from System32."
        )
    return found


def _skipped(path: Path, root: Path) -> bool:
    if path.suffix.lower() in SKIP_SUFFIXES:
        return True
    parts = {part.lower() for part in path.relative_to(root).parts}
    return bool(parts & SKIP_PARTS)


def _copy_tree(origin: Path, destination: Path) -> None:
    for path in origin.rglob("*"):
        if not path.is_file() or _skipped(path, origin):
            continue
        target = destination / path.relative_to(origin)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def find_executable(root: Path) -> Path:
    matches = [path for path in root.rglob("shipmblang.exe") if path.is_file()]
    if not matches:
        matches = [path for path in root.rglob("shipmblang") if path.is_file()]
    if len(matches) != 1:
        raise PortableBuildError(f"Expected one shipmblang executable in {root}, found {len(matches)}.")
    return matches[0]


def _dedupe(root: Path, name: str, keeper: Path) -> None:
    keeper_resolved = keeper.resolve()
    for path in list(root.rglob(name)):
        if path.is_file() and path.resolve() != keeper_resolved:
            path.unlink()


def _prefer_native(paths: list[Path]) -> Path:
    def rank(path: Path) -> tuple:
        text = path.as_posix().lower()
        native = 0 if "/native/" in f"{text}/" else 1
        return (native, len(text), text)

    return sorted(paths, key=rank)[0]


def _place_vc_dlls(root: Path, exe: Path, vc_dlls: dict[str, Path]) -> None:
    for name, source in vc_dlls.items():
        if name not in VC_RUNTIME_DLLS:
            raise PortableBuildError(f"Refusing to add {name}; it is not a VC runtime DLL this zip ships.")
        target = exe.parent / name
        if not target.is_file():
            shutil.copy2(source, target)
        _dedupe(root, name, target)


def _dedupe_tools(root: Path) -> None:
    for name in ("shipmb_vision.dll", "llama-quantize.exe"):
        found = [path for path in root.rglob(name) if path.is_file()]
        if len(found) > 1:
            _dedupe(root, name, _prefer_native(found))


def _readme_text(version: str, pins: VisionPins, *, with_weights: bool) -> str:
    weights = (
        "This zip includes the two runtime weight files in the vision folder.\n"
        "They are used automatically. An explicit SHIPMB_VISION_MODEL_DIR still wins.\n"
        if with_weights
        else
        "This zip does not include model weights. The first setup downloads them.\n"
    )
    return (
        f"shipmblang {version} for Windows x64\n"
        "\n"
        "Unzip this folder anywhere. You can add it to PATH. No Python install\n"
        "and no Visual C++ redistributable are required.\n"
        "\n"
        "  shipmblang.exe --version\n"
        "  shipmblang.exe setup --vision\n"
        "  shipmblang.exe photo.shipmb --format text\n"
        "\n"
        "setup --vision downloads the MiniCPM-V 4.6 language model "
        f"({pins.llm.filename}, {pins.llm.size} bytes)\n"
        f"and the f16 projector ({pins.f16.filename}, {pins.f16.size} bytes), then quantizes\n"
        f"that projector to {pins.q8.filename} ({pins.q8.size} bytes) with llama-quantize.\n"
        "The files are stored in %LOCALAPPDATA%\\shipmblang\\vision unless\n"
        "SHIPMB_VISION_MODEL_DIR is set. setup --vision --check reports what is present.\n"
        "\n"
        f"{weights}"
        "Write image paths with forward slashes. A backslash inside quotes is an escape.\n"
        "\n"
        '  Look at "C:/Users/me/photo.png" and tell me what is in it.\n'
        "\n"
        "A vision answer stops after 16 tokens, so a longer sentence can end early.\n"
        "\n"
        "Licenses are in the licenses folder. Pins are in the pins folder.\n"
    )


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="ascii", newline="\n")


def _license_files(destination: Path, pins: VisionPins) -> None:
    root = repo_root()
    licenses = destination / "licenses"
    licenses.mkdir(parents=True, exist_ok=True)
    copies = (
        (root / "LICENSE", licenses / "Apache-2.0.txt"),
        (root / "NOTICE", licenses / "NOTICE"),
        (root / "native" / "shipmb_vision" / "licenses" / "llama.cpp-MIT.txt", licenses / "llama.cpp-MIT.txt"),
        (root / "native" / "shipmb_vision" / "NOTICE", licenses / "shipmb_vision-NOTICE.txt"),
        (root / "native" / "shipmb_vision" / "vendor" / "JSON-LICENSE.MIT", licenses / "nlohmann-json-MIT.txt"),
    )
    for source, target in copies:
        if source.is_file():
            shutil.copy2(source, target)
    pin_dir = destination / "pins"
    pin_dir.mkdir(parents=True, exist_ok=True)
    if pins.source is not None:
        for name in ("pins.json", "weight_pins.json"):
            source = pins.source / name
            if source.is_file():
                shutil.copy2(source, pin_dir / name)
    _write_text(
        licenses / "VC-RUNTIME.txt",
        "Microsoft Visual C++ runtime, app-local copy\n"
        "\n"
        "vcruntime140.dll, vcruntime140_1.dll, and msvcp140.dll (when the executable\n"
        "imports it) are Distributable Code. Visual Studio's Redist.txt lists them,\n"
        "and the Visual Studio license allows an application to ship those DLLs in\n"
        "its own folder. This zip places one copy of each next to shipmblang.exe.\n"
        "\n"
        "The Universal CRT (ucrtbase.dll and api-ms-win-crt-*.dll) is part of\n"
        "Windows 10 and later. It is not included.\n",
    )
    _write_text(
        licenses / "PYTHON-AND-PYINSTALLER.txt",
        "CPython is included under the PSF License. PyInstaller packs this program.\n"
        "The PyInstaller bootloader is GPL-2.0 with the Bootloader Exception, which\n"
        "allows it to be combined with the application it starts. UPX is not used.\n"
        "The Tk window is not included. sqlite3 is included because notes and memory\n"
        "use it.\n",
    )
    _write_text(
        licenses / "MINICPM-V.txt",
        "MiniCPM-V 4.6 weights from openbmb/MiniCPM-V-4.6-gguf are Apache-2.0.\n"
        "See Apache-2.0.txt in this folder. The default zip does not contain the\n"
        "weights. setup --vision downloads the language model and the f16 projector.\n"
        "mmproj-model-q8_0.gguf is produced locally and is not a separate download.\n"
        "A zip built with --with-weights contains the language model and the q8\n"
        "projector only. The f16 projector is not packed.\n",
    )


def assemble_portable_tree(
    onedir: Path,
    destination: Path,
    *,
    with_weights: bool = False,
    weight_source: Path | None = None,
    pins: VisionPins | None = None,
    vc_dlls: dict[str, Path] | None = None,
    version: str | None = None,
) -> Path:
    """Copy an onedir tree into ``destination`` and add licenses, pins, and weights."""
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    _copy_tree(onedir, destination)
    exe = find_executable(destination)
    if vc_dlls:
        missing = [name for name in REQUIRED_VC_DLLS if name not in vc_dlls]
        if missing:
            raise PortableBuildError(f"VC runtime DLLs were not found: {', '.join(missing)}")
        _place_vc_dlls(destination, exe, vc_dlls)
    _dedupe_tools(destination)
    loaded = pins if pins is not None else load_pins()
    _license_files(destination, loaded)
    _write_text(
        destination / "README.txt",
        _readme_text(version or package_version(), loaded, with_weights=with_weights),
    )
    if with_weights:
        cache = weight_source if weight_source is not None else None
        if cache is None:
            from shipmblang.vision_setup import vision_model_dir

            cache = vision_model_dir()
        vision = destination / "vision"
        if vision.exists():
            shutil.rmtree(vision)
        vision.mkdir()
        for pin in runtime_weights(loaded):
            verify_weight_file(cache / pin.filename, pin)
            shutil.copy2(cache / pin.filename, vision / pin.filename)
        f16 = vision / loaded.f16.filename
        if f16.exists():
            raise PortableBuildError("The f16 projector must not be packed.")
    else:
        packed = sorted(path.name for path in destination.rglob("*.gguf") if path.is_file())
        if packed:
            raise PortableBuildError("The default zip must not contain weights: " + ", ".join(packed))
    leftover = [path for path in destination.rglob("*") if path.is_file() and path.suffix.lower() in SKIP_SUFFIXES]
    if leftover:
        names = ", ".join(path.name for path in leftover[:5])
        raise PortableBuildError(f"Debug files are still in the tree: {names}")
    return destination


def write_portable_zip(source: Path, destination: Path, *, root_name: str | None = None) -> None:
    """Deflate level 9. Each member uses a Zip64 local header.

    ``allowZip64`` writes Zip64 central-directory records when the archive
    passes the classic limits. The largest packed weight is under 2 GiB;
    forcing the local header keeps that member valid if a later file grows
    past the 32-bit size. The archive contains one top-level directory.
    """
    prefix = (root_name or source.name).strip("/\\")
    if not prefix or prefix in {".", ".."} or "/" in prefix or "\\" in prefix:
        raise PortableBuildError(f"Refusing zip root name {prefix!r}.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    with zipfile.ZipFile(
        destination, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True, compresslevel=COMPRESS_LEVEL,
    ) as archive:
        files = sorted(item for item in source.rglob("*") if item.is_file())
        if not files:
            raise PortableBuildError(f"Nothing to zip in {source}.")
        for path in files:
            arcname = f"{prefix}/{path.relative_to(source).as_posix()}"
            info = zipfile.ZipInfo.from_file(path, arcname)
            info.filename = arcname
            info.compress_type = zipfile.ZIP_DEFLATED
            with archive.open(info, "w", force_zip64=True) as handle, path.open("rb") as src:
                shutil.copyfileobj(src, handle, length=1024 * 1024)


def classify_member(name: str) -> str:
    base = name.rsplit("/", 1)[-1].lower()
    if base == "shipmb_vision.dll":
        return "vision_dll"
    if base == "llama-quantize.exe":
        return "llama_quantize"
    if base in VC_RUNTIME_DLLS:
        return "vc_runtime"
    if base == "minicpm-v-4_6-q4_k_m.gguf":
        return "weight_llm"
    if base == "mmproj-model-f16.gguf":
        return "weight_f16"
    if base == "mmproj-model-q8_0.gguf":
        return "weight_q8"
    return "exe_and_python"


def report_zip(path: Path, kind: str, pins: VisionPins | None = None) -> list[str]:
    """Lines the README size table is filled from. ``kind`` is ``default`` or ``with_weights``."""
    if kind not in {"default", "with_weights"}:
        raise PortableBuildError(f"Unknown zip report kind: {kind}")
    totals = {name: [0, 0] for name in (
        "exe_and_python", "vision_dll", "llama_quantize", "vc_runtime", "weight_llm", "weight_f16", "weight_q8",
    )}
    per_vc = {name: 0 for name in VC_RUNTIME_DLLS}
    members: list[tuple[int, int, str]] = []
    unzipped = 0
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            bucket = classify_member(info.filename)
            totals[bucket][0] += info.file_size
            totals[bucket][1] += info.compress_size
            unzipped += info.file_size
            base = info.filename.rsplit("/", 1)[-1].lower()
            if base in per_vc:
                per_vc[base] += info.file_size
            members.append((info.file_size, info.compress_size, info.filename))
    lines = [
        f"SIZE {kind}_zip_bytes={path.stat().st_size}",
        f"SIZE {kind}_unzipped_bytes={unzipped}",
    ]
    for name in ("exe_and_python", "vision_dll", "llama_quantize", "vc_runtime"):
        uncompressed, compressed = totals[name]
        lines.append(f"SIZE {name}_uncompressed_bytes={uncompressed}")
        lines.append(f"SIZE {name}_compressed_bytes={compressed}")
    for name, size in per_vc.items():
        stem = name[:-4]
        lines.append(f"SIZE vc_{stem}_uncompressed_bytes={size}")
    if totals["weight_f16"][0]:
        lines.append(f"SIZE packed_f16_uncompressed_bytes={totals['weight_f16'][0]}")
    loaded = pins if pins is not None else load_pins()
    lines.extend(pinned_size_lines(loaded))
    if kind == "default":
        # Unzipped program plus the three cache files setup leaves behind.
        weights_on_disk = loaded.llm.size + loaded.f16.size + loaded.q8.size
        lines.append(f"SIZE disk_after_setup_bytes={unzipped + weights_on_disk}")
    members.sort(key=lambda item: (-item[0], item[2]))
    for index, (uncompressed, compressed, name) in enumerate(members[:10], start=1):
        lines.append(f"SIZE top {index} {uncompressed} {compressed} {name}")
    return lines


# Keys the README size table copies. The build prints one `SIZE <key>=` line each.
SIZE_TABLE_KEYS = (
    "default_zip_bytes",
    "default_unzipped_bytes",
    "with_weights_zip_bytes",
    "with_weights_unzipped_bytes",
    "exe_and_python_uncompressed_bytes",
    "exe_and_python_compressed_bytes",
    "vision_dll_uncompressed_bytes",
    "vision_dll_compressed_bytes",
    "llama_quantize_uncompressed_bytes",
    "llama_quantize_compressed_bytes",
    "vc_runtime_uncompressed_bytes",
    "vc_runtime_compressed_bytes",
    "vc_vcruntime140_uncompressed_bytes",
    "vc_vcruntime140_1_uncompressed_bytes",
    "vc_msvcp140_uncompressed_bytes",
    "weight_llm_bytes",
    "weight_f16_bytes",
    "weight_q8_bytes",
    "download_bytes",
    "weights_on_disk_bytes",
    "disk_after_setup_bytes",
)


def size_values(lines: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in lines:
        if not line.startswith("SIZE ") or "=" not in line:
            continue
        key, value = line[len("SIZE "):].split("=", 1)
        if key.startswith("top "):
            continue
        values[key] = value
    return values


def require_size_keys(lines: list[str]) -> dict[str, str]:
    values = size_values(lines)
    missing = [key for key in SIZE_TABLE_KEYS if key not in values]
    if missing:
        raise PortableBuildError("Size report is missing: " + ", ".join(missing))
    return values


def with_weights_archive_lines(path: Path) -> list[str]:
    """Archive sizes only. Component totals stay the ones from the default zip."""
    wanted = ("SIZE with_weights_zip_bytes=", "SIZE with_weights_unzipped_bytes=")
    found = [line for line in report_zip(path, "with_weights") if line.startswith(wanted)]
    if len(found) != 2:
        raise PortableBuildError("The with-weights zip did not report its sizes.")
    return found


def not_built_weight_lines() -> list[str]:
    return [
        "SIZE with_weights_zip_bytes=not_built",
        "SIZE with_weights_unzipped_bytes=not_built",
    ]
