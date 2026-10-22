"""Real bundled compiler smoke tests at the public language boundary."""
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from shipmblang import compile_hyperframes, write_hyperframes_project

ROOT = Path(__file__).resolve().parents[1]


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


def _text_style(html, text):
    match = re.search(rf'style="([^"]*)"[^>]*>{re.escape(text)}</div>', html)
    if match is None:
        raise AssertionError(html)
    return match.group(1)


class HyperFramesTextPlacementTests(unittest.TestCase):
    def test_title_example_uses_content_box_at_top_left(self):
        source = (ROOT / "examples" / "hyperframes-title.shipmb").read_text(encoding="utf-8")
        artifact = compile_hyperframes(source)
        self.assertEqual(artifact["status"], "compiled", artifact)
        self.assertFalse([item for item in artifact["diagnostics"] if item["code"] == "SMBHF003"], artifact["diagnostics"])
        html = artifact["target_code"]["files"]["index.html"]
        self.assertIn("Hello from ShipMBLang", html)
        style = _text_style(html, "Hello from ShipMBLang")
        self.assertRegex(style, r"left:120(?:\.0)?px")
        self.assertRegex(style, r"top:280(?:\.0)?px")
        self.assertNotIn("left:-520", style)
        self.assertNotIn("width:1280", style)
        width = 64 * 0.62 * len("Hello from ShipMBLang")
        self.assertIn(f"width:{width}px", style)
        self.assertNotEqual(width, 1280)

    def test_placed_text_near_the_right_edge_warns_and_compiles(self):
        source = '''Create a video at 320 by 180 pixels and 24 frames per second.
Add scene "intro" lasting 1 second.
Show text "Hello from ShipMBLang" as "title" in scene "intro".
Place "title" at 300 by 10 pixels.
Set the font size of "title" to 64 pixels.
'''
        artifact = compile_hyperframes(source)
        self.assertEqual(artifact["status"], "compiled", artifact)
        warnings = [item for item in artifact["diagnostics"] if item["level"] == "warning" and item["code"] == "SMBHF003"]
        self.assertEqual(len(warnings), 1, artifact["diagnostics"])
        self.assertIn("outside the frame", warnings[0]["message"])

    def test_unplaced_text_stays_full_frame_and_centered(self):
        artifact = compile_hyperframes(SOURCE)
        self.assertEqual(artifact["status"], "compiled", artifact)
        style = _text_style(artifact["target_code"]["files"]["index.html"], "Hello")
        self.assertRegex(style, r"left:0(?:\.0)?px")
        self.assertIn("width:320px", style)
        self.assertNotIn("width:223.2", style)
        self.assertFalse(any(item["code"] == "SMBHF003" for item in artifact["diagnostics"]))

    def test_explicit_size_keeps_center_anchor(self):
        source = '''Create a video at 320 by 180 pixels and 24 frames per second.
Add scene "intro" lasting 1 second.
Show text "Hi" as "title" in scene "intro".
Place "title" at 100 by 40 pixels.
Set the size of "title" to 80 by 40 pixels.
'''
        artifact = compile_hyperframes(source)
        self.assertEqual(artifact["status"], "compiled", artifact)
        style = _text_style(artifact["target_code"]["files"]["index.html"], "Hi")
        self.assertRegex(style, r"left:60(?:\.0)?px")
        self.assertRegex(style, r"top:20(?:\.0)?px")
        self.assertRegex(style, r"width:80(?:\.0)?px")
        self.assertFalse(any(item["code"] == "SMBHF003" for item in artifact["diagnostics"]))
