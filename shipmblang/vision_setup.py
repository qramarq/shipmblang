"""``shipmblang setup --vision``: weights, local q8_0 projector, and the native library.

The language model and the f16 projector are downloaded from the pinned
Hugging Face revision. ``mmproj-model-q8_0.gguf`` is not on Hugging Face. It is
produced with llama-quantize (llama.cpp b11846, type Q8_0, no extra flags) and
checked against the pin. Files land in the cache directory the native library
searches. A second run that already matches the pins does not download again.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


HF_REPO = "openbmb/MiniCPM-V-4.6-gguf"
USER_AGENT = "shipmblang-setup"
CHUNK = 1024 * 1024


class VisionSetupError(RuntimeError):
    """A vision setup failure the command should print and exit on."""


@dataclass(frozen=True)
class FilePin:
    filename: str
    sha256: str
    size: int
    url: str | None = None


@dataclass(frozen=True)
class VisionPins:
    llm: FilePin
    f16: FilePin
    q8: FilePin
    source: Path | None = None


def vision_model_dir(env: dict | None = None, platform: str | None = None) -> Path:
    """Match the cache path in the native library, including an empty HOME."""
    env = os.environ if env is None else env
    override = env.get("SHIPMB_VISION_MODEL_DIR")
    if override:
        return Path(override)
    system = platform or sys.platform
    if system == "win32":
        local = env.get("LOCALAPPDATA")
        if local:
            return Path(local) / "shipmblang" / "vision"
        user = env.get("USERPROFILE")
        if user:
            return Path(user) / "AppData" / "Local" / "shipmblang" / "vision"
        return Path("shipmblang") / "vision"
    if system == "darwin":
        home = env.get("HOME")
        return Path(home if home else ".") / "Library" / "Caches" / "shipmblang" / "vision"
    xdg = env.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / "shipmblang" / "vision"
    home = env.get("HOME")
    if not home:
        return Path(".") / ".cache" / "shipmblang" / "vision"
    return Path(home) / ".cache" / "shipmblang" / "vision"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def matches_pin(path: Path, pin: FilePin) -> bool:
    if not path.is_file():
        return False
    if path.stat().st_size != pin.size:
        return False
    return _sha256(path) == pin.sha256


def _hf_url(repo: str, revision: str, filename: str) -> str:
    return f"https://huggingface.co/{repo}/resolve/{revision}/{filename}"


def _pin_dirs() -> list[Path]:
    """Checkout sources, then pins installed beside the library or inside a frozen app."""
    from shipmblang.vision_build import package_library_path, source_root

    found: list[Path] = []
    root = source_root()
    if root is not None:
        found.append(root)
    beside = package_library_path().parent
    found.append(beside)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        found.append(Path(meipass) / "shipmblang" / "_compiler" / "native")
        found.append(Path(meipass) / "native" / "shipmb_vision")
    return found


def load_pins(source: Path | None = None) -> VisionPins:
    """Load weight pins and check them against the native pins and vision.py."""
    if source is not None:
        root = source
    else:
        root = next((path for path in _pin_dirs() if (path / "weight_pins.json").is_file() and (path / "pins.json").is_file()), None)
    if root is None:
        raise VisionSetupError(
            "Vision weight pins were not found. Expected native/shipmb_vision/weight_pins.json."
        )
    weight_path = root / "weight_pins.json"
    native_path = root / "pins.json"
    if not weight_path.is_file() or not native_path.is_file():
        raise VisionSetupError(f"Vision pins are incomplete in {root}.")
    weight = json.loads(weight_path.read_text(encoding="utf-8"))
    native = json.loads(native_path.read_text(encoding="utf-8"))
    llm = weight["language_model"]
    f16 = weight["mmproj_f16_source"]
    q8 = weight["mmproj"]
    pairs = (
        (llm, native["language_model"], "language model"),
        (f16, native["mmproj_f16"], "f16 projector"),
        (q8, native["mmproj_q8_0"], "q8_0 projector"),
    )
    for left, right, label in pairs:
        if left["sha256"] != right["sha256"] or int(left["bytes"]) != int(right["bytes"]):
            raise VisionSetupError(f"Vision pin files disagree on the {label}.")
    from shipmblang._compiler.vision import LLM_FILENAME, MMPROJ_FILENAME, MODEL_SHA256

    if llm["filename"] != LLM_FILENAME or llm["sha256"] != MODEL_SHA256:
        raise VisionSetupError("weight_pins.json does not match vision.py's language-model pin.")
    if q8["filename"] != MMPROJ_FILENAME:
        raise VisionSetupError("weight_pins.json does not match vision.py's projector filename.")
    revision = llm["huggingface_revision"]
    if f16["huggingface_revision"] != revision or llm["huggingface_repo"] != HF_REPO or f16["huggingface_repo"] != HF_REPO:
        raise VisionSetupError("Vision download pins must use the same Hugging Face repository and revision.")
    return VisionPins(
        llm=FilePin(llm["filename"], llm["sha256"], int(llm["bytes"]), _hf_url(HF_REPO, revision, llm["filename"])),
        f16=FilePin(f16["filename"], f16["sha256"], int(f16["bytes"]), _hf_url(HF_REPO, revision, f16["filename"])),
        q8=FilePin(q8["filename"], q8["sha256"], int(q8["bytes"]), None),
        source=root,
    )


def urllib_opener(url: str, headers: dict[str, str], timeout: float = 60):
    request = urllib.request.Request(url, headers=headers)
    return urllib.request.urlopen(request, timeout=timeout)


def _network_message(label: str, error: BaseException) -> str:
    reason = getattr(error, "reason", error)
    return (
        f"The network is unavailable, so {label} could not be downloaded ({reason}). "
        "A partial file was kept when one was started. "
        "Check the connection and run `shipmblang setup --vision` again to resume."
    )


def _offline_message(label: str, path: Path) -> str:
    return (
        f"The network is off (--offline) and {label} is not in the cache at {path}. "
        "Connect to the network and run `shipmblang setup --vision`, or restore the cached file."
    )


def _progress(label: str, done: int, total: int, state: dict) -> None:
    now = time.monotonic()
    percent = int(done * 100 / total) if total else 0
    if percent == state.get("percent") and done != total and now - state.get("when", 0) < 1:
        return
    state["percent"] = percent
    state["when"] = now
    print(f"{label}: {done}/{total} ({percent}%)", flush=True)


def _response_status(response) -> int:
    status = getattr(response, "status", None)
    if status is None and hasattr(response, "getcode"):
        status = response.getcode()
    return int(status or 0)


def download_verified(pin: FilePin, dest: Path, *, opener, offline: bool) -> str:
    """Download ``pin`` to ``dest`` with resume, then check size and SHA-256.

    Returns ``present`` when the cached file already matches, or ``downloaded``.
    """
    if pin.url is None:
        raise VisionSetupError(f"{pin.filename} is produced locally and is not downloaded.")
    if matches_pin(dest, pin):
        print(f"{pin.filename}: already installed ({pin.size} bytes, sha256 {pin.sha256})", flush=True)
        return "present"
    if dest.exists():
        dest.unlink()
    if offline:
        raise VisionSetupError(_offline_message(pin.filename, dest))
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(dest.name + ".partial")
    if partial.is_file() and partial.stat().st_size == pin.size and _sha256(partial) == pin.sha256:
        os.replace(partial, dest)
        print(f"{pin.filename}: verified resumed download ({pin.size} bytes, sha256 {pin.sha256})", flush=True)
        return "downloaded"
    if partial.is_file() and partial.stat().st_size > pin.size:
        partial.unlink()
    resume = partial.stat().st_size if partial.is_file() else 0
    headers = {"User-Agent": USER_AGENT}
    if resume:
        headers["Range"] = f"bytes={resume}-"
        print(f"{pin.filename}: resuming at byte {resume}", flush=True)
    else:
        print(f"{pin.filename}: downloading {pin.size} bytes", flush=True)
        print(pin.url, flush=True)
    try:
        with opener(pin.url, headers) as response:
            status = _response_status(response)
            if resume and status == 200:
                resume = 0
                mode = "wb"
            elif resume and status == 206:
                mode = "ab"
            elif status == 200 and not resume:
                mode = "wb"
            elif status in {200, 206}:
                mode = "wb"
                resume = 0
            else:
                raise VisionSetupError(f"Could not download {pin.filename}: HTTP {status} from {pin.url}.")
            length = response.headers.get("Content-Length") if hasattr(response, "headers") else None
            if length is not None and status == 200 and int(length) != pin.size:
                raise VisionSetupError(
                    f"{pin.filename} on the server is {length} bytes; the pin says {pin.size}."
                )
            done = resume
            state: dict = {}
            with partial.open(mode) as handle:
                while True:
                    chunk = response.read(CHUNK)
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    _progress(pin.filename, done, pin.size, state)
    except VisionSetupError:
        raise
    except urllib.error.HTTPError as error:
        raise VisionSetupError(f"Could not download {pin.filename}: HTTP {error.code} from {pin.url}.") from error
    except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.IncompleteRead) as error:
        raise VisionSetupError(_network_message(pin.filename, error)) from error
    if not partial.is_file() or partial.stat().st_size != pin.size or _sha256(partial) != pin.sha256:
        got_size = partial.stat().st_size if partial.is_file() else 0
        got_hash = _sha256(partial) if partial.is_file() else ""
        partial.unlink(missing_ok=True)
        raise VisionSetupError(
            f"{pin.filename} failed verification. Expected {pin.size} bytes and sha256 {pin.sha256}; "
            f"got {got_size} bytes and sha256 {got_hash or 'missing'}."
        )
    os.replace(partial, dest)
    print(f"{pin.filename}: verified ({pin.size} bytes, sha256 {pin.sha256})", flush=True)
    return "downloaded"


def quantize_projector(f16: Path, dest: Path, pin: FilePin, quantize_bin: Path) -> str:
    """Run llama-quantize Q8_0 with no extra flags and check the pin."""
    if matches_pin(dest, pin):
        print(f"{pin.filename}: already quantized ({pin.size} bytes, sha256 {pin.sha256})", flush=True)
        return "present"
    if dest.exists():
        dest.unlink()
    partial = dest.with_name(dest.name + ".partial")
    if partial.exists():
        partial.unlink()
    if not quantize_bin.is_file():
        raise VisionSetupError(
            "llama-quantize was not found. Build it with `python tools/build_vision.py` "
            "(that passes -DSHIPMB_VISION_QUANTIZE=ON) or set SHIPMB_LLAMA_QUANTIZE."
        )
    command = [str(quantize_bin), str(f16), str(partial), "Q8_0"]
    print("Quantizing the projector: " + " ".join(command), flush=True)
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        partial.unlink(missing_ok=True)
        raise VisionSetupError(f"llama-quantize exited {completed.returncode}.")
    if not matches_pin(partial, pin):
        got_size = partial.stat().st_size if partial.is_file() else 0
        got_hash = _sha256(partial) if partial.is_file() else ""
        partial.unlink(missing_ok=True)
        raise VisionSetupError(
            f"{pin.filename} failed verification after quantization. "
            f"Expected {pin.size} bytes and sha256 {pin.sha256}; "
            f"got {got_size} bytes and sha256 {got_hash or 'missing'}."
        )
    os.replace(partial, dest)
    print(f"{pin.filename}: verified ({pin.size} bytes, sha256 {pin.sha256})", flush=True)
    return "quantized"


def _confirm(cache: Path, pins: VisionPins, assume_yes: bool, input_fn) -> bool:
    needed = []
    for pin in (pins.llm, pins.f16):
        if not matches_pin(cache / pin.filename, pin):
            needed.append(pin)
    q8_needed = not matches_pin(cache / pins.q8.filename, pins.q8)
    if not needed and not q8_needed:
        return True
    if needed:
        total = sum(pin.size for pin in needed)
        names = ", ".join(pin.filename for pin in needed)
        print(f"ShipMBLang will download {names} ({total} bytes) into {cache}.")
    if q8_needed:
        print(f"ShipMBLang will quantize {pins.f16.filename} to {pins.q8.filename} with llama-quantize Q8_0.")
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        print("Re-run with --yes to set up vision without a prompt.", file=sys.stderr)
        return False
    answer = input_fn("Download and prepare vision weights? [Y/n] ")
    if answer.strip().lower() in {"", "y", "yes"}:
        return True
    print("Vision setup cancelled. Nothing was changed.")
    return False


def _status_line(path: Path, pin: FilePin) -> str:
    if matches_pin(path, pin):
        return f"ok  {pin.filename}  {pin.size} bytes  {pin.sha256}"
    if path.is_file():
        return f"mismatch  {pin.filename}  cache has {path.stat().st_size} bytes, pin is {pin.size}"
    partial = path.with_name(path.name + ".partial")
    if partial.is_file():
        return f"partial  {pin.filename}  {partial.stat().st_size}/{pin.size} bytes"
    return f"missing  {pin.filename}"


def setup_vision(
    *,
    offline: bool = False,
    check: bool = False,
    dry_run: bool = False,
    assume_yes: bool = False,
    cache_dir: Path | None = None,
    opener=None,
    quantize_fn=None,
    ensure_library=None,
    pins: VisionPins | None = None,
    input_fn=input,
    env: dict | None = None,
) -> int:
    """Install vision weights and the native library. Returns a process exit code."""
    try:
        loaded = pins if pins is not None else load_pins()
        cache = cache_dir if cache_dir is not None else vision_model_dir(env)
        cache.mkdir(parents=True, exist_ok=True)
        from shipmblang import vision_build

        library = vision_build.existing_library()
        print(f"Vision cache: {cache}")
        if library is not None:
            print(f"Vision library: {library}")
        else:
            print("Vision library: not installed")
        for pin in (loaded.llm, loaded.f16, loaded.q8):
            print(_status_line(cache / pin.filename, pin))
        if check and not dry_run:
            ready = library is not None and matches_pin(cache / loaded.llm.filename, loaded.llm) and matches_pin(cache / loaded.q8.filename, loaded.q8)
            if not ready:
                print("Vision is not ready. Run `shipmblang setup --vision`.", file=sys.stderr)
                return 1
            print("Vision is ready.")
            return 0
        if dry_run:
            print("Dry run. No files will be downloaded, quantized, or built.")
            if library is None:
                print("Would build native/shipmb_vision when a C++ toolchain is present, otherwise stop with an error.")
            for pin in (loaded.llm, loaded.f16):
                if not matches_pin(cache / pin.filename, pin):
                    print(f"Would download {pin.url}")
            if not matches_pin(cache / loaded.q8.filename, loaded.q8):
                print(f"Would quantize {loaded.f16.filename} to {loaded.q8.filename} with Q8_0.")
            return 0
        if not _confirm(cache, loaded, assume_yes, input_fn):
            return 2
        if ensure_library is None:
            library = vision_build.ensure_installed(offline=offline, quantize=True)
        else:
            library = ensure_library()
        if library is None or not Path(library).is_file():
            raise VisionSetupError("The vision library is still missing after setup.")
        print(f"Vision library: {library}")
        fetch = opener if opener is not None else urllib_opener
        download_verified(loaded.llm, cache / loaded.llm.filename, opener=fetch, offline=offline)
        download_verified(loaded.f16, cache / loaded.f16.filename, opener=fetch, offline=offline)
        if quantize_fn is not None:
            if not matches_pin(cache / loaded.q8.filename, loaded.q8):
                quantize_fn(cache / loaded.f16.filename, cache / loaded.q8.filename)
                if not matches_pin(cache / loaded.q8.filename, loaded.q8):
                    raise VisionSetupError(
                        f"{loaded.q8.filename} failed verification after quantization. "
                        f"Expected sha256 {loaded.q8.sha256}."
                    )
                print(f"{loaded.q8.filename}: verified ({loaded.q8.size} bytes, sha256 {loaded.q8.sha256})", flush=True)
            else:
                print(f"{loaded.q8.filename}: already quantized ({loaded.q8.size} bytes, sha256 {loaded.q8.sha256})", flush=True)
        else:
            tool = vision_build.find_quantize_tool()
            if tool is None:
                raise VisionSetupError(
                    "llama-quantize was not found next to the vision build. "
                    "Run `python tools/build_vision.py` so the pinned llama.cpp quantizer is built."
                )
            quantize_projector(cache / loaded.f16.filename, cache / loaded.q8.filename, loaded.q8, tool)
        print("Vision weights are installed.")
        print(f"  {cache / loaded.llm.filename}")
        print(f"  {cache / loaded.q8.filename}")
        return 0
    except VisionSetupError as error:
        print(f"shipmblang: {error}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as error:
        print(f"shipmblang: command failed (exit {error.returncode}).", file=sys.stderr)
        return 1
    except RuntimeError as error:
        print(f"shipmblang: {error}", file=sys.stderr)
        return 1
