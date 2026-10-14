"""Explicit, pinned, writable renderer setup; never called on app launch."""
import argparse
from pathlib import Path
import shutil
import subprocess
from .media_workspace import renderer_root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    destination = renderer_root(args.root)
    source = Path(__file__).parent / '_compiler/hyperframes'
    destination.mkdir(parents=True, exist_ok=True)
    for folder in ('node', 'vendor'):
        (destination / folder).mkdir(exist_ok=True)
        for file in (source / folder).iterdir():
            if file.is_file():
                target = destination / folder / file.name
                if target.exists() and target.read_bytes() != file.read_bytes():
                    raise ValueError(f'Renderer resource differs from the pinned version: {target}')
                shutil.copyfile(file, target)
    subprocess.run([shutil.which('npm.cmd') or shutil.which('npm'), 'ci', '--prefix', str(destination / 'node')], check=True)
    print(f'Renderer installed: {destination}')


if __name__ == '__main__':
    main()
