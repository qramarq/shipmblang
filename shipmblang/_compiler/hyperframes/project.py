"""Explicit filesystem and renderer boundary for video compilation."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile

from .compiler import compile_hyperframes, diagnostic, media_path

RESOURCES = Path(__file__).resolve().parent


def _failure(error):
    return {"status": "error", "diagnostics": [diagnostic(str(error), code="SMBHF100")]}


def write_hyperframes_project(artifact, directory, *, asset_root=None):
    """Write a new project. Never overwrite; paths resolve beneath asset_root."""
    staging = None
    try:
        if isinstance(artifact, dict) and "target_code" in artifact:
            artifact = artifact["target_code"]
        if not isinstance(artifact, dict) or not isinstance(artifact.get("source"), str):
            raise ValueError("Expected a successful HyperFrames compiler artifact.")
        expected = compile_hyperframes(artifact["source"])["target_code"]
        if expected is None or expected != artifact:
            raise ValueError("Artifact is invalid or modified; recompile its source.")
        destination = Path(directory).absolute()
        if destination.exists() or destination.is_symlink():
            raise ValueError(f"Project destination already exists: {destination}")
        root = Path(asset_root or Path.cwd()).resolve(strict=True)
        assets = []
        for element in artifact["composition"]["elements"]:
            if element["kind"] == "text":
                continue
            path = (root / element["value"].replace("\\", "/")).resolve(strict=True)
            if not path.is_relative_to(root) or not path.is_file():
                raise ValueError(f"Media must be a regular file inside asset_root: {element['value']}")
            assets.append((path, media_path(element)))
        vendor = RESOURCES / "vendor"
        for name in ("gsap.min.js", "inter-latin-400-normal.woff2"):
            if not (vendor / name).is_file():
                raise ValueError(f"Missing packaged vendor resource {name}; reinstall the compiler package.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".shipmb-project-", dir=destination.parent)).resolve()
        (staging / "assets").mkdir()
        for path, local in assets:
            shutil.copyfile(path, staging / local)
        shutil.copytree(vendor, staging / "vendor")
        (staging / "index.html").write_text(artifact["files"]["index.html"], encoding="utf-8")
        (staging / "source.smb").write_text(artifact["source"], encoding="utf-8")
        metadata = {"producer": "shipmbcompiler", "target": "hyperframes", "version": "1", "composition": artifact["composition"]}
        (staging / "shipmb.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        source_map = {e["id"]: e["span"] for e in [*artifact["composition"]["scenes"], *artifact["composition"]["elements"]]}
        (staging / "source-map.json").write_text(json.dumps(source_map, indent=2), encoding="utf-8")
        # Reserve the destination atomically; even an empty preexisting directory is protected.
        destination.mkdir()
        try:
            for child in staging.iterdir():
                child.rename(destination / child.name)
        except BaseException:
            # Only remove the directory this invocation reserved.
            if destination.resolve().parent == staging.parent:
                shutil.rmtree(destination)
            raise
        return {"status": "written", "project_dir": str(destination.resolve()), "diagnostics": []}
    except (OSError, ValueError, TypeError) as error:
        return _failure(error)
    finally:
        if staging is not None and staging.is_dir() and staging.parent == Path(directory).absolute().parent.resolve():
            shutil.rmtree(staging)


def _run_bridge(args, timeout):
    command = [shutil.which("node"), str(RESOURCES / "node" / "bridge.mjs"), *args]
    options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    process = subprocess.Popen(command, stdout=subprocess.PIPE, text=True, encoding="utf-8", **options)
    try:
        stdout, _ = process.communicate(timeout=timeout)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise
    try:
        result = json.loads(stdout)
    except ValueError as error:
        raise ValueError(f"Renderer returned invalid output (exit {process.returncode}).") from error
    if process.returncode or result.get("status") != "rendered":
        raise ValueError(result.get("error", "HyperFrames rendering failed."))
    return result


def render_hyperframes_project(directory, output, *, timeout=600):
    """Render explicitly via the optional Node SDK. Return diagnostics on failure."""
    temporary = None
    try:
        if not isinstance(timeout, (int, float)) or not 0 < timeout <= 86400:
            raise ValueError("timeout must be between 0 and 86400 seconds.")
        project = Path(directory).resolve(strict=True)
        metadata = json.loads((project / "shipmb.json").read_text(encoding="utf-8"))
        if not isinstance(metadata, dict) or metadata.get("target") != "hyperframes" or metadata.get("version") != "1":
            raise ValueError("Expected a ShipMB HyperFrames project version 1.")
        destination = Path(output).absolute()
        if destination.suffix.lower() != ".mp4":
            raise ValueError("The initial renderer supports .mp4 output only.")
        if destination.exists() or destination.is_symlink():
            raise ValueError(f"Output already exists: {destination}")
        missing = [name for name in ("node", "ffmpeg", "ffprobe") if not shutil.which(name)]
        if missing:
            raise ValueError("Missing rendering tools on PATH: " + ", ".join(missing))
        if not (RESOURCES / "node" / "node_modules" / "@hyperframes" / "producer").is_dir():
            raise ValueError(f"Install renderer dependencies explicitly: npm ci --prefix \"{RESOURCES / 'node'}\"")
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, path = tempfile.mkstemp(prefix=".shipmb-render-", suffix=".mp4", dir=destination.parent)
        os.close(fd)
        temporary = Path(path)
        result = _run_bridge([str(project), str(temporary)], timeout)
        if not temporary.is_file() or temporary.stat().st_size < 100:
            raise ValueError("Renderer reported success without a valid output file.")
        # An exclusive hard link publishes the complete file without clobbering a racing writer.
        os.link(temporary, destination)
        media = result.get("media")
        if isinstance(media, dict) and isinstance(media.get("format"), dict):
            media["format"]["filename"] = str(destination.resolve())
        return {"status": "rendered", "output": str(destination.resolve()), "media": media, "diagnostics": []}
    except (OSError, ValueError, TypeError, KeyError, subprocess.TimeoutExpired) as error:
        return _failure(error)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
