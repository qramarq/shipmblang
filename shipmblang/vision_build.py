"""Build the vendored shipmb_vision library and install it for vision.py.

llama.cpp is not in the tree. CMake FetchContent clones tag b11846 and applies
patches/llama.cpp-b11846-shipmb.patch. The shared library is copied to
shipmblang/_compiler/native/, which is the path vision.py opens when
SHIPMB_VISION_BRIDGE is unset.

On Windows the Visual Studio generator from vswhere is the default. A
Developer shell that already has ``cl`` and ``ninja`` on PATH uses Ninja
instead. The DLL is multi-config, so the built file is under ``Release/``.
The MSVC runtime is the static CRT (see the CMake lists).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def library_filename() -> str:
    if sys.platform == "win32":
        return "shipmb_vision.dll"
    if sys.platform == "darwin":
        return "libshipmb_vision.dylib"
    return "libshipmb_vision.so"


def quantize_filename() -> str:
    return "llama-quantize.exe" if sys.platform == "win32" else "llama-quantize"


def source_candidates() -> list[Path]:
    """Checkout, installed package, and frozen executable, in that order."""
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "native" / "shipmb_vision")
    here = Path(__file__).resolve()
    candidates.append(here.parents[1] / "native" / "shipmb_vision")
    candidates.append(here.parent / "native" / "shipmb_vision")
    return candidates


def source_root() -> Path | None:
    for path in source_candidates():
        if (path / "CMakeLists.txt").is_file() and (path / "pins.json").is_file():
            return path
    return None


def package_library_path() -> Path:
    """Directory vision.py searches when SHIPMB_VISION_BRIDGE is unset."""
    from shipmblang._compiler import vision as vision_module

    return Path(vision_module.__file__).resolve().parent / "native" / library_filename()


def package_quantize_path() -> Path:
    return package_library_path().parent / "bin" / quantize_filename()


def default_compilers() -> tuple[str, str]:
    """Choose a C and C++ compiler.

    CMake's default ``/usr/bin/c++`` is Clang on some machines and then fails to
    link libstdc++. gcc/g++ is the default when both are installed. ``CC`` and
    ``CXX`` still win when they are set, and ``SHIPMB_VISION_CC`` /
    ``SHIPMB_VISION_CXX`` win over those.
    """
    cc = os.environ.get("SHIPMB_VISION_CC") or os.environ.get("CC")
    cxx = os.environ.get("SHIPMB_VISION_CXX") or os.environ.get("CXX")
    # A single variable is not enough to override the default. CMake would
    # otherwise fill the other one with /usr/bin/c++, which may be Clang.
    if cc and cxx:
        return cc, cxx
    gcc, gxx = shutil.which("gcc"), shutil.which("g++")
    if gcc and gxx:
        return gcc, gxx
    clang, clangxx = shutil.which("clang"), shutil.which("clang++")
    if clang and clangxx:
        return clang, clangxx
    return cc or "cc", cxx or "c++"


def vswhere_candidates() -> list[Path]:
    found: list[Path] = []
    for key in ("ProgramFiles(x86)", "ProgramFiles"):
        root = os.environ.get(key)
        if not root:
            continue
        found.append(Path(root) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe")
    which = shutil.which("vswhere")
    if which:
        found.append(Path(which))
    return found


def vswhere_executable() -> Path | None:
    for path in vswhere_candidates():
        if path.is_file():
            return path
    return None


def detect_visual_studio() -> dict[str, str] | None:
    """Newest VS install that has the MSVC x64 toolset, according to vswhere."""
    exe = vswhere_executable()
    if exe is None:
        return None
    command = [
        str(exe), "-latest", "-products", "*",
        "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
        "-format", "json", "-utf8",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    if completed.returncode != 0:
        command = command[:-1]
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    try:
        installs = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None
    if not installs:
        return None
    info = installs[0]
    version = str(info.get("installationVersion") or "")
    major_text = version.split(".", 1)[0]
    if not major_text.isdigit():
        return None
    major = int(major_text)
    product_line = str((info.get("catalog") or {}).get("productLineVersion") or "")
    if not product_line.isdigit():
        product_line = {15: "2017", 16: "2019", 17: "2022", 18: "2026"}.get(major, "")
    if not product_line:
        return None
    install_path = info.get("installationPath")
    if not install_path:
        return None
    return {
        "generator": f"Visual Studio {major} {product_line}",
        "path": str(install_path),
        "version": version,
    }


def _dev_shell() -> bool:
    return bool(os.environ.get("VSCMD_VER") or os.environ.get("VCToolsInstallDir"))


def windows_cmake_args(cc: str | None = None, cxx: str | None = None) -> tuple[list[str], bool]:
    """CMake arguments for Windows, and whether the generator is multi-config.

    An explicit compiler pair is used as given. Otherwise a Developer shell
    (``cl`` and ``ninja`` already on PATH) uses Ninja. Every other machine
    uses the Visual Studio generator vswhere reports, which does not need
    ``cl`` on PATH. The second value is True for that multi-config generator.
    """
    if cc or cxx:
        if not cc or not cxx:
            raise RuntimeError("Pass both a C and a C++ compiler on Windows, or neither.")
        if not shutil.which(cc) or not shutil.which(cxx):
            raise RuntimeError(f"Compiler was not found: cc={cc} cxx={cxx}")
        if shutil.which("ninja"):
            return [
                "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release",
                f"-DCMAKE_C_COMPILER={cc}", f"-DCMAKE_CXX_COMPILER={cxx}",
            ], False
        return ["-DCMAKE_BUILD_TYPE=Release", f"-DCMAKE_C_COMPILER={cc}", f"-DCMAKE_CXX_COMPILER={cxx}"], False
    if shutil.which("cl") and shutil.which("ninja") and _dev_shell():
        return [
            "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release",
            "-DCMAKE_C_COMPILER=cl", "-DCMAKE_CXX_COMPILER=cl",
        ], False
    visual_studio = detect_visual_studio()
    if visual_studio is not None:
        return ["-G", visual_studio["generator"], "-A", "x64"], True
    if shutil.which("cl") and shutil.which("ninja"):
        return [
            "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release",
            "-DCMAKE_C_COMPILER=cl", "-DCMAKE_CXX_COMPILER=cl",
        ], False
    raise RuntimeError(
        "Building shipmb_vision on Windows needs Visual Studio 2022 with the Desktop C++ workload. "
        "vswhere did not find Microsoft.VisualStudio.Component.VC.Tools.x86.x64, and cl.exe is not on PATH. "
        "Install Visual Studio 2022 or Build Tools, or run this from a Developer PowerShell that has Ninja."
    )


def toolchain_available(cc: str | None = None, cxx: str | None = None) -> bool:
    if not shutil.which("cmake") or not shutil.which("git"):
        return False
    if sys.platform == "win32" and not (cc and cxx):
        try:
            windows_cmake_args()
        except RuntimeError:
            return False
        return True
    chosen_cc, chosen_cxx = (cc, cxx) if cc and cxx else default_compilers()
    return bool(shutil.which(chosen_cc) and shutil.which(chosen_cxx))


def existing_library() -> Path | None:
    """A library vision.py will actually open: bridge, frozen pack, or package path."""
    bridge = os.environ.get("SHIPMB_VISION_BRIDGE")
    if bridge and Path(bridge).is_file():
        return Path(bridge)
    from shipmblang.standalone import packed_vision_library

    packed = packed_vision_library()
    if packed is not None:
        return packed
    installed = package_library_path()
    if installed.is_file():
        return installed
    return None


def artifact_rank(path: Path) -> tuple:
    """Prefer the Release output of a multi-config build over Debug."""
    parts = [part.lower() for part in path.parts]
    if "cmakefiles" in parts:
        config = 9
    elif "debug" in parts:
        config = 4
    elif "relwithdebinfo" in parts:
        config = 3
    elif "minsizerel" in parts:
        config = 2
    elif "release" in parts:
        config = 0
    else:
        config = 1
    return (config, len(parts), str(path).lower())


def _best_artifact(paths: list[Path]) -> Path | None:
    files = [path for path in paths if path.is_file()]
    if not files:
        return None
    return min(files, key=artifact_rank)


def find_built_library(build_dir: Path) -> Path | None:
    if not build_dir.is_dir():
        return None
    return _best_artifact(list(build_dir.rglob(library_filename())))


def find_quantize_tool(build_dir: Path | None = None) -> Path | None:
    """llama-quantize from a frozen pack, the install dir, or a build tree."""
    name = quantize_filename()
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        for relative in (
            Path("native") / "shipmb_vision" / "bin" / name,
            Path("shipmblang") / "_compiler" / "native" / "bin" / name,
        ):
            packed = Path(meipass) / relative
            if packed.is_file():
                return packed
    override = os.environ.get("SHIPMB_LLAMA_QUANTIZE")
    if override and Path(override).is_file():
        return Path(override)
    roots: list[Path] = []
    if build_dir is not None:
        roots.append(build_dir)
    installed = package_quantize_path().parent
    roots.append(installed)
    source = source_root()
    if source is not None:
        roots.append(source / "build")
    seen: set[Path] = set()
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        resolved = root.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        found.extend(root.rglob(name))
    return _best_artifact(found)


def _license_sources(source: Path) -> list[tuple[Path, Path]]:
    library_dir = package_library_path().parent
    mapping = (
        ("LICENSE", "LICENSE"),
        ("NOTICE", "NOTICE"),
        ("licenses/llama.cpp-MIT.txt", "licenses/llama.cpp-MIT.txt"),
        ("pins.json", "pins.json"),
        ("weight_pins.json", "weight_pins.json"),
    )
    found = []
    for relative, destination in mapping:
        path = source / relative
        if path.is_file():
            found.append((path, library_dir / destination))
    return found


def _replace_installed(src: Path, dest: Path) -> None:
    """Atomic replace. On Windows a loaded DLL or scanner can refuse the first try."""
    delay = 0.05
    last: Exception | None = None
    for _ in range(20):
        try:
            os.replace(src, dest)
            return
        except OSError as error:
            last = error
            winerror = getattr(error, "winerror", None)
            if os.name != "nt" or winerror not in {5, 32, 33}:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 0.5)
    raise RuntimeError(
        f"Could not install {dest.name} because another program has it open ({last}). "
        "Close the process that loaded the vision library and run the build again."
    )


def _install_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_name(dest.name + ".installing")
    if temporary.exists():
        temporary.unlink()
    shutil.copy2(src, temporary)
    if os.name != "nt":
        temporary.chmod(temporary.stat().st_mode | 0o755)
    try:
        _replace_installed(temporary, dest)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    if os.name != "nt":
        dest.chmod(dest.stat().st_mode | 0o755)


def install_library(built: Path, source: Path | None = None) -> Path:
    """Copy the shared library and its license files to where vision.py looks."""
    if not built.is_file():
        raise RuntimeError(f"Built vision library was not found: {built}")
    destination = package_library_path()
    _install_file(built, destination)
    root = source if source is not None else source_root()
    if root is not None:
        for origin, target in _license_sources(root):
            _install_file(origin, target)
    return destination


def install_quantize(tool: Path) -> Path:
    destination = package_quantize_path()
    _install_file(tool, destination)
    return destination


def cmake_build_command(output: Path, jobs: int, multi_config: bool) -> list[str]:
    command = ["cmake", "--build", str(output), "--parallel", str(jobs)]
    if multi_config:
        command.extend(["--config", "Release"])
    return command


def _windows_missing_toolchain() -> str:
    return (
        "The shipmb_vision library is not installed, and no Visual Studio C++ toolchain was found. "
        "Install Visual Studio 2022 (or the Build Tools) with the Desktop development with C++ workload, "
        "plus CMake and git. cl.exe does not need to be on PATH. "
        "Then run `shipmblang setup --vision`."
    )


def _unix_missing_toolchain(cc: str, cxx: str) -> str:
    return (
        "The shipmb_vision library is not installed, and no C++ toolchain is available to build it. "
        "Install CMake, git, and g++ (Debian/Ubuntu: sudo apt-get install build-essential cmake git ca-certificates), "
        "then run `shipmblang setup --vision`. "
        f"A compiler can also be selected with --cc and --cxx on python tools/build_vision.py. "
        f"Looked for cc={cc} cxx={cxx}."
    )


def configure_and_build(
    *,
    source: Path | None = None,
    build_dir: Path | None = None,
    cc: str | None = None,
    cxx: str | None = None,
    quantize: bool = True,
    jobs: int | None = None,
) -> dict[str, Path | None]:
    """Configure, build, and install. Returns the installed library and quantize tool."""
    root = source if source is not None else source_root()
    if root is None:
        raise RuntimeError(
            "The vendored shipmb_vision sources were not found. Expected native/shipmb_vision/CMakeLists.txt."
        )
    if not shutil.which("cmake") or not shutil.which("git"):
        raise RuntimeError("Building shipmb_vision requires CMake and git.")
    multi_config = False
    extra: list[str]
    if sys.platform == "win32":
        extra, multi_config = windows_cmake_args(cc, cxx)
    else:
        chosen_cc, chosen_cxx = (cc, cxx) if cc and cxx else default_compilers()
        if not shutil.which(chosen_cc) or not shutil.which(chosen_cxx):
            raise RuntimeError(f"Compiler was not found: cc={chosen_cc} cxx={chosen_cxx}")
        extra = [
            "-DCMAKE_BUILD_TYPE=Release",
            "-DGGML_CCACHE=OFF",
            f"-DCMAKE_C_COMPILER={chosen_cc}",
            f"-DCMAKE_CXX_COMPILER={chosen_cxx}",
        ]
    if sys.platform == "win32" and "-DGGML_CCACHE=OFF" not in extra:
        extra.append("-DGGML_CCACHE=OFF")
    output = build_dir if build_dir is not None else root / "build"
    output.mkdir(parents=True, exist_ok=True)
    configure = [
        "cmake", "-S", str(root), "-B", str(output),
        *extra,
        f"-DSHIPMB_VISION_QUANTIZE={'ON' if quantize else 'OFF'}",
    ]
    print("Configuring shipmb_vision:", " ".join(configure), flush=True)
    subprocess.run(configure, check=True)
    parallel = jobs if jobs is not None else (os.cpu_count() or 1)
    build = cmake_build_command(output, parallel, multi_config)
    print("Building shipmb_vision:", " ".join(build), flush=True)
    subprocess.run(build, check=True)
    built = find_built_library(output)
    if built is None:
        raise RuntimeError(f"The build finished without producing {library_filename()} in {output}")
    installed = install_library(built, root)
    tool = find_quantize_tool(output) if quantize else None
    if quantize and tool is None:
        raise RuntimeError(f"The build finished without producing {quantize_filename()} in {output}")
    if tool is not None:
        tool = install_quantize(tool)
    print(f"Installed {installed}", flush=True)
    if tool is not None:
        print(f"llama-quantize: {tool}", flush=True)
    return {"library": installed, "quantize": tool, "build_dir": output}


def ensure_installed(*, offline: bool = False, quantize: bool = True) -> Path:
    """Reuse a packed or installed library, otherwise build the vendored sources."""
    found = existing_library()
    if found is not None:
        return found
    root = source_root()
    if sys.platform == "win32":
        env_cc = os.environ.get("SHIPMB_VISION_CC")
        env_cxx = os.environ.get("SHIPMB_VISION_CXX")
        cc, cxx = (env_cc, env_cxx) if env_cc and env_cxx else (None, None)
    else:
        cc, cxx = default_compilers()
    if root is None:
        raise RuntimeError(
            "The shipmb_vision library is not packed with this install, and the vendored sources "
            "are not available. Build native/shipmb_vision on a machine with CMake and copy "
            f"{library_filename()} next to the compiler's native/ directory, or set SHIPMB_VISION_BRIDGE."
        )
    if not toolchain_available(cc, cxx):
        if sys.platform == "win32":
            raise RuntimeError(_windows_missing_toolchain())
        raise RuntimeError(_unix_missing_toolchain(cc or "", cxx or ""))
    fetched = root / "build" / "_deps" / "llamacpp-src" / ".git"
    if offline and not fetched.exists():
        raise RuntimeError(
            "The network is off (--offline), the shipmb_vision library is not installed, and llama.cpp "
            "has not been fetched yet. Connect to the network and run `shipmblang setup --vision`, "
            "or build the library first with python tools/build_vision.py."
        )
    try:
        result = configure_and_build(source=root, cc=cc, cxx=cxx, quantize=quantize)
    except subprocess.CalledProcessError as error:
        detail = f"The vision library build failed (exit {error.returncode})."
        if offline:
            detail += " The network is off, so a missing llama.cpp download cannot be retried."
        raise RuntimeError(detail) from error
    library = result["library"]
    if library is None or not Path(library).is_file():
        raise RuntimeError("The vision library build did not install a library.")
    return Path(library)


def standalone_datas() -> list[tuple[Path, str]]:
    """Library, pins, license files, and llama-quantize to pack into the frozen executable."""
    datas: list[tuple[Path, str]] = []
    packed: set[Path] = set()
    library = package_library_path()
    if library.is_file():
        datas.append((library, "shipmblang/_compiler/native"))
        packed.add(library.resolve())
        for path in library.parent.rglob("*"):
            if not path.is_file() or path.resolve() in packed:
                continue
            parent = path.parent.relative_to(library.parent).as_posix()
            destination = "shipmblang/_compiler/native" if parent == "." else f"shipmblang/_compiler/native/{parent}"
            datas.append((path, destination))
            packed.add(path.resolve())
    tool = find_quantize_tool()
    if tool is not None and tool.is_file() and tool.resolve() not in packed:
        datas.append((tool, "native/shipmb_vision/bin"))
    return datas


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", help="C compiler. Defaults to gcc when it is installed, otherwise clang or CC. On Windows, leave this unset to use Visual Studio.")
    parser.add_argument("--cxx", help="C++ compiler. Defaults to g++ when it is installed, otherwise clang++ or CXX.")
    parser.add_argument("--build-dir", type=Path, help="CMake build directory (default: native/shipmb_vision/build).")
    parser.add_argument("--jobs", type=int, help="Parallel compile jobs (default: the CPU count).")
    parser.add_argument("--no-quantize", action="store_true", help="Do not build llama-quantize.")
    args = parser.parse_args(argv)
    if (args.cc is None) != (args.cxx is None):
        parser.error("Pass both --cc and --cxx, or neither.")
    try:
        configure_and_build(
            build_dir=args.build_dir,
            cc=args.cc,
            cxx=args.cxx,
            quantize=not args.no_quantize,
            jobs=args.jobs,
        )
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(f"shipmblang: {error}", file=sys.stderr)
        code = error.returncode if isinstance(error, subprocess.CalledProcessError) else 1
        return code or 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
