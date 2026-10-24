"""Copy the vendored compiler to and from the shipmbcompiler checkout.

The compiler git checkout nests the project: ``shipmbcompiler/pyproject.toml``
and the import package ``shipmbcompiler/shipmbcompiler/``. ``bundle_compiler.py``
is pointed at that project directory, so bundle path ``X`` is
``shipmbcompiler/shipmbcompiler/X`` from the git root. A checkout that already
is the project (pyproject.toml beside the package) is accepted too.

Text comparisons ignore CR/LF. Unchanged upstream blobs are not rewritten, and
a real edit is staged with the upstream blob's newline style so the pull
request does not turn a line-ending difference into a content diff. Non-Python
HyperFrames resources stay byte-for-byte in this repo when their normalized
text is unchanged, because ``BUNDLED.json`` hashes those CRLF bytes.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.bundle_compiler import stage_bundle
from tools.verify_bundle import verify_directory


TEXT_SUFFIXES = {'.py', '.mjs', '.js', '.cjs', '.json', '.txt', '.md', '.toml',
                 '.yml', '.yaml', '.html', '.css', '.svg', '.map'}
METADATA_FILES = {'shipmblang/_compiler/BUNDLED.json', 'apps/mobile/src/compiler-snapshot.json'}
DOWNSTREAM_MARKER = 'Compiler-Sync: downstream'
PATCHES_MARKER = 'Compiler-Sync: local-patches'
ADOPT_SUBJECT = 'Sync compiler from shipmblang-compiler@'
PATCH_SUBJECT = 'Record compiler local_patches'
LANGUAGE_ONLY = {'BUNDLED.json'}


class InboundConflict(RuntimeError):
    def __init__(self, conflicts):
        self.conflicts = list(conflicts)
        names = ', '.join(self.conflicts)
        super().__init__(
            'Inbound sync stopped because these files changed in shipmblang and in '
            f'shipmblang-compiler since source_commit: {names}. '
            'Resolve them in one repository and rerun this workflow. No pull request was opened.')


def is_text(name):
    return PurePosixPath(name).suffix.lower() in TEXT_SUFFIXES


def to_lf(data):
    return data.replace(b'\r\n', b'\n').replace(b'\r', b'\n')


def normalized(name, data):
    return to_lf(data) if is_text(name) else data


def normalized_equal(name, left, right):
    return normalized(name, left) == normalized(name, right)


def ending_style(data):
    crlf = data.count(b'\r\n')
    bare_lf = data.count(b'\n') - crlf
    return 'crlf' if crlf > bare_lf else 'lf'


def render_like(name, bundled, upstream):
    """Return bundled content using upstream's newline style for changed text."""
    if not is_text(name):
        return bundled
    lf = to_lf(bundled)
    if upstream is not None and ending_style(upstream) == 'crlf':
        return lf.replace(b'\n', b'\r\n')
    return lf


def safe_name(name):
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name
            or path.as_posix() != name or name in LANGUAGE_ONLY):
        raise ValueError(f'Unsafe bundle path: {name}')
    return name


def snapshot_path(snapshot, name):
    safe_name(name)
    root = Path(snapshot).resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f'Snapshot path escapes directory: {name}')
    return path


def load_manifest(snapshot):
    return json.loads((Path(snapshot) / 'BUNDLED.json').read_text(encoding='utf-8'))


def ordered_manifest(manifest):
    ordered = {
        'distribution': manifest['distribution'],
        'version': manifest['version'],
        'sha256': {name: manifest['sha256'][name] for name in sorted(manifest['sha256'])},
        'source_commit': manifest['source_commit'],
        'local_patches': sorted(manifest.get('local_patches', [])),
    }
    if 'components' in manifest:
        ordered['components'] = manifest['components']
    return ordered


def manifest_bytes(manifest):
    return (json.dumps(ordered_manifest(manifest), indent=2) + '\n').encode()


