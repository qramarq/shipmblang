"""Verify recorded snapshot bytes in a directory or an already opened wheel."""
import hashlib
import json
from pathlib import Path, PurePosixPath


def verify_bundle(read_bytes):
    """read_bytes accepts a snapshot-relative POSIX path; no compiler imports."""
    manifest_bytes = read_bytes("BUNDLED.json")
    record = json.loads(manifest_bytes)
    hashes = record["sha256"]
    if not hashes or not {"__init__.py", "direct.py", "runtime.py"} <= hashes.keys():
        raise ValueError("Incomplete compiler manifest")
    for name, expected in hashes.items():
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name or path.as_posix() != name:
            raise ValueError(f"Unsafe manifest path: {name}")
        if hashlib.sha256(read_bytes(name)).hexdigest() != expected:
            raise ValueError(f"Snapshot hash mismatch: {name}")
    return {"version": record["version"], "files": len(hashes),
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest()}


def verify_directory(directory):
    root = Path(directory).resolve()

    def read(name):
        path = (root / name).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"Snapshot path escapes directory: {name}")
        return path.read_bytes()

    return verify_bundle(read)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    print(json.dumps(verify_directory(parser.parse_args().snapshot), indent=2))
