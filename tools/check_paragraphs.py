"""Check installed language/compiler paragraph semantics via API and CLI.

Run with the intended Python environment:
  python -I tools/check_paragraphs.py <language-checkout>
The caller supplies installed packages; this script does not alter sys.path.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from shipmblang import run_direct_program


def main():
    root = Path(sys.argv[1]).resolve()
    fixtures = [
        ("multiple_paragraphs.shipmb", "27\n"),
        ("paragraph_functions.shipmb", "720\n"),
    ]
    with tempfile.TemporaryDirectory(prefix="shipmb-paragraphs-") as folder:
        source_file = Path(folder) / "multiple paragraphs.smb"
        for name, expected in fixtures:
            quoted = (root / "examples" / name).read_text(encoding="utf-8")
            paragraphs = quoted.strip().split("\n\n")
            # The examples have no blank lines within an individual quoted block.
            bodies = [paragraph[1:-1] for paragraph in paragraphs]
            variants = [quoted, '"' + "\n\n".join(bodies) + '"\n']
            if name == "multiple_paragraphs.shipmb":
                variants.append(quoted.replace("    Set total", "”\n\n“    Set total", 1))
            for source in variants:
                for newline in ("\n", "\r\n"):
                    exact = source.replace("\n", newline)
                    result = run_direct_program(exact, profile="general", memory=False)
                    assert result["source"] == exact, result
                    assert result["runtime"]["stdout"] == expected, result
                    source_file.write_bytes(exact.encode("utf-8"))
                    process = subprocess.run(
                        [sys.executable, "-X", "utf8", "-I", "-m", "shipmblang", "run",
                         "--file", str(source_file), "--pipeline", "direct", "--profile", "general", "--memory", "off"],
                        cwd=folder, capture_output=True, text=True, encoding="utf-8")
                    assert process.returncode == 0, process.stderr + process.stdout
                    loaded = json.loads(process.stdout)
                    assert loaded["source"] == exact, loaded
                    assert loaded["runtime"]["stdout"] == expected, loaded
        invalid_sources = [
            '“Show "😀".”\r\n\r\n“Show missing.”',
            '"Start with total at 4."\n\n"Send an email to everyone."\n\n"Show total."',
            '"Let first be 1."\n\n"Let second be 2."\n\n"Show it."',
        ]
        for source in invalid_sources:
            result = run_direct_program(source, profile="general", memory=False)
            assert result["source"] == source, result
            assert result["status"] != "compiled", result
            assert result.get("runtime") is None, result
            assert result.get("target_code") is None, result
            assert result.get("diagnostics") or result.get("clarifications"), result
            if "missing" in source:
                spans = [d.get("span") or d.get("source_span") for d in result.get("diagnostics", []) + result.get("clarifications", [])]
                assert any(span and source.index("Show missing") <= span["start"] <= source.index("missing") for span in spans), result
            source_file.write_bytes(source.encode("utf-8"))
            process = subprocess.run(
                [sys.executable, "-X", "utf8", "-I", "-m", "shipmblang", "run",
                 "--file", str(source_file), "--pipeline", "direct", "--profile", "general", "--memory", "off"],
                cwd=folder, capture_output=True, text=True, encoding="utf-8")
            assert process.returncode == 1, process.stderr + process.stdout
            loaded = json.loads(process.stdout)
            assert loaded["source"] == source and loaded.get("runtime") is None, loaded
    print("Paragraph checks passed: shared values, nested loops/conditions, functions, both quote layouts, LF/CRLF, Unicode spans, no partial run.")


if __name__ == "__main__":
    main()
