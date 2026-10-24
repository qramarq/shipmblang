"""Detection and install planning for shipmblang setup. No real installers run."""

import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from shipmblang import cli, editor
from shipmblang.setup_tools import (
    COMPONENTS,
    SETUP_HINT,
    HostFacts,
    SetupUsageError,
    Snapshot,
    apply_recorded_tool_env,
    build_plan,
    child,
    classify_distro,
    detect,
    latest_vlc_installer_name,
    main,
    missing_tool_hint,
    render_plan,
    select_components,
)


def host(**overrides) -> HostFacts:
    values = dict(
        system="Linux",
        arch="x86_64",
        bits=64,
        distro="debian",
        brew=None,
        winget=False,
        sudo=True,
        euid=1000,
        home="/home/u",
        program_files=r"C:\Program Files",
        program_files_x86=r"C:\Program Files (x86)",
        env={},
        files=frozenset(),
        dirs=frozenset(),
        which_map={},
        versions={},
    )
    values.update(overrides)
    return HostFacts(**values)


def planned(facts: HostFacts, selected=COMPONENTS, **kwargs) -> str:
    steps = build_plan(
        Snapshot(),
        facts,
        selected,
        assume_yes=kwargs.get("assume_yes", False),
        service_up=kwargs.get("service_up", False),
        model=kwargs.get("model"),
    )
    return render_plan(steps)


class DistroAndListingTests(unittest.TestCase):
    def test_distro_families(self):
        self.assertEqual(classify_distro('ID=ubuntu\nID_LIKE=debian\n'), "debian")
        self.assertEqual(classify_distro('ID="linuxmint"\n'), "debian")
        self.assertEqual(classify_distro("ID=fedora\n"), "fedora")
        self.assertEqual(classify_distro('ID=arch\nID_LIKE="archlinux"\n'), "arch")
        self.assertEqual(classify_distro("ID=alpine\n"), "unknown")

    def test_latest_vlc3_installer_is_chosen_per_architecture(self):
        html = (
            '<a href="vlc-3.0.20-win64.exe">old</a>'
            '<a href="vlc-3.0.21-win64.exe">new</a>'
            '<a href="vlc-3.0.21-win32.exe">32</a>'
            '<a href="vlc-4.0.0-win64.exe">ignored</a>'
        )
        self.assertEqual(latest_vlc_installer_name(html, 64), "vlc-3.0.21-win64.exe")
        self.assertEqual(latest_vlc_installer_name(html, 32), "vlc-3.0.21-win32.exe")
        with_zip = html + '<a href="vlc-3.0.20-win64.zip">zip</a>'
        self.assertEqual(latest_vlc_installer_name(with_zip, 64), "vlc-3.0.20-win64.zip")

    def test_component_selection(self):
        self.assertEqual(select_components(("vlc", "ffmpeg"), ("vlc",)), ("ffmpeg",))
        self.assertEqual(select_components((), ("ollama",)), ("rust", "ffmpeg", "vlc"))
        with self.assertRaises(SetupUsageError):
            select_components(("node",), ())
        with self.assertRaises(SetupUsageError):
            select_components(("ffmpeg",), ("ffmpeg",))


