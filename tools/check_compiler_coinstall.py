"""Build and coinstall both local distributions, entirely in disposable folders.

Run with a Python containing setuptools, wheel and pip, passing the compiler repo.
No network or modification of either source checkout is required.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import venv


def command(args, *, cwd, env=None):
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"{args}:\n{result.stdout}\n{result.stderr}")
    return result.stdout


def main():
    language = Path(__file__).resolve().parents[1]
    compiler = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="shipmb-coinstall-") as directory:
        root = Path(directory)
        wheels = root / "wheels"
        wheels.mkdir()
        for name, source, packages, modules in (
            ("language", language, ["shipmblang", "driplm", "shiplang", "shipmb", "driplang"], []),
            ("compiler", compiler, ["shipmbcompiler"], ["shipmbc.py"]),
        ):
            staging = root / name
            staging.mkdir()
            for file in ["pyproject.toml", "README.md", *(["LICENSE"] if (source / "LICENSE").is_file() else []), *modules]:
                shutil.copy2(source / file, staging / file)
            for package in packages:
                shutil.copytree(source / package, staging / package, ignore=shutil.ignore_patterns("__pycache__"))
            command([sys.executable, "-c", "from setuptools.build_meta import build_wheel; import sys; build_wheel(sys.argv[1])", str(wheels)], cwd=staging)
        language_wheel = next(wheels.glob("shipmblang-*.whl"))
        compiler_wheel = next(wheels.glob("shipmbcompiler-*.whl"))
        for index, order in enumerate(((language_wheel, compiler_wheel), (compiler_wheel, language_wheel))):
            environment = root / f"venv-{index}"
            venv.EnvBuilder(with_pip=False).create(environment)
            executable = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            for wheel in order:
                command([sys.executable, "-m", "pip", "--python", str(executable), "install", "--no-index", "--no-deps", str(wheel)], cwd=root)
            env = {**os.environ, "SHIPMB_MEMORY": "off"}
            check = """
import importlib.metadata as metadata
import json
import shipmblang, shipmbcompiler
assert metadata.version('shipmblang') == '0.2.1'
assert metadata.metadata('shipmblang')['License-Expression'] == 'LicenseRef-Proprietary'
assert callable(shipmblang.build_onboarding_manifest)
assert callable(shipmblang.run_onboarding_checks)
assert metadata.version('shipmbcompiler') == '0.2.3'
assert shipmblang.compile_natural_program('Use ShipMB.', memory=False)['core'] == 'use shipmb'
result = shipmblang.compile_direct_program('Use the tv pack library in shipmblang to control this Roku TV like a remote.', memory=False)
assert result['status'] == 'compiled', result
assert result['target_code']['producer'] == 'shipmbcompiler'
import os, sqlite3
os.environ['SHIPMB_MEMORY'] = 'on'
shipmblang.compile_natural_program('  Use ShipMB.\\n', memory_path='test-memory.sqlite3')
shipmblang.compile_direct_program('Use the tv pack library in shipmblang to control this Roku TV like a remote.', memory_path='test-memory.sqlite3')
with sqlite3.connect('test-memory.sqlite3') as connection:
    rows = connection.execute('SELECT source,pipeline FROM submissions').fetchall()
