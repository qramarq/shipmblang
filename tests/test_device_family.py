"""Device-family prose should not invent a device target or list_resources."""

import unittest

from driplm.natural_syntax import compile_natural_program


EMBEDDED_PARAGRAPH = """Use the embedded device family.
Expose the gpio resource.
Show device resources."""

EXPECTED_EMBEDDED_CORE = [
    "use shipmb",
    'device = family "embedded"',
    'device |> resource "gpio"',
    "device_resources |> show",
]

ROKU_RESOURCES = "use the resources a roku remote would have"


def _stripped_lines(core: str) -> list[str]:
    return [line.strip() for line in core.splitlines()]


class DeviceFamilyTests(unittest.TestCase):
    def test_embedded_paragraph_matches_documented_core(self):
        core = compile_natural_program(EMBEDDED_PARAGRAPH, memory=False)["core"]
        self.assertEqual(_stripped_lines(core), EXPECTED_EMBEDDED_CORE)
        self.assertNotIn("device_target", core)
        self.assertNotIn("list_resources", core)

    def test_roku_resources_sentence_keeps_list_resources(self):
        core = compile_natural_program(ROKU_RESOURCES, memory=False)["core"]
        self.assertIn('remote |> capability "list_resources"', core)
        self.assertNotIn("device_target = device as device", core)
        self.assertIn(
            'device_target = remote_controller platform "roku" as remote_controller',
            core,
        )


if __name__ == "__main__":
    unittest.main()
