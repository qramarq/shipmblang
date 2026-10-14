import hashlib
import tempfile
from pathlib import Path
import unittest

from tools.bundle_compiler import stage_bundle
from tools.verify_bundle import verify_directory


class BundleStagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'compiler'
        self.package = self.source / 'shipmbcompiler'
        self.package.mkdir(parents=True)
        (self.source / 'pyproject.toml').write_text('[project]\nname="shipmbcompiler"\nversion="test"\n')
        for name in ('__init__.py', 'direct.py', 'runtime.py'):
            (self.package / name).write_text('# fixture\n')
        self.target = self.root / 'candidate'

    def test_explicit_resources_are_copied_and_hashed(self):
        resources = ['data/words.sqlite', 'data/LICENSE', 'data/corpus.json', 'hyperframes/node/producer.mjs', 'hyperframes/node/package.json']
        (self.package / 'data').mkdir()
        (self.package / 'hyperframes/node').mkdir(parents=True)
        (self.package / 'hyperframes/__init__.py').write_text('# nested package\n')
        for name in resources:
            (self.package / name).write_bytes(b'fixture bytes')
        (self.package / 'secret.txt').write_text('not a declared resource')
        record = stage_bundle(self.source, self.target, resources)
        self.assertEqual(verify_directory(self.target)['files'], 9)
        for name in resources:
            self.assertEqual(record['sha256'][name], hashlib.sha256(b'fixture bytes').hexdigest())
        self.assertFalse((self.target / 'secret.txt').exists())

    def test_existing_destination_is_never_overwritten(self):
        self.target.mkdir()
        with self.assertRaisesRegex(ValueError, 'must not exist'):
            stage_bundle(self.source, self.target)

    def test_node_dependencies_are_never_snapshotted(self):
        dependency = self.package / 'hyperframes/node/node_modules/example'
        dependency.mkdir(parents=True)
        (dependency / 'helper.py').write_text('# dependency')
        record = stage_bundle(self.source, self.target)
        self.assertEqual(len(record['sha256']), 3)

    def test_missing_or_unsafe_resources_leave_no_candidate(self):
        for name in ('../escape', '/absolute', 'C:/absolute', 'data\\escape', 'missing.sqlite', 'BUNDLED.json', 'hyperframes/node/node_modules/helper.js'):
            with self.subTest(name=name):
                with self.assertRaises((ValueError, FileNotFoundError)):
                    stage_bundle(self.source, self.target, [name])
                self.assertFalse(self.target.exists())

    def test_approved_destination_rejected(self):
        approved = Path(__file__).resolve().parents[1] / 'shipmblang/_compiler'
        with self.assertRaisesRegex(ValueError, 'approved snapshot'):
            stage_bundle(self.source, approved)