class DetectTests(unittest.TestCase):
    def test_standard_locations_and_cargo_home(self):
        lib = "/usr/lib/x86_64-linux-gnu/libvlc.so.5"
        files = frozenset({
            "/usr/bin/ffmpeg",
            "/usr/bin/ffprobe",
            lib,
            "/home/u/.cargo/bin/cargo",
            "/usr/local/bin/ollama",
        })
        snapshot = detect(host(files=files))
        self.assertEqual(snapshot.ffmpeg, "/usr/bin/ffmpeg")
        self.assertEqual(snapshot.ffprobe, "/usr/bin/ffprobe")
        self.assertEqual(snapshot.vlc_dir, "/usr/lib/x86_64-linux-gnu")
        self.assertEqual(snapshot.cargo, "/home/u/.cargo/bin/cargo")
        self.assertEqual(snapshot.ollama, "/usr/local/bin/ollama")
        self.assertTrue(all(snapshot.ready(name) for name in COMPONENTS))

    def test_env_and_path_win_over_later_directories(self):
        files = frozenset({
            "/opt/ffmpeg/ffmpeg",
            "/opt/ffmpeg/ffprobe",
            "/usr/bin/ffmpeg",
            "/usr/bin/ffprobe",
            "/custom/bin/ffmpeg",
            "/custom/bin/ffprobe",
        })
        from_env = detect(host(env={
            "SHIPMB_FFMPEG_PATH": "/opt/ffmpeg/ffmpeg",
            "SHIPMB_FFPROBE_PATH": "/opt/ffmpeg/ffprobe",
        }, files=files))
        self.assertEqual(from_env.ffmpeg, "/opt/ffmpeg/ffmpeg")
        from_path = detect(host(which_map={"ffmpeg": "/custom/bin/ffmpeg", "ffprobe": "/custom/bin/ffprobe"}, files=files))
        self.assertEqual(from_path.ffmpeg, "/custom/bin/ffmpeg")
        self.assertEqual(from_path.ffprobe, "/custom/bin/ffprobe")

    def test_plain_libvlc_without_soname_is_not_vlc3(self):
        files = frozenset({"/usr/lib/x86_64-linux-gnu/libvlc.so"})
        snapshot = detect(host(files=files))
        self.assertIsNone(snapshot.vlc_dir)
        self.assertIn("libvlc.so.5", snapshot.notes["vlc"])

    def test_windows_vlc3_matching_architecture(self):
        directory = child("Windows", r"C:\Program Files", "VideoLAN", "VLC")
        exe = child("Windows", directory, "vlc.exe")
        library = child("Windows", directory, "libvlc.dll")
        snapshot = detect(host(
            system="Windows",
            arch="AMD64",
            files=frozenset({exe, library}),
            versions={exe: "VLC version 3.0.21 Vetinari"},
        ))
        self.assertEqual(snapshot.vlc_dir, directory)

    def test_windows_vlc4_is_not_accepted(self):
        directory = child("Windows", r"C:\Program Files", "VideoLAN", "VLC")
        exe = child("Windows", directory, "vlc.exe")
        library = child("Windows", directory, "libvlc.dll")
        snapshot = detect(host(
            system="Windows",
            arch="AMD64",
            files=frozenset({exe, library}),
            versions={exe: "VLC version 4.0.0"},
        ))
        self.assertIsNone(snapshot.vlc_dir)
        self.assertIn("3.x", snapshot.notes["vlc"])

    def test_windows_x86_library_does_not_match_64_bit(self):
        directory = child("Windows", r"C:\Program Files (x86)", "VideoLAN", "VLC")
        exe = child("Windows", directory, "vlc.exe")
        library = child("Windows", directory, "libvlc.dll")
        snapshot = detect(host(
            system="Windows",
            bits=64,
            files=frozenset({exe, library}),
            versions={exe: "VLC version 3.0.21 Vetinari"},
        ))
        self.assertIsNone(snapshot.vlc_dir)
        self.assertIn("architecture", snapshot.notes["vlc"])

    def test_macos_app_bundle(self):
        directory = "/Applications/VLC.app/Contents/MacOS/lib"
        exe = "/Applications/VLC.app/Contents/MacOS/VLC"
        snapshot = detect(host(
            system="Darwin",
            arch="arm64",
            home="/Users/u",
            files=frozenset({child("Darwin", directory, "libvlc.dylib"), exe}),
            versions={exe: "VLC version 3.0.20 Vetinari"},
        ))
        self.assertEqual(snapshot.vlc_dir, directory)

    def test_windows_cargo_and_ollama_standard_dirs(self):
        cargo = child("Windows", r"C:\Users\u", ".cargo", "bin", "cargo.exe")
        ollama = child("Windows", r"C:\Users\u\AppData\Local", "Programs", "Ollama", "ollama.exe")
        snapshot = detect(host(system="Windows", home=r"C:\Users\u", files=frozenset({cargo, ollama})))
        self.assertEqual(snapshot.cargo, cargo)
        self.assertEqual(snapshot.ollama, ollama)


