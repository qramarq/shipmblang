"""The OpenIDEA plugin matches that IDE's plugin.toml and language schemas."""

import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "extensions" / "openidea-shipmblang"
MANIFEST = PLUGIN / "plugin.toml"
LANGUAGE = PLUGIN / "languages" / "shipmblang.toml"

# Fields PluginManifest accepts (deny_unknown_fields, kebab-case).
MANIFEST_FIELDS = {
    "id",
    "name",
    "version",
    "description",
    "authors",
    "homepage",
    "change-notes",
    "openidea-api",
    "wasm",
    "permissions",
    "contributes",
}
CONTRIBUTION_FIELDS = {"commands", "languages", "themes"}
# Fields LanguageConfig accepts. Unknown keys are ignored by the IDE, so a typo
# here would ship a language that silently drops a setting.
LANGUAGE_FIELDS = {
    "id",
    "name",
    "extensions",
    "filenames",
    "first-line",
    "line-comment",
    "block-comment",
    "indent",
    "ui-mode",
    "framework-ui-modes",
    "tree-sitter",
    "language-servers",
    "debugger",
    "formatter",
}
SERVER_FIELDS = {
    "name",
    "command",
    "args",
    "env",
    "root-markers",
    "require-root-marker",
    "initialization-options",
    "settings",
    "install-hint",
    "connect",
    "fallback",
    "max-java",
}
# CodeMirror mode name OpenIDEA resolves for ui-mode. "Properties files" colors
# '#' comments, which is the comment token the compiler accepts.
UI_MODE = "Properties files"


def _load(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


class OpenIdeaPluginTests(unittest.TestCase):
    def test_manifest_matches_openidea_schema(self):
        manifest = _load(MANIFEST)
        self.assertEqual(set(manifest), MANIFEST_FIELDS & set(manifest))
        unknown = set(manifest) - MANIFEST_FIELDS
        self.assertEqual(unknown, set(), manifest)
        self.assertEqual(manifest["id"], "shipmblang")
        self.assertRegex(manifest["id"], r"^[a-z0-9][a-z0-9_-]{0,63}$")
        self.assertEqual(manifest["name"].strip(), "ShipMBLang")
        self.assertRegex(manifest["version"], r"^[0-9]+\.[0-9]+\.[0-9]+$")
        self.assertTrue(manifest["description"].strip())
        self.assertEqual(manifest["authors"], ["ZMachinery LLC"])
        self.assertEqual(manifest["openidea-api"], "0.1")
        self.assertNotIn("wasm", manifest)
        self.assertNotIn("permissions", manifest)
        contributes = manifest["contributes"]
        self.assertEqual(set(contributes) - CONTRIBUTION_FIELDS, set())
        languages = contributes["languages"]
        self.assertEqual(len(languages), 1)
        rel = languages[0]["path"]
        self.assertEqual(set(languages[0]), {"path"})
        path = Path(rel)
        self.assertFalse(path.is_absolute())
        self.assertNotIn("..", path.parts)
        target = PLUGIN / path
        self.assertTrue(target.is_file(), target)
        self.assertEqual(target.resolve(), LANGUAGE.resolve())

    def test_language_definition_wires_lsp(self):
        language = _load(LANGUAGE)
        self.assertEqual(set(language) - LANGUAGE_FIELDS, set(), language)
        self.assertNotIn("tree-sitter", language)
        self.assertEqual(language["id"], "shipmblang")
        self.assertEqual(language["name"], "ShipMBLang")
        self.assertEqual(language["extensions"], ["shipmb", "smb", "shiplang"])
        for ext in language["extensions"]:
            self.assertEqual(ext, ext.lower())
            self.assertFalse(ext.startswith("."))
        self.assertEqual(language["line-comment"], "#")
        self.assertNotIn("block-comment", language)
        self.assertEqual(language["indent"], {"tab-size": 2, "insert-spaces": True})
        self.assertEqual(language["ui-mode"], UI_MODE)
        servers = language["language-servers"]
        self.assertEqual([server["name"] for server in servers], ["shipmblang", "shipmblang-python"])
        primary, fallback = servers
        self.assertEqual(set(primary) - SERVER_FIELDS, set())
        self.assertEqual(set(fallback) - SERVER_FIELDS, set())
        self.assertEqual(primary["command"], "shipmblang")
        self.assertEqual(primary["args"], ["lsp"])
        self.assertEqual(primary["root-markers"], [".git"])
        self.assertTrue(primary["install-hint"].strip())
        self.assertNotIn("fallback", primary)
        self.assertTrue(fallback["fallback"])
        self.assertEqual(fallback["command"], "python")
        self.assertEqual(fallback["args"], ["-X", "utf8", "-m", "shipmblang", "lsp"])
        self.assertEqual(fallback["root-markers"], [".git"])
        self.assertTrue(fallback["install-hint"].strip())

    def test_line_comment_matches_the_compiler(self):
        from shipmblang._compiler.lexer import TOKEN_RE

        language = _load(LANGUAGE)
        self.assertEqual(language["line-comment"], "#")
        comment = TOKEN_RE.pattern
        self.assertIn(r"\#", comment)
        self.assertRegex(comment, r"bad_comment>//")
        sample = "Show 1. # keep\n// no\n"
        kinds = [match.lastgroup for match in TOKEN_RE.finditer(sample)]
        self.assertIn("comment", kinds)
        self.assertIn("bad_comment", kinds)


if __name__ == "__main__":
    unittest.main()
