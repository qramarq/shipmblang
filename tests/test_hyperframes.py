"""Language integration tests; grammar and rendering belong to the compiler."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from shipmblang import hyperframes
from shipmblang.cli import main


class HyperFramesTests(unittest.TestCase):
    def invoke(self, *args):
        stream = io.StringIO()
        with patch('sys.argv', ['shipmblang', 'hyperframes', *map(str, args)]), contextlib.redirect_stdout(stream):
            try:
                main()
                code = 0
            except SystemExit as error:
                code = error.code
        return code, json.loads(stream.getvalue())

    def test_public_api_forwards_artifact_unchanged(self):
        import shipmblang
        compiler = Mock()
        artifact = {'status': 'compiled', 'diagnostics': [], 'syntax_tree': {}, 'target_code': {}}
        compiler.compile_hyperframes.return_value = artifact
        with patch.object(hyperframes, '_compiler', return_value=compiler):
            self.assertIs(shipmblang.compile_hyperframes('source'), artifact)
            shipmblang.write_hyperframes_project(artifact, 'project', asset_root='assets')
            shipmblang.render_hyperframes_project('project', 'movie.mp4', timeout=42)
        compiler.compile_hyperframes.assert_called_once_with('source')
        compiler.write_hyperframes_project.assert_called_once_with(artifact, 'project', asset_root='assets')
        compiler.render_hyperframes_project.assert_called_once_with('project', 'movie.mp4', timeout=42)

    def test_compile_writes_without_rendering_or_model(self):
        compiler = Mock()
        compiler.compile_hyperframes.return_value = {'status': 'compiled', 'diagnostics': [{'level': 'warning', 'message': 'timing rounded'}]}
        compiler.write_hyperframes_project.return_value = {'status': 'written', 'directory': 'project'}
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'clip.shipmb'
            source.write_text('source', encoding='utf-8-sig')
            with patch.object(hyperframes, '_compiler', return_value=compiler), patch('shipmblang.providers.load_chat_provider', side_effect=AssertionError('Model called')):
                code, result = self.invoke('compile', source, '-o', 'project')
            self.assertEqual(code, 0)
            self.assertEqual(result['status'], 'written')
            self.assertEqual(result['diagnostics'], compiler.compile_hyperframes.return_value['diagnostics'])
            compiler.compile_hyperframes.assert_called_once_with('source')
            compiler.write_hyperframes_project.assert_called_once_with(compiler.compile_hyperframes.return_value, Path('project'), asset_root=source.resolve().parent)
            compiler.render_hyperframes_project.assert_not_called()

    def test_failed_compile_preserves_diagnostics_and_does_not_write(self):
        compiler = Mock()
        artifact = {'status': 'error', 'diagnostics': [{'message': 'unsupported', 'span': {'start': 0, 'end': 4}}]}
        compiler.compile_hyperframes.return_value = artifact
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'clip.shipmb'
            source.write_text('nope')
            with patch.object(hyperframes, '_compiler', return_value=compiler):
                code, result = self.invoke('compile', source, '-o', 'project')
        self.assertEqual((code, result), (1, artifact))
        compiler.write_hyperframes_project.assert_not_called()
        compiler.render_hyperframes_project.assert_not_called()

    def test_render_forwards_failure_and_timeout(self):
        compiler = Mock()
        compiler.render_hyperframes_project.return_value = {'status': 'error', 'diagnostics': [{'message': 'Node missing'}]}
        with patch.object(hyperframes, '_compiler', return_value=compiler):
            code, result = self.invoke('render', 'project', '-o', 'clip.mp4', '--timeout', '12')
        self.assertEqual(code, 1)
        self.assertEqual(result['diagnostics'][0]['message'], 'Node missing')
        compiler.render_hyperframes_project.assert_called_once_with(Path('project'), Path('clip.mp4'), timeout=12)
        compiler.compile_hyperframes.assert_not_called()

    def test_missing_source_is_json_error(self):
        code, result = self.invoke('compile', 'missing-file.shipmb', '-o', 'project')
        self.assertEqual(code, 1)
        self.assertEqual(result['status'], 'error')

    def test_missing_snapshot_has_actionable_error(self):
        error = ModuleNotFoundError(name='shipmblang._compiler.hyperframes')
        with patch.object(hyperframes.importlib, 'import_module', side_effect=error):
            with self.assertRaisesRegex(hyperframes.CompilerUnavailableError, 'lacks HyperFrames'):
                hyperframes.compile_hyperframes('source')

    def test_internal_missing_dependency_is_not_misreported(self):
        error = ModuleNotFoundError(name='internal_dependency')
        with patch.object(hyperframes.importlib, 'import_module', side_effect=error):
            with self.assertRaises(ModuleNotFoundError):
                hyperframes.compile_hyperframes('source')

    def test_timeout_must_be_finite_and_positive(self):
        import argparse
        for value in ('0', '-1', 'nan', 'inf'):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                hyperframes._timeout(value)
