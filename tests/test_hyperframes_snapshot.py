"""Real bundled compiler smoke tests at the public language boundary."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shipmblang import compile_hyperframes, write_hyperframes_project


SOURCE = '''Create a video at 320 by 180 pixels and 24 frames per second.
Add scene "intro" lasting 1 second.
Show text "Hello" as "title" in scene "intro".
'''


class HyperFramesSnapshotTests(unittest.TestCase):
    def test_compile_and_write_without_node_or_model(self):
        with patch('subprocess.Popen', side_effect=AssertionError('Subprocess during compile')), patch(
                'shipmblang.providers.load_chat_provider', side_effect=AssertionError('Model during compile')):
            artifact = compile_hyperframes(SOURCE)
            self.assertEqual(artifact['status'], 'compiled', artifact)
            with tempfile.TemporaryDirectory() as folder:
                project = Path(folder) / 'project'
                result = write_hyperframes_project(artifact, project, asset_root=folder)
                self.assertEqual(result['status'], 'written', result)
                self.assertIn('Hello', (project / 'index.html').read_text(encoding='utf-8'))

    def test_unsupported_prose_returns_diagnostics(self):
        result = compile_hyperframes('Make something amazing using a model.')
        self.assertEqual(result['status'], 'error')
        self.assertTrue(result['diagnostics'])
