"""Minimal MCP stdio server for ShipMBLang editor integrations."""

from __future__ import annotations

import json
import io
import os
from pathlib import Path
import sys
from typing import Any
from contextlib import redirect_stdout

from .device_families import (
    format_device_family_library,
    format_device_resource,
    get_device_family,
    list_device_families,
    require_device_family,
)
from .error_explainer import (
    build_printurf_report,
    format_editor_context,
    render_printurf_report,
)
from .project_context import build_codebase_index, format_codebase_index


SERVER_NAME = "shipmblang"
PROTOCOL_VERSION = "2025-06-18"

_engine = None
_indexed_root: str | None = None
_indexed_codebase: dict[str, Any] | None = None
_active_device_family = "host"


def main() -> None:
    """Run a newline-delimited JSON-RPC MCP server over stdio."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = _handle_request(request)
        except Exception as exc:
            response = _error_response(None, -32603, str(exc))
        if response is not None:
            sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
            sys.stdout.flush()


def _handle_request(request: dict[str, Any]) -> dict[str, Any] | None:
    method = request.get("method")
    request_id = request.get("id")
    params = request.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                "serverInfo": {"name": SERVER_NAME, "version": "0.1.0"},
            },
        }

    if method in {"notifications/initialized", "notifications/cancelled"}:
        return None

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": _tools()}}

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        try:
            text = _call_tool(name, arguments)
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"content": [{"type": "text", "text": text}], "isError": False},
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"content": [{"type": "text", "text": str(exc)}], "isError": True},
            }

    if method == "resources/list":
        resources = _device_resources()
        if _indexed_root:
            resources.append(
                {
                    "uri": "shipmblang://indexed-codebase",
                    "name": "Indexed codebase",
                    "description": _indexed_root,
                    "mimeType": "text/plain",
                }
            )
        return {"jsonrpc": "2.0", "id": request_id, "result": {"resources": resources}}

    if method == "resources/read":
        uri = str(params.get("uri") or "")
        device_resource = _read_device_resource(uri)
        if device_resource is not None:
            return {"jsonrpc": "2.0", "id": request_id, "result": {"contents": [device_resource]}}
        if uri in {
            "shipmblang://indexed-codebase",
            "shipmb://indexed-codebase",
            "shiplang://indexed-codebase",
            "drip://indexed-codebase",
        } and _indexed_root:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "contents": [
                        {
                            "uri": "shipmblang://indexed-codebase",
                            "mimeType": "text/plain",
                            "text": format_codebase_index(_indexed_codebase) if _indexed_codebase else f"ShipMBLang indexed root: {_indexed_root}",
                        }
                    ]
                },
            }
        return _error_response(request_id, -32602, "Unknown resource")

    if method == "prompts/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"prompts": []}}

    return _error_response(request_id, -32601, f"Unknown method: {method}")


def _tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "printurf",
            "description": "Explain a runtime error, compiler warning, or stack trace using local code context.",
            "inputSchema": _explain_error_schema(),
        },
        {
            "name": "shipmblang_explain_error",
            "description": "ShipMBLang alias for printurf.",
            "inputSchema": _explain_error_schema(),
        },
        {
            "name": "shipmb_explain_error",
            "description": "ShipMB alias for printurf.",
            "inputSchema": _explain_error_schema(),
        },
        {
            "name": "shiplang_explain_error",
            "description": "Compatibility alias for printurf.",
            "inputSchema": _explain_error_schema(),
        },
        {
            "name": "shipmblang_index_codebase",
            "description": "Record the workspace root that ShipMBLang should treat as the current codebase.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "root_path": {"type": "string", "description": "Workspace root path."},
                    "max_files": {"type": "integer", "description": "Maximum source files to index."},
                },
                "required": ["root_path"],
            },
        },
        {
            "name": "shipmb_index_codebase",
            "description": "Record the workspace root that ShipMB should treat as the current codebase.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "root_path": {"type": "string", "description": "Workspace root path."},
                    "max_files": {"type": "integer", "description": "Maximum source files to index."},
                },
                "required": ["root_path"],
            },
        },
        {
            "name": "shiplang_index_codebase",
            "description": "Legacy compatibility alias for shipmblang_index_codebase.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "root_path": {"type": "string", "description": "Workspace root path."},
                    "max_files": {"type": "integer", "description": "Maximum source files to index."},
                },
                "required": ["root_path"],
            },
        },
        {
            "name": "drip_explain_error",
            "description": "Legacy compatibility alias for printurf.",
            "inputSchema": _explain_error_schema(),
        },
        {
            "name": "drip_index_codebase",
            "description": "Legacy compatibility alias for shipmblang_index_codebase.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "root_path": {"type": "string", "description": "Workspace root path."},
                    "max_files": {"type": "integer", "description": "Maximum source files to index."},
                },
                "required": ["root_path"],
            },
        },
        {
            "name": "shipmblang_list_device_families",
            "description": "List ShipMBLang device family libraries and their available resources.",
            "inputSchema": _device_family_schema(required_family=False, required_resource=False),
        },
        {
            "name": "shipmblang_select_device_family",
            "description": "Select the current ShipMBLang device family so active-device resources point at that target.",
            "inputSchema": _device_family_schema(required_family=True, required_resource=False),
        },
        {
            "name": "shipmblang_get_device_resource",
            "description": "Read one resource from the selected or specified ShipMBLang device family.",
            "inputSchema": _device_family_schema(required_family=False, required_resource=True),
        },
    ]


def _explain_error_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "raw_error": {"type": "string", "description": "Raw diagnostic, warning, or stack trace."},
            "code_context": {"type": "string", "description": "Relevant source code context."},
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Files or directories to inspect for project context.",
            },
            "root_path": {"type": "string", "description": "Project root for relative paths."},
            "file_path": {"type": "string", "description": "Path to the source file."},
            "line": {"type": "integer", "description": "1-based line number for the failing code."},
            "format": {"type": "string", "enum": ["text", "json"], "description": "Return readable text or JSON."},
        },
        "required": [],
    }


def _device_family_schema(*, required_family: bool, required_resource: bool) -> dict[str, Any]:
    required = []
    if required_family:
        required.append("family")
    if required_resource:
        required.append("resource")
    return {
        "type": "object",
        "properties": {
            "family": {"type": "string", "description": "Device family name or alias, such as host, cuda, browser, or embedded."},
            "resource": {"type": "string", "description": "Resource name inside the device family, such as filesystem, tensors, dom, or gpio."},
            "format": {"type": "string", "enum": ["text", "json"], "description": "Return readable text or JSON."},
        },
        "required": required,
    }


def _call_tool(name: str, arguments: dict[str, Any]) -> str:
    if name in {"printurf", "shipmblang_explain_error", "shipmb_explain_error", "shiplang_explain_error", "drip_explain_error"}:
        return _tool_explain_error(arguments)
    if name in {"shipmblang_index_codebase", "shipmb_index_codebase", "shiplang_index_codebase", "drip_index_codebase"}:
        return _tool_index_codebase(arguments)
    if name == "shipmblang_list_device_families":
        return _tool_list_device_families(arguments)
    if name == "shipmblang_select_device_family":
        return _tool_select_device_family(arguments)
    if name == "shipmblang_get_device_resource":
        return _tool_get_device_resource(arguments)
    raise ValueError(f"Unknown tool: {name}")


def _tool_explain_error(arguments: dict[str, Any]) -> str:
    raw_error = str(arguments.get("raw_error") or "")
    file_path = arguments.get("file_path")
    line = arguments.get("line")
    code_context = str(arguments.get("code_context") or "")
    paths = [str(path) for path in (arguments.get("paths") or [])]
    root_path = arguments.get("root_path") or _indexed_root
    output_format = str(arguments.get("format") or "text")

    if file_path and not code_context:
        path = Path(str(file_path))
        if path.exists() and path.is_file():
            source = path.read_text(encoding="utf-8", errors="replace")
            code_context = format_editor_context(str(path), source, int(line) if line else None)
        if str(file_path) not in paths:
            paths.insert(0, str(file_path))

    engine = _load_engine()
    report = build_printurf_report(
        raw_error=raw_error,
        code_context=code_context,
        paths=paths,
        root=root_path,
        line=int(line) if line else None,
        engine=engine,
    )
    if output_format == "json":
        return json.dumps(report, indent=2)
    return render_printurf_report(report, include_context=bool(paths))


def _tool_index_codebase(arguments: dict[str, Any]) -> str:
    global _indexed_root, _indexed_codebase
    root = Path(str(arguments.get("root_path") or "")).resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Codebase root does not exist: {root}")
    _indexed_root = str(root)
    max_files = int(arguments.get("max_files") or 80)
    _indexed_codebase = build_codebase_index(root, max_files=max_files)
    file_count = _indexed_codebase["file_count"]
    return f"Error: No code error was provided. Cause: ShipMBLang indexed {file_count} source files under `{root}` for editor context. Fix: Call `printurf` with a raw error and relevant file or code context."


def _tool_list_device_families(arguments: dict[str, Any]) -> str:
    family = arguments.get("family")
    if str(arguments.get("format") or "text") == "json":
        payload = require_device_family(str(family)) if family else list_device_families()
        return json.dumps(payload, indent=2)
    return format_device_family_library(str(family)) if family else format_device_family_library()


def _tool_select_device_family(arguments: dict[str, Any]) -> str:
    global _active_device_family
    family = require_device_family(str(arguments.get("family") or ""))
    _active_device_family = family["name"]
    if str(arguments.get("format") or "text") == "json":
        return json.dumps(family, indent=2)
    return format_device_family_library(_active_device_family)


def _tool_get_device_resource(arguments: dict[str, Any]) -> str:
    family = str(arguments.get("family") or _active_device_family)
    resource = str(arguments.get("resource") or "")
    if str(arguments.get("format") or "text") == "json":
        from .device_families import require_device_resource

        return json.dumps(require_device_resource(family, resource), indent=2)
    return format_device_resource(family, resource)


def _device_resources() -> list[dict[str, Any]]:
    active = require_device_family(_active_device_family)
    resources = [
        {
            "uri": "shipmblang://device-families",
            "name": "Device family libraries",
            "description": "All ShipMBLang device families and their resource surfaces.",
            "mimeType": "text/plain",
        },
        {
            "uri": "shipmblang://active-device",
            "name": f"Active device: {active['display_name']}",
            "description": active["description"],
            "mimeType": "text/plain",
        },
    ]
    for family in list_device_families():
        resources.append(
            {
                "uri": f"shipmblang://device-family/{family['name']}",
                "name": f"Device family: {family['display_name']}",
                "description": family["description"],
                "mimeType": "text/plain",
            }
        )
    for resource in active["resources"]:
        resources.append(
            {
                "uri": f"shipmblang://device-family/{active['name']}/resource/{resource['name']}",
                "name": f"{active['display_name']} resource: {resource['name']}",
                "description": resource["description"],
                "mimeType": "text/plain",
            }
        )
    return resources


def _read_device_resource(uri: str) -> dict[str, str] | None:
    if uri in {"shipmblang://device-families", "shipmb://device-families", "shiplang://device-families"}:
        return {"uri": "shipmblang://device-families", "mimeType": "text/plain", "text": format_device_family_library()}
    if uri in {"shipmblang://active-device", "shipmb://active-device", "shiplang://active-device"}:
        return {
            "uri": "shipmblang://active-device",
            "mimeType": "text/plain",
            "text": format_device_family_library(_active_device_family),
        }
    prefix = "shipmblang://device-family/"
    if not uri.startswith(prefix):
        return None
    path = uri[len(prefix) :].strip("/")
    if not path:
        return None
    parts = path.split("/")
    if len(parts) == 1:
        family = require_device_family(parts[0])
        return {
            "uri": f"shipmblang://device-family/{family['name']}",
            "mimeType": "text/plain",
            "text": format_device_family_library(family["name"]),
        }
    if len(parts) == 3 and parts[1] == "resource":
        family = require_device_family(parts[0])
        return {
            "uri": f"shipmblang://device-family/{family['name']}/resource/{parts[2]}",
            "mimeType": "text/plain",
            "text": format_device_resource(family["name"], parts[2]),
        }
    return None


def _load_engine():
    global _engine
    if _engine is not None:
        return _engine

    checkpoint = os.environ.get("SHIPLANG_CHECKPOINT") or os.environ.get("DRIP_CHECKPOINT", "checkpoints/best_model.pt")
    tokenizer = os.environ.get("SHIPLANG_TOKENIZER") or os.environ.get("DRIP_TOKENIZER", "data/tokenizer.json")
    device = os.environ.get("SHIPLANG_DEVICE") or os.environ.get("DRIP_DEVICE", "cpu")
    if not Path(checkpoint).exists() or not Path(tokenizer).exists():
        return None

    try:
        from .inference import DripInference

        with redirect_stdout(io.StringIO()):
            _engine = DripInference(checkpoint, tokenizer, device)
        return _engine
    except Exception as exc:
        print(f"ShipMBLang: failed to load local model engine: {exc}", file=sys.stderr)
        return None


def _error_response(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


if __name__ == "__main__":
    main()