def pin_for(manifest):
    ordered = ordered_manifest(manifest)
    return {
        'version': ordered['version'],
        'commit': ordered['source_commit'],
        'local_patches': list(ordered['local_patches']),
        'manifest_sha256': hashlib.sha256(json.dumps(ordered, sort_keys=True).encode()).hexdigest(),
    }


def write_pin(path, manifest):
    Path(path).write_text(json.dumps(pin_for(manifest), indent=2) + '\n', encoding='utf-8')


def git_text(repo, args):
    result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, check=False)
    if result.returncode:
        detail = result.stderr.decode() or result.stdout.decode()
        raise RuntimeError(detail.strip() or f'git {" ".join(args)} failed')
    return result.stdout.decode()


def git_root(path):
    return Path(git_text(path, ['rev-parse', '--show-toplevel']).strip())


def locate_project(repo):
    """Return the directory bundle_compiler.py expects (the one with pyproject.toml)."""
    repo = Path(repo)
    candidates = [repo, repo / 'shipmbcompiler']
    found = []
    for candidate in candidates:
        pyproject = candidate / 'pyproject.toml'
        if not pyproject.is_file():
            continue
        try:
            metadata = tomllib.loads(pyproject.read_text(encoding='utf-8-sig'))
        except (OSError, tomllib.TOMLDecodeError) as error:
            raise ValueError(f'Could not read {pyproject}: {error}') from error
        if metadata.get('project', {}).get('name') == 'shipmbcompiler':
            found.append(candidate.resolve())
    for candidate in found:
        if (candidate / 'shipmbcompiler' / '__init__.py').is_file():
            return candidate
    raise ValueError(
        'Could not find the shipmbcompiler project. Expected pyproject.toml with '
        'project.name = "shipmbcompiler" at the checkout root or in shipmbcompiler/. '
        'The compiler repository nests the project, so the package path from the git '
        'root is shipmbcompiler/shipmbcompiler/.')


def package_prefix(project):
    """Git path of the import package, for example shipmbcompiler/shipmbcompiler."""
    project = locate_project(project)
    root = git_root(project)
    relative = project.resolve().relative_to(root.resolve()).as_posix()
    prefix = 'shipmbcompiler' if relative == '.' else f'{relative}/shipmbcompiler'
    return root, prefix


def blob_bytes(repo, commit, git_path):
    commit_probe = subprocess.run(
        ['git', '-C', str(repo), 'cat-file', '-e', f'{commit}^{{commit}}'], capture_output=True)
    if commit_probe.returncode:
        detail = commit_probe.stderr.decode().strip()
        raise RuntimeError(
            f'Cannot read compiler commit {commit}. Fetch the full shipmblang-compiler history; '
            f'source_commit must be present. {detail}')
    spec = f'{commit}:{git_path}'
    probe = subprocess.run(['git', '-C', str(repo), 'cat-file', '-e', spec], capture_output=True)
    if probe.returncode:
        err = probe.stderr.decode()
        if 'does not exist' in err or 'exists on disk' in err:
            return None
        raise RuntimeError(f'Cannot read {git_path} at {commit}: {err.strip()}')
    result = subprocess.run(['git', '-C', str(repo), 'cat-file', 'blob', spec], capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode().strip())
    return result.stdout


def manifest_names(snapshot):
    manifest = load_manifest(snapshot)
    return [safe_name(name) for name in sorted(manifest['sha256'])]


def resource_paths(snapshot, project=None):
    """Non-Python bundle resources, plus HyperFrames data files upstream already has."""
    names = {name for name in manifest_names(snapshot) if not name.endswith('.py')}
    if project is not None:
        package = locate_project(project) / 'shipmbcompiler'
        root = package / 'hyperframes'
        if root.is_dir():
            for path in root.rglob('*'):
                if not path.is_file():
                    continue
                relative = path.relative_to(package).as_posix()
                parts = set(PurePosixPath(relative).parts)
                if 'node_modules' in parts or '__pycache__' in parts or path.suffix == '.py':
                    continue
                safe_name(relative)
                names.add(relative)
    return sorted(names)


