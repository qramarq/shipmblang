'ShipMBLang implementation package.\n\nThe public import path is ``shipmblang``. This package name remains as the\nbacking implementation module for compatibility.'

from importlib import import_module as _import_module

__version__ = "0.1.0"

_EXPORTS = {
    'build_error_prompt': ('.error_explainer', 'build_error_prompt'),
    'build_printurf_report': ('.error_explainer', 'build_printurf_report'),
    'drip_printf': ('.error_explainer', 'drip_printf'),
    'explain_error': ('.error_explainer', 'explain_error'),
    'format_editor_context': ('.error_explainer', 'format_editor_context'),
    'printurf': ('.error_explainer', 'printurf'),
    'render_printurf_report': ('.error_explainer', 'render_printurf_report'),
    'synthesize_error_explanation': ('.error_explainer', 'synthesize_error_explanation'),
    'format_device_family_library': ('.device_families', 'format_device_family_library'),
    'format_device_resource': ('.device_families', 'format_device_resource'),
    'get_device_family': ('.device_families', 'get_device_family'),
    'get_device_resource': ('.device_families', 'get_device_resource'),
    'list_device_families': ('.device_families', 'list_device_families'),
    'list_device_resources': ('.device_families', 'list_device_resources'),
    'code_optimization': ('.natural_syntax', 'code_optimization'),
    'compile_natural_program': ('.natural_syntax', 'compile_natural_program'),
    'intermediate_code_generation': ('.natural_syntax', 'intermediate_code_generation'),
    'lexical_analysis': ('.natural_syntax', 'lexical_analysis'),
    'render_core_program': ('.natural_syntax', 'render_core_program'),
    'run_natural_program': ('.natural_syntax', 'run_natural_program'),
    'semantic_analysis': ('.natural_syntax', 'semantic_analysis'),
    'syntax_analysis': ('.natural_syntax', 'syntax_analysis'),
    'target_code_generation': ('.natural_syntax', 'target_code_generation'),
    'build_onboarding_manifest': ('.onboarding', 'build_onboarding_manifest'),
    'run_onboarding_checks': ('.onboarding', 'run_onboarding_checks'),
    'drip': ('.error_explainer', 'drip_printf'),
    'DripConfig': ('.config', 'DripConfig'),
    'TrainConfig': ('.config', 'TrainConfig'),
    'DripLM': ('.model', 'DripLM'),
}

def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module, attribute = _EXPORTS[name]
    value = getattr(_import_module(module, __name__), attribute)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))


__all__ = [
    '__version__',
    'build_error_prompt',
    'build_onboarding_manifest',
    'build_printurf_report',
    'code_optimization',
    'compile_natural_program',
    'drip',
    'drip_printf',
    'explain_error',
    'format_device_family_library',
    'format_device_resource',
    'format_editor_context',
    'get_device_family',
    'get_device_resource',
    'list_device_families',
    'list_device_resources',
    'lexical_analysis',
    'intermediate_code_generation',
    'printurf',
    'render_printurf_report',
    'render_core_program',
    'semantic_analysis',
    'synthesize_error_explanation',
    'syntax_analysis',
    'target_code_generation',
    'run_natural_program',
    'run_onboarding_checks',
]