class PlanTests(unittest.TestCase):
    def test_debian_commands_and_privilege(self):
        text = planned(host())
        self.assertIn("apt-get install -y --no-install-recommends ffmpeg", text)
        self.assertIn("apt-get install -y --no-install-recommends vlc", text)
        self.assertIn("https://sh.rustup.rs", text)
        self.assertIn("https://ollama.com/install.sh", text)
        self.assertIn("ollama serve", text)
        self.assertNotIn("sudo --non-interactive", text)
        assumed = planned(host(), assume_yes=True)
        self.assertIn("sudo --non-interactive DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ffmpeg", assumed)
        as_root = planned(host(euid=0))
        self.assertNotIn("sudo", as_root)
        self.assertIn("apt-get install", as_root)
        self.assertIn("sudo was not found", planned(host(sudo=False)))

    def test_fedora_arch_and_unknown_distros(self):
        self.assertIn("dnf install -y ffmpeg", planned(host(distro="fedora")))
        self.assertIn("RPM Fusion", planned(host(distro="fedora")))
        self.assertIn("pacman -S --noconfirm vlc", planned(host(distro="arch")))
        self.assertIn("was not recognized", planned(host(distro="unknown")))

    def test_macos_uses_brew_without_installing_it(self):
        text = planned(host(system="Darwin", arch="arm64", brew="/opt/homebrew/bin/brew"))
        self.assertIn("[ffmpeg] brew install ffmpeg", text)
        self.assertIn("[vlc] brew install --cask vlc", text)
        self.assertIn("https://ollama.com/install.sh", text)
        self.assertNotIn("apt-get", text)
        missing_brew = planned(host(system="Darwin", brew=None))
        self.assertIn("https://brew.sh", missing_brew)
        self.assertIn("https://sh.rustup.rs", missing_brew)
        self.assertNotIn("[ffmpeg] brew install ffmpeg", missing_brew)

    def test_windows_winget_and_fallbacks(self):
        text = planned(host(system="Windows", arch="AMD64", bits=64, winget=True))
        self.assertIn("Rustlang.Rustup", text)
        self.assertIn("Gyan.FFmpeg.Essentials", text)
        self.assertIn("ffmpeg-master-latest-win64-lgpl.zip", text)
        self.assertIn("VideoLAN.VLC", text)
        self.assertIn("https://download.videolan.org/pub/videolan/vlc/last/win64/", text)
        self.assertIn("Ollama.Ollama", text)
        self.assertIn("https://ollama.com/download/OllamaSetup.exe", text)
        self.assertIn("if still missing:", text)
        fallback = planned(host(system="Windows", arch="AMD64", bits=64, winget=False))
        self.assertNotIn("winget", fallback)
        self.assertIn("https://win.rustup.rs/x86_64", fallback)
        self.assertIn("ffmpeg-master-latest-win64-lgpl.zip", fallback)

    def test_only_and_skip_limit_the_plan(self):
        ffmpeg_only = planned(host(), ("ffmpeg",))
        self.assertIn("ffmpeg", ffmpeg_only)
        self.assertNotIn("ollama.com", ffmpeg_only)
        self.assertNotIn("rustup", ffmpeg_only)
        self.assertNotIn("vlc", ffmpeg_only)
        without_ollama = planned(host(), ("rust", "ffmpeg", "vlc"))
        self.assertNotIn("ollama", without_ollama)

    def test_named_model_is_pulled_only_when_requested(self):
        text = planned(host(), model="demo:latest")
        self.assertIn("ollama pull demo:latest", text)


