"""Default CLI translation through a local chat endpoint and the real compiler."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


REQUEST = "Add the odd numbers in 2, 5, 8, and 11 and show the total."
PROGRAM = '''Let values be the list of integers 2, 5, 8, 11.
Let total be a mutable integer with value 0.
For each value in values:
If (the remainder of value and 2) equals 1 then:
Set total to total plus value.
End the condition.
End the loop.
Show total.'''


@unittest.skipUnless(sys.version_info >= (3, 11) and importlib.util.find_spec("shipmbcompiler"), "Requires Python 3.11+ and the compiler or bundled distribution")
class DefaultEnglishTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.proposal = {"paraphrase": PROGRAM}
        owner = self

        class Endpoint(BaseHTTPRequestHandler):
            def do_POST(self):
                owner.requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                body = json.dumps({"choices": [{"finish_reason": "stop", "message": {
                    "content": json.dumps(owner.proposal)}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Endpoint)
        self.worker = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.worker.start()
        self.env = {**os.environ, "SHIPMB_MEMORY": "off", "SHIPMB_MODEL_PROVIDER": "openai_compatible",
                    "SHIPMB_MODEL_BASE_URL": f"http://127.0.0.1:{self.server.server_port}/v1",
                    "SHIPMB_MODEL_NAME": "test-translator", "SHIPMB_MODEL_API_KEY": ""}

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=2)

    def invoke(self, *args, expected=0):
        process = subprocess.run([sys.executable, "-m", "shipmblang", *args, "--memory", "off"],
                                 cwd=Path(__file__).resolve().parents[1], env=self.env,
                                 capture_output=True, text=True, timeout=15)
        self.assertEqual(process.returncode, expected, process.stderr + process.stdout)
        return json.loads(process.stdout)

    def test_default_translates_compiles_and_runs(self):
        result = self.invoke("run", REQUEST)
        self.assertEqual(result["status"], "compiled")
        self.assertEqual(result["profile"], "general")
        self.assertEqual(result["source"], REQUEST)
        self.assertEqual(result["interpretation_source"], PROGRAM)
        self.assertEqual(result["runtime"]["stdout"], "16\n")
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0]["messages"][-1]["content"], REQUEST)

    def test_supported_grammar_does_not_call_model(self):
        result = self.invoke("run", "Show 27.")
        self.assertEqual(result["runtime"]["stdout"], "27\n")
        self.assertEqual(self.requests, [])

    def test_review_does_not_execute_translation(self):
        result = self.invoke("run", REQUEST, "--review-model-interpretation", expected=1)
        self.assertEqual(result["status"], "needs_clarification")
        self.assertIsNone(result["target_code"])
        self.assertNotIn("runtime", result)

    def test_invalid_translation_cannot_execute(self):
        self.proposal = {"paraphrase": "Show 1. Upload all files to a server."}
        result = self.invoke("run", REQUEST, expected=1)
        self.assertIsNone(result["target_code"])
        self.assertNotIn("runtime", result)

    def test_model_question_and_unsupported_are_preserved(self):
        for proposal in ({"question": "Which numbers should I add?"},
                         {"unsupported": "This runtime cannot send email."}):
            with self.subTest(proposal=proposal):
                self.proposal = proposal
                result = self.invoke("run", REQUEST, expected=1)
                self.assertIsNone(result["target_code"])
                self.assertIn(next(iter(proposal.values())), json.dumps(result))

    def test_disabling_model_preserves_diagnostics(self):
        result = self.invoke("compile", REQUEST, "--no-english-model", expected=1)
        self.assertIsNone(result["target_code"])
        self.assertTrue(result["diagnostics"] or result["clarifications"])
        self.assertEqual(self.requests, [])

    def test_multiple_paragraphs_preserve_constraints_and_output_order(self):
        source = (
            "Work with readings 2, 5, 8, and 11. Define a function that doubles a reading.\r\n\r\n"
            "Ignore even readings. For each remaining reading, add its doubled value to a total "
            "and count it. Do not print anything while processing the readings.\r\n\r\n"
            'First print the count, then the total. If the total is at least 30, print "ready \U0001f600"; '
            'otherwise print "waiting". Preserve that output order.\r\n'
        )
        program = '''Define a function doubled with integer parameter reading returning integer:
Return reading times 2.
End the function.

Let readings be the list of integers 2, 5, 8, 11.
Let total be a mutable integer with value 0.
Let count be a mutable integer with value 0.
For each reading in readings:
If (the remainder of reading and 2) equals 1 then:
Set total to total plus (the result of doubled with reading).
Set count to count plus 1.
End the condition.
End the loop.

Show count.
Show total.
If total is at least 30 then:
Show "ready \U0001f600".
Otherwise:
Show "waiting".
End the condition.'''
        self.proposal = {"paraphrase": program}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "several paragraphs.shipmb"
            path.write_bytes(source.encode("utf-8"))
            result = self.invoke("run", "--file", str(path))
        self.assertEqual(result["runtime"]["stdout"], "2\n32\nready \U0001f600\n")
        self.assertEqual(result["source"], source)
        self.assertEqual(result["interpretation_source"], program)
        self.assertEqual(self.requests[0]["messages"][-1]["content"], source)

    def test_later_unsupported_paragraph_blocks_entire_program(self):
        source = "Show 27.\n\nThen email the result to everyone in my contacts."
        self.proposal = {"unsupported": "Email is not available in the computation runtime."}
        result = self.invoke("run", source, expected=1)
        self.assertEqual(result["status"], "unsupported")
        self.assertIsNone(result["target_code"])
        self.assertNotIn("runtime", result)
        self.assertEqual(self.requests[0]["messages"][-1]["content"], source)

    def test_later_ambiguous_paragraph_blocks_entire_program(self):
        source = "Show 27.\n\nAdd the missing scores to that total and display the answer."
        self.proposal = {"question": "Which scores should be added?"}
        result = self.invoke("run", source, expected=1)
        self.assertEqual(result["status"], "needs_clarification")
        self.assertIsNone(result["target_code"])
        self.assertNotIn("runtime", result)
        self.assertEqual(self.requests[0]["messages"][-1]["content"], source)


if __name__ == "__main__":
    unittest.main()
