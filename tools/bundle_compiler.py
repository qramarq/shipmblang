"""Stage a compiler candidate without replacing the approved language snapshot."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tomllib


def stage_bundle(compiler_repo, target, resources=()):
    source = Path(compiler_repo).resolve()
    target = Path(target).resolve()
    approved = (Path(__file__).resolve().parents[1] / 'shipmblang/_compiler').resolve()
    if target == approved or target.is_relative_to(approved):
        raise ValueError('The approved snapshot cannot be a staging destination')
    if target.exists():
        raise ValueError('Staging destination must not exist')
    metadata = tomllib.loads((source / 'pyproject.toml').read_text(encoding='utf-8-sig'))
    if metadata['project']['name'] != 'shipmbcompiler':
        raise ValueError('Expected the shipmbcompiler repository')
    package = source / 'shipmbcompiler'
    files = {p.relative_to(package).as_posix(): p for p in package.rglob('*.py')
             if not {'node_modules', '__pycache__'} & set(p.relative_to(package).parts)}
    for name in resources:
        path = PurePosixPath(name)
        if (path.is_absolute() or '..' in path.parts or 'node_modules' in path.parts
                or '__pycache__' in path.parts or '\\' in name or ':' in name
                or path.as_posix() != name or name == 'BUNDLED.json'):
            raise ValueError(f'Unsafe resource path: {name}')
        files[name] = package / name
    if not {'__init__.py', 'direct.py', 'runtime.py'} <= files.keys():
        raise ValueError('Compiler source is incomplete')
    # Read and validate everything before creating a candidate. Hash copied bytes,
    # so concurrent source edits cannot disagree with the recorded manifest.
    contents = {}
    for name, path in sorted(files.items()):
        if not path.resolve().is_relative_to(package.resolve()):
            raise ValueError(f'Source escapes compiler package: {name}')
        data = path.read_bytes()
        contents[name] = data.replace(b"\r\n", b"\n") if path.suffix == ".py" else data
    record = {'distribution': 'shipmbcompiler', 'version': metadata['project']['version'],
              'sha256': {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}}
    target.mkdir(parents=True, exist_ok=False)
    for name, data in contents.items():
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    (target / 'BUNDLED.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('compiler_repo', type=Path)
    parser.add_argument('--output', type=Path, required=True, help='New candidate directory; never the approved snapshot')
    parser.add_argument('--resource', action='append', default=[], help='Explicit package-relative data/license path; repeat as needed')
    args = parser.parse_args()
    record = stage_bundle(args.compiler_repo, args.output, args.resource)
    print(f"Staged shipmbcompiler {record['version']} ({len(record['sha256'])} files). Approval is required for integration.")


if __name__ == '__main__':
    main()
