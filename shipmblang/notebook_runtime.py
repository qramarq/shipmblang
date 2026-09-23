"""Provenance for the exact bundled notes compiler."""
import hashlib
import json
from pathlib import Path

def compiler_snapshot():
    root = Path(__file__).parent / "_compiler"
    manifest = json.loads((root / "BUNDLED.json").read_text(encoding="utf-8"))
    for filename, expected in manifest["sha256"].items():
        path = (root / filename).resolve()
        if not path.is_relative_to(root.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Compiler snapshot integrity check failed: {filename}")
    return {"version": manifest["version"], "commit": manifest["source_commit"],
            "manifest_sha256": hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()}
