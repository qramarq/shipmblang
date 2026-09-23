"""Build one wheel and verify it alone in a clean environment, without network."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import venv
import zipfile


def command(args, cwd):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout


def main():
    source = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="shipmb-bundle-") as folder:
        root = Path(folder)
        staging = root / "source"
        staging.mkdir()
        for name in ("pyproject.toml", "README.md", "LICENSE", "NOTICE"):
            shutil.copy2(source / name, staging / name)
        for name in ("shipmblang", "driplm", "shiplang", "shipmb", "driplang"):
            shutil.copytree(source / name, staging / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        wheels = root / "wheels"
        wheels.mkdir()
        command([sys.executable, "-c", "from setuptools.build_meta import build_wheel; import sys; build_wheel(sys.argv[1])", str(wheels)], staging)
        wheel = next(wheels.glob("*.whl"))
        with zipfile.ZipFile(wheel) as archive:
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
from shipmblang import run_direct_program
assert importlib.util.find_spec('shipmbcompiler') is None
assert importlib.util.find_spec('shipmbc') is None
assert not any(e.name == 'shipmbc' for e in metadata.entry_points(group='console_scripts'))
result = run_direct_program('Show 2 plus 3.', memory=False, model_provider=None)
assert result['runtime']['stdout'] == '5\\n', result
print(json.dumps({'installed': metadata.version('shipmblang'), 'output': result['runtime']['stdout']}))
'''
        print(command([str(python), "-I", "-c", check], root).strip())
        result = json.loads(command([str(python), "-I", "-m", "shipmblang", "run", "Show 2 plus 3.", "--memory", "off", "--no-english-model"], root))
        assert result["runtime"]["stdout"] == "5\n", result
        print("PASS: one wheel, private bundled compiler, no separate compiler package or command, API and CLI execute.")


if __name__ == "__main__":
    main()
