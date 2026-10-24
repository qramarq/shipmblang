"""Install Rust, FFmpeg, VLC, and Ollama from official sources.

The standalone executable does not embed these tools. ``shipmblang setup`` detects
what is already on PATH, in standard install locations, or named by the existing
``SHIPMB_FFMPEG_PATH``, ``SHIPMB_FFPROBE_PATH``, and ``SHIPMB_VLC_DIR`` variables,
then installs only what is missing. Recorded paths fill gaps later; they never
override a flag, an existing variable, or a tool already on PATH.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass, field

COMPONENTS = ("rust", "ffmpeg", "vlc", "ollama")
OLLAMA_BASE_URL = "http://127.0.0.1:11434"
OLLAMA_VERSION_URL = OLLAMA_BASE_URL + "/api/version"
SETUP_HINT = (
    "Run `shipmblang setup` to install Rust, FFmpeg, VLC, or Ollama. "
    "Nothing is installed automatically."
)
_MODEL_NAME = re.compile(r"^[A-Za-z0-9_.:/-]+$")
_VLC_INSTALLER = re.compile(r'href="(vlc-3\.[0-9.]+-win(?:64|32)\.(?:exe|zip))"')
_WINGET = (
    "winget install --exact --id {package} "
    "--accept-package-agreements --accept-source-agreements --disable-interactivity"
)
_RUSTUP_UNIX = "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal"
_OLLAMA_UNIX = "curl -fsSL https://ollama.com/install.sh | sh"
_FFMPEG_LGPL_WIN64 = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
    "ffmpeg-master-latest-win64-lgpl.zip"
)
_OLLAMA_SETUP_EXE = "https://ollama.com/download/OllamaSetup.exe"
_USER_AGENT = "shipmblang-setup"


class SetupUsageError(ValueError):
    """``--only`` / ``--skip`` named an unknown component."""


@dataclass
class HostFacts:
    """Platform facts. ``files`` set means a simulated host that must not install."""

    system: str
    arch: str
    bits: int
    distro: str
    brew: str | None
    winget: bool
    sudo: bool
    euid: int
    home: str
    program_files: str
    program_files_x86: str
    env: dict
    files: frozenset | None = None
    dirs: frozenset | None = None
    which_map: dict | None = None
    versions: dict | None = None
    notes: dict = field(default_factory=dict)


@dataclass
class Snapshot:
    cargo: str | None = None
    ffmpeg: str | None = None
    ffprobe: str | None = None
    vlc_dir: str | None = None
    ollama: str | None = None
    notes: dict = field(default_factory=dict)

    def ready(self, component: str) -> bool:
        if component == "rust":
            return bool(self.cargo)
        if component == "ffmpeg":
            return bool(self.ffmpeg and self.ffprobe)
        if component == "vlc":
            return bool(self.vlc_dir)
        if component == "ollama":
            return bool(self.ollama)
        return False


@dataclass
class Step:
    component: str
    action: str
    command: str = ""
    url: str = ""
    detail: str = ""
    fallback: bool = False

    def preview(self) -> list[str]:
        prefix = "if still missing: " if self.fallback else ""
        if self.action == "shell":
            body = [self.command]
        elif self.action == "download-ffmpeg":
            body = [f"download and extract {self.url} into the ShipMBLang data directory"]
        elif self.action == "download-vlc":
            body = [f"download the latest VLC 3.x zip (or installer) from {self.url} and install it for this user"]
        elif self.action == "download-ollama":
            body = [f"download {self.url} and run it (/VERYSILENT)"]
        elif self.action == "download-rustup":
            body = [f"download {self.url} and run rustup-init.exe -y --profile minimal"]
        elif self.action == "service":
            body = [
                "start Ollama if "
                + OLLAMA_VERSION_URL
                + " is not answering (`ollama serve`)"
            ]
        elif self.action == "pull":
            body = [f"ollama pull {self.command}"]
        else:
            body = [self.detail or self.command]
        if self.detail and self.action == "shell":
            body.append(self.detail)
        return [f"[{self.component}] {prefix}{line}" for line in body]


def child(system: str, parent: str, *parts: str) -> str:
    sep = "\\" if system == "Windows" else "/"
    path = parent.rstrip("\\/")
    for part in parts:
        path += sep + part.strip("\\/")
    return path


def data_directory(env: dict | None = None) -> Path:
    env = os.environ if env is None else env
    override = env.get("SHIPMB_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        base = Path(env.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(env.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "ShipMBLang"


def config_path(env: dict | None = None) -> Path:
    return data_directory(env) / "tools.json"


def facts_data_dir(facts: HostFacts) -> str:
    override = facts.env.get("SHIPMB_DATA_DIR")
    if override:
        return override
    if facts.system == "Windows":
        base = facts.env.get("LOCALAPPDATA") or child("Windows", facts.home, "AppData", "Local")
    else:
        base = facts.env.get("XDG_DATA_HOME") or child(facts.system, facts.home, ".local", "share")
    return child(facts.system, base, "ShipMBLang")


def classify_distro(text: str) -> str:
    ident = ""
    like = ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("ID="):
            ident = line.split("=", 1)[1].strip().strip("'\"").lower()
        elif line.startswith("ID_LIKE="):
            like = line.split("=", 1)[1].strip().strip("'\"").lower()
    tokens = set(ident.replace(",", " ").split()) | set(like.replace(",", " ").split())
    if tokens & {"debian", "ubuntu", "linuxmint", "pop"}:
        return "debian"
    if tokens & {"fedora", "rhel", "centos", "rocky", "almalinux"}:
        return "fedora"
    if tokens & {"arch", "manjaro", "endeavouros"}:
        return "arch"
    return "unknown"


def latest_vlc_installer_name(html: str, bits: int) -> str | None:
    """Prefer the newest VLC 3.x zip, then the newest 3.x installer, for this CPU."""
    suffix = "64" if bits != 32 else "32"
    found = [name for name in _VLC_INSTALLER.findall(html) if f"-win{suffix}." in name]
    if not found:
        return None

    def sort_key(name: str) -> tuple:
        kind = 1 if name.endswith(".zip") else 0
        return (kind, tuple(int(part) for part in re.findall(r"\d+", name)))

    return sorted(found, key=sort_key)[-1]


def is_vlc3(text: str) -> bool:
    match = re.search(r"version\s+(\d+)", text, re.IGNORECASE)
    if match:
        return match.group(1) == "3"
    return re.search(r"\b3\.\d+\.\d+", text) is not None


def missing_tool_hint(message: str) -> str:
    text = str(message)
    lowered = text.lower()
    if "executable not found" in text or "needs rust and cargo" in lowered or "https://rustup.rs" in text:
        return SETUP_HINT
    if "no such file" in lowered and any(name in lowered for name in ("ffmpeg", "ffprobe", "vlc", "ollama", "cargo", "rustc")):
        return SETUP_HINT
    return ""


def split_names(values: list[str]) -> tuple[str, ...]:
    names = []
    for value in values:
        for part in value.replace(" ", ",").split(","):
            item = part.strip().lower()
            if item:
                names.append(item)
    return tuple(names)


def select_components(only: tuple[str, ...], skip: tuple[str, ...]) -> tuple[str, ...]:
    unknown = [name for name in (*only, *skip) if name not in COMPONENTS]
    if unknown:
        allowed = ", ".join(COMPONENTS)
        raise SetupUsageError(f"Unknown setup component '{unknown[0]}'. Choose from {allowed}.")
    chosen = COMPONENTS if not only else tuple(name for name in COMPONENTS if name in only)
    chosen = tuple(name for name in chosen if name not in skip)
    if not chosen:
        raise SetupUsageError("No setup components left. Adjust --only and --skip.")
    return chosen


def validate_model_name(name: str) -> str:
    cleaned = name.strip()
    if (
        not cleaned
        or len(cleaned) > 128
        or ".." in cleaned
        or cleaned.startswith(("/", "\\"))
        or not _MODEL_NAME.fullmatch(cleaned)
    ):
        raise SetupUsageError("Model names must use letters, numbers, and . _ : / - only.")
    return cleaned


def _is_file(facts: HostFacts, path: str) -> bool:
    if not path:
        return False
    if facts.files is None:
        return Path(path).is_file()
    return path in facts.files


def _is_dir(facts: HostFacts, path: str) -> bool:
    if not path:
        return False
    if facts.files is None:
        return Path(path).is_dir()
    if facts.dirs and path in facts.dirs:
        return True
    prefix = path.rstrip("\\/")
    return any(item.startswith(prefix + "/") or item.startswith(prefix + "\\") for item in facts.files or ())


def _first_file(facts: HostFacts, candidates: list[str]) -> str | None:
    for candidate in candidates:
        if candidate and _is_file(facts, candidate):
            return candidate
    return None


def which(facts: HostFacts, name: str) -> str | None:
    names = [name] if name.lower().endswith(".exe") else [name, name + ".exe"]
    if facts.which_map is not None:
        for item in names:
            found = facts.which_map.get(item)
            if found:
                return found
        return None
    if facts.files is None:
        found = shutil.which(name)
        if found:
            return found
        return _which_in_dirs(name, _windows_extra_dirs() if facts.system == "Windows" else [])
    for directory in facts.env.get("PATH", "").split(os.pathsep):
        if not directory:
            continue
        found = _first_file(facts, [child(facts.system, directory, item) for item in names])
        if found:
            return found
    return None


def _which_in_dirs(name: str, directories: list[str]) -> str | None:
    names = [name, name + ".exe"] if not name.lower().endswith(".exe") else [name]
    for directory in directories:
        for item in names:
            candidate = Path(directory) / item
            if candidate.is_file():
                return str(candidate)
    return None


def _windows_extra_dirs() -> list[str]:
    if os.name != "nt":
        return []
    import winreg

    directories = []
    for hive, subkey in (
        (winreg.HKEY_CURRENT_USER, r"Environment"),
        (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
    ):
        try:
            with winreg.OpenKey(hive, subkey) as key:
                value, _kind = winreg.QueryValueEx(key, "Path")
        except OSError:
            continue
        directories.extend(part for part in str(value).split(";") if part)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        directories.append(str(Path(local) / "Microsoft" / "WinGet" / "Links"))
    return directories


def _sibling(system: str, path: str, name: str) -> str:
    sep = "\\" if system == "Windows" else "/"
    parent, _sep, _filename = path.rstrip("\\/").rpartition(sep)
    if not parent:
        return name
    return parent + sep + name


def _darwin_plist_version(executable: str) -> str:
    contents = _parent_dir("Darwin", _parent_dir("Darwin", executable))
    plist_path = child("Darwin", contents, "Info.plist")
    try:
        import plistlib

        with open(plist_path, "rb") as handle:
            data = plistlib.load(handle)
    except (OSError, ValueError):
        return ""
    version = data.get("CFBundleShortVersionString") or data.get("CFBundleVersion") or ""
    return f"VLC version {version}" if version else ""


def _read_version(facts: HostFacts, executable: str) -> str:
    if facts.versions is not None and executable in facts.versions:
        return facts.versions[executable]
    if facts.files is not None:
        return ""
    try:
        completed = subprocess.run(
            [executable, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (completed.stdout or "") + "\n" + (completed.stderr or "")


def _linux_lib_dirs(arch: str) -> list[str]:
    normalized = arch.lower()
    if normalized in {"x86_64", "amd64"}:
        return ["/usr/lib/x86_64-linux-gnu", "/usr/lib64", "/usr/local/lib", "/usr/lib"]
    if normalized in {"aarch64", "arm64"}:
        return ["/usr/lib/aarch64-linux-gnu", "/usr/lib64", "/usr/local/lib", "/usr/lib"]
    if normalized in {"armv7l", "armv6l"}:
        return ["/usr/lib/arm-linux-gnueabihf", "/usr/lib", "/usr/local/lib"]
    return ["/usr/lib", "/usr/lib64", "/usr/local/lib"]


def _binary_bits(path: str) -> int | None:
    try:
        with open(path, "rb") as handle:
            if handle.read(2) != b"MZ":
                return None
            handle.seek(0x3C)
            pe_offset = int.from_bytes(handle.read(4), "little")
            handle.seek(pe_offset)
            if handle.read(4) != b"PE\0\0":
                return None
            machine = int.from_bytes(handle.read(2), "little")
    except OSError:
        return None
    if machine == 0x8664:
        return 64
    if machine == 0x14C:
        return 32
    if machine == 0xAA64:
        return 64
    return None


def _arch_matches(facts: HostFacts, binary: str) -> bool:
    if facts.system != "Windows":
        return True
    lowered = binary.replace("/", "\\").lower()
    if facts.files is not None:
        if facts.bits == 64 and "\\program files (x86)\\" in lowered:
            return False
        if facts.bits == 32 and "\\program files (x86)\\" not in lowered and "\\program files\\" in lowered:
            return facts.arch.lower() in {"x86", "i686"}
        return True
    bits = _binary_bits(binary)
    if bits is None:
        if facts.bits == 64 and "program files (x86)" in lowered:
            return False
        return True
    if facts.arch.lower() in {"arm64", "aarch64"}:
        return bits == 64
    return bits == facts.bits


def _vlc_library_names(system: str) -> tuple[str, ...]:
    if system == "Windows":
        return ("libvlc.dll",)
    if system == "Darwin":
        return ("libvlc.dylib", "libvlc.5.dylib")
    return ("libvlc.so.5",)


def _dir_has_vlc_lib(facts: HostFacts, directory: str) -> str | None:
    for name in _vlc_library_names(facts.system):
        candidate = child(facts.system, directory, name)
        if _is_file(facts, candidate):
            return candidate
    return None


def _accept_vlc_dir(facts: HostFacts, directory: str, executable: str | None) -> bool:
    library = _dir_has_vlc_lib(facts, directory)
    if not library:
        return False
    if facts.system == "Linux":
        return True
    if not executable or not _is_file(facts, executable):
        facts.notes["vlc"] = "LibVLC was found but the VLC 3.x version could not be read."
        return False
    if not _arch_matches(facts, executable):
        facts.notes["vlc"] = "VLC is installed, but its architecture does not match this ShipMBLang build."
        return False
    version = _read_version(facts, executable)
    if facts.system == "Darwin" and not version.strip() and facts.files is None:
        version = _darwin_plist_version(executable)
    if not version.strip():
        facts.notes["vlc"] = "LibVLC was found but the VLC 3.x version could not be read."
        return False
    if not is_vlc3(version):
        facts.notes["vlc"] = "VLC is installed, but ShipMBLang needs LibVLC 3.x (VLC 4 is not used)."
        return False
    return True


def _detect_rust(facts: HostFacts) -> str | None:
    found = which(facts, "cargo")
    if found:
        return found
    cargo_home = facts.env.get("CARGO_HOME") or child(facts.system, facts.home, ".cargo")
    names = ["cargo.exe", "cargo"] if facts.system == "Windows" else ["cargo"]
    return _first_file(facts, [child(facts.system, cargo_home, "bin", name) for name in names])


def _detect_ffmpeg(facts: HostFacts) -> tuple[str | None, str | None]:
    names = ["ffmpeg.exe", "ffmpeg"] if facts.system == "Windows" else ["ffmpeg"]
    probe_names = ["ffprobe.exe", "ffprobe"] if facts.system == "Windows" else ["ffprobe"]
    ffmpeg_candidates = []
    ffprobe_candidates = []
    env_ffmpeg = facts.env.get("SHIPMB_FFMPEG_PATH")
    env_ffprobe = facts.env.get("SHIPMB_FFPROBE_PATH")
    if env_ffmpeg:
        ffmpeg_candidates.append(env_ffmpeg)
    if env_ffprobe:
        ffprobe_candidates.append(env_ffprobe)
    located = which(facts, "ffmpeg")
    located_probe = which(facts, "ffprobe")
    if located:
        ffmpeg_candidates.append(located)
    if located_probe:
        ffprobe_candidates.append(located_probe)
    data_bin = child(facts.system, facts_data_dir(facts), "ffmpeg", "bin")
    standard = [data_bin]
    if facts.system == "Windows":
        standard.extend([
            r"C:\ffmpeg\bin",
            child("Windows", facts.home, "ffmpeg", "bin"),
            child("Windows", facts.env.get("LOCALAPPDATA", child("Windows", facts.home, "AppData", "Local")), "Microsoft", "WinGet", "Links"),
        ])
    elif facts.system == "Darwin":
        standard.extend(["/opt/homebrew/bin", "/usr/local/bin"])
    else:
        standard.extend(["/usr/bin", "/usr/local/bin"])
    for directory in standard:
        ffmpeg_candidates.extend(child(facts.system, directory, name) for name in names)
        ffprobe_candidates.extend(child(facts.system, directory, name) for name in probe_names)
    if facts.files is None and facts.system == "Windows":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            root = Path(local) / "Microsoft" / "WinGet" / "Packages"
            if root.is_dir():
                for binary in root.glob("Gyan.FFmpeg*/**/ffmpeg.exe"):
                    ffmpeg_candidates.append(str(binary))
                    ffprobe_candidates.append(str(binary.with_name("ffprobe.exe")))
    ffmpeg = _first_file(facts, ffmpeg_candidates)
    if ffmpeg:
        sibling_names = ["ffprobe.exe", "ffprobe"] if facts.system == "Windows" else ["ffprobe"]
        ffprobe_candidates = [_sibling(facts.system, ffmpeg, name) for name in sibling_names] + ffprobe_candidates
    ffprobe = _first_file(facts, ffprobe_candidates)
    return ffmpeg, ffprobe


def _parent_dir(system: str, path: str) -> str:
    sep = "\\" if system == "Windows" else "/"
    parent, _sep, _name = path.rstrip("\\/").rpartition(sep)
    return parent


def _vlc_candidates(facts: HostFacts) -> list[tuple[str, str | None]]:
    pairs: list[tuple[str, str | None]] = []
    configured = facts.env.get("SHIPMB_VLC_DIR")
    if configured:
        executable = None
        if facts.system == "Windows":
            executable = child("Windows", configured, "vlc.exe")
        elif facts.system == "Darwin":
            executable = child("Darwin", _parent_dir("Darwin", configured), "VLC")
        pairs.append((configured, executable))
    if facts.system == "Linux":
        for directory in _linux_lib_dirs(facts.arch):
            pairs.append((directory, None))
        if facts.files is None:
            import glob

            for library in glob.glob("/usr/lib/*/libvlc.so.5"):
                pairs.append((str(Path(library).parent), None))
    elif facts.system == "Darwin":
        directories = [
            "/Applications/VLC.app/Contents/MacOS/lib",
            child("Darwin", facts.home, "Applications", "VLC.app", "Contents", "MacOS", "lib"),
            "/opt/homebrew/lib",
            "/usr/local/lib",
        ]
        for directory in directories:
            pairs.append((directory, child("Darwin", _parent_dir("Darwin", directory), "VLC")))
    else:
        data_vlc = child("Windows", facts_data_dir(facts), "vlc")
        matching = facts.program_files if facts.bits == 64 else facts.program_files_x86
        other = facts.program_files_x86 if facts.bits == 64 else facts.program_files
        for directory in (
            data_vlc,
            child("Windows", matching, "VideoLAN", "VLC"),
            child("Windows", other, "VideoLAN", "VLC"),
        ):
            pairs.append((directory, child("Windows", directory, "vlc.exe")))
    located = which(facts, "vlc")
    if located and facts.system == "Windows":
        parent = _parent_dir("Windows", located.replace("/", "\\"))
        if parent:
            pairs.insert(0, (parent, located))
    elif located and facts.system == "Darwin":
        mac_dir = _parent_dir("Darwin", located)
        if mac_dir:
            pairs.insert(0, (child("Darwin", mac_dir, "lib"), located))
    return pairs


def _detect_vlc(facts: HostFacts) -> str | None:
    mismatch = False
    for directory, executable in _vlc_candidates(facts):
        library = _dir_has_vlc_lib(facts, directory)
        if not library:
            continue
        if facts.system == "Windows" and not _arch_matches(facts, executable or library):
            mismatch = True
            continue
        if _accept_vlc_dir(facts, directory, None if facts.system == "Linux" else executable):
            facts.notes.pop("vlc", None)
            return directory
    if mismatch and "vlc" not in facts.notes:
        facts.notes["vlc"] = "VLC is installed, but its architecture does not match this ShipMBLang build."
    elif "vlc" not in facts.notes:
        facts.notes["vlc"] = "LibVLC 3.x was not found (libvlc.so.5, libvlc.dll, or libvlc.dylib from VLC 3)."
    return None


def _detect_ollama(facts: HostFacts) -> str | None:
    found = which(facts, "ollama")
    if found:
        return found
    if facts.system == "Windows":
        local = facts.env.get("LOCALAPPDATA") or child("Windows", facts.home, "AppData", "Local")
        candidates = [
            child("Windows", local, "Programs", "Ollama", "ollama.exe"),
            child("Windows", local, "Ollama", "ollama.exe"),
            child("Windows", facts.program_files, "Ollama", "ollama.exe"),
        ]
    else:
        candidates = [
            "/usr/local/bin/ollama",
            "/usr/bin/ollama",
            child(facts.system, facts.home, ".local", "bin", "ollama"),
        ]
    return _first_file(facts, candidates)


def detect(facts: HostFacts) -> Snapshot:
    facts.notes = {}
    ffmpeg, ffprobe = _detect_ffmpeg(facts)
    return Snapshot(
        cargo=_detect_rust(facts),
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        vlc_dir=_detect_vlc(facts),
        ollama=_detect_ollama(facts),
        notes=dict(facts.notes),
    )


def _privilege(facts: HostFacts, assume_yes: bool) -> str | None:
    if facts.euid == 0:
        return ""
    if not facts.sudo:
        return None
    if assume_yes:
        return "sudo --non-interactive "
    return "sudo "


def _package_steps(facts: HostFacts, component: str, package: str, assume_yes: bool) -> list[Step]:
    privilege = _privilege(facts, assume_yes)
    if facts.distro == "debian":
        if privilege is None:
            return [_manual_privilege(component, package)]
        return [Step(component, "shell", command=(
            f"{privilege}DEBIAN_FRONTEND=noninteractive apt-get update && "
            f"{privilege}DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends {package}"
        ))]
    if facts.distro == "fedora":
        if privilege is None:
            return [_manual_privilege(component, package)]
        command = f"{privilege}dnf install -y {package}"
        detail = ""
        if component == "ffmpeg":
            detail = "Fedora and RHEL may need RPM Fusion before the ffmpeg package is available."
        return [Step(component, "shell", command=command, detail=detail)]
    if facts.distro == "arch":
        if privilege is None:
            return [_manual_privilege(component, package)]
        return [Step(component, "shell", command=f"{privilege}pacman -S --noconfirm {package}")]
    return [Step(
        component,
        "manual",
        detail=(
            f"This Linux distribution was not recognized. Install the '{package}' package "
            f"with its package manager, then rerun shipmblang setup. "
            "Fedora and RHEL often need RPM Fusion before FFmpeg is available."
        ),
    )]


def _manual_privilege(component: str, package: str) -> Step:
    return Step(
        component,
        "manual",
        detail=(
            f"Install '{package}' with administrator rights (sudo was not found), "
            "then rerun shipmblang setup."
        ),
    )


def _rustup_windows_url(arch: str) -> str:
    normalized = arch.lower()
    if normalized in {"amd64", "x86_64"}:
        return "https://win.rustup.rs/x86_64"
    if normalized in {"arm64", "aarch64"}:
        return "https://win.rustup.rs/aarch64"
    return "https://win.rustup.rs/i686"


def _ffmpeg_lgpl_url(facts: HostFacts) -> str | None:
    if facts.bits == 64 and facts.arch.lower() not in {"arm64", "aarch64"}:
        return _FFMPEG_LGPL_WIN64
    return None


def build_plan(snapshot: Snapshot, facts: HostFacts, selected: tuple[str, ...], *, assume_yes: bool, service_up: bool, model: str | None) -> list[Step]:
    steps: list[Step] = []
    if "rust" in selected and not snapshot.ready("rust"):
        if facts.system == "Windows":
            if facts.winget:
                steps.append(Step("rust", "shell", command=_WINGET.format(package="Rustlang.Rustup")))
            steps.append(Step(
                "rust", "download-rustup", url=_rustup_windows_url(facts.arch),
                fallback=facts.winget,
            ))
        else:
            steps.append(Step("rust", "shell", command=_RUSTUP_UNIX))
    if "ffmpeg" in selected and not snapshot.ready("ffmpeg"):
        steps.extend(_tool_install_steps(facts, "ffmpeg", assume_yes))
    if "vlc" in selected and not snapshot.ready("vlc"):
        steps.extend(_tool_install_steps(facts, "vlc", assume_yes))
    if "ollama" in selected and not snapshot.ready("ollama"):
        steps.extend(_tool_install_steps(facts, "ollama", assume_yes))
    if "ollama" in selected and not service_up:
        steps.append(Step("ollama", "service"))
    if model and "ollama" in selected:
        steps.append(Step("ollama", "pull", command=model))
    return steps


def _tool_install_steps(facts: HostFacts, component: str, assume_yes: bool) -> list[Step]:
    if facts.system == "Windows":
        return _windows_install_steps(facts, component)
    if facts.system == "Darwin":
        return _darwin_install_steps(facts, component)
    package = {"ffmpeg": "ffmpeg", "vlc": "vlc", "ollama": ""}[component]
    if component == "ollama":
        return [Step("ollama", "shell", command=_OLLAMA_UNIX)]
    return _package_steps(facts, component, package, assume_yes)


def _darwin_install_steps(facts: HostFacts, component: str) -> list[Step]:
    if component == "ollama":
        return [Step("ollama", "shell", command=_OLLAMA_UNIX)]
    if not facts.brew:
        manual = {
            "ffmpeg": "FFmpeg on macOS is installed with Homebrew (`brew install ffmpeg`). Install Homebrew from https://brew.sh, then rerun shipmblang setup. ShipMBLang does not install Homebrew.",
            "vlc": "VLC on macOS is installed with Homebrew (`brew install --cask vlc`). Install Homebrew from https://brew.sh, then rerun shipmblang setup. ShipMBLang does not install Homebrew.",
        }[component]
        return [Step(component, "manual", detail=manual)]
    brew = "brew" if Path(facts.brew).name == "brew" else facts.brew
    if component == "ffmpeg":
        return [Step("ffmpeg", "shell", command=f"{brew} install ffmpeg")]
    return [Step("vlc", "shell", command=f"{brew} install --cask vlc")]


def _windows_install_steps(facts: HostFacts, component: str) -> list[Step]:
    if component == "ffmpeg":
        steps = []
        if facts.winget:
            steps.append(Step("ffmpeg", "shell", command=_WINGET.format(package="Gyan.FFmpeg.Essentials")))
        url = _ffmpeg_lgpl_url(facts)
        if url:
            steps.append(Step("ffmpeg", "download-ffmpeg", url=url, fallback=facts.winget))
        elif not facts.winget:
            steps.append(Step(
                "ffmpeg",
                "manual",
                detail=(
                    "Install an FFmpeg build that matches this CPU, including ffprobe. "
                    "ShipMBLang does not embed FFmpeg. A 64-bit LGPL build is "
                    + _FFMPEG_LGPL_WIN64
                ),
            ))
        return steps
    if component == "vlc":
        steps = []
        if facts.winget:
            steps.append(Step("vlc", "shell", command=_WINGET.format(package="VideoLAN.VLC")))
        index = "https://download.videolan.org/pub/videolan/vlc/last/" + ("win64/" if facts.bits != 32 else "win32/")
        steps.append(Step("vlc", "download-vlc", url=index, fallback=facts.winget))
        return steps
    steps = []
    if facts.winget:
        steps.append(Step("ollama", "shell", command=_WINGET.format(package="Ollama.Ollama")))
    steps.append(Step("ollama", "download-ollama", url=_OLLAMA_SETUP_EXE, fallback=facts.winget))
    return steps


def format_report(snapshot: Snapshot, selected: tuple[str, ...]) -> str:
    lines = []
    for name in selected:
        if name == "ffmpeg":
            lines.append(_found_line("ffmpeg", snapshot.ffmpeg))
            lines.append(_found_line("ffprobe", snapshot.ffprobe))
            continue
        if snapshot.ready(name):
            location = {"rust": snapshot.cargo, "vlc": snapshot.vlc_dir, "ollama": snapshot.ollama}[name]
            lines.append(f"{name}: found ({location})")
        else:
            note = snapshot.notes.get(name)
            suffix = f" — {note}" if note else ""
            lines.append(f"{name}: missing{suffix}")
    return "\n".join(lines)


def _found_line(name: str, path: str | None) -> str:
    if path:
        return f"{name}: found ({path})"
    return f"{name}: missing"


def render_plan(steps: list[Step]) -> str:
    lines = []
    for step in steps:
        lines.extend(step.preview())
    return "\n".join(lines)


def load_tools(env: dict | None = None) -> dict:
    path = config_path(env)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def config_from_snapshot(snapshot: Snapshot, previous: dict | None = None) -> dict:
    previous = previous or {}
    config = {"version": 1, "ollama_base_url": OLLAMA_BASE_URL}
    fresh = {
        "ffmpeg": snapshot.ffmpeg,
        "ffprobe": snapshot.ffprobe,
        "vlc_dir": snapshot.vlc_dir,
        "cargo": snapshot.cargo,
        "ollama": snapshot.ollama,
    }
    for key, value in fresh.items():
        if value:
            config[key] = value
        elif isinstance(previous.get(key), str) and previous[key]:
            config[key] = previous[key]
    return config


def save_tools(snapshot: Snapshot, env: dict | None = None) -> Path:
    path = config_path(env)
    path.parent.mkdir(parents=True, exist_ok=True)
    config = config_from_snapshot(snapshot, load_tools(env))
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


def _path_has(path_value: str, directory: str) -> bool:
    target = os.path.normcase(os.path.normpath(directory))
    for item in path_value.split(os.pathsep):
        if item and os.path.normcase(os.path.normpath(item)) == target:
            return True
    return False


def apply_recorded_tool_env(env: dict | None = None) -> None:
    """Fill missing tool locations from tools.json without overriding flags, env, or PATH."""
    env = os.environ if env is None else env
    config = load_tools(env if env is not os.environ else None)
    if not config:
        return

    def on_path(name: str) -> bool:
        return shutil.which(name, path=env.get("PATH")) is not None

    ffmpeg = config.get("ffmpeg")
    if isinstance(ffmpeg, str) and ffmpeg and not env.get("SHIPMB_FFMPEG_PATH") and not on_path("ffmpeg") and Path(ffmpeg).is_file():
        env["SHIPMB_FFMPEG_PATH"] = ffmpeg
    ffprobe = config.get("ffprobe")
    if isinstance(ffprobe, str) and ffprobe and not env.get("SHIPMB_FFPROBE_PATH") and not on_path("ffprobe") and Path(ffprobe).is_file():
        env["SHIPMB_FFPROBE_PATH"] = ffprobe
    vlc_dir = config.get("vlc_dir")
    if isinstance(vlc_dir, str) and vlc_dir and not env.get("SHIPMB_VLC_DIR") and Path(vlc_dir).is_dir():
        env["SHIPMB_VLC_DIR"] = vlc_dir
    extras = []
    for key, command in (("cargo", "cargo"), ("ollama", "ollama")):
        path = config.get(key)
        if not isinstance(path, str) or not path or not Path(path).is_file() or on_path(command):
            continue
        directory = str(Path(path).parent)
        if not _path_has(env.get("PATH", ""), directory):
            extras.append(directory)
    if extras:
        current = env.get("PATH", "")
        env["PATH"] = (current + os.pathsep if current else "") + os.pathsep.join(extras)


def inspect_host() -> HostFacts:
    system = platform_system()
    arch = platform_machine()
    bits = 64 if sys.maxsize > 2**32 else 32
    env = dict(os.environ)
    home = str(Path.home())
    distro = "unknown"
    if system == "Linux":
        try:
            distro = classify_distro(Path("/etc/os-release").read_text(encoding="utf-8"))
        except OSError:
            distro = "unknown"
    brew = None
    if system == "Darwin":
        brew = shutil.which("brew")
        if not brew:
            for candidate in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew"):
                if Path(candidate).is_file():
                    brew = candidate
                    break
    try:
        euid = os.geteuid()
    except AttributeError:
        euid = 0
    return HostFacts(
        system=system,
        arch=arch,
        bits=bits,
        distro=distro,
        brew=brew,
        winget=system == "Windows" and shutil.which("winget") is not None,
        sudo=shutil.which("sudo") is not None,
        euid=euid,
        home=home,
        program_files=env.get("ProgramFiles", r"C:\Program Files"),
        program_files_x86=env.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        env=env,
    )


def platform_system() -> str:
    import platform

    return platform.system()


def platform_machine() -> str:
    import platform

    return platform.machine()


def ollama_api_up() -> bool:
    try:
        with urllib.request.urlopen(OLLAMA_VERSION_URL, timeout=2) as response:
            return 200 <= getattr(response, "status", 200) < 300
    except Exception:
        return False


def ensure_ollama_service(binary: str) -> bool:
    if ollama_api_up():
        return True
    kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "DETACHED_PROCESS", 0)
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen([binary, "serve"], **kwargs)
    except OSError as error:
        print(f"shipmblang: could not start Ollama: {error}", file=sys.stderr)
        return False
    deadline = time.time() + 60
    while time.time() < deadline:
        if ollama_api_up():
            return True
        time.sleep(0.5)
    print(
        "shipmblang: Ollama is installed but the service at "
        + OLLAMA_VERSION_URL
        + " did not start. Run `ollama serve` and check its log.",
        file=sys.stderr,
    )
    return False


def _download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)


def _run_shell(command: str) -> int:
    print(f"Running: {command}", flush=True)
    completed = subprocess.run(command, shell=True, check=False)
    if completed.returncode != 0:
        print(f"shipmblang: command exited {completed.returncode}: {command}", file=sys.stderr)
    return completed.returncode


def _extract_vlc_zip(archive: Path, facts: HostFacts) -> None:
    extract_root = archive.parent / "vlc-extract"
    extract_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(extract_root)
    libraries = list(extract_root.rglob("libvlc.dll"))
    if not libraries:
        print("shipmblang: the VLC archive did not contain libvlc.dll.", file=sys.stderr)
        return
    target = Path(facts_data_dir(facts)) / "vlc"
    if target.exists():
        shutil.rmtree(target)
    shutil.move(str(libraries[0].parent), str(target))


def _extract_ffmpeg_zip(archive: Path, facts: HostFacts) -> None:
    destination = Path(facts_data_dir(facts)) / "ffmpeg" / "bin"
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            name = Path(info.filename).name.lower()
            if name in {"ffmpeg.exe", "ffprobe.exe"}:
                target = destination / Path(info.filename).name
                with bundle.open(info) as source, target.open("wb") as handle:
                    shutil.copyfileobj(source, handle)


def _run_download(step: Step, facts: HostFacts) -> None:
    temp_root = Path(tempfile.mkdtemp(prefix="shipmblang-setup-"))
    try:
        if step.action == "download-ffmpeg":
            archive = temp_root / "ffmpeg-lgpl.zip"
            print(f"Downloading: {step.url}", flush=True)
            _download(step.url, archive)
            _extract_ffmpeg_zip(archive, facts)
            return
        if step.action == "download-rustup":
            installer = temp_root / "rustup-init.exe"
            print(f"Downloading: {step.url}", flush=True)
            _download(step.url, installer)
            _run_shell_list([str(installer), "-y", "--profile", "minimal"])
            return
        if step.action == "download-ollama":
            installer = temp_root / "OllamaSetup.exe"
            print(f"Downloading: {step.url}", flush=True)
            _download(step.url, installer)
            code = _run_shell_list([str(installer), "/VERYSILENT", "/NORESTART"])
            if code != 0:
                print("shipmblang: the Ollama installer may need an administrator account.", file=sys.stderr)
            return
        if step.action == "download-vlc":
            print(f"Downloading VLC index: {step.url}", flush=True)
            request = urllib.request.Request(step.url, headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(request, timeout=60) as response:
                html = response.read().decode("utf-8", "replace")
            name = latest_vlc_installer_name(html, facts.bits)
            if not name:
                print(f"shipmblang: no VLC 3.x package was listed at {step.url}", file=sys.stderr)
                return
            package_url = step.url.rstrip("/") + "/" + name
            package = temp_root / name
            print(f"Downloading: {package_url}", flush=True)
            _download(package_url, package)
            if name.endswith(".zip"):
                _extract_vlc_zip(package, facts)
            else:
                code = _run_shell_list([str(package), "/S"])
                if code != 0:
                    print("shipmblang: the VLC installer may need an administrator account.", file=sys.stderr)
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def _run_shell_list(args: list[str]) -> int:
    print("Running: " + " ".join(args), flush=True)
    completed = subprocess.run(args, check=False)
    if completed.returncode != 0:
        print(f"shipmblang: command exited {completed.returncode}: {' '.join(args)}", file=sys.stderr)
    return completed.returncode


def execute_plan(steps: list[Step], facts: HostFacts) -> tuple[bool, bool]:
    """Run install steps. Returns (service_failed, pull_failed)."""
    if facts.files is not None:
        raise RuntimeError("Refusing to run installers for a simulated host.")
    service_failed = False
    pull_failed = False
    for step in steps:
        if step.action in {"shell", "download-ffmpeg", "download-vlc", "download-ollama", "download-rustup"}:
            if detect(facts).ready(step.component):
                continue
            if step.action == "shell":
                _run_shell(step.command)
            else:
                try:
                    _run_download(step, facts)
                except Exception as error:
                    print(f"shipmblang: download failed: {error}", file=sys.stderr)
            continue
        if step.action == "manual":
            if detect(facts).ready(step.component):
                continue
            print(step.detail, file=sys.stderr)
            continue
        if step.action == "service":
            snapshot = detect(facts)
            if not snapshot.ollama:
                continue
            if not ensure_ollama_service(snapshot.ollama):
                service_failed = True
            continue
        if step.action == "pull":
            snapshot = detect(facts)
            if not snapshot.ollama:
                print("shipmblang: Ollama is not available, so no model was pulled.", file=sys.stderr)
                pull_failed = True
                continue
            code = _run_shell_list([snapshot.ollama, "pull", step.command])
            if code != 0:
                pull_failed = True
    return service_failed, pull_failed


def _confirm(steps: list[Step], assume_yes: bool, input_fn) -> bool:
    if not steps:
        print("All requested tools are already available.")
        return True
    print("ShipMBLang will install the missing tools:")
    print(render_plan(steps))
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        print("Re-run with --yes to install without a prompt.", file=sys.stderr)
        return False
    answer = input_fn("Install these tools? [Y/n] ")
    if answer.strip().lower() in {"", "y", "yes"}:
        return True
    print("Install cancelled. Nothing was changed.")
    return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shipmblang setup",
        description=(
            "Detect Rust, FFmpeg, VLC (LibVLC 3.x), and Ollama, and install any that are missing "
            "from official sources. Nothing is embedded in the ShipMBLang executable."
        ),
    )
    parser.add_argument("--yes", action="store_true", help="Install without prompting. Does not download Ollama models.")
    parser.add_argument("--check", action="store_true", help="Report what is missing and exit nonzero if any selected tool is absent.")
    parser.add_argument("--dry-run", action="store_true", help="Print the install commands without running them.")
    parser.add_argument("--only", action="append", default=[], help="Comma-separated components to include: rust, ffmpeg, vlc, ollama.")
    parser.add_argument("--skip", action="append", default=[], help="Comma-separated components to leave untouched.")
    parser.add_argument("--pull-models", action="store_true", help="Pull an Ollama model. Requires --model, or a typed name when interactive.")
    parser.add_argument("--model", default="", help="Ollama model name used with --pull-models. There is no default model.")
    parser.add_argument(
        "--vision", action="store_true",
        help=(
            "Download the pinned MiniCPM-V 4.6 weights, quantize the projector locally, "
            "and build or reuse the native vision library."
        ),
    )
    parser.add_argument(
        "--offline", action="store_true",
        help="With --vision, do not use the network. Reuse cached weights and fail if they are missing.",
    )
    return parser


def main(argv=None, *, input_fn=input, host_fn=inspect_host, detect_fn=detect, execute_fn=execute_plan, service_fn=ollama_api_up) -> int:
    args = build_parser().parse_args(argv)
    if args.offline and not args.vision:
        print("shipmblang: --offline is only valid with setup --vision.", file=sys.stderr)
        return 2
    if args.vision:
        if args.only or args.skip or args.pull_models or args.model:
            print(
                "shipmblang: setup --vision does not take --only, --skip, --pull-models, or --model.",
                file=sys.stderr,
            )
            return 2
        from .vision_setup import setup_vision

        return setup_vision(
            offline=args.offline, check=args.check, dry_run=args.dry_run,
            assume_yes=args.yes, input_fn=input_fn,
        )
    try:
        selected = select_components(split_names(args.only), split_names(args.skip))
        model = validate_model_name(args.model) if args.model else ""
    except SetupUsageError as error:
        print(f"shipmblang: {error}", file=sys.stderr)
        return 2
    facts = host_fn()
    snapshot = detect_fn(facts)
    print(format_report(snapshot, selected))
    if args.check and not args.dry_run:
        return 0 if all(snapshot.ready(name) for name in selected) else 1
    service_up = True
    if "ollama" in selected:
        service_up = service_fn() if snapshot.ollama else False
    pull_name = model if args.pull_models and model else None
    steps = build_plan(snapshot, facts, selected, assume_yes=args.yes, service_up=service_up, model=pull_name)
    if args.pull_models and "ollama" not in selected:
        print("shipmblang: --pull-models needs Ollama. Remove it from --skip or add it to --only.", file=sys.stderr)
        return 2
    if args.pull_models and not model and args.yes:
        print("Skipping Ollama model pull: no model name was given. Pass --model NAME.")
    if args.dry_run:
        if steps:
            print("Dry run. No installers will be started.")
            print(render_plan(steps))
        else:
            print("Dry run. No install commands are needed.")
        if args.check:
            return 0 if all(snapshot.ready(name) for name in selected) else 1
        return 0
    if not _confirm(steps, args.yes, input_fn):
        return 2
    prompted_model = ""
    if args.pull_models and not model and not args.yes and sys.stdin.isatty():
        typed = input_fn("Ollama model name to pull (Enter to skip): ")
        if typed.strip():
            try:
                prompted_model = validate_model_name(typed)
            except SetupUsageError as error:
                print(f"shipmblang: {error}", file=sys.stderr)
                return 2
            steps.append(Step("ollama", "pull", command=prompted_model))
    elif not args.pull_models and not args.yes and "ollama" in selected and sys.stdin.isatty() and not args.check:
        typed = input_fn("Ollama model name to pull (Enter to skip; ShipMBLang has no default model): ")
        if typed.strip():
            try:
                prompted_model = validate_model_name(typed)
            except SetupUsageError as error:
                print(f"shipmblang: {error}", file=sys.stderr)
                return 2
            steps.append(Step("ollama", "pull", command=prompted_model))
    service_failed, pull_failed = execute_fn(steps, facts)
    fresh = detect_fn(facts)
    save_tools(fresh)
    missing = [name for name in selected if not fresh.ready(name)]
    if missing or service_failed or pull_failed:
        if missing:
            print("shipmblang: still missing: " + ", ".join(missing), file=sys.stderr)
        return 1
    print(f"Recorded tool paths in {config_path()}")
    return 0


__all__ = [
    "COMPONENTS",
    "SETUP_HINT",
    "HostFacts",
    "Snapshot",
    "Step",
    "apply_recorded_tool_env",
    "build_plan",
    "child",
    "classify_distro",
    "detect",
    "format_report",
    "latest_vlc_installer_name",
    "main",
    "missing_tool_hint",
    "select_components",
]