def read_snapshot_file(snapshot, name, manifest=None):
    manifest = manifest or load_manifest(snapshot)
    data = snapshot_path(snapshot, name).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != manifest['sha256'][name]:
        raise ValueError(f'Snapshot hash mismatch: {name}')
    return data


def copy_back(snapshot, project):
    """Write bundle files onto the compiler checkout. Return changed git paths.

    Blobs whose normalized content already matches are left untouched. Changed
    text is written with the existing blob's newline style.
    """
    snapshot = Path(snapshot)
    manifest = load_manifest(snapshot)
    root, prefix = package_prefix(project)
    package = locate_project(project) / 'shipmbcompiler'
    changed = []
    preserved = []
    for name in manifest_names(snapshot):
        bundled = read_snapshot_file(snapshot, name, manifest)
        git_path = f'{prefix}/{name}'
        blob = blob_bytes(root, 'HEAD', git_path)
        destination = snapshot_path(package, name)
        if blob is not None and normalized_equal(name, bundled, blob):
            preserved.append(name)
            continue
        data = render_like(name, bundled, blob)
        if blob is not None and data == blob and destination.is_file() and destination.read_bytes() == blob:
            preserved.append(name)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        changed.append(git_path)
    return {'changed': changed, 'preserved': preserved, 'package': prefix}


def head_file_mode(repo, relative):
    result = subprocess.run(
        ['git', '-C', str(repo), 'ls-files', '-s', '--', relative], capture_output=True, text=True)
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.split()[0]
    return '100644'


def stage_exact(repo, relative_paths):
    """Stage paths with filters disabled so Git does not renormalize newlines."""
    root = git_root(repo)
    for relative in relative_paths:
        path = PurePosixPath(relative)
        if path.is_absolute() or '..' in path.parts or '\\' in relative or path.as_posix() != relative:
            raise ValueError(f'Unsafe git path: {relative}')
        absolute = root / relative
        oid = subprocess.run(
            ['git', '-C', str(root), 'hash-object', '-w', '--no-filters', '--', str(absolute)],
            capture_output=True, text=True, check=True).stdout.strip()
        mode = head_file_mode(root, relative)
        subprocess.run(
            ['git', '-C', str(root), 'update-index', '--add', '--cacheinfo', f'{mode},{oid},{relative}'],
            check=True)


def local_patches(snapshot, project, commit=None):
    """Files whose normalized content differs from upstream ``commit`` (default source_commit)."""
    snapshot = Path(snapshot)
    manifest = load_manifest(snapshot)
    commit = (commit or manifest.get('source_commit') or '').strip()
    if len(commit) != 40 or any(char not in '0123456789abcdef' for char in commit.lower()):
        raise ValueError(f'source_commit must be a 40-character sha, not {commit!r}')
    root, prefix = package_prefix(project)
    patches = []
    for name in manifest_names(snapshot):
        bundled = read_snapshot_file(snapshot, name, manifest)
        blob = blob_bytes(root, commit, f'{prefix}/{name}')
        if blob is None or not normalized_equal(name, bundled, blob):
            patches.append(name)
    return patches


def apply_local_patches(snapshot, patches, pin):
    snapshot = Path(snapshot)
    pin = Path(pin)
    manifest = load_manifest(snapshot)
    patches = sorted({safe_name(name) for name in patches})
    current_pin = json.loads(pin.read_text(encoding='utf-8')) if pin.is_file() else None
    if manifest.get('local_patches') == patches and current_pin == pin_for(manifest):
        return False
    manifest['local_patches'] = patches
    (snapshot / 'BUNDLED.json').write_bytes(manifest_bytes(manifest))
    write_pin(pin, manifest)
    return True


