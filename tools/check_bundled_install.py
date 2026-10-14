"""Build one wheel and verify it alone in a clean environment, without network."""
import json
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import venv
import zipfile
from verify_bundle import verify_bundle, verify_directory


def command(args, cwd):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout


def main():
    source = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, help='Candidate snapshot to test in an isolated build')
    args = parser.parse_args()
    snapshot = args.snapshot or source / "shipmblang/_compiler"
    identity = verify_directory(snapshot)
    with tempfile.TemporaryDirectory(prefix="shipmb-bundle-") as folder:
        root = Path(folder)
        staging = root / "source"
        staging.mkdir()
        for name in ("pyproject.toml", "README.md", "LICENSE", "NOTICE"):
            shutil.copy2(source / name, staging / name)
        for name in ("shipmblang", "driplm", "shiplang", "shipmb", "driplang"):
            shutil.copytree(source / name, staging / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        if args.snapshot:
            destination = (staging / 'shipmblang/_compiler').resolve()
            if not destination.is_relative_to(staging.resolve()):
                raise ValueError('Candidate destination escapes temporary build')
            shutil.rmtree(destination)
            shutil.copytree(snapshot, destination, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        wheels = root / "wheels"
        wheels.mkdir()
        command([sys.executable, "-c", "from setuptools.build_meta import build_wheel; import sys; build_wheel(sys.argv[1])", str(wheels)], staging)
        wheel = next(wheels.glob("*.whl"))
        with zipfile.ZipFile(wheel) as archive:
            packaged_identity = verify_bundle(lambda name: archive.read("shipmblang/_compiler/" + name))
            assert packaged_identity == identity, "Wheel snapshot differs from source"
            names = archive.namelist()
            assert "shipmblang/_compiler/direct.py" in names
            assert "shipmblang/_compiler/BUNDLED.json" in names
            assert not any(name.startswith(("shipmbcompiler/", "shipmbc.")) for name in names)
            metadata = archive.read(next(name for name in names if name.endswith(".dist-info/METADATA"))).decode()
            assert "Requires-Dist: shipmbcompiler" not in metadata
        environment = root / "venv"
        venv.EnvBuilder(with_pip=False).create(environment)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        command([sys.executable, "-m", "pip", "--python", str(python), "install", "--no-index", "--no-deps", str(wheel)], root)
        check = '''
import importlib.util, importlib.metadata as metadata, json
from shipmblang import FFmpegExecutor, compile_direct_program, run_direct_program
assert importlib.util.find_spec('shipmbcompiler') is None
assert importlib.util.find_spec('shipmbc') is None
assert not any(e.name == 'shipmbc' for e in metadata.entry_points(group='console_scripts'))
result = run_direct_program('Show 2 plus 3.', memory=False, model_provider=None)
assert result['runtime']['stdout'] == '5\\n', result
vlc_program = 'Open VLC player "p" from "input.mp4". Show the VLC state of "p". Close VLC player "p".'
vlc_artifact = compile_direct_program(vlc_program, memory=False, model_provider=None)
assert vlc_artifact['status'] == 'compiled', vlc_artifact
assert vlc_artifact['target_code']['version'] == '0.5'
class FakeVLC:
    def invoke(self, operation, values):
        return 'playing' if operation == 'state' else None
vlc_result = run_direct_program(vlc_program, vlc_executor=FakeVLC(), memory=False, model_provider=None)
assert vlc_result['runtime']['stdout'].strip() == 'playing', vlc_result
media = 'Convert "input.mp4" to "output.mp4".'
compiled = compile_direct_program(media, memory=False, model_provider=None)
assert compiled['status'] == 'compiled', compiled
assert compiled['target_code']['version'] == '0.4', compiled
assert 'runtime' not in compiled, compiled
denied = run_direct_program(media, memory=False, model_provider=None)
assert any(d['level'] == 'error' for d in denied['diagnostics']), denied
assert callable(FFmpegExecutor)
print(json.dumps({'installed': metadata.version('shipmblang'), 'output': result['runtime']['stdout']}))
'''
        print(command([str(python), "-I", "-c", check], root).strip())
        result = json.loads(command([str(python), "-I", "-m", "shipmblang", "run", "Show 2 plus 3.", "--memory", "off", "--no-english-model"], root))
        assert result["runtime"]["stdout"] == "5\n", result
        media = json.loads(command([str(python), "-I", "-m", "shipmblang", "compile",
                                    'Convert "input.mp4" to "output.mp4".', "--memory", "off",
                                    "--no-english-model"], root))
        assert media["version"] == "0.4", media
        if (snapshot / 'hyperframes/__init__.py').exists():
            video_source = root / 'clip.shipmb'
            video_source.write_text(
                'Create a video at 320 by 180 pixels and 24 frames per second.\n'
                'Add scene "intro" lasting 1 second.\n'
                'Show text "Hello" as "title" in scene "intro".\n', encoding='utf-8')
            video_project = root / 'video-project'
            video_result = json.loads(command([
                str(python), '-I', '-m', 'shipmblang', 'hyperframes', 'compile',
                str(video_source), '--out', str(video_project)], root))
            assert video_result['status'] == 'written', video_result
            assert (video_project / 'index.html').is_file()
            print('PASS: installed HyperFrames CLI writes a standalone HTML project without Node dependencies.')
        print("PASS: one wheel, private bundled compiler, no separate compiler package or command, API and CLI execute.")
        print(json.dumps(identity, sort_keys=True))


if __name__ == "__main__":
    main()
