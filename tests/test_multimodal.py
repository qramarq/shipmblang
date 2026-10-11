"""Regression coverage for ordered image and English compiler requests."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from shipmblang._compiler.direct import compile_direct_program
from shipmblang._compiler.english_model import (
    EnglishModelFrontend,
    ImageAnchorError,
    MULTIMODAL_CONTRACT_VERSION,
)


PNG = b"\x89PNG\r\n\x1a\n" + b"test-image"


class MultimodalContractTests(unittest.TestCase):
    def test_frontend_interleaves_text_and_images_at_anchors(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / "one.png", Path(directory) / "two.png"
            first.write_bytes(PNG)
            second.write_bytes(PNG)
            provider = Mock()
            provider.chat_completion.return_value = {"choices": [{"finish_reason": "stop", "message": {
                "content": json.dumps({"paraphrase": "Show 9."})}}]}

            proposal = EnglishModelFrontend(provider)(
                "Before [[image:1]] between [[image:2]] after.", images=[first, second]
            )

        self.assertEqual(MULTIMODAL_CONTRACT_VERSION, "shipmb-image-prose-v2")
        self.assertEqual(proposal, {"paraphrase": "Show 9."})
        content = provider.chat_completion.call_args.args[0][1]["content"]
        kinds = [block["type"] for block in content]
        self.assertEqual(kinds, ["text", "text", "image_url", "text", "text", "image_url", "text"])
        self.assertEqual(content[0]["text"], "Before ")
        self.assertEqual(content[3]["text"], " between ")
        self.assertEqual(content[6]["text"], " after.")

    def test_frontend_rejects_duplicate_or_unmatched_image_anchors(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "one.png"
            image.write_bytes(PNG)
            frontend = EnglishModelFrontend(Mock())
            for source in ("[[image:1]] and [[image:1]]", "[[image:2]]"):
                with self.subTest(source=source), self.assertRaises(ImageAnchorError):
                    frontend(source, images=[image])

    def test_missing_attachment_returns_structured_clarification(self):
        result = compile_direct_program("Read [[image:1]].", memory=False, model_provider=None)

        self.assertEqual(result["status"], "needs_clarification")
        self.assertEqual(result["clarifications"][0]["id"], "missing-image")
        self.assertTrue(result["memory"]["image_input_not_persisted"])
        self.assertIsNone(result["target_code"])


if __name__ == "__main__":
    unittest.main()
