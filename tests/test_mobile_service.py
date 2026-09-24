import io
import json
import subprocess
import unittest
from unittest.mock import Mock

from shipmblang.mobile_service import compiler_snapshot, create_app

TOKEN = "test-only-token-not-for-deployment-123456"


class MobileServiceTests(unittest.TestCase):
    def request(self, app, value=None, *, path="/v1/run", method="POST", token=TOKEN, origin=None):
        body = json.dumps(value).encode()
        environ = {"REQUEST_METHOD": method, "PATH_INFO": path,
                   "CONTENT_TYPE": "application/json", "CONTENT_LENGTH": str(len(body)),
                   "HTTP_AUTHORIZATION": "Bearer " + token, "wsgi.input": io.BytesIO(body)}
        if origin:
            environ["HTTP_ORIGIN"] = origin
        response = []
        output = app(environ, lambda status, headers: response.extend([status, dict(headers)]))
        return response[0], response[1], json.loads(b"".join(output))

    def test_actual_snapshot_and_runtime(self):
        app = create_app(TOKEN)
        status, _, info = self.request(app, path="/v1/info", method="GET")
        self.assertEqual(status, "200 OK")
        self.assertEqual(info["compiler"]["commit"], '125c12ef57973bad3d9e0270b295cf6cda8e5402')
        status, _, result = self.request(app, {"source": "Pls show me the total of 2 and 3.", "compiler": info["compiler"]})
        self.assertEqual(status, "200 OK")
        self.assertTrue(result["ok"])
        self.assertEqual(result["stdout"], "5\n")

    def test_rejects_auth_and_snapshot_before_execution(self):
        runner = Mock()
        app = create_app(TOKEN, runner=runner)
        self.assertEqual(self.request(app, {}, token="bad")[0], "401 Unauthorized")
        self.assertEqual(self.request(app, {"source": "Show 9.", "compiler": {}})[0], "409 Conflict")
        self.assertEqual(self.request(app, {"source": 8})[0], "400 Bad Request")
        runner.assert_not_called()

    def test_browser_origins_are_explicit(self):
        app = create_app(TOKEN, allowed_origin="http://localhost:8081")
        status, headers, _ = self.request(app, path="/v1/info", method="GET", origin="http://localhost:8081")
        self.assertEqual(status, "200 OK")
        self.assertEqual(headers["Access-Control-Allow-Origin"], "http://localhost:8081")
        self.assertEqual(self.request(app, origin="https://untrusted.example")[0], "403 Forbidden")

    def test_timeout_and_large_request(self):
        runner = Mock(side_effect=subprocess.TimeoutExpired("compiler", 20))
        app = create_app(TOKEN, runner=runner)
        self.assertEqual(self.request(app, {"source": "Show 5.", "compiler": compiler_snapshot()})[0], "408 Request Timeout")
        self.assertEqual(self.request(app, {"source": "a" * 70000})[0], "413 Content Too Large")
        self.assertEqual(runner.call_count, 1)

    def test_invalid_program_returns_diagnostics(self):
        status, _, result = self.request(create_app(TOKEN), {"source": "Present it.", "compiler": compiler_snapshot()})
        self.assertEqual(status, "200 OK")
        self.assertFalse(result["ok"])
        self.assertTrue(result["diagnostics"] or result["clarifications"])
        self.assertEqual(result["stdout"], "")

    def test_snapshot_pin_matches_mobile_client(self):
        from pathlib import Path
        pin = Path(__file__).resolve().parents[1] / "apps/mobile/src/compiler-snapshot.json"
        self.assertEqual(json.loads(pin.read_text()), compiler_snapshot())

    def test_token_is_required(self):
        with self.assertRaises(ValueError):
            create_app("short")

    def test_check_uses_compile_only(self):
        runner = Mock(return_value=(0, {"diagnostics": []}))
        app = create_app(TOKEN, runner=runner)
        status, _, result = self.request(app, {"source": "Show 5.", "compiler": compiler_snapshot()}, path="/v1/check")
        self.assertEqual(status, "200 OK")
        self.assertTrue(result["ok"])
        self.assertEqual(result["stdout"], "")
        runner.assert_called_once_with("Show 5.", "compile", timeout=20)

    def test_remote_media_returns_diagnostic_without_host_execution(self):
        from pathlib import Path
        source = (Path(__file__).resolve().parents[1] / "examples/vlc-playback.shipmb").read_text()
        status, _, result = self.request(create_app(TOKEN), {"source": source, "compiler": compiler_snapshot()})
        self.assertEqual(status, "200 OK")
        self.assertFalse(result["ok"])
        self.assertIn("not enabled in Notes", result["diagnostics"][0]["message"])
