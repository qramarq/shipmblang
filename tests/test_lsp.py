"""Scripted language-server checks, including UTF-16 positions."""
import io
import json
import subprocess
import sys
import unittest

from shipmblang.lsp import (
    LanguageServer, codepoint_to_utf16_position, diagnostics_from_result,
    hover_markdown, serve, utf16_position_to_codepoint,
)


def frame(payload: dict) -> bytes:
    body = json.dumps(payload).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


def read_frames(buffer: bytes) -> list[dict]:
    messages = []
    view = memoryview(buffer)
    while view:
        marker = bytes(view).find(b"\r\n\r\n")
        if marker < 0:
            break
        header = bytes(view[:marker]).decode("ascii")
        length = int(header.split(":", 1)[1].strip())
        start = marker + 4
        messages.append(json.loads(bytes(view[start:start + length]).decode("utf-8")))
        view = view[start + length:]
    return messages


class PositionTests(unittest.TestCase):
    def test_emoji_code_points_become_utf16_units(self):
        source = 'Show "😀".'
        # 😀 is one code point and two UTF-16 units. The closing quote is after it.
        offset = source.index("😀") + 1
        position = codepoint_to_utf16_position(source, offset)
        self.assertEqual(position, {"line": 0, "character": len('Show "') + 2})
        self.assertEqual(utf16_position_to_codepoint(source, 0, position["character"]), offset)

    def test_newline_and_accent_stay_on_their_line(self):
        source = 'Present "café".\nShow 2.'
        offset = source.index("2")
        position = codepoint_to_utf16_position(source, offset)
        self.assertEqual(position["line"], 1)
        self.assertEqual(position["character"], source.split("\n")[1].index("2"))
        self.assertEqual(utf16_position_to_codepoint(source, 1, position["character"]), offset)


class ServerTests(unittest.TestCase):
    def test_initialize_hover_diagnostics_and_run(self):
        server = LanguageServer()
        opened = server.handle({
            "jsonrpc": "2.0", "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": "file:///sum.shipmb", "languageId": "shipmblang", "version": 1,
                                        "text": "Show the sum of 2 and 3.\n"}},
        })
        self.assertEqual(opened[0]["method"], "textDocument/publishDiagnostics")
        self.assertEqual(opened[0]["params"]["diagnostics"], [])
        hover = server.handle({
            "jsonrpc": "2.0", "id": 3, "method": "textDocument/hover",
            "params": {"textDocument": {"uri": "file:///sum.shipmb"}, "position": {"line": 0, "character": 0}},
        })[0]["result"]
        self.assertIn("const 2", hover["contents"]["value"])
        self.assertIn("show", hover["contents"]["value"])
        ran = server.handle({
            "jsonrpc": "2.0", "id": 4, "method": "workspace/executeCommand",
            "params": {"command": "shipmblang.run", "arguments": ["file:///sum.shipmb"]},
        })[0]["result"]
        self.assertEqual(ran["status"], "compiled")
        self.assertEqual(ran["exitCode"], 0)
        self.assertEqual(ran["stdout"], "5\n")

    def test_clarification_span_is_utf16(self):
        source = "Show 😀."
        server = LanguageServer()
        published = server.handle({
            "jsonrpc": "2.0", "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": "file:///ask.shipmb", "text": source}},
        })[0]["params"]["diagnostics"]
        self.assertTrue(published)
        diagnostic = published[0]
        self.assertEqual(diagnostic["severity"], 2)
        start = diagnostic["range"]["start"]["character"]
        end = diagnostic["range"]["end"]["character"]
        # The emoji is one code point and two UTF-16 units.
        self.assertEqual(end - start, 2)
        self.assertIn("😀", source[utf16_position_to_codepoint(source, 0, start):])
        markdown = hover_markdown(source, 0, start)
        self.assertIn("```", markdown)

    def test_framed_stdio_round_trip(self):
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"processId": None, "capabilities": {}}},
            {"jsonrpc": "2.0", "method": "initialized", "params": {}},
            {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {
                "textDocument": {"uri": "file:///p.shipmb", "text": "Show the sum of 2 and 3."}}},
            {"jsonrpc": "2.0", "id": 2, "method": "shutdown", "params": None},
            {"jsonrpc": "2.0", "method": "exit"},
        ]
        incoming = io.BytesIO(b"".join(frame(item) for item in requests))
        outgoing = io.BytesIO()
        self.assertEqual(serve(incoming, outgoing), 0)
        messages = read_frames(outgoing.getvalue())
        self.assertEqual(messages[0]["id"], 1)
        self.assertIn("shipmblang.compile", json.dumps(messages[0]["result"]))
        self.assertTrue(any(item.get("method") == "textDocument/publishDiagnostics" for item in messages))
        self.assertEqual(messages[-1]["id"], 2)
        self.assertIsNone(messages[-1]["result"])

    def test_cli_version_and_check(self):
        version = subprocess.run([sys.executable, "-m", "shipmblang", "--version"], capture_output=True, text=True, check=False)
        self.assertEqual(version.returncode, 0, version.stderr)
        self.assertEqual(version.stdout.strip(), "shipmblang 0.6.0")
        checked = subprocess.run([sys.executable, "-m", "shipmblang", "lsp", "--check"], capture_output=True, text=True, check=False)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertIn("lsp ok", checked.stdout)

    def test_diagnostics_helper_uses_source_spans(self):
        items = diagnostics_from_result("abc", {"diagnostics": [
            {"message": "Nope", "span": {"start": 1, "end": 2}, "code": "SMBX", "level": "error"}], "clarifications": []})
        self.assertEqual(items[0]["range"]["start"]["character"], 1)
        self.assertEqual(items[0]["range"]["end"]["character"], 2)
        self.assertEqual(items[0]["code"], "SMBX")


if __name__ == "__main__":
    unittest.main()