def _decide(name, ours, theirs, base):
    ours_n = normalized(name, ours) if ours is not None else None
    theirs_n = normalized(name, theirs) if theirs is not None else None
    base_n = normalized(name, base) if base is not None else None
    if ours is not None and theirs is not None and ours_n == theirs_n:
        return 'keep', ours
    if ours is None and theirs is not None:
        return 'take', theirs
    if theirs is None and ours is not None:
        if base is not None and ours_n == base_n:
            return 'drop', None
        if base is not None and ours_n != base_n:
            return 'conflict', None
        return 'keep', ours
    if base is not None and ours_n == base_n and theirs_n != base_n:
        return 'take', theirs
    if base is not None and theirs_n == base_n and ours_n != base_n:
        return 'keep', ours
    return 'conflict', None


def plan_inbound(snapshot, project, head, output):
    """Decide how to reconcile the snapshot with compiler HEAD and write a candidate.

    ``adopt`` moves source_commit to HEAD. local_patches is cleared only when the
    normalized snapshot matches HEAD. Local edits upstream has not touched are kept
    and listed. ``record-patches`` leaves source_commit in place and only fixes
    local_patches. ``up-to-date`` writes nothing. Conflicts raise InboundConflict
    after writing plan.json.
    """
    snapshot = Path(snapshot)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError(f'Plan output is not empty: {output}')
    manifest = load_manifest(snapshot)
    base_commit = manifest.get('source_commit') or ''
    head = head.strip().lower()
    if len(head) != 40 or any(char not in '0123456789abcdef' for char in head):
        raise ValueError(f'compiler HEAD must be a 40-character sha, not {head!r}')
    project = locate_project(project)
    root, prefix = package_prefix(project)
    actual = git_text(root, ['rev-parse', 'HEAD']).strip().lower()
    if actual != head:
        raise ValueError(f'Compiler checkout HEAD {actual} does not match {head}')
    with tempfile.TemporaryDirectory(prefix='shipmb-sync-') as tmp:
        staged = Path(tmp) / 'staged'
        stage_bundle(project, staged, resource_paths(snapshot, project))
        staged_manifest = load_manifest(staged)
        names = sorted(set(manifest['sha256']) | set(staged_manifest['sha256']))
        kept = {}
        conflicts = []
        took_upstream = False
        for name in names:
            safe_name(name)
            ours = read_snapshot_file(snapshot, name, manifest) if name in manifest['sha256'] else None
            theirs = (staged / name).read_bytes() if name in staged_manifest['sha256'] else None
            base = blob_bytes(root, base_commit, f'{prefix}/{name}') if base_commit else None
            action, data = _decide(name, ours, theirs, base)
            if action == 'conflict':
                conflicts.append(name)
                continue
            if action == 'drop':
                if ours is not None:
                    took_upstream = True
                continue
            if action == 'take' and (ours is None or not normalized_equal(name, ours, data)):
                took_upstream = True
            kept[name] = data
        patches = sorted(
            name for name, data in kept.items()
            if name not in staged_manifest['sha256']
            or not normalized_equal(name, data, (staged / name).read_bytes()))
        file_changes = sorted(
            name for name in set(manifest['sha256']) | set(kept)
            if (None if name not in manifest['sha256'] else read_snapshot_file(snapshot, name, manifest))
            != kept.get(name))
        recorded = sorted(manifest.get('local_patches', []))
        if conflicts:
            plan = {
                'action': 'conflict', 'head': head, 'source_commit': manifest.get('source_commit'),
                'patches': patches, 'changed': file_changes, 'conflicts': conflicts,
                'metadata_only': False, 'version': manifest.get('version'),
            }
            (output / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n', encoding='utf-8')
            raise InboundConflict(conflicts)
        matches_head = not patches
        if matches_head or took_upstream:
            new_manifest = {
                'distribution': staged_manifest['distribution'],
                'version': staged_manifest['version'],
                'sha256': {name: hashlib.sha256(kept[name]).hexdigest() for name in sorted(kept)},
                'source_commit': head,
                'local_patches': patches,
            }
            if 'components' in manifest:
                new_manifest['components'] = manifest['components']
            if not file_changes and ordered_manifest(new_manifest) == ordered_manifest(manifest):
                plan = {
                    'action': 'up-to-date', 'head': head, 'source_commit': manifest.get('source_commit'),
                    'patches': recorded, 'changed': [], 'conflicts': [], 'metadata_only': True,
                    'version': manifest.get('version'),
                }
                (output / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n', encoding='utf-8')
                return plan
            action = 'adopt'
        elif patches != recorded:
            action = 'record-patches'
            new_manifest = dict(manifest)
            new_manifest['local_patches'] = patches
            new_manifest['sha256'] = {name: hashlib.sha256(kept[name]).hexdigest() for name in sorted(kept)}
        else:
            plan = {
                'action': 'up-to-date', 'head': head, 'source_commit': manifest.get('source_commit'),
                'patches': patches, 'changed': [], 'conflicts': [], 'metadata_only': True,
                'version': manifest.get('version'),
            }
            (output / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n', encoding='utf-8')
            return plan
        candidate = output / 'candidate'
        candidate.mkdir()
        for name, data in sorted(kept.items()):
            destination = snapshot_path(candidate, name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        (candidate / 'BUNDLED.json').write_bytes(manifest_bytes(new_manifest))
        verify_directory(candidate)
        metadata_only = not file_changes
        plan = {
            'action': action,
            'head': head,
            'source_commit': ordered_manifest(new_manifest)['source_commit'],
            'patches': ordered_manifest(new_manifest)['local_patches'],
            'changed': file_changes,
            'conflicts': [],
            'metadata_only': metadata_only,
            'version': new_manifest['version'],
        }
        (output / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n', encoding='utf-8')
        return plan


def install_candidate(candidate, snapshot, pin):
    """Replace manifest files in the snapshot with the candidate. Keep unknown files."""
    candidate = Path(candidate).resolve()
    snapshot = Path(snapshot).resolve()
    if candidate == snapshot or candidate.is_relative_to(snapshot) or snapshot.is_relative_to(candidate):
        raise ValueError('Candidate and snapshot must be different directories')
    verify_directory(candidate)
    new_manifest = load_manifest(candidate)
    old_manifest = load_manifest(snapshot)
    for name in old_manifest['sha256']:
        if name not in new_manifest['sha256']:
            path = snapshot_path(snapshot, name)
            if path.is_file():
                path.unlink()
    names = list(new_manifest['sha256']) + ['BUNDLED.json']
    for name in names:
        source = (candidate / 'BUNDLED.json').resolve() if name == 'BUNDLED.json' else snapshot_path(candidate, name)
        destination = (snapshot / 'BUNDLED.json').resolve() if name == 'BUNDLED.json' else snapshot_path(snapshot, name)
        if name == 'BUNDLED.json' and (source.parent != candidate or destination.parent != snapshot):
            raise ValueError('Refusing to move BUNDLED.json outside the snapshot')
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
    verify_directory(snapshot)
    write_pin(pin, load_manifest(snapshot))


def message_is_echo(message):
    if DOWNSTREAM_MARKER in message or PATCHES_MARKER in message:
        return True
    subject = message.splitlines()[0] if message.strip() else ''
    return subject.startswith(ADOPT_SUBJECT) or subject.startswith(PATCH_SUBJECT)


def push_should_skip(repo, event, before, after):
    """True when an outbound run would only echo a sync this repo already absorbed."""
    if event != 'push':
        return False, 'not a push; manual runs compare content and no-op if nothing changed'
    if not before or set(before) <= {'0'}:
        return False, 'push has no previous commit to compare'
    if not after:
        return False, 'push has no head commit'
    try:
        names = [name for name in git_text(repo, ['diff', '--name-only', f'{before}..{after}']).splitlines() if name]
        commits = [sha for sha in git_text(repo, ['rev-list', '--no-merges', f'{before}..{after}']).split() if sha]
    except RuntimeError as error:
        raise RuntimeError(
            f'Cannot compare {before}..{after}. Check out shipmblang with full history. {error}') from error
    if commits and all(message_is_echo(git_text(repo, ['log', '-1', '--format=%B', sha])) for sha in commits):
        return True, 'every commit in the push is a downstream compiler sync or a local_patches record'
    if not names:
        return True, 'the push does not change any files'
    if set(names) <= METADATA_FILES:
        return True, 'the push only changes bundle provenance or the mobile compiler pin'
    return False, 'the push changes vendored compiler files'


def _emit_github_output(skip, reason):
    print(f'skip={str(skip).lower()}')
    print(f'reason={reason}')
    path = os.environ.get('GITHUB_OUTPUT')
    if not path:
        return
    with open(path, 'a', encoding='utf-8') as handle:
        handle.write(f'skip={str(skip).lower()}\n')
        handle.write(f'reason<<EOF\n{reason}\nEOF\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)

    locate = commands.add_parser('locate', help='Print the shipmbcompiler project directory')
    locate.add_argument('repo', type=Path)

    resources = commands.add_parser('resources', help='Print bundle --resource paths')
    resources.add_argument('--snapshot', type=Path, required=True)
    resources.add_argument('--project', type=Path)

    copy = commands.add_parser('copy-back', help='Copy the bundle onto a compiler checkout')
    copy.add_argument('--snapshot', type=Path, required=True)
    copy.add_argument('--project', type=Path, required=True)

    stage = commands.add_parser('stage-exact', help='Stage paths without newline renormalization')
    stage.add_argument('--repo', type=Path, required=True)
    stage.add_argument('paths', nargs='+')

    patches = commands.add_parser('local-patches', help='List or record files that differ from source_commit')
    patches.add_argument('--snapshot', type=Path, required=True)
    patches.add_argument('--project', type=Path, required=True)
    patches.add_argument('--commit')
    patches.add_argument('--apply', action='store_true')
    patches.add_argument('--pin', type=Path)

    plan = commands.add_parser('plan-inbound', help='Plan a downstream snapshot update')
    plan.add_argument('--snapshot', type=Path, required=True)
    plan.add_argument('--project', type=Path, required=True)
    plan.add_argument('--commit', required=True, help='shipmblang-compiler HEAD')
    plan.add_argument('--output', type=Path, required=True)

    install = commands.add_parser('install-candidate', help='Swap a candidate snapshot into the tree')
    install.add_argument('--candidate', type=Path, required=True)
    install.add_argument('--snapshot', type=Path, required=True)
    install.add_argument('--pin', type=Path, required=True)

    gate = commands.add_parser('push-gate', help='Decide whether an outbound push should no-op')
    gate.add_argument('--repo', type=Path, default=Path('.'))
    gate.add_argument('--event', required=True)
    gate.add_argument('--before', default='')
    gate.add_argument('--after', default='')

    args = parser.parse_args(argv)
    if args.command == 'locate':
        print(locate_project(args.repo))
    elif args.command == 'resources':
        for name in resource_paths(args.snapshot, args.project):
            print(name)
    elif args.command == 'copy-back':
        print(json.dumps(copy_back(args.snapshot, args.project), indent=2))
    elif args.command == 'stage-exact':
        stage_exact(args.repo, args.paths)
    elif args.command == 'local-patches':
        found = local_patches(args.snapshot, args.project, args.commit)
        updated = False
        if args.apply:
            if args.pin is None:
                parser.error('--apply requires --pin')
            updated = apply_local_patches(args.snapshot, found, args.pin)
        print(json.dumps({'patches': found, 'updated': updated}, indent=2))
    elif args.command == 'plan-inbound':
        try:
            plan_inbound(args.snapshot, args.project, args.commit, args.output)
        except InboundConflict as error:
            print(str(error), file=sys.stderr)
            return 2
    elif args.command == 'install-candidate':
        install_candidate(args.candidate, args.snapshot, args.pin)
    elif args.command == 'push-gate':
        skip, reason = push_should_skip(args.repo, args.event, args.before, args.after)
        _emit_github_output(skip, reason)
    return 0


if __name__ == '__main__':
    sys.exit(main())
