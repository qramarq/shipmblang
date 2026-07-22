"""ShipMBLang implementation package.

The public import path is ``shipmblang``. This package name remains as the
backing implementation module for compatibility.
"""

from .error_explainer import (
    build_error_prompt,
    build_printurf_report,
    drip_printf,
    explain_error,
    format_editor_context,
    printurf,
    render_printurf_report,
    synthesize_error_explanation,
)
from .device_families import (
    format_device_family_library,
    format_device_resource,
    get_device_family,
    get_device_resource,
    list_device_families,
    list_device_resources,
)
from .natural_syntax import (
    code_optimization,
    compile_natural_program,
    intermediate_code_generation,
    lexical_analysis,
    render_core_program,
    run_natural_program,
    semantic_analysis,
    syntax_analysis,
    target_code_generation,
)
from .onboarding import build_onboarding_manifest, run_onboarding_checks

drip = drip_printf

__version__ = "0.1.0"


def __getattr__(name):
    """Load training/model symbols only when callers actually need torch."""
    if name in {"DripConfig", "TrainConfig"}:
        from .config import DripConfig, TrainConfig

        return {"DripConfig": DripConfig, "TrainConfig": TrainConfig}[name]
    if name == "DripLM":
        from .model import DripLM

        return DripLM
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "__version__",
    "build_error_prompt",
    "build_onboarding_manifest",
    "build_printurf_report",
    "code_optimization",
    "compile_natural_program",
    "drip",
    "drip_printf",
    "explain_error",
    "format_device_family_library",
    "format_device_resource",
    "format_editor_context",
    "get_device_family",
    "get_device_resource",
    "list_device_families",
    "list_device_resources",
    "lexical_analysis",
    "intermediate_code_generation",
    "printurf",
    "render_printurf_report",
    "render_core_program",
    "semantic_analysis",
    "synthesize_error_explanation",
    "syntax_analysis",
    "target_code_generation",
    "run_natural_program",
    "run_onboarding_checks",
]
