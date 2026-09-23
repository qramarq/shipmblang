"""ShipMBLang prose compiler package."""

__all__ = ["compile_source", "compile_direct_program", "TriggerLexicon"]


def __getattr__(name):
    # Importing the direct compiler must not import the legacy IR pipeline.
    if name == "compile_source":
        from .compiler import compile_source
        return compile_source
    if name == "compile_direct_program":
        from .direct import compile_direct_program
        return compile_direct_program
    if name == "TriggerLexicon":
        from .thesaurus import TriggerLexicon
        return TriggerLexicon
    raise AttributeError(name)