class ApplyEnvTests(unittest.TestCase):
    def test_recorded_paths_fill_gaps_without_overriding_flags_or_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data"
            data.mkdir()
            on_path = root / "bin"
            on_path.mkdir()
            (on_path / "ffmpeg").write_text("", encoding="utf-8")
            (on_path / "ffmpeg.exe").write_text("", encoding="utf-8")
            (on_path / "ffmpeg").chmod(0o755)
            (on_path / "ffmpeg.exe").chmod(0o755)
            recorded = root / "recorded-ffmpeg"
            recorded.write_text("", encoding="utf-8")
            preset_vlc = root / "preset-vlc"
            preset_vlc.mkdir()
            (data / "tools.json").write_text(json.dumps({
                "version": 1,
                "ffmpeg": str(recorded),
                "vlc_dir": str(root / "recorded-vlc"),
            }), encoding="utf-8")
            (root / "recorded-vlc").mkdir()
            env = {
                "SHIPMB_DATA_DIR": str(data),
                "PATH": str(on_path),
                "SHIPMB_VLC_DIR": str(preset_vlc),
                "PATHEXT": os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD"),
                "HOME": str(root),
            }
            for key in ("SYSTEMROOT", "USERPROFILE"):
                if key in os.environ:
                    env[key] = os.environ[key]
            with patch.dict(os.environ, env, clear=True):
                apply_recorded_tool_env()
                self.assertNotIn("SHIPMB_FFMPEG_PATH", os.environ)
                self.assertEqual(os.environ["SHIPMB_VLC_DIR"], str(preset_vlc))

    def test_recorded_paths_apply_when_missing_and_append_bin_dirs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data"
            data.mkdir()
            empty = root / "empty"
            empty.mkdir()
            ffmpeg = root / "ffmpeg"
            ffprobe = root / "ffprobe"
            ffmpeg.write_text("", encoding="utf-8")
            ffprobe.write_text("", encoding="utf-8")
            vlc = root / "vlc"
            vlc.mkdir()
            cargo = root / "cargo-bin" / "cargo"
            cargo.parent.mkdir()
            cargo.write_text("", encoding="utf-8")
            ollama = root / "ollama-bin" / "ollama"
            ollama.parent.mkdir()
            ollama.write_text("", encoding="utf-8")
            (data / "tools.json").write_text(json.dumps({
                "ffmpeg": str(ffmpeg),
                "ffprobe": str(ffprobe),
                "vlc_dir": str(vlc),
                "cargo": str(cargo),
                "ollama": str(ollama),
            }), encoding="utf-8")
            env = {
                "SHIPMB_DATA_DIR": str(data),
                "PATH": str(empty),
                "PATHEXT": os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD"),
                "HOME": str(root),
            }
            for key in ("SYSTEMROOT", "USERPROFILE"):
                if key in os.environ:
                    env[key] = os.environ[key]
            with patch.dict(os.environ, env, clear=True):
                os.environ.pop("SHIPMB_FFMPEG_PATH", None)
                os.environ.pop("SHIPMB_FFPROBE_PATH", None)
                os.environ.pop("SHIPMB_VLC_DIR", None)
                apply_recorded_tool_env()
                self.assertEqual(os.environ["SHIPMB_FFMPEG_PATH"], str(ffmpeg))
                self.assertEqual(os.environ["SHIPMB_FFPROBE_PATH"], str(ffprobe))
                self.assertEqual(os.environ["SHIPMB_VLC_DIR"], str(vlc))
                self.assertNotIn("SHIPMB_MODEL_PROVIDER", os.environ)
                path = os.environ["PATH"]
                self.assertTrue(path.startswith(str(empty)))
                self.assertIn(str(cargo.parent), path)
                self.assertIn(str(ollama.parent), path)
                self.assertLess(path.index(str(empty)), path.index(str(cargo.parent)))

    def test_existing_ffmpeg_variable_is_kept(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data"
            data.mkdir()
            recorded = root / "ffmpeg"
            recorded.write_text("", encoding="utf-8")
            (data / "tools.json").write_text(json.dumps({"ffmpeg": str(recorded)}), encoding="utf-8")
            with patch.dict(os.environ, {"SHIPMB_DATA_DIR": str(data), "SHIPMB_FFMPEG_PATH": "/preset/ffmpeg", "PATH": str(root)}, clear=False):
                apply_recorded_tool_env()
                self.assertEqual(os.environ["SHIPMB_FFMPEG_PATH"], "/preset/ffmpeg")


class MainTests(unittest.TestCase):
    def _run(self, argv, snapshot, detect_fn=None, execute_fn=None, service_fn=None, input_fn=None, facts=None):
        directory = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(directory, ignore_errors=True))
        calls = []

        def execute(steps, _facts):
            calls.append(steps)
            return False, False

        def default_detect(_facts):
            return snapshot

        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.dict(os.environ, {"SHIPMB_DATA_DIR": directory}, clear=False), patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            code = main(
                argv,
                input_fn=input_fn or (lambda _prompt: ""),
                host_fn=lambda: facts or host(),
                detect_fn=detect_fn or default_detect,
                execute_fn=execute_fn or execute,
                service_fn=service_fn or (lambda: True),
            )
        return code, stdout.getvalue(), stderr.getvalue(), Path(directory), calls

    def test_check_is_report_only(self):
        code, out, _err, directory, calls = self._run(["--check"], Snapshot())
        self.assertEqual(code, 1)
        self.assertIn("ffmpeg: missing", out)
        self.assertIn("ffprobe: missing", out)
        self.assertIn("rust: missing", out)
        self.assertIn("vlc: missing", out)
        self.assertIn("ollama: missing", out)
        self.assertEqual(calls, [])
        self.assertFalse((directory / "tools.json").exists())

    def test_dry_run_prints_commands_without_installing(self):
        code, out, _err, directory, calls = self._run(["--dry-run"], Snapshot())
        self.assertEqual(code, 0)
        self.assertIn("apt-get", out)
        self.assertIn("https://sh.rustup.rs", out)
        self.assertIn("https://ollama.com/install.sh", out)
        self.assertEqual(calls, [])
        self.assertFalse((directory / "tools.json").exists())

    def test_yes_without_model_does_not_pull(self):
        code, out, _err, _directory, _calls = self._run(["--yes", "--dry-run", "--pull-models"], Snapshot())
        self.assertEqual(code, 0)
        self.assertIn("Skipping Ollama model pull", out)
        self.assertNotIn("ollama pull", out)

    def test_pull_models_names_the_model(self):
        code, out, _err, _directory, _calls = self._run(["--dry-run", "--pull-models", "--model", "demo:latest"], Snapshot())
        self.assertEqual(code, 0)
        self.assertIn("ollama pull demo:latest", out)

    def test_invalid_names_exit_2(self):
        code, _out, err, _directory, calls = self._run(["--only", "node"], Snapshot())
        self.assertEqual(code, 2)
        self.assertIn("Unknown setup component", err)
        self.assertEqual(calls, [])
        code, _out, err, _directory, _calls = self._run(["--pull-models", "--model", "../evil", "--dry-run"], Snapshot())
        self.assertEqual(code, 2)
        self.assertIn("Model names", err)

    def test_noninteractive_refusal_and_decline(self):
        with patch.object(sys.stdin, "isatty", return_value=False):
            code, _out, err, directory, calls = self._run(["--only", "ffmpeg"], Snapshot())
        self.assertEqual(code, 2)
        self.assertIn("--yes", err)
        self.assertEqual(calls, [])
        self.assertFalse((directory / "tools.json").exists())
        with patch.object(sys.stdin, "isatty", return_value=True):
            code, _out, _err, _directory, calls = self._run(["--only", "ffmpeg"], Snapshot(), input_fn=lambda _prompt: "n")
        self.assertEqual(code, 2)
        self.assertEqual(calls, [])

    def test_yes_installs_and_records_config(self):
        ready = Snapshot(
            cargo="/home/u/.cargo/bin/cargo",
            ffmpeg="/usr/bin/ffmpeg",
            ffprobe="/usr/bin/ffprobe",
            vlc_dir="/usr/lib/x86_64-linux-gnu",
            ollama="/usr/local/bin/ollama",
        )
        state = {"calls": 0}

        def detect_fn(_facts):
            state["calls"] += 1
            return Snapshot() if state["calls"] == 1 else ready

        code, out, _err, directory, calls = self._run(["--yes", "--skip", "ollama"], Snapshot(), detect_fn=detect_fn, service_fn=lambda: False)
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 1)
        self.assertTrue(any(step.component == "ffmpeg" for step in calls[0]))
        self.assertFalse(any(step.component == "ollama" for step in calls[0]))
        config = json.loads((directory / "tools.json").read_text(encoding="utf-8"))
        self.assertEqual(config["ffmpeg"], "/usr/bin/ffmpeg")
        self.assertEqual(config["ffprobe"], "/usr/bin/ffprobe")
        self.assertEqual(config["vlc_dir"], "/usr/lib/x86_64-linux-gnu")
        self.assertEqual(config["cargo"], "/home/u/.cargo/bin/cargo")
        self.assertEqual(config["ollama_base_url"], "http://127.0.0.1:11434")
        self.assertNotIn("\r", (directory / "tools.json").read_text(encoding="utf-8"))
        self.assertIn("Recorded tool paths", out)

    def test_setup_help_and_missing_tool_hint(self):
        self.assertEqual(missing_tool_hint("ffmpeg executable not found; install it or configure its path."), SETUP_HINT)
        self.assertEqual(missing_tool_hint("VLC execution requires shipmb_vlc.dll; build the native shipmb_vlc target"), "")
        self.assertIn("Nothing is installed automatically", missing_tool_hint(
            "ShipMBLang Editor needs Rust and Cargo. Install Rust from https://rustup.rs, then rerun this command."
        ))
        with patch.object(sys, "argv", ["shipmblang", "setup", "--help"]), patch("sys.stdout", io.StringIO()) as stdout:
            with self.assertRaises(SystemExit) as raised:
                cli.main()
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--check", stdout.getvalue())
        self.assertIn("--dry-run", stdout.getvalue())

    def test_editor_offers_setup_without_installing(self):
        message = "ShipMBLang Editor needs Rust and Cargo. Install Rust from https://rustup.rs, then rerun this command."
        with patch.object(sys, "argv", ["shipmblang", "editor"]), patch("sys.stderr", io.StringIO()) as stderr, patch("shipmblang.editor.compiler_snapshot", return_value=None), patch.object(editor, "editor_launch_plan", side_effect=editor.EditorLaunchError(message)):
            with self.assertRaises(SystemExit) as raised:
                cli.main()
        self.assertEqual(raised.exception.code, 2)
        self.assertIn(message, stderr.getvalue())
        self.assertIn("shipmblang setup", stderr.getvalue())
        self.assertIn("Nothing is installed automatically", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
