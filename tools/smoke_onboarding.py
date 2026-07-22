"""Smoke-test the ShipMBLang onboarding contract command."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test python -m shipmblang onboarding.")
    parser.add_argument("--python", default=sys.executable, help="Python executable to run ShipMBLang.")
    parser.add_argument("--cwd", default=".", help="Working directory for the onboarding command.")
    args = parser.parse_args()

    result = subprocess.run(
        [
            args.python,
            "-m",
            "shipmblang",
            "onboarding",
            "--format",
            "json",
            "--check",
            "--root",
            args.cwd,
        ],
        cwd=Path(args.cwd),
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    manifest = json.loads(result.stdout)

    assert manifest["schema_version"] == 1, manifest
    assert manifest["name"] == "shipmblang", manifest
    assert manifest["status"] == "ready", manifest
    assert manifest["install"]["argv"][1:4] == ["-m", "pip", "install"], manifest["install"]
    assert manifest["commands"]["onboarding"][1:] == ["-m", "shipmblang", "onboarding"], manifest["commands"]
    assert manifest["mcp"]["args"] == ["-m", "shipmblang", "mcp"], manifest["mcp"]
    assert all(check["status"] == "pass" for check in manifest["checks"]), manifest["checks"]

    print("ShipMBLang onboarding smoke test passed")


if __name__ == "__main__":
    main()
