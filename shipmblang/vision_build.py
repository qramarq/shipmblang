"""Build the vendored shipmb_vision library and install it for vision.py.

llama.cpp is not in the tree. CMake FetchContent clones tag b11846 and applies
patches/llama.cpp-b11846-shipmb.patch. The shared library is copied to
shipmblang/_compiler/native/, which is the path vision.py opens when
SHIPMB_VISION_BRIDGE is unset.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys


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


def toolchain_available(cc: str | None = None, cxx: str | None = None) -> bool:
    chosen_cc, chosen_cxx = (cc, cxx) if cc and cxx else default_compilers()
    return bool(shutil.which("cmake") and shutil.which("git") and shutil.which(chosen_cc) and shutil.which(chosen_cxx))


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


def find_quantize_tool(build_dir: Path | None = None) -> Path | None:
    """llama-quantize from a build tree or from a frozen executable."""
    names = {quantize_filename()}
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        packed = Path(meipass) / "native" / "shipmb_vision" / "bin" / quantize_filename()
        if packed.is_file():
            return packed
    override = os.environ.get("SHIPMB_LLAMA_QUANTIZE")
    if override and Path(override).is_file():
        return Path(override)
    roots: list[Path] = []
    if build_dir is not None:
        roots.append(build_dir)
    source = source_root()
    if source is not None:
        roots.append(source / "build")
    seen: set[Path] = set()
    for root in roots:
        if not root.is_dir():
            continue
        resolved = root.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        for path in root.rglob(quantize_filename()):
            if path.is_file() and path.name in names:
                return path
    return None


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


def install_library(built: Path, source: Path | None = None) -> Path:
    """Copy the shared library and its license files to where vision.py looks."""
    if not built.is_file():
        raise RuntimeError(f"Built vision library was not found: {built}")
    destination = package_library_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(built, destination)
    if os.name != "nt":
        destination.chmod(destination.stat().st_mode | 0o755)
    root = source if source is not None else source_root()
    if root is not None:
        for origin, target in _license_sources(root):
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origin, target)
    return destination


def _built_library(build_dir: Path) -> Path | None:
    direct = build_dir / library_filename()
    if direct.is_file():
        return direct
    for path in build_dir.rglob(library_filename()):
        if path.is_file() and path.name == library_filename():
            return path
    return None


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
    chosen_cc, chosen_cxx = (cc, cxx) if cc and cxx else default_compilers()
    if not shutil.which("cmake") or not shutil.which("git"):
        raise RuntimeError("Building shipmb_vision requires CMake and git.")
    if not shutil.which(chosen_cc) or not shutil.which(chosen_cxx):
        raise RuntimeError(f"Compiler was not found: cc={chosen_cc} cxx={chosen_cxx}")
    output = build_dir if build_dir is not None else root / "build"
    output.mkdir(parents=True, exist_ok=True)
    configure = [
        "cmake", "-S", str(root), "-B", str(output),
        "-DCMAKE_BUILD_TYPE=Release",
        "-DGGML_CCACHE=OFF",
        f"-DCMAKE_C_COMPILER={chosen_cc}",
        f"-DCMAKE_CXX_COMPILER={chosen_cxx}",
        f"-DSHIPMB_VISION_QUANTIZE={'ON' if quantize else 'OFF'}",
    ]
    print("Configuring shipmb_vision:", " ".join(configure), flush=True)
    subprocess.run(configure, check=True)
    parallel = str(jobs if jobs is not None else (os.cpu_count() or 1))
    print(f"Building shipmb_vision ({parallel} jobs)", flush=True)
    subprocess.run(["cmake", "--build", str(output), "--parallel", parallel], check=True)
    built = _built_library(output)
    if built is None:
        raise RuntimeError(f"The build finished without producing {library_filename()} in {output}")
    installed = install_library(built, root)
    tool = find_quantize_tool(output) if quantize else None
    if quantize and tool is None:
        raise RuntimeError(f"The build finished without producing {quantize_filename()} in {output}")
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
    cc, cxx = default_compilers()
    if root is None:
        raise RuntimeError(
            "The shipmb_vision library is not packed with this install, and the vendored sources "
            "are not available. Build native/shipmb_vision on a machine with CMake and copy "
            f"{library_filename()} next to the compiler's native/ directory, or set SHIPMB_VISION_BRIDGE."
        )
    if not toolchain_available(cc, cxx):
        raise RuntimeError(
            "The shipmb_vision library is not installed, and no C++ toolchain is available to build it. "
            "Install CMake, git, and g++ (Debian/Ubuntu: sudo apt-get install build-essential cmake git ca-certificates), "
            "then run `shipmblang setup --vision`. "
            f"A compiler can also be selected with --cc and --cxx on python tools/build_vision.py. "
            f"Looked for cc={cc} cxx={cxx}."
        )
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
    library = package_library_path()
    if library.is_file():
        datas.append((library, "shipmblang/_compiler/native"))
        for path in library.parent.rglob("*"):
            if not path.is_file() or path == library:
                continue
            parent = path.parent.relative_to(library.parent).as_posix()
            destination = "shipmblang/_compiler/native" if parent == "." else f"shipmblang/_compiler/native/{parent}"
            datas.append((path, destination))
    tool = find_quantize_tool()
    if tool is not None and tool.is_file():
        datas.append((tool, "native/shipmb_vision/bin"))
    return datas


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", help="C compiler. Defaults to gcc when it is installed, otherwise clang or CC.")
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
