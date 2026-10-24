"""Language Server Protocol for ShipMBLang, using only the standard library.

The server speaks Content-Length framed JSON-RPC on stdin/stdout. Diagnostics
and hover use the bundled compiler. Source spans from the compiler are Unicode
code-point offsets and are converted to UTF-16 positions for LSP.
"""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as package_version
import json
import sys


COMPILE = "shipmblang.compile"
RUN = "shipmblang.run"
COMMANDS = [COMPILE, RUN]


def shipmblang_version() -> str:
    try:
        return package_version("shipmblang")
    except PackageNotFoundError:
        return "0.6.0"


def codepoint_to_utf16_position(source: str, offset: int) -> dict:
    """Convert a compiler code-point offset to an LSP UTF-16 position."""
    chars = list(source or "")
    if offset < 0:
        offset = 0
    if offset > len(chars):
        offset = len(chars)
    head = "".join(chars[:offset])
    line_number = head.count("\n")
    column_text = head[head.rfind("\n") + 1:]
    return {"line": line_number, "character": _utf16_units(column_text)}


def utf16_position_to_codepoint(source: str, line: int, character: int) -> int:
    """Convert an LSP UTF-16 position to a compiler code-point offset."""
    lines = (source or "").split("\n")
    if line < 0:
        return 0
    if line >= len(lines):
        return len(list(source or ""))
    prior = sum(len(item) + 1 for item in lines[:line])
    units = 0
    count = 0
    for char in lines[line]:
        if units >= character:
            break
        units += _utf16_units(char)
        count += 1
    return prior + count


def line_codepoint_span(source: str, line: int) -> tuple[int, int]:
    lines = (source or "").split("\n")
    if line < 0 or line >= len(lines):
        return 0, 0
    start = sum(len(item) + 1 for item in lines[:line])
    return start, start + len(lines[line])


def _utf16_units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


