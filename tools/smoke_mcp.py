"""Smoke-test the ShipLang MCP stdio server as a standalone client."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test python -m shipmblang mcp.")
    parser.add_argument("--python", default=sys.executable, help="Python executable to run the MCP server.")
    parser.add_argument("--cwd", default=".", help="Working directory for the MCP server.")
    args = parser.parse_args()

    proc = subprocess.Popen(
        [args.python, "-m", "shipmblang", "mcp"],
        cwd=Path(args.cwd),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    assert proc.stdin is not None
    assert proc.stdout is not None

    try:
        initialize = request(proc, 1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "shipmblang-smoke", "version": "0.1.0"}})
        assert initialize["result"]["serverInfo"]["name"] == "shipmblang"

        notify(proc, "notifications/initialized", {})

        tools = request(proc, 2, "tools/list", {})
        tool_names = {tool["name"] for tool in tools["result"]["tools"]}
        assert "printurf" in tool_names
        assert "shipmblang_explain_error" in tool_names
        assert "shipmblang_index_codebase" in tool_names
        assert "shiplang_explain_error" in tool_names
        assert "shiplang_index_codebase" in tool_names
        assert "drip_explain_error" in tool_names
        assert "drip_index_codebase" in tool_names

        indexed = request(
            proc,
            3,
            "tools/call",
            {
                "name": "shipmblang_index_codebase",
                "arguments": {"root_path": str(Path(args.cwd).resolve()), "max_files": 20},
            },
        )
        indexed_text = indexed["result"]["content"][0]["text"]
        assert "indexed" in indexed_text, indexed_text

        explanation = request(
            proc,
            4,
            "tools/call",
            {
                "name": "printurf",
                "arguments": {
                    "raw_error": "NameError: name 'CHECKPOINT_PAT' is not defined",
                    "code_context": "> 1: print(CHECKPOINT_PAT)",
                },
            },
        )
        text = explanation["result"]["content"][0]["text"]
        assert text.startswith("Error: "), text
        assert " Cause: " in text, text
        assert " Fix: " in text, text

        structured = request(
            proc,
            5,
            "tools/call",
            {
                "name": "printurf",
                "arguments": {
                    "raw_error": "NameError: name 'main' is not defined",
                    "paths": ["shipmblang/__main__.py"],
                    "format": "json",
                },
            },
        )
        report = json.loads(structured["result"]["content"][0]["text"])
        assert report["status"] == "error", report
        assert report["diagnostic_count"] == 1, report
        assert report["project"]["file_count"] >= 1, report

        print("MCP smoke test passed")
    finally:
        proc.kill()
        proc.wait(timeout=5)


def request(proc: subprocess.Popen[str], request_id: int, method: str, params: dict) -> dict:
    send(proc, {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
    line = read_line(proc)
    response = json.loads(line)
    assert response.get("jsonrpc") == "2.0", response
    assert response.get("id") == request_id, response
    assert "error" not in response, response
    return response


def notify(proc: subprocess.Popen[str], method: str, params: dict) -> None:
    send(proc, {"jsonrpc": "2.0", "method": method, "params": params})


def send(proc: subprocess.Popen[str], message: dict) -> None:
    assert proc.stdin is not None
    proc.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
    proc.stdin.flush()


def read_line(proc: subprocess.Popen[str]) -> str:
    assert proc.stdout is not None
    line = proc.stdout.readline()
    if not line:
        stderr = proc.stderr.read() if proc.stderr else ""
        raise RuntimeError(f"MCP server closed stdout unexpectedly. stderr={stderr}")
    return line


if __name__ == "__main__":
    main()
