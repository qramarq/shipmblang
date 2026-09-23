"""Refresh the private compiler snapshot from its separate source repository."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tomllib


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("compiler_repo", type=Path)
    args = parser.parse_args()
    source = args.compiler_repo.resolve()
    metadata = tomllib.loads((source / "pyproject.toml").read_text(encoding="utf-8-sig"))
    if metadata["project"]["name"] != "shipmbcompiler":
        parser.error("Expected the shipmbcompiler repository")
    package = source / "shipmbcompiler"
    files = sorted(package.rglob("*.py"))
    if not (package / "direct.py").is_file() or not (package / "runtime.py").is_file():
        parser.error("Compiler source is incomplete")
    root = Path(__file__).resolve().parents[1]
    target = (root / "shipmblang/_compiler").resolve()
    paths = {file.relative_to(package) for file in files}
    # Only remove stale Python modules inside this dedicated vendored package.
    for stale in target.rglob("*.py"):
        if stale.relative_to(target) not in paths:
            if not stale.resolve().is_relative_to(target):
                raise ValueError("Refusing a path outside the compiler snapshot")
            stale.unlink()
    hashes = {}
    for file in files:
        relative = file.relative_to(package)
        destination = target / relative
        if not destination.resolve().is_relative_to(target):
            raise ValueError("Refusing a path outside the compiler snapshot")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(file, destination)
        hashes[relative.as_posix()] = hashlib.sha256(file.read_bytes()).hexdigest()
    record = {"distribution": "shipmbcompiler", "version": metadata["project"]["version"], "sha256": hashes}
    (target / "BUNDLED.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"Bundled shipmbcompiler {record['version']} ({len(files)} modules). Run the packaging check before release.")


if __name__ == "__main__":
    main()
