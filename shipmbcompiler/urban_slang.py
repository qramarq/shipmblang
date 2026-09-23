from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .thesaurus import CANONICAL_TRIGGERS


MAX_URBAN_TERMS = 50
MAX_URBAN_TERM_CHARS = 128
MAX_MCP_TIMEOUT_SECONDS = 60.0
MAX_MCP_RESPONSE_BYTES = 1_000_000


@dataclass(frozen=True)
class UrbanDefinition:
    rank: int
    defid: int
    word: str
    definition: str
    example: str
    author: str
    permalink: str
    thumbs_up: int
    thumbs_down: int
    score: int
    written_on: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UrbanDefinition":
        return cls(
            rank=_int_value(data.get("rank")),
            defid=_int_value(data.get("defid")),
            word=str(data.get("word") or ""),
            definition=str(data.get("definition") or ""),
            example=str(data.get("example") or ""),
            author=str(data.get("author") or ""),
            permalink=str(data.get("permalink") or ""),
            thumbs_up=_int_value(data.get("thumbs_up")),
            thumbs_down=_int_value(data.get("thumbs_down")),
            score=_int_value(data.get("score")),
            written_on=str(data.get("written_on") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "defid": self.defid,
            "word": self.word,
            "definition": self.definition,
            "example": self.example,
            "author": self.author,
            "permalink": self.permalink,
            "thumbs_up": self.thumbs_up,
            "thumbs_down": self.thumbs_down,
            "score": self.score,
            "written_on": self.written_on,
        }


class MCPClientError(RuntimeError):
    pass


class UrbanDictionaryMCPClient:
    def __init__(
        self,
        server_path: str | Path | None = None,
        node_command: str = "node",
        timeout_seconds: float = 20.0,
    ) -> None:
        if server_path is None:
            raise ValueError("An explicit, trusted Urban Dictionary MCP server path is required.")
        path = Path(server_path).expanduser().resolve(strict=True)
        if not path.is_file():
            raise ValueError(f"Urban Dictionary MCP server must be a regular file: {path}")
        if not node_command or "\x00" in node_command:
            raise ValueError("node_command must be a non-empty executable path or command name.")
        if not 0 < timeout_seconds <= MAX_MCP_TIMEOUT_SECONDS:
            raise ValueError(f"timeout_seconds must be between 0 and {MAX_MCP_TIMEOUT_SECONDS:g}.")
        self.server_path = str(path)
        self.node_command = node_command
        self.timeout_seconds = timeout_seconds
        self._next_id = 1
        self._process: subprocess.Popen[bytes] | None = None

    def __enter__(self) -> "UrbanDictionaryMCPClient":
        self.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def start(self) -> None:
        if self._process is not None:
            return
        self._process = subprocess.Popen(
            [self.node_command, self.server_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=str(pathlib_parent(self.server_path)),
            env=_restricted_subprocess_env(),
        )
        self.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "shipmbcompiler", "version": "0.1.0"},
            },
        )

    def close(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        if process.stdin:
            process.stdin.close()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        process = self._require_process()
        request_id = self._next_id
        self._next_id += 1
        message = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        assert process.stdin is not None
        process.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
        process.stdin.flush()

        while True:
            line = self._readline()
            if not line:
                raise MCPClientError("Urban Dictionary MCP server exited before replying.")
            response = json.loads(line)
            if response.get("id") != request_id:
                continue
            if "error" in response:
                error = response["error"]
                raise MCPClientError(str(error.get("message") or error))
            result = response.get("result")
            return result if isinstance(result, dict) else {}

    def define(self, term: str, limit: int = 3, sort_by: str = "top") -> list[UrbanDefinition]:
        if not 1 <= limit <= 10:
            raise ValueError("Urban Dictionary definition limit must be between 1 and 10.")
        if sort_by not in {"top", "recent", "api"}:
            raise ValueError("Urban Dictionary sort order must be top, recent, or api.")
        result = self.request(
            "tools/call",
            {
                "name": "urban_dictionary_define",
                "arguments": {"term": term, "limit": limit, "sort_by": sort_by},
            },
        )
        if result.get("isError"):
            content = result.get("content") or []
            message = content[0].get("text") if content and isinstance(content[0], dict) else "Urban Dictionary lookup failed"
            raise MCPClientError(str(message))
        structured = result.get("structuredContent") or {}
        definitions = structured.get("definitions") or []
        if not isinstance(definitions, list):
            return []
        return [UrbanDefinition.from_dict(item) for item in definitions if isinstance(item, dict)]

    def _require_process(self) -> subprocess.Popen[bytes]:
        if self._process is None:
            raise MCPClientError("Urban Dictionary MCP client has not been started.")
        if self._process.poll() is not None:
            raise MCPClientError("Urban Dictionary MCP server is not running.")
        return self._process

    def _readline(self) -> str:
        process = self._require_process()
        assert process.stdout is not None
        lines: queue.Queue[bytes] = queue.Queue(maxsize=1)

        def read_line() -> None:
            lines.put(process.stdout.readline(MAX_MCP_RESPONSE_BYTES + 1))

        thread = threading.Thread(target=read_line, daemon=True)
        thread.start()
        try:
            raw_line = lines.get(timeout=self.timeout_seconds)
        except queue.Empty as error:
            process.terminate()
            raise MCPClientError(f"Urban Dictionary MCP server did not reply within {self.timeout_seconds:g}s.") from error
        if len(raw_line) > MAX_MCP_RESPONSE_BYTES:
            process.terminate()
            raise MCPClientError(f"Urban Dictionary MCP response exceeds the {MAX_MCP_RESPONSE_BYTES}-byte limit.")
        try:
            return raw_line.decode("utf-8")
        except UnicodeDecodeError as error:
            raise MCPClientError("Urban Dictionary MCP server returned non-UTF-8 output.") from error


def parse_terms(raw_terms: str | list[str]) -> list[str]:
    values = [raw_terms] if isinstance(raw_terms, str) else raw_terms
    terms: list[str] = []
    for value in values:
        for term in str(value).split(","):
            normalized = _normalize_term(term)
            if normalized and normalized not in terms:
                if len(normalized) > MAX_URBAN_TERM_CHARS:
                    raise ValueError(f"Urban Dictionary term exceeds the {MAX_URBAN_TERM_CHARS}-character limit.")
                terms.append(normalized)
                if len(terms) > MAX_URBAN_TERMS:
                    raise ValueError(f"At most {MAX_URBAN_TERMS} Urban Dictionary terms may be synced at once.")
    return terms


def parse_maps(raw_maps: list[str] | None) -> dict[str, str]:
    maps: dict[str, str] = {}
    for raw_map in raw_maps or []:
        if "=" not in raw_map:
            raise ValueError(f"Map entry must use term=canonical syntax: {raw_map!r}")
        term, canonical = raw_map.split("=", 1)
        term = _normalize_term(term)
        canonical = _normalize_term(canonical)
        if not term or not canonical:
            raise ValueError(f"Map entry must include both term and canonical trigger: {raw_map!r}")
        if canonical not in CANONICAL_TRIGGERS:
            allowed = ", ".join(sorted(CANONICAL_TRIGGERS))
            raise ValueError(f"Unknown canonical trigger {canonical!r}. Allowed triggers: {allowed}")
        maps[term] = canonical
    return maps


def sync_urban_slang(
    terms: list[str],
    term_maps: dict[str, str],
    server_path: str | Path | None = None,
    limit: int = 3,
    sort_by: str = "top",
    node_command: str = "node",
) -> dict[str, Any]:
    terms = parse_terms(terms)
    normalized_maps = {parse_terms(key)[0]: value for key, value in term_maps.items() if parse_terms(key)}
    for canonical in normalized_maps.values():
        if canonical not in CANONICAL_TRIGGERS:
            raise ValueError(f"Unknown canonical trigger {canonical!r}.")

    entries: dict[str, dict[str, Any]] = {}
    candidates: list[dict[str, Any]] = []
    with UrbanDictionaryMCPClient(server_path, node_command=node_command) as client:
        for term in terms:
            definitions = client.define(term, limit=limit, sort_by=sort_by)
            canonical = normalized_maps.get(term)
            candidate = _candidate_entry(term, canonical, definitions)
            candidates.append(candidate)
            if canonical:
                entry = entries.setdefault(canonical, {"synonyms": [], "definitions": []})
                if term not in entry["synonyms"]:
                    entry["synonyms"].append(term)
                for definition in definitions:
                    summary = _definition_summary(definition)
                    if summary and summary not in entry["definitions"]:
                        entry["definitions"].append(summary)

    return {
        "shipmb_thesaurus_version": 1,
        "generated_by": "shipmbc slang sync",
        "source": {
            "type": "urban_dictionary_mcp",
            "server": str(server_path),
            "tool": "urban_dictionary_define",
            "review_required": True,
            "offline_compile": True,
            "note": "Only terms explicitly mapped to known canonical triggers are active compiler synonyms.",
        },
        "triggers": entries,
        "urban_dictionary_candidates": candidates,
    }


def write_slang_thesaurus(data: dict[str, Any], out_path: str | Path) -> None:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _candidate_entry(term: str, canonical: str | None, definitions: list[UrbanDefinition]) -> dict[str, Any]:
    return {
        "term": term,
        "mapped_to": canonical,
        "active": canonical is not None,
        "review_status": "mapped" if canonical else "candidate_unreviewed",
        "definitions": [definition.to_dict() for definition in definitions],
    }


def _definition_summary(definition: UrbanDefinition) -> str:
    text = " ".join(definition.definition.split())
    if len(text) > 180:
        text = text[:177].rstrip() + "..."
    parts = [f"Urban Dictionary defid {definition.defid}", f"score {definition.score}"]
    if definition.permalink:
        parts.append(definition.permalink)
    return f"{' | '.join(parts)}: {text}" if text else " | ".join(parts)


def _normalize_term(term: str) -> str:
    return " ".join(term.lower().replace("_", " ").split())


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def pathlib_parent(path: str) -> Path:
    return Path(path).parent


def _restricted_subprocess_env() -> dict[str, str]:
    """Pass only OS variables needed to find and start the chosen local server."""
    allowed = ("PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP")
    return {key: value for key in allowed if (value := os.environ.get(key)) is not None}
