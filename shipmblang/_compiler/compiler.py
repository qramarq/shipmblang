from __future__ import annotations

from typing import Any

from .source_format import looks_like_core
from .diagnostics import printurf
from .ir import intermediate_code_generation
from .lexer import lexical_analysis
from .limits import MAX_SOURCE_CHARS
from .models import Diagnostic, Span
from .optimizer import code_optimization
from .parser import explain_syntax_errors, syntax_analysis
from .semantics import semantic_analysis
from .target import target_code_generation
from .thesaurus import TriggerLexicon, default_lexicon


def compile_source(
    source: str,
    target: str = "bytecode",
    run: bool = False,
    wordnet_dir: str | None = None,
    thesaurus_path: str | None = None,
    lexicon: TriggerLexicon | None = None,
    *,
    include_core: bool = True,
    memory: bool = True,
    memory_path: str | None = None,
    project: str | None = None,
) -> dict[str, Any]:
    from .memory_support import capture_submission
    try:
        result = _compile_source(source, target, run, wordnet_dir, thesaurus_path, lexicon, include_core=include_core)
    except Exception as error:
        if isinstance(source, str):
            failed = {"status": "failed", "diagnostics": [{"level": "error", "message": str(error)}]}
            capture_submission(source, failed, pipeline="ir", memory=memory, memory_path=memory_path, project=project)
        raise
    capture_submission(source, result, pipeline="ir", memory=memory, memory_path=memory_path, project=project)
    return result


def _compile_source(source, target, run, wordnet_dir, thesaurus_path, lexicon, *, include_core):
    """Compile source; omit optional Core export with include_core=False.

    Core input still loads its parser. Execution is opt-in and loads the runtime
    only after compilation succeeds. The default result remains compatible.
    """
    if not isinstance(source, str):
        raise TypeError("source must be a string")
    if len(source) > MAX_SOURCE_CHARS:
        raise ValueError(f"Source input exceeds the {MAX_SOURCE_CHARS}-character limit.")
    active_lexicon = lexicon or default_lexicon(wordnet_dir, thesaurus_path)
    tokens, lexical_diagnostics = lexical_analysis(source, active_lexicon)
    core_source = None
    if looks_like_core(source):
        from .core import core_syntax_analysis

        syntax_tree, syntax_diagnostics = core_syntax_analysis(source)
        if include_core:
            core_source = source.strip()
    else:
        syntax_tree, syntax_diagnostics = syntax_analysis(source, tokens, active_lexicon)
        if include_core:
            from .core import core_lowering

            core_source = core_lowering(syntax_tree)
    semantic_model = semantic_analysis(syntax_tree)
    ir = intermediate_code_generation(semantic_model)
    optimized_ir = code_optimization(ir)
    bytecode, target_diagnostics = target_code_generation(optimized_ir, target)
    runtime = None
    runtime_diagnostics = []
    compile_errors = any(diagnostic.level == "error" for diagnostic in [
        *lexical_diagnostics,
        *syntax_diagnostics,
        *semantic_model.diagnostics,
        *target_diagnostics,
    ])
    if run and not compile_errors:
        from .runtime import run_bytecode

        runtime, runtime_diagnostics = run_bytecode(bytecode)
    elif run:
        runtime_diagnostics.append(
            Diagnostic(
                "error",
                "SMB6004",
                "Runtime execution was skipped because compilation produced errors.",
                Span(0, 0),
                "Fix all compilation errors before requesting runtime execution.",
            )
        )

    diagnostics = [
        *lexical_diagnostics,
        *syntax_diagnostics,
        *semantic_model.diagnostics,
        *target_diagnostics,
        *runtime_diagnostics,
    ]
    diagnostics = _unique_diagnostics(diagnostics)
    return {
        "tokens": [token.to_dict() for token in tokens],
        "syntax_tree": syntax_tree.to_dict(),
        "syntax_explanations": explain_syntax_errors(syntax_tree, source),
        "core_source": core_source,
        "semantic_model": semantic_model.to_dict(),
        "intermediate_code": [op.to_dict() for op in ir],
        "optimized_code": [op.to_dict() for op in optimized_ir],
        "target_code": bytecode.to_dict(),
        "runtime": runtime,
        "trigger_lexicon": {
            "source": active_lexicon.source,
            "offline": True,
            "wordnet_loaded": "wordnet:" in active_lexicon.source,
            "extra_thesaurus_loaded": "thesaurus:" in active_lexicon.source,
            "thesaurus_entries": sum(len(words) for words in active_lexicon.synonyms.values()),
            "dictionary_entries": sum(len(definitions) for definitions in active_lexicon.definitions.values()),
        },
        "diagnostics": [diagnostic.to_dict() for diagnostic in diagnostics],
        "printurf": [printurf(diagnostic, source) for diagnostic in diagnostics],
    }


def _unique_diagnostics(diagnostics):
    seen = set()
    unique = []
    for diagnostic in diagnostics:
        key = (diagnostic.level, diagnostic.code, diagnostic.message, diagnostic.span.start, diagnostic.span.end)
        if key in seen:
            continue
        seen.add(key)
        unique.append(diagnostic)
    return unique
