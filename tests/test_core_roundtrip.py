"""Published Core must round-trip through the IR pipeline without error diagnostics."""

from pathlib import Path
import unittest

from shipmblang._compiler.compiler import compile_source
from shipmblang._compiler.core import core_syntax_analysis


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
LEGACY_SOURCE = "Use Python. Declare an integer variable total set to 4. Show total."


def error_diagnostics(result):
    return [diagnostic for diagnostic in result["diagnostics"] if diagnostic["level"] == "error"]


class CoreRoundtripTests(unittest.TestCase):
    def assert_no_errors(self, result):
        errors = error_diagnostics(result)
        if errors:
            messages = "\n".join(
                f"{diagnostic.get('code')}: {diagnostic.get('message')} [{diagnostic.get('span')}]"
                for diagnostic in errors
            )
            print(messages)
            self.fail(messages)

    def test_legacy_python_core_compiles(self):
        from driplm.natural_syntax import compile_natural_program

        core = compile_natural_program(LEGACY_SOURCE, memory=False)["core"]
        result = compile_source(core, run=False, memory=False)
        self.assert_no_errors(result)
        forms = [
            instruction["operands"].get("form")
            for instruction in result["target_code"]["bytecode"]
            if instruction["opcode"] == "core_declare"
        ]
        self.assertEqual(forms, ["target_language", "let", "pipeline"])
        self.assertEqual(result["target_code"]["bytecode"][0]["opcode"], "use_prelude")

    def test_core_contract_compiles(self):
        source = (EXAMPLES / "core_contract.shipmb").read_text(encoding="utf-8")
        result = compile_source(source, run=False, memory=False)
        self.assert_no_errors(result)
        opcodes = [instruction["opcode"] for instruction in result["target_code"]["bytecode"]]
        self.assertEqual(opcodes[0], "use_prelude")
        self.assertIn("core_declare", opcodes)
        self.assertNotIn("declare_capability", opcodes)
        self.assertTrue(any(diagnostic["code"] == "SMB7001" for diagnostic in result["diagnostics"]))
        self.assertTrue(any(diagnostic["level"] == "note" for diagnostic in result["diagnostics"]))

    def test_existing_lines_keep_their_kinds(self):
        source = "\n".join([
            "use shipmb",
            "architecture |> show",
            "error |> printurf |> show",
            'library "tv_pack" from "shipmblang"',
            'device_target = tv platform "roku" as tv',
            'remote |> capability "remote_control" agentic',
            'device |> capability "power_on" native',
            "device_target = device as device",
            'mcp "server" |> tool "tool"',
        ])
        tree, _diagnostics = core_syntax_analysis(source)
        kinds = {child.surface_text: child.kind for child in tree.children}
        self.assertEqual(kinds["use shipmb"], "UsePrelude")
        self.assertEqual(kinds["architecture |> show"], "ArchitectureDebug")
        self.assertEqual(kinds["error |> printurf |> show"], "CorePipeline")
        self.assertEqual(kinds['library "tv_pack" from "shipmblang"'], "ImportLibrary")
        self.assertEqual(kinds['device_target = tv platform "roku" as tv'], "DeviceTarget")
        self.assertEqual(kinds['remote |> capability "remote_control" agentic'], "CapabilityStatement")
        self.assertEqual(kinds['device |> capability "power_on" native'], "CoreDeclaration")
        self.assertEqual(kinds["device_target = device as device"], "CoreDeclaration")
        native = next(child for child in tree.children if child.surface_text.endswith("native"))
        self.assertEqual(native.roles["form"], "capability")
        self.assertEqual(native.roles["text"], 'device |> capability "power_on" native')
        plain_target = next(child for child in tree.children if child.surface_text == "device_target = device as device")
        self.assertEqual(plain_target.kind, "CoreDeclaration")
        self.assertEqual(plain_target.roles["form"], "device_target")
        self.assertEqual(kinds['mcp "server" |> tool "tool"'], "MCPToolCall")

        result = compile_source("use shipmb\narchitecture |> show\n", run=False, memory=False)
        self.assert_no_errors(result)
        self.assertEqual(
            [instruction["opcode"] for instruction in result["target_code"]["bytecode"]],
            ["use_prelude"],
        )

    def test_published_forms_compile(self):
        source = "\n".join([
            "use shipmb",
            "# intent: kept as a comment",
            'target language "python"',
            'import "math"',
            'from "collections" import ["Counter"]',
            'from "mod" import symbols',
            "let total: int = 0",
            "const limit: int = 1",
            "project |> index",
            "error |> printurf |> suggest_fix |> show",
            'device |> resource "gpio"',
            "device_resources |> show",
            'project = open "demo"',
            'device = family "embedded"',
            'write x to "path"',
            "fn boot_device(device):",
            "pass",
            "return total",
            'bridge device <-> shipmb.vision using "grpc"',
            "class camera_controller:",
            "property active_device",
            "method start(device):",
            "call boot_device()",
            "call boot_device with camera",
            "if ready:",
            "for item in items:",
            "camera_id = \"front-door\"",
            "retry_count = 3",
            "enabled = true",
            "providers = [native_camera, opencv_bridge, browser_camera]",
            "routes = []",
            'routes append "local"',
            "type telemetry_packet:",
            "field device_id: string",
            "interface operator_console:",
            'mode "client"',
            "notify_user true",
            'privacy "local_only"',
            "device robot_arm:",
            "interlock emergency_stop required",
            "interlock operator_present when speed > 0",
            "policy allow movement when emergency_stop == false and operator_present == true",
            "capability scan_frame:",
            "provider native_camera priority 100 native",
            "provider opencv_bridge priority 50",
        ])
        result = compile_source(source, run=False, memory=False)
        self.assert_no_errors(result)
        tree, diagnostics = core_syntax_analysis(source)
        self.assertFalse(any(diagnostic.level == "error" for diagnostic in diagnostics))
        forms = {child.surface_text: child.roles.get("form") for child in tree.children if child.kind == "CoreDeclaration"}
        self.assertEqual(forms['project = open "demo"'], "open_project")
        self.assertEqual(forms['device = family "embedded"'], "device_family")
        self.assertEqual(forms["let total: int = 0"], "let")
        self.assertEqual(forms["const limit: int = 1"], "const")
        self.assertEqual(forms["project |> index"], "pipeline")
        self.assertEqual(forms["error |> printurf |> suggest_fix |> show"], "pipeline")
        self.assertEqual(forms["camera_id = \"front-door\""], "assignment")
        self.assertEqual(forms['routes append "local"'], "append")

    def test_garbage_line_is_still_an_error(self):
        result = compile_source("use shipmb\nthis is not core ???\n", run=False, memory=False)
        errors = error_diagnostics(result)
        if not any(diagnostic["code"] == "SMB1005" for diagnostic in errors):
            messages = "\n".join(
                f"{diagnostic.get('code')}: {diagnostic.get('message')}" for diagnostic in result["diagnostics"]
            )
            print(messages)
            self.fail(messages)
        tree, diagnostics = core_syntax_analysis("???")
        self.assertEqual(tree.children[0].kind, "UnsupportedStatement")
        self.assertTrue(any(diagnostic.code == "SMB1005" for diagnostic in diagnostics))

    def test_trailing_comma_is_still_an_error(self):
        result = compile_source(
            "use shipmb\nproviders = [native_camera, opencv_bridge,]\n",
            run=False,
            memory=False,
        )
        errors = error_diagnostics(result)
        self.assertTrue(any(diagnostic["code"] == "SMB1006" for diagnostic in errors))

    def test_core_declare_reaches_runtime(self):
        result = compile_source("use shipmb\nlet total: int = 4\n", run=True, memory=False)
        self.assert_no_errors(result)
        declared = [
            instruction for instruction in result["target_code"]["bytecode"]
            if instruction["opcode"] == "core_declare"
        ]
        self.assertEqual(len(declared), 1)
        self.assertEqual(declared[0]["operands"]["form"], "let")
        self.assertEqual(declared[0]["operands"]["text"], "let total: int = 4")
        events = result["runtime"]["events"]
        self.assertIn(
            {"event": "core.declared", "form": "let", "text": "let total: int = 4"},
            events,
        )


if __name__ == "__main__":
    unittest.main()