assert ('  Use ShipMB.\\n', 'legacy') in rows, rows
assert any(pipeline == 'direct' for source, pipeline in rows), rows
print(json.dumps({'language': shipmblang.__file__, 'compiler': shipmbcompiler.__file__}))
"""
            print(command([str(executable), "-I", "-c", check], cwd=root, env=env).strip())
            output = command([str(executable), "-I", "-m", "shipmblang", "compile", "Use the tv pack library in shipmblang to control this Roku TV like a remote.", "--pipeline", "direct", "--memory", "off"], cwd=root, env=env)
            assert json.loads(output)["producer"] == "shipmbcompiler"
            output = command([str(executable), "-I", "-m", "shipmblang", "compile", "Control it like a remote.", "--pipeline", "direct", "--interpretation", "Use the tv pack library in shipmblang to control this Roku TV like a remote.", "--format", "json", "--memory", "off"], cwd=root, env=env)
            clarification = json.loads(output)
            assert clarification["source"] == "Control it like a remote."
            assert clarification["status"] == "compiled"
            for alias in ("shipmb-compile", "shipmblang-compile", "shiplang-compile"):
                script = environment / (f"Scripts/{alias}.exe" if os.name == "nt" else f"bin/{alias}")
                output = command([str(script), "Use the tv pack library in shipmblang to control this Roku TV like a remote.", "--pipeline", "direct", "--memory", "off"], cwd=root, env=env)
                assert json.loads(output)["producer"] == "shipmbcompiler"
            output = command([str(executable), "-I", "-m", "shipmblang", "run", "Use the tv pack library in shipmblang to control this Roku TV like a remote.", "--pipeline", "direct", "--memory", "off"], cwd=root, env=env)
            assert "runtime" in json.loads(output)
            for action in ("compile", "run"):
                output = command([str(executable), "-I", "-m", "shipmblang", action, "Use the tv pack library in shipmblang to control this Roku TV like a remote.", "--pipeline", "ir", "--format", "json", "--memory", "off"], cwd=root, env=env)
                result = json.loads(output)
                assert result["core_source"] is None
                assert result["target_code"]["bytecode"]
                if action == "run":
                    assert result["runtime"] is not None
            spaced_file = root / "program with spaces.smb"
            spaced_file.write_text('Let greeting be "caf\u00e9". Show greeting.', encoding="utf-8")
            output = command([str(executable), "-X", "utf8", "-I", "-m", "shipmblang", "run", "--file", str(spaced_file), "--pipeline", "direct", "--profile", "general", "--memory", "off"], cwd=root, env=env)
            assert json.loads(output)["runtime"]["stdout"] == "caf\u00e9\n"
            general_source = (language / "examples" / "general_sum.shipmb").read_text(encoding="utf-8")
            for action in ("compile", "run"):
                output = command([str(executable), "-I", "-m", "shipmblang", action, general_source, "--pipeline", "direct", "--profile", "general", "--format", "json", "--memory", "off"], cwd=root, env=env)
                result = json.loads(output)
                assert result["status"] == "compiled", result
                assert result["target_code"]["version"] == "0.3"
                assert result["target_code"]["profile"] == "general"
                if action == "run":
                    assert result["runtime"]["stdout"] == "27\n", result
                    assert result["runtime"]["output"] == ["27"], result
            prose_source = (language / "examples" / "quoted_paragraph.shipmb").read_text(encoding="utf-8")
            spaced_file.write_bytes(prose_source.encode("utf-8"))
            output = command([str(executable), "-X", "utf8", "-I", "-m", "shipmblang", "run", "--file", str(spaced_file), "--pipeline", "direct", "--profile", "general", "--memory", "off"], cwd=root, env=env)
            prose_result = json.loads(output)
            assert prose_result["source"] == prose_source
            assert prose_result["runtime"]["stdout"] == "12\n", prose_result
            function_source = (language / "examples" / "general_functions.shipmb").read_text(encoding="utf-8")
            api_check = """
import json, sys
from shipmblang import compile_direct_program, run_direct_program
compiled = compile_direct_program(sys.argv[1], profile='general', memory=False)
assert compiled['status'] == 'compiled', compiled
assert compiled['target_code']['functions'], compiled
executed = run_direct_program(sys.argv[1], profile='general', memory=False)
assert executed['target_code'] == compiled['target_code']
assert executed['runtime']['stdout'] == '720\\n', executed
assert executed['runtime']['output'] == ['720'], executed
"""
            command([str(executable), "-I", "-c", api_check, function_source], cwd=root, env=env)
            for action in ("compile", "run"):
                output = command([str(executable), "-I", "-m", "shipmblang", action, function_source, "--pipeline", "direct", "--profile", "general", "--format", "json", "--memory", "off"], cwd=root, env=env)
                result = json.loads(output)
                assert result["status"] == "compiled", result
                assert result["target_code"]["functions"], result
                if action == "run":
                    assert result["runtime"]["stdout"] == "720\n", result
                    assert result["runtime"]["output"] == ["720"], result
            print(command([str(executable), "-X", "utf8", "-I", str(language / "tools/check_paragraphs.py"), str(language)], cwd=root, env=env).strip())
            if index == 0 and os.environ.get("SHIPMB_CODE_EXE"):
                editor_env = {**env, "SHIPMB_TEST_PYTHON": str(executable), "SHIPMB_TEST_CWD": str(root), "SHIPMB_TEST_EXAMPLES": str(language / "examples")}
                code_args = [os.environ["SHIPMB_CODE_EXE"], "--user-data-dir", str(root / "vscode-profile"), "--extensions-dir", str(root / "vscode-extensions"),
                    "--extensionDevelopmentPath=" + str(language / "extensions/vscode-shipmblang"),
                    "--extensionTestsPath=" + str(language / "extensions/vscode-shipmblang/test/host"),
                    "--skip-welcome", "--skip-release-notes", "--disable-workspace-trust", "--disable-gpu", "--no-sandbox"]
                startup = None
                if os.name == "nt":
                    startup = subprocess.STARTUPINFO(); startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW; startup.wShowWindow = 0
                editor = subprocess.run(code_args, cwd=root, env=editor_env, capture_output=True, text=True, timeout=120, startupinfo=startup)
                assert editor.returncode == 0, editor.stdout + editor.stderr
                assert "SHIPMB_EDITOR_HOST_PASS" in editor.stdout + editor.stderr, editor.stdout + editor.stderr
                print("Real VS Code extension host passed")
            print(f"Installation order {index + 1}: API, aliases, memory, general sum/functions, direct and IR run passed")


if __name__ == "__main__":
    main()
