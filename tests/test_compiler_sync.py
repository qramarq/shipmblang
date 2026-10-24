import ast
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from shipmblang.notebook_runtime import compiler_snapshot
from tools.compiler_sync import (
    InboundConflict, apply_local_patches, copy_back, install_candidate, local_patches,
    locate_project, main, pin_for, plan_inbound, push_should_skip, resource_paths, stage_exact,
)


ROOT = Path(__file__).resolve().parents[1]
PATCHED = (
    'core.py', 'general_codegen.py', 'general_english.py', 'general_runtime.py',
    'hyperframes/compiler.py', 'ir.py', 'media_english.py', 'runtime.py',
    'semantics.py', 'target.py', 'vlc_english.py',
)
CRLF_TEXT = (
    'hyperframes/node/bridge.mjs', 'hyperframes/node/package.json',
    'hyperframes/node/package-lock.json', 'hyperframes/vendor/INTER-LICENSE.txt',
    'hyperframes/vendor/THIRD-PARTY.md', 'hyperframes/vendor/gsap.min.js',
)
UNCHANGED_CRLF_PY = ('compiler.py', 'source_format.py')


def git(repo, *args, text=True):
    return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True, text=text).stdout


def init_repo(path):
    subprocess.check_call(['git', 'init', '-b', 'main', str(path)])
    for key, value in (('user.email', 'test@example.com'), ('user.name', 'Test'),
                       ('core.autocrlf', 'false'), ('commit.gpgsign', 'false')):
        git(path, 'config', key, value)


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode())


def commit_all(repo, message):
    git(repo, 'add', '-A')
    git(repo, 'commit', '-m', message)
    return git(repo, 'rev-parse', 'HEAD').strip()


def bundled_compiler_version(snapshot):
    """Version string declared by the vendored compiler source. No network."""
    found = []
    for name in ('direct.py', '__init__.py'):
        path = Path(snapshot) / name
        if not path.is_file():
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in tree.body:
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            else:
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id in {'COMPILER_VERSION', '__version__'}:
                    literal = ast.literal_eval(value)
                    if not isinstance(literal, str) or not literal.strip():
                        raise AssertionError(f'{name} {target.id} is not a version string')
                    found.append(literal)
    if not found:
        raise AssertionError('bundled compiler does not declare COMPILER_VERSION or __version__')
    if len(set(found)) != 1:
        raise AssertionError(f'bundled compiler version strings disagree: {found}')
    return found[0]


def manifest_for(files, commit, patches=()):
    return {
        'distribution': 'shipmbcompiler',
        'version': '0.5.0',
        'sha256': {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())},
        'source_commit': commit,
        'local_patches': list(patches),
        'components': {'hyperframes': {'files': ['hyperframes/compiler.py']}},
    }


def write_snapshot(directory, files, commit, patches=()):
    for name, data in files.items():
        write(directory / name, data)
    record = manifest_for(files, commit, patches)
    write(directory / 'BUNDLED.json', json.dumps(record, indent=2) + '\n')
    return record


class CompilerSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def make_nested(self, files):
        repo = self.root / 'compiler'
        repo.mkdir()
        init_repo(repo)
        project = repo / 'shipmbcompiler'
        package = project / 'shipmbcompiler'
        write(project / 'pyproject.toml', '[project]\nname="shipmbcompiler"\nversion="0.5.0"\n')
        for name, data in files.items():
            write(package / name, data)
        return repo, project

    def test_locate_accepts_nested_repo_root_and_project_directory(self):
        repo, project = self.make_nested({'__init__.py': b'', 'direct.py': b'', 'runtime.py': b''})
        self.assertEqual(locate_project(repo), project.resolve())
        self.assertEqual(locate_project(project), project.resolve())
        with self.assertRaisesRegex(ValueError, 'shipmbcompiler/shipmbcompiler'):
            locate_project(self.root / 'missing')

    def test_resources_follow_the_manifest_and_hyperframes_and_skip_node_modules(self):
        repo, project = self.make_nested({
            '__init__.py': b'', 'direct.py': b'', 'runtime.py': b'',
            'hyperframes/node/bridge.mjs': b'export {}\n',
            'hyperframes/node/node_modules/leftpad/index.js': b'module.exports = 1\n',
            'notes.txt': b'not a resource\n',
        })
        snapshot = self.root / 'snapshot'
        files = {
            '__init__.py': b'', 'direct.py': b'', 'runtime.py': b'',
            'hyperframes/node/bridge.mjs': b'export {}\r\n',
            'data/LICENSE': b'license\n',
        }
        write_snapshot(snapshot, files, 'a' * 40)
        self.assertEqual(resource_paths(snapshot, repo), ['data/LICENSE', 'hyperframes/node/bridge.mjs'])
        self.assertNotIn('hyperframes/node/node_modules/leftpad/index.js', resource_paths(snapshot, project))

    def test_copy_back_preserves_newline_only_blobs_and_styles_real_edits(self):
        # Models the drift reported against shipmblang-compiler: eleven content edits,
        # CRLF Python blobs upstream, and CRLF HyperFrames resources in the bundle.
        upstream = {}
        bundled = {}
        for name in ('__init__.py', 'direct.py'):
            upstream[name] = b"print('base')\n"
            bundled[name] = upstream[name]
        for name in UNCHANGED_CRLF_PY:
            upstream[name] = b"print('same')\r\n"
            bundled[name] = b"print('same')\n"
        for name in PATCHED:
            text = 'runtime' if name == 'runtime.py' else name
            upstream[name] = f"print('old {text}')\r\n".encode() if name in UNCHANGED_CRLF_PY or name in ('core.py', 'general_runtime.py', 'runtime.py') else f"print('old {text}')\n".encode()
            bundled[name] = f"print('new {text}')\n".encode()
        for name in CRLF_TEXT:
            upstream[name] = b'{\n  "name": "same"\n}\n'
            bundled[name] = b'{\r\n  "name": "same"\r\n}\r\n'
        upstream['hyperframes/vendor/inter-latin-400-normal.woff2'] = b'woff\r\n\x00\n\r'
        bundled['hyperframes/vendor/inter-latin-400-normal.woff2'] = upstream['hyperframes/vendor/inter-latin-400-normal.woff2']
        repo, project = self.make_nested(upstream)
        base = commit_all(repo, 'base')
        before = {
            name: git(repo, 'rev-parse', f'HEAD:shipmbcompiler/shipmbcompiler/{name}', text=False)
            for name in UNCHANGED_CRLF_PY + CRLF_TEXT
        }
        snapshot = self.root / 'snapshot'
        write_snapshot(snapshot, bundled, base)
        write(snapshot / 'NOTES.txt', b'language only\n')
        result = copy_back(snapshot, repo)
        self.assertEqual(
            [path.split('shipmbcompiler/shipmbcompiler/')[1] for path in result['changed']],
            sorted(PATCHED))
        self.assertIn('compiler.py', result['preserved'])
        self.assertIn('hyperframes/node/bridge.mjs', result['preserved'])
        self.assertFalse((project / 'shipmbcompiler' / 'BUNDLED.json').exists())
        self.assertFalse((project / 'shipmbcompiler' / 'NOTES.txt').exists())
        core = (project / 'shipmbcompiler' / 'core.py').read_bytes()
        self.assertEqual(core, b"print('new core.py')\r\n")
        self.assertEqual((project / 'shipmbcompiler' / 'general_english.py').read_bytes(), b"print('new general_english.py')\n")
        stage_exact(repo, result['changed'])
        git(repo, 'commit', '-m', 'sync')
        stored = git(repo, 'cat-file', 'blob', 'HEAD:shipmbcompiler/shipmbcompiler/core.py', text=False)
        self.assertEqual(stored, b"print('new core.py')\r\n")
        for name, oid in before.items():
            self.assertEqual(git(repo, 'rev-parse', f'HEAD:shipmbcompiler/shipmbcompiler/{name}', text=False), oid)
        self.assertEqual(local_patches(snapshot, repo, base), sorted(PATCHED))

    def test_flat_project_maps_to_shipmbcompiler_not_a_doubled_path(self):
        repo = self.root / 'flat'
        repo.mkdir()
        init_repo(repo)
        write(repo / 'pyproject.toml', '[project]\nname="shipmbcompiler"\nversion="0.5.0"\n')
        write(repo / 'shipmbcompiler' / '__init__.py', b'')
        write(repo / 'shipmbcompiler' / 'direct.py', b'')
        write(repo / 'shipmbcompiler' / 'runtime.py', b"print('old')\n")
        commit_all(repo, 'base')
        snapshot = self.root / 'flat-snapshot'
        files = {
            '__init__.py': b'', 'direct.py': b'', 'runtime.py': b"print('new')\n",
        }
        write_snapshot(snapshot, files, git(repo, 'rev-parse', 'HEAD').strip())
        result = copy_back(snapshot, repo)
        self.assertEqual(result['changed'], ['shipmbcompiler/runtime.py'])
        self.assertEqual((repo / 'shipmbcompiler' / 'runtime.py').read_bytes(), b"print('new')\n")

    def test_local_patches_apply_does_not_rewrite_file_hashes(self):
        repo, project = self.make_nested({'__init__.py': b'a\n', 'direct.py': b'b\n', 'runtime.py': b'c\r\n'})
        base = commit_all(repo, 'base')
        snapshot = self.root / 'snap'
        files = {'__init__.py': b'a\n', 'direct.py': b'b\n', 'runtime.py': b'changed\n'}
        record = write_snapshot(snapshot, files, base)
        pin = self.root / 'pin.json'
        pin.write_text('{}\n')
        self.assertTrue(apply_local_patches(snapshot, local_patches(snapshot, repo), pin))
        updated = json.loads((snapshot / 'BUNDLED.json').read_text())
        self.assertEqual(updated['sha256'], record['sha256'])
        self.assertEqual(updated['source_commit'], base)
        self.assertEqual(updated['local_patches'], ['runtime.py'])
        self.assertEqual(json.loads(pin.read_text()), pin_for(updated))
        self.assertFalse(apply_local_patches(snapshot, ['runtime.py'], pin))

    def test_inbound_records_local_edits_without_reverting_them(self):
        files = {'__init__.py': b'', 'direct.py': b'', 'runtime.py': b"print('run')\n", 'core.py': b"print('old')\r\n"}
        repo, _project = self.make_nested(files)
        base = commit_all(repo, 'base')
        snapshot = self.root / 'snap'
        bundled = dict(files)
        bundled['core.py'] = b"print('new')\n"
        bundled['hyperframes/node/bridge.mjs'] = b'export {}\r\n'
        write(repo / 'shipmbcompiler' / 'shipmbcompiler' / 'hyperframes' / 'node' / 'bridge.mjs', b'export {}\n')
        git(repo, 'add', '-A')
        git(repo, 'commit', '--amend', '--no-edit')
        base = git(repo, 'rev-parse', 'HEAD').strip()
        write_snapshot(snapshot, bundled, base)
        output = self.root / 'plan'
        plan = plan_inbound(snapshot, repo, base, output)
        self.assertEqual(plan['action'], 'record-patches')
        self.assertEqual(plan['patches'], ['core.py'])
        self.assertEqual(plan['changed'], [])
        self.assertTrue(plan['metadata_only'])
        candidate = json.loads((output / 'candidate' / 'BUNDLED.json').read_text())
        self.assertEqual(candidate['source_commit'], base)
        self.assertEqual(candidate['local_patches'], ['core.py'])
        self.assertEqual(candidate['sha256']['core.py'], hashlib.sha256(b"print('new')\n").hexdigest())
        self.assertEqual(candidate['sha256']['hyperframes/node/bridge.mjs'], hashlib.sha256(b'export {}\r\n').hexdigest())
        self.assertIn(b'\r\n', (output / 'candidate' / 'hyperframes' / 'node' / 'bridge.mjs').read_bytes())
        self.assertEqual(candidate['components']['hyperframes']['files'], ['hyperframes/compiler.py'])

    def test_inbound_adopts_matching_upstream_without_flapping_resource_hashes(self):
        files = {
            '__init__.py': b'', 'direct.py': b'', 'runtime.py': b"print('run')\n",
            'core.py': b"print('old')\r\n",
            'hyperframes/node/bridge.mjs': b'export {}\n',
        }
        repo, _project = self.make_nested(files)
        base = commit_all(repo, 'base')
        snapshot = self.root / 'snap'
        bundled = dict(files)
        bundled['core.py'] = b"print('new')\n"
        bundled['hyperframes/node/bridge.mjs'] = b'export {}\r\n'
        write_snapshot(snapshot, bundled, base)
        write(repo / 'shipmbcompiler' / 'shipmbcompiler' / 'core.py', b"print('new')\r\n")
        head = commit_all(repo, 'land the edit')
        output = self.root / 'plan'
        plan = plan_inbound(snapshot, repo, head, output)
        self.assertEqual(plan['action'], 'adopt')
        self.assertEqual(plan['patches'], [])
        self.assertEqual(plan['changed'], [])
        self.assertTrue(plan['metadata_only'])
        candidate = json.loads((output / 'candidate' / 'BUNDLED.json').read_text())
        self.assertEqual(candidate['source_commit'], head)
        self.assertEqual(candidate['local_patches'], [])
        self.assertEqual((output / 'candidate' / 'core.py').read_bytes(), b"print('new')\n")
        self.assertEqual((output / 'candidate' / 'hyperframes' / 'node' / 'bridge.mjs').read_bytes(), b'export {}\r\n')
        self.assertEqual(candidate['sha256']['hyperframes/node/bridge.mjs'], hashlib.sha256(bundled['hyperframes/node/bridge.mjs']).hexdigest())

    def test_inbound_keeps_local_patches_while_taking_unrelated_upstream_edits(self):
        files = {'__init__.py': b'', 'direct.py': b"print('d')\n", 'runtime.py': b'', 'core.py': b"print('old')\n"}
        repo, _project = self.make_nested(files)
        base = commit_all(repo, 'base')
        snapshot = self.root / 'snap'
        bundled = dict(files)
        bundled['core.py'] = b"print('local')\n"
        write_snapshot(snapshot, bundled, base)
        write(repo / 'shipmbcompiler' / 'shipmbcompiler' / 'direct.py', b"print('upstream')\n")
        head = commit_all(repo, 'upstream direct')
        plan = plan_inbound(snapshot, repo, head, self.root / 'plan')
        self.assertEqual(plan['action'], 'adopt')
        self.assertEqual(plan['patches'], ['core.py'])
        self.assertEqual(plan['changed'], ['direct.py'])
        self.assertEqual(plan['source_commit'], head)
        candidate = self.root / 'plan' / 'candidate'
        self.assertEqual((candidate / 'core.py').read_bytes(), b"print('local')\n")
        self.assertEqual((candidate / 'direct.py').read_bytes(), b"print('upstream')\n")

    def test_inbound_refuses_a_file_both_sides_edited(self):
        files = {'__init__.py': b'', 'direct.py': b'', 'runtime.py': b'', 'core.py': b"print('old')\n"}
        repo, _project = self.make_nested(files)
        base = commit_all(repo, 'base')
        snapshot = self.root / 'snap'
        bundled = dict(files)
        bundled['core.py'] = b"print('local')\n"
        write_snapshot(snapshot, bundled, base)
        write(repo / 'shipmbcompiler' / 'shipmbcompiler' / 'core.py', b"print('upstream')\n")
        head = commit_all(repo, 'upstream core')
        output = self.root / 'plan'
        with self.assertRaises(InboundConflict) as caught:
            plan_inbound(snapshot, repo, head, output)
        self.assertEqual(caught.exception.conflicts, ['core.py'])
        self.assertEqual(json.loads((output / 'plan.json').read_text())['action'], 'conflict')
        self.assertEqual(main([
            'plan-inbound', '--snapshot', str(snapshot), '--project', str(repo),
            '--commit', head, '--output', str(self.root / 'cli-plan')]), 2)

    def test_install_updates_pin_and_leaves_language_only_files(self):
        snapshot = self.root / 'snapshot'
        files = {'__init__.py': b'', 'direct.py': b'', 'runtime.py': b'old\n', 'extra.py': b'gone\n'}
        write_snapshot(snapshot, files, 'b' * 40)
        write(snapshot / 'NOTES.txt', b'keep\n')
        candidate = self.root / 'candidate'
        write_snapshot(candidate, {'__init__.py': b'', 'direct.py': b'', 'runtime.py': b'new\n'}, 'c' * 40)
        pin = self.root / 'compiler-snapshot.json'
        install_candidate(candidate, snapshot, pin)
        self.assertEqual((snapshot / 'runtime.py').read_bytes(), b'new\n')
        self.assertFalse((snapshot / 'extra.py').exists())
        self.assertEqual((snapshot / 'NOTES.txt').read_bytes(), b'keep\n')
        self.assertEqual(json.loads(pin.read_text())['commit'], 'c' * 40)
        with self.assertRaisesRegex(ValueError, 'different directories'):
            install_candidate(snapshot, snapshot, pin)

    def test_push_gate_skips_echoes_and_metadata_only(self):
        repo = self.root / 'lang'
        repo.mkdir()
        init_repo(repo)
        write(repo / 'shipmblang' / '_compiler' / 'runtime.py', b'one\n')
        first = commit_all(repo, 'initial')
        write(repo / 'shipmblang' / '_compiler' / 'runtime.py', b'two\n')
        downstream = commit_all(repo, 'Sync compiler from shipmblang-compiler@abc1234\n\nCompiler-Sync: downstream\n')
        self.assertEqual(push_should_skip(repo, 'push', first, downstream)[0], True)
        write(repo / 'shipmblang' / '_compiler' / 'BUNDLED.json', b'{}\n')
        write(repo / 'apps' / 'mobile' / 'src' / 'compiler-snapshot.json', b'{}\n')
        meta = commit_all(repo, 'Record compiler local_patches\n\nCompiler-Sync: local-patches\n')
        self.assertEqual(push_should_skip(repo, 'push', downstream, meta)[0], True)
        write(repo / 'shipmblang' / '_compiler' / 'runtime.py', b'three\n')
        edited = commit_all(repo, 'edit the vendored compiler')
        skip, reason = push_should_skip(repo, 'push', meta, edited)
        self.assertFalse(skip)
        self.assertIn('vendored compiler', reason)
        self.assertFalse(push_should_skip(repo, 'workflow_dispatch', '', '')[0])
        write(repo / 'shipmblang' / '_compiler' / 'direct.py', b'later\n')
        mixed = commit_all(repo, 'follow-up edit')
        self.assertFalse(push_should_skip(repo, 'push', downstream, mixed)[0])

    def test_vendored_snapshot_contract(self):
        snapshot = ROOT / 'shipmblang' / '_compiler'
        manifest = json.loads((snapshot / 'BUNDLED.json').read_text(encoding='utf-8'))
        non_python = sorted(name for name in manifest['sha256'] if not name.endswith('.py'))
        self.assertEqual(resource_paths(snapshot), non_python)
        self.assertIn('hyperframes/vendor/inter-latin-400-normal.woff2', non_python)
        for name in CRLF_TEXT:
            data = (snapshot / name).read_bytes()
            self.assertTrue(data.count(b'\r\n'), name)
            stripped = data.replace(b'\r\n', b'')
            self.assertNotIn(b'\n', stripped, name)
            self.assertNotIn(b'\r', stripped, name)
        for name in ('compiler.py', 'core.py', 'general_runtime.py', 'runtime.py', 'source_format.py'):
            self.assertNotIn(b'\r', (snapshot / name).read_bytes(), name)
        self.assertEqual(pin_for(manifest), compiler_snapshot())
        self.assertEqual(pin_for(manifest), json.loads((ROOT / 'apps/mobile/src/compiler-snapshot.json').read_text()))

    def test_bundled_compiler_versions_agree(self):
        snapshot = ROOT / 'shipmblang' / '_compiler'
        manifest = json.loads((snapshot / 'BUNDLED.json').read_text(encoding='utf-8'))
        pin = json.loads((ROOT / 'apps/mobile/src/compiler-snapshot.json').read_text(encoding='utf-8'))
        source_version = bundled_compiler_version(snapshot)
        self.assertEqual(manifest['version'], source_version)
        self.assertEqual(pin['version'], source_version)
        self.assertEqual(compiler_snapshot()['version'], source_version)


if __name__ == '__main__':
    unittest.main()
