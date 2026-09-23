"""Opt-in English syntax -> bytecode compiler. No Core or IR dependency."""
from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy

from .english import CATALOG_VERSION, GRAMMAR_VERSION, parse_english, diagnostic
from .limits import MAX_SOURCE_CHARS
from .memory_support import open_memory, project_context
from .clarification import revision, apply_answers

COMPILER_VERSION = "0.5.0"
_DEFAULT_MODEL = object()


def _nodes(tree):
    for sentence in tree["children"]:
        yield from sentence["children"]


def emit_direct(tree):
    """Walk resolved syntax directly; this list is the FINAL target bytecode."""
    bytecode = []
    seen = set()
    capabilities = []

    def emit(opcode, operands, node=None, *, declaration=False):
        key = (opcode, json.dumps(operands, sort_keys=True))
        if declaration and key in seen:
            return
        seen.add(key)
        if node and node["fields"].get("guard") == "if_able":
            operands = {"guard": "if_able", "action": {"opcode": opcode, "operands": operands}}
            opcode = "guarded_action"
        bytecode.append({"pc": len(bytecode), "opcode": opcode, "operands": operands,
                         "source_span": node["span"] if node else {"start": 0, "end": 0}})

    emit("use_prelude", {"name": "shipmb", "generated": True})
    # Declarations precede effects, but all executable requests retain source order.
    for kind in ("LibraryRequest", "DeviceReference", "CapabilityRequest", "CommandRequest", "ErrorHandler"):
        for node in _nodes(tree):
            if node["kind"] != kind:
                continue
            fields = node["fields"]
            if kind == "LibraryRequest":
                emit("import_library", {"name": fields["name"], "source": fields["source"]}, declaration=True)
            elif kind == "DeviceReference":
                emit("device_target", {"name": "tv", "platform": "roku", "alias": "tv"}, declaration=True)
            elif kind in {"CapabilityRequest", "CommandRequest"}:
                args = {"target": "remote", "name": fields["name"], "agentic": bool(fields.get("agentic"))}
                emit("declare_capability", args, declaration=True)
                if args not in capabilities:
                    capabilities.append(args)
            else:
                emit("on_error", {"condition": "command_failure", "pipeline": fields["pipeline"]}, declaration=True)
    for node in _nodes(tree):
        kind, fields = node["kind"], node["fields"]
        if kind == "CommandRequest":
            emit("run", {"target": "remote", "command": fields["command"]}, node)
        elif kind == "InstallationRequest":
            emit("install_package", {"package": fields["package"], "target": fields["target"]}, node)
        elif kind == "InterfaceRequest":
            emit("declare_interface", {"name": fields["name"], "mode": "client"}, node)
    return {
        "producer": "shipmbcompiler", "target": "shipmblang-bytecode", "version": "0.2",
        "native_machine_code": False, "bytecode": bytecode,
        "debug": {"producer": "shipmbcompiler", "pipeline": "direct", "grammar": GRAMMAR_VERSION},
        "runtime_contract": {"capability_context": {"declared": capabilities, "source": "compiled_declarations"}},
    }


