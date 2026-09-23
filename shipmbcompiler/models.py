from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Span:
    start: int
    end: int

    def to_dict(self) -> dict[str, int]:
        return {"start": self.start, "end": self.end}


@dataclass
class Diagnostic:
    level: str
    code: str
    message: str
    span: Span
    help: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "span": self.span.to_dict(),
        }
        if self.help:
            data["help"] = self.help
        return data


@dataclass
class Token:
    kind: str
    lexeme: str
    normalized: str
    span: Span
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "lexeme": self.lexeme,
            "normalized": self.normalized,
            "span": self.span.to_dict(),
            "confidence": self.confidence,
        }


@dataclass
class SyntaxNode:
    kind: str
    span: Span
    surface_text: str
    roles: dict[str, Any] = field(default_factory=dict)
    children: list["SyntaxNode"] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def yield_text(self) -> str:
        if self.children:
            return " ".join(child.surface_text for child in self.children).strip()
        return self.surface_text

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "span": self.span.to_dict(),
            "surface_text": self.surface_text,
            "roles": self.roles,
            "children": [child.to_dict() for child in self.children],
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
        }


@dataclass
class Symbol:
    name: str
    kind: str
    type: str
    span: Span
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "type": self.type,
            "span": self.span.to_dict(),
            "metadata": self.metadata,
        }


@dataclass
class SemanticOp:
    op: str
    args: dict[str, Any]
    span: Span
    type: str = "Any"
    effects: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "op": self.op,
            "args": self.args,
            "span": self.span.to_dict(),
            "type": self.type,
            "effects": self.effects,
        }


@dataclass
class SemanticModel:
    symbols: dict[str, Symbol] = field(default_factory=dict)
    types: dict[str, str] = field(default_factory=dict)
    effects: list[str] = field(default_factory=list)
    ownership: dict[str, str] = field(default_factory=dict)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    ops: list[SemanticOp] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbols": {name: symbol.to_dict() for name, symbol in self.symbols.items()},
            "types": self.types,
            "effects": self.effects,
            "ownership": self.ownership,
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "ops": [op.to_dict() for op in self.ops],
        }


@dataclass
class IROp:
    ir: str
    op: str
    result: str | None
    arg1: str | None
    arg2: str | None
    args: dict[str, Any]
    type: str
    effects: list[str]
    span: Span

    def to_dict(self) -> dict[str, Any]:
        return {
            "ir": self.ir,
            "op": self.op,
            "result": self.result,
            "arg1": self.arg1,
            "arg2": self.arg2,
            "args": self.args,
            "type": self.type,
            "effects": self.effects,
            "span": self.span.to_dict(),
        }


@dataclass
class BytecodeProgram:
    target: str
    version: str
    native_machine_code: bool
    bytecode: list[dict[str, Any]]
    debug: dict[str, Any] = field(default_factory=dict)
    runtime_contract: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "version": self.version,
            "native_machine_code": self.native_machine_code,
            "bytecode": self.bytecode,
            "runtime_contract": self.runtime_contract,
            "debug": self.debug,
        }