class LanguageServer:
    def __init__(self):
        self.documents: dict[str, str] = {}
        self.running = True

    def handle(self, message: dict) -> list[dict]:
        if not isinstance(message, dict):
            return []
        method = message.get("method")
        message_id = message.get("id")
        params = message.get("params") or {}
        if not isinstance(params, dict) and method not in {"shutdown"}:
            params = {}
        try:
            if method == "initialize":
                return [self._result(message_id, self._initialize())]
            if method == "initialized":
                return []
            if method == "shutdown":
                return [self._result(message_id, None)]
            if method == "exit":
                self.running = False
                return []
            if method == "textDocument/didOpen":
                return self._did_open(params)
            if method == "textDocument/didChange":
                return self._did_change(params)
            if method == "textDocument/didSave":
                return self._did_save(params)
            if method == "textDocument/didClose":
                uri = ((params.get("textDocument") or {}).get("uri"))
                if uri:
                    self.documents.pop(uri, None)
                return []
            if method == "textDocument/hover":
                return [self._result(message_id, self._hover(params))]
            if method == "workspace/executeCommand":
                return [self._result(message_id, self._execute(params))]
            if message_id is not None:
                return [self._error(message_id, -32601, f"Method not found: {method}")]
            return []
        except Exception as error:
            if message_id is not None:
                return [self._error(message_id, -32603, str(error))]
            return []

    def _initialize(self) -> dict:
        return {
            "capabilities": {
                "positionEncoding": "utf-16",
                "textDocumentSync": {"openClose": True, "change": 1, "save": {"includeText": True}},
                "hoverProvider": True,
                "executeCommandProvider": {"commands": list(COMMANDS)},
            },
            "serverInfo": {"name": "shipmblang", "version": shipmblang_version()},
        }

    def _did_open(self, params: dict) -> list[dict]:
        document = params.get("textDocument") or {}
        uri = document.get("uri") or ""
        text = document.get("text") or ""
        if uri:
            self.documents[uri] = text
        return [self._diagnostics(uri, text)]

    def _did_change(self, params: dict) -> list[dict]:
        uri = ((params.get("textDocument") or {}).get("uri")) or ""
        changes = params.get("contentChanges") or []
        if changes and isinstance(changes[0], dict) and "text" in changes[0]:
            self.documents[uri] = changes[0].get("text") or ""
        return [self._diagnostics(uri, self.documents.get(uri, ""))]

    def _did_save(self, params: dict) -> list[dict]:
        document = params.get("textDocument") or {}
        uri = document.get("uri") or ""
        if "text" in params and isinstance(params.get("text"), str):
            self.documents[uri] = params["text"]
        return [self._diagnostics(uri, self.documents.get(uri, ""))]

    def _diagnostics(self, uri: str, text: str) -> dict:
        items = []
        if text.strip():
            result = _compile(text)
            items = diagnostics_from_result(text, result)
        return {"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics",
                "params": {"uri": uri, "diagnostics": items}}

    def _hover(self, params: dict) -> dict | None:
        uri = ((params.get("textDocument") or {}).get("uri")) or ""
        position = params.get("position") or {}
        text = self.documents.get(uri)
        if text is None:
            return None
        line = int(position.get("line") or 0)
        character = int(position.get("character") or 0)
        contents = hover_markdown(text, line, character)
        if not contents:
            return None
        start, end = line_codepoint_span(text, line)
        return {
            "contents": {"kind": "markdown", "value": contents},
            "range": {"start": codepoint_to_utf16_position(text, start),
                      "end": codepoint_to_utf16_position(text, end)},
        }

    def _execute(self, params: dict) -> dict:
        command = params.get("command")
        if command not in COMMANDS:
            raise ValueError(f"Unknown command: {command}")
        text, uri = self._command_text(params.get("arguments") or [])
        result = _run(text) if command == RUN else _compile(text)
        if uri:
            self.documents[uri] = text
        runtime = result.get("runtime") or {}
        status = result.get("status")
        return {
            "status": status,
            "exitCode": 0 if status == "compiled" else 1,
            "stdout": runtime.get("stdout"),
            "output": result.get("output"),
            "diagnostics": result.get("diagnostics") or [],
            "clarifications": result.get("clarifications") or [],
            "uri": uri,
        }

    def _command_text(self, arguments) -> tuple[str, str | None]:
        if not arguments:
            raise ValueError("Pass the program text or an open document URI.")
        first = arguments[0]
        if isinstance(first, str):
            if first in self.documents:
                return self.documents[first], first
            return first, None
        if isinstance(first, dict):
            uri = first.get("uri")
            if first.get("text") is not None:
                return str(first.get("text")), uri
            if uri and uri in self.documents:
                return self.documents[uri], uri
        raise ValueError("Pass the program text or an open document URI.")

    @staticmethod
    def _result(message_id, value) -> dict:
        return {"jsonrpc": "2.0", "id": message_id, "result": value}

    @staticmethod
    def _error(message_id, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def diagnostics_from_result(source: str, result: dict) -> list[dict]:
    items = []
    for diagnostic in result.get("diagnostics") or []:
        items.append(_diagnostic(source, diagnostic, severity=1 if diagnostic.get("level") != "warning" else 2))
    for question in result.get("clarifications") or []:
        items.append(_diagnostic(source, {
            "message": question.get("question") or "The compiler needs clarification.",
            "span": question.get("span") or {},
            "code": question.get("id") or "clarification",
            "level": "warning",
        }, severity=2))
    return items


def _diagnostic(source: str, diagnostic: dict, *, severity: int) -> dict:
    span = diagnostic.get("span") or diagnostic.get("source_span") or {}
    start = int(span.get("start") or 0)
    end = int(span.get("end") or start)
    if end < start:
        end = start
    return {
        "range": {"start": codepoint_to_utf16_position(source, start),
                  "end": codepoint_to_utf16_position(source, end)},
        "severity": severity,
        "source": "shipmblang",
        "message": diagnostic.get("message") or "Compiler diagnostic",
        "code": diagnostic.get("code") or "",
    }


def hover_markdown(source: str, line: int, character: int) -> str:
    if not source.strip():
        return ""
    result = _compile(source)
    start, end = line_codepoint_span(source, line)
    offset = utf16_position_to_codepoint(source, line, character)
    lines = source.split("\n")
    line_text = lines[line] if 0 <= line < len(lines) else ""
    parts = [f"```\n{line_text}\n```"]
    relevant = []
    for diagnostic in diagnostics_from_result(source, result):
        diag_line = diagnostic["range"]["start"]["line"]
        if diag_line == line:
            relevant.append(diagnostic["message"])
    if relevant:
        parts.append("\n".join(f"- {message}" for message in relevant))
    bytecode = ((result.get("target_code") or {}).get("bytecode") or []) if result.get("status") == "compiled" else []
    ops = []
    for instruction in bytecode:
        span = instruction.get("source_span") or {}
        if _overlaps(span, start, end) or _overlaps(span, offset, offset + 1):
            ops.append(_opcode_line(instruction))
    if ops:
        parts.append("This line compiles to:\n\n" + "\n".join(f"- `{op}`" for op in ops))
    elif result.get("status") == "compiled":
        node = _smallest_node(result.get("syntax_tree"), offset)
        if node is not None:
            parts.append(f"Compiler node: `{node.get('kind')}`")
    return "\n\n".join(part for part in parts if part)


def _overlaps(span: dict, start: int, end: int) -> bool:
    if not isinstance(span, dict) or "start" not in span:
        return False
    return int(span.get("start") or 0) < end and int(span.get("end") or 0) > start


def _opcode_line(instruction: dict) -> str:
    opcode = instruction.get("opcode") or "op"
    operands = instruction.get("operands") or {}
    if opcode == "const":
        return f"const {operands.get('value')}"
    if opcode == "binary":
        return f"binary {operands.get('operator')}"
    if not operands:
        return opcode
    rendered = ", ".join(f"{key}={value}" for key, value in operands.items())
    return f"{opcode} {rendered}"


def _smallest_node(node, offset: int):
    best = None
    best_span = None

    def visit(item):
        nonlocal best, best_span
        if not isinstance(item, dict):
            return
        span = item.get("span")
        if isinstance(span, dict) and span.get("start") is not None and span.get("end") is not None:
            if int(span["start"]) <= offset < int(span["end"]):
                width = int(span["end"]) - int(span["start"])
                if best_span is None or width < best_span:
                    best = item
                    best_span = width
        for value in item.values():
            if isinstance(value, dict):
                visit(value)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

    visit(node)
    return best


def _compile(source: str) -> dict:
    from .pipelines import compile_direct_program

    return compile_direct_program(
        source, memory=False, model_provider=None, accept_model_interpretation=False, profile="general")


def _run(source: str) -> dict:
    from .pipelines import run_direct_program

    return run_direct_program(
        source, memory=False, model_provider=None, accept_model_interpretation=False, profile="general")


def _read_message(stream):
    headers = {}
    while True:
        line = stream.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        decoded = line.decode("ascii", errors="replace")
        if ":" not in decoded:
            continue
        key, value = decoded.split(":", 1)
        headers[key.strip().lower()] = value.strip()
    length = int(headers.get("content-length", "0"))
    if length < 0:
        raise ValueError("Invalid Content-Length.")
    body = stream.read(length)
    if len(body) != length:
        return None
    return json.loads(body.decode("utf-8"))


def _write_message(stream, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    stream.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    stream.write(body)
    stream.flush()


def serve(input_stream=None, output_stream=None) -> int:
    incoming = input_stream if input_stream is not None else sys.stdin.buffer
    outgoing = output_stream if output_stream is not None else sys.stdout.buffer
    server = LanguageServer()
    while server.running:
        message = _read_message(incoming)
        if message is None:
            break
        for response in server.handle(message):
            _write_message(outgoing, response)
    return 0


def self_check() -> int:
    server = LanguageServer()
    responses = server.handle({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"processId": None, "capabilities": {}},
    })
    encoded = json.dumps(responses)
    if COMPILE not in encoded or RUN not in encoded:
        print("lsp check failed: compile and run commands were not advertised", file=sys.stderr)
        return 1
    server.handle({"jsonrpc": "2.0", "id": 2, "method": "shutdown", "params": None})
    server.handle({"jsonrpc": "2.0", "method": "exit"})
    if server.running:
        print("lsp check failed: exit did not stop the server", file=sys.stderr)
        return 1
    print("lsp ok")
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv in (["-h"], ["--help"]):
        print("Usage: shipmblang lsp")
        print("Serve the ShipMBLang language server on standard input and output.")
        print("shipmblang lsp --check   verify the server without a client")
        return 0
    if argv == ["--check"]:
        return self_check()
    if argv:
        print("Usage: shipmblang lsp", file=sys.stderr)
        return 2
    return serve()


if __name__ == "__main__":
    raise SystemExit(main())