def compile_direct_program(source, *, memory=True, memory_path=None, project=None, bindings=None,
                           clarification_answers=None, model_provider=_DEFAULT_MODEL, profile="general",
                           accept_model_interpretation=True, ffmpeg_catalog=None):
    """Compile known English, or return structured clarification/unsupported status.

Answers use {'interpretation': '<clarified English>'}. Model callbacks propose
{'paraphrase': '<English>'}, {'question': '<question>'}, or
{'unsupported': '<reason>'}. Validated proposals compile by default; set
accept_model_interpretation=False to review them first. This permits compilation, not
execution, and does not confirm the model's meaning in persistent memory.
Confirmed paraphrases are parsed and validated again, never treated as code.
"""
    if not isinstance(source, str):
        raise TypeError("source must be a string")
    if profile not in {"roku", "general"}:
        raise ValueError("Direct profile must be roku or general.")
    if model_provider is _DEFAULT_MODEL:
        if os.environ.get("SHIPMB_MODEL_PROVIDER", "none").strip().lower() in {"", "none", "disabled"}:
            model_provider = None
        else:
            def model_provider(source):
                from .english_model import load_english_model
                provider = load_english_model(profile, **({'ffmpeg_catalog': ffmpeg_catalog} if ffmpeg_catalog is not None else {}))
                if provider is None:
                    raise ValueError("English model configuration is unavailable.")
                return provider(source)
    parse = parse_english
    grammar, catalog = GRAMMAR_VERSION, CATALOG_VERSION
    if profile == "general":
        from .general_english import parse_general, GRAMMAR_VERSION as grammar, CATALOG_VERSION as catalog
        parse = parse_general
    context = {"project": project_context(project), "bindings": bindings or {}}
    if profile != "roku":
        context["profile"] = profile
    from .general_vocabulary import VOCABULARY_VERSION
    versions = {"compiler": COMPILER_VERSION, "grammar": grammar,
                "catalog": catalog, "vocabulary": VOCABULARY_VERSION if profile == "general" else "contextual-builtin-1"}
    result = {"source": source, "source_revision": revision(source), "pipeline": "direct", "profile": profile, "status": "unsupported", "core_source": None,
              "target_code": None, "diagnostics": [], "clarifications": [],
              "tokens": [], "syntax_tree": None, "symbols": {}, "memory": {"enabled": False}}
    store = None
    try:
        store = open_memory(memory, memory_path)
        result["memory"]["enabled"] = store is not None
    except Exception as error:
        result["diagnostics"].append(diagnostic("SMBM001", f"Memory unavailable: {error}", 0, 0, level="warning"))
    try:
        if len(source) > MAX_SOURCE_CHARS:
            result["diagnostics"].append(diagnostic("SMBD107", "Source exceeds the supported input limit.", 0, len(source)))
            return _save(store, result, context, versions)
        confirmed = store.lookup_confirmed(source, context, versions, project=context["project"]) if store else []
        related = store.lookup_related(source, context, project=context["project"]) if store else []
        candidates = store.lookup_candidates(source, context, versions, project=context["project"]) if store else []
        interpretations = {json.dumps(row["meaning"], sort_keys=True) for row in confirmed}
        answer = (clarification_answers or {}).get("interpretation")
        if clarification_answers and "answers" in clarification_answers:
            if answer is not None:
                raise ValueError("Supply either a whole interpretation or focused answers, not both.")
            _, _, _, _, source_questions = parse(source, bindings)
            answer, provenance = apply_answers(source, source_questions, clarification_answers)
            result["clarification_provenance"] = provenance
        if answer is not None and (not isinstance(answer, str) or not answer.strip() or len(answer) > MAX_SOURCE_CHARS):
            raise ValueError("The interpretation answer must be nonempty English within the source limit.")
        resolved_source = answer or source
        stale = [row for row in related if row["status"] == "confirmed" and row["versions"] != versions]
        if not answer and (stale or (candidates and not confirmed and not (model_provider and accept_model_interpretation))):
            suggestions = []
            for row in stale or candidates:
                meaning = row["meaning"]
                if isinstance(meaning, dict) and isinstance(meaning.get("clarified_source"), str):
                    if meaning["clarified_source"] not in suggestions:
                        suggestions.append(meaning["clarified_source"])
            result["status"] = "needs_clarification"
            result["clarifications"] = [{"id": "memory-interpretation", "question": "A remembered interpretation needs confirmation for this source and compiler version. Restate or select the intended program.", "choices": suggestions, "span": {"start": 0, "end": len(source)}}]
            return _save(store, result, context, versions)
        if not answer and len(interpretations) > 1:
            result["status"] = "needs_clarification"
            result["clarifications"] = [{"id": "memory-conflict", "question": "Confirmed meanings conflict. Restate the intended program.", "choices": [], "span": {"start": 0, "end": len(source)}}]
            return _save(store, result, context, versions)
        if not answer and len(interpretations) == 1:
            meaning = json.loads(next(iter(interpretations)))
            if not isinstance(meaning, dict) or not isinstance(meaning.get("clarified_source"), str):
                raise ValueError("Remembered meaning has an unsupported format; clarification is required.")
            resolved_source = meaning["clarified_source"]
            result["memory"]["reused_confirmed"] = True
        if resolved_source != source:
            result["interpretation_source"] = resolved_source
            result["interpretation_revision"] = revision(resolved_source)
        key_data = {"source": resolved_source, "original_source": source, "context": context,
                    "versions": versions, "pipeline": "direct",
                    "confirmed": [(r["id"], r["revision"]) for r in confirmed],
                    "memory_revision": store.memory_revision(context["project"], context) if store else None}
        key = hashlib.sha256(json.dumps(key_data, sort_keys=True).encode()).hexdigest()
        cached = store.get_cache(key) if store else None
        if isinstance(cached, dict) and cached.get("source") == resolved_source and cached.get("checksum") == hashlib.sha256(json.dumps(cached.get("parsed"), sort_keys=True).encode()).hexdigest():
            # The cache contains only lexical/syntax results, never runnable code.
            parsed = cached["parsed"]
            result["memory"]["cache_hit"] = True
        else:
            parsed = parse(resolved_source, bindings)
            if store:
                checksum = hashlib.sha256(json.dumps(parsed, sort_keys=True).encode()).hexdigest()
                store.put_cache(key, {"source": resolved_source, "parsed": parsed, "checksum": checksum})
            result["memory"]["cache_hit"] = False
        tokens, tree, symbols, errors, questions = deepcopy(parsed)
        result.update(tokens=tokens, syntax_tree=tree, symbols=symbols, clarifications=questions)
        result["diagnostics"].extend(errors)
        result["status"] = "unsupported" if errors else "needs_clarification" if questions else "compiled"
        if result["status"] != "compiled" and model_provider is not None and not answer:
            # A provider is a proposal source, not a compiler or execution authority.
            from .english_model import validate_proposal
            proposal = validate_proposal(model_provider(resolved_source))
            if "question" in proposal:
                result["status"] = "needs_clarification"
                result["diagnostics"] = [d for d in result["diagnostics"] if d["level"] != "error"]
                result["clarifications"] = [{"id": "model-question", "question": proposal["question"],
                                            "choices": [], "span": {"start": 0, "end": len(source)}}]
                return _save(store, result, context, versions)
            if "unsupported" in proposal:
                result["status"] = "unsupported"
                result["clarifications"] = []
                result["diagnostics"].append(diagnostic("SMBD110", proposal["unsupported"], 0, len(source)))
                return _save(store, result, context, versions)
            paraphrase = proposal["paraphrase"]
            proposal_tokens, proposal_tree, proposal_symbols, proposal_errors, proposal_questions = parse(paraphrase, bindings)
            if proposal_errors or proposal_questions:
                result["diagnostics"].append(diagnostic("SMBD108", "Model proposal failed deterministic validation.", 0, len(source)))
            else:
                result["diagnostics"] = [d for d in result["diagnostics"] if d["level"] != "error"]
                result["status"] = "needs_clarification"
                result["clarifications"] = [{"id": "model-interpretation", "question": "Does this interpretation express your intended program?", "choices": [paraphrase], "span": {"start": 0, "end": len(source)}}]
                result["candidate_interpretation"] = {"clarified_source": paraphrase}
                if accept_model_interpretation:
                    resolved_source = paraphrase
                    tree, symbols = proposal_tree, proposal_symbols
                    result.update(status="compiled", tokens=proposal_tokens, syntax_tree=tree,
                                  symbols=symbols, clarifications=[], interpretation_source=paraphrase,
                                  interpretation_revision=revision(paraphrase),
                                  interpretation_origin="model")
        if result["status"] == "compiled":
            if profile == "general":
                from .general_codegen import emit_general, GeneralLimitError
                try:
                    result["target_code"] = emit_general(tree, symbols)
                except GeneralLimitError as error:
                    result["status"] = "unsupported"
                    result["diagnostics"].append(diagnostic("SMBG103", str(error), 0, len(resolved_source)))
            else:
                result["target_code"] = emit_direct(tree)
        return _save(store, result, context, versions, answer=answer)
    except Exception as error:
        # Memory/model failures do not result in a guessed or stale runnable program.
        result["target_code"] = None
        result["status"] = "needs_clarification"
        result["diagnostics"].append(diagnostic("SMBD109", f"Interpretation could not be validated: {error}", 0, len(source)))
        result["clarifications"] = [{"id": "interpretation", "question": "Please restate the intended program explicitly.", "choices": [], "span": {"start": 0, "end": len(source)}}]
        return _save(store, result, context, versions)


def _save(store, result, context, versions, *, answer=None):
    if store is None:
        return result
    try:
        submission = store.record_submission(result["source"], context["project"], "direct", result)
        result["memory"]["submission_id"] = submission
        for question in result.get("clarifications", []):
            store.record_clarification(submission, question["question"], "")
        meaning = {"clarified_source": answer} if answer else result.get("candidate_interpretation")
        if meaning:
            candidate = store.add_candidate(submission, meaning, context, versions)
            result["memory"]["interpretation_id"] = candidate
            if answer and result["status"] == "compiled":
                store.confirm(candidate, "user clarification", replace_existing=True)
                store.record_clarification(submission, "Restate the intended program", answer, interpretation_id=candidate)
    except Exception as error:
        result["diagnostics"].append(diagnostic("SMBM001", f"Memory persistence failed: {error}", 0, 0, level="warning"))
    return result
