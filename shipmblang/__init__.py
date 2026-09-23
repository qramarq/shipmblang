'ShipMBLang public Python API for programming ShipMB.'

from importlib import import_module as _import_module

_EXPORTS = {
    'VLCExecutor': ('._compiler.vlc', 'VLCExecutor'),
    'FFmpegExecutor': ('._compiler.ffmpeg', 'FFmpegExecutor'),
    'compile_hyperframes': ('.hyperframes', 'compile_hyperframes'),
    'write_hyperframes_project': ('.hyperframes', 'write_hyperframes_project'),
    'render_hyperframes_project': ('.hyperframes', 'render_hyperframes_project'),
    'build_printurf_report': ('driplm', 'build_printurf_report'),
    'build_onboarding_manifest': ('driplm', 'build_onboarding_manifest'),
    'code_optimization': ('driplm', 'code_optimization'),
    'compile_natural_program': ('driplm', 'compile_natural_program'),
    'drip': ('driplm', 'drip'),
    'drip_printf': ('driplm', 'drip_printf'),
    'explain_error': ('driplm', 'explain_error'),
    'format_device_family_library': ('driplm', 'format_device_family_library'),
    'format_device_resource': ('driplm', 'format_device_resource'),
    'format_editor_context': ('driplm', 'format_editor_context'),
    'get_device_family': ('driplm', 'get_device_family'),
    'get_device_resource': ('driplm', 'get_device_resource'),
    'intermediate_code_generation': ('driplm', 'intermediate_code_generation'),
    'lexical_analysis': ('driplm', 'lexical_analysis'),
    'list_device_families': ('driplm', 'list_device_families'),
    'list_device_resources': ('driplm', 'list_device_resources'),
    'printurf': ('driplm', 'printurf'),
    'render_printurf_report': ('driplm', 'render_printurf_report'),
    'render_core_program': ('driplm', 'render_core_program'),
    'run_natural_program': ('driplm', 'run_natural_program'),
    'run_onboarding_checks': ('driplm', 'run_onboarding_checks'),
    'semantic_analysis': ('driplm', 'semantic_analysis'),
    'syntax_analysis': ('driplm', 'syntax_analysis'),
    'target_code_generation': ('driplm', 'target_code_generation'),
    'compile_direct_program': ('.pipelines', 'compile_direct_program'),
    'run_direct_program': ('.pipelines', 'run_direct_program'),
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
    'VLCExecutor',
    'FFmpegExecutor',
    'compile_hyperframes',
    'write_hyperframes_project',
    'render_hyperframes_project',
    'build_printurf_report',
    'build_onboarding_manifest',
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
    'intermediate_code_generation',
    'lexical_analysis',
    'list_device_families',
    'list_device_resources',
    'printurf',
    'render_printurf_report',
    'render_core_program',
    'run_natural_program',
    'run_onboarding_checks',
    'semantic_analysis',
    'syntax_analysis',
    'target_code_generation',
    'compile_direct_program',
    'run_direct_program',
]
