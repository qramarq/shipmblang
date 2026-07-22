"""ShipMBLang natural syntax compiler wrapper."""

from driplm.natural_syntax import *  # noqa: F401,F403
from driplm.natural_syntax import (
    code_optimization,
    intermediate_code_generation,
    lexical_analysis,
    main,
    run_main,
    semantic_analysis,
    syntax_analysis,
    target_code_generation,
)

__all__ = [
    "code_optimization",
    "intermediate_code_generation",
    "lexical_analysis",
    "main",
    "run_main",
    "semantic_analysis",
    "syntax_analysis",
    "target_code_generation",
]
