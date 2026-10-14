"""Structured FFmpeg jobs and an explicit host executor (not a sandbox).

Compilation imports validation only. Discovery and subprocess execution are lazy.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time

MAX_OPERANDS = 4096
MAX_TEXT = 1000000
RESERVED = {'-i', '-y', '-n', '-stdin', '-nostdin', '-progress', '-filter_complex',
            '-filter_complex_script', '-report', '-h', '-help', '-version'}
# Only rules with unambiguous scopes/arity are encoded here. The executable is
# authoritative for its build-specific AVOptions and component compatibility.
RULES = {
    '-loglevel': ({'global'}, True), '-v': ({'global'}, True),
    '-hide_banner': ({'global'}, False), '-stats': ({'global'}, False), '-nostats': ({'global'}, False),
    '-map': ({'output'}, True), '-map_metadata': ({'output'}, True), '-map_chapters': ({'output'}, True),
    '-vf': ({'output'}, True), '-af': ({'output'}, True), '-filter': ({'output'}, True),
    '-c': ({'input', 'output'}, True), '-codec': ({'input', 'output'}, True),
    '-f': ({'input', 'output'}, True), '-ss': ({'input', 'output'}, True),
    '-t': ({'input', 'output'}, True), '-to': ({'input', 'output'}, True),
    '-r': ({'input', 'output'}, True), '-s': ({'input', 'output'}, True),
    '-b': ({'output'}, True), '-crf': ({'output'}, True), '-preset': ({'output'}, True),
    '-pix_fmt': ({'input', 'output'}, True), '-ar': ({'input', 'output'}, True),
    '-ac': ({'input', 'output'}, True), '-metadata': ({'output'}, True),
    '-vn': ({'input', 'output'}, False), '-an': ({'input', 'output'}, False),
    '-sn': ({'input', 'output'}, False), '-dn': ({'input', 'output'}, False),
    '-shortest': ({'output'}, False), '-re': ({'input'}, False),
    '-hwaccel': ({'input'}, True), '-stream_loop': ({'input'}, True),
}


def empty_job():
    return {'global_options': [], 'inputs': [], 'outputs': [], 'filtergraphs': [], 'overwrite': False}


def validate_job(job, argument_types=None):
    """Check a resolved job or a bytecode template with typed operand references."""
    if not isinstance(job, dict) or set(job) != set(empty_job()):
        raise ValueError('Invalid FFmpeg job schema.')
    if type(job['overwrite']) is not bool:
        raise ValueError('Invalid FFmpeg overwrite setting.')
    if argument_types is not None and (not isinstance(argument_types, list) or len(argument_types) > MAX_OPERANDS
            or any(t not in ('text', 'integer') for t in argument_types)):
        raise ValueError('Invalid FFmpeg operand types.')
    refs = []

    def value(item, text_only=False):
        if argument_types is not None:
            if not isinstance(item, dict) or set(item) != {'operand'} or type(item['operand']) is not int:
                raise ValueError('Invalid FFmpeg operand reference.')
            index = item['operand']
            if not 0 <= index < len(argument_types) or text_only and argument_types[index] != 'text':
                raise ValueError('Invalid FFmpeg operand type or index.')
            refs.append(index)
        elif type(item) not in ((str,) if text_only else (str, int)):
            raise ValueError('FFmpeg values must be text or integers.')
        elif '\0' in str(item) or len(str(item).encode('utf-8')) > MAX_TEXT or str(item) == '':
            raise ValueError('FFmpeg values must be nonempty bounded text without NUL bytes.')

    def options(items, scope):
        if not isinstance(items, list) or len(items) > MAX_OPERANDS:
            raise ValueError('Invalid FFmpeg option list.')
        for item in items:
            if not isinstance(item, dict) or set(item) != {'name', 'value'}:
                raise ValueError('Invalid FFmpeg option schema.')
            name = item['name']
            if not isinstance(name, str) or not re.fullmatch(r'-[A-Za-z0-9_]+(?::[^\s\x00]+)?', name) or len(name) > 256:
                raise ValueError('Use one FFmpeg option name, not a command string.')
            base = name.split(':', 1)[0]
            if base in RESERVED:
                raise ValueError(f'{base} is controlled by the FFmpeg job structure.')
            rule = RULES.get(base)
            if rule and (scope not in rule[0] or rule[1] != (item['value'] is not None)):
                raise ValueError(f'{name} has an invalid scope or requires a different argument count.')
            if item['value'] is not None:
                value(item['value'])

    options(job['global_options'], 'global')
    names = set()
    for scope in ('input', 'output'):
        entries = job[scope + 's']
        if not isinstance(entries, list) or len(entries) > MAX_OPERANDS:
            raise ValueError('Invalid FFmpeg input/output list.')
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {'name', 'url', 'options'}:
                raise ValueError('Invalid FFmpeg input/output schema.')
            name = entry['name']
            if not isinstance(name, str) or not re.fullmatch(r'[a-z_][a-z_0-9]*', name) or name in names:
                raise ValueError('FFmpeg input/output names must be unique identifiers.')
            names.add(name)
            value(entry['url'], True)
            options(entry['options'], scope)
    if not job['outputs']:
        raise ValueError('An FFmpeg job requires at least one output.')
    graphs = job['filtergraphs']
    if not isinstance(graphs, list) or len(graphs) > MAX_OPERANDS:
        raise ValueError('Invalid FFmpeg filtergraph list.')
    for graph in graphs:
        value(graph, True)
    if not job['inputs'] and not graphs:
        raise ValueError('An FFmpeg job needs an input or a source filtergraph.')
    if argument_types is not None and sorted(refs) != list(range(len(argument_types))):
        raise ValueError('Each FFmpeg operand must be referenced exactly once.')
    if argument_types is None:
        for graph in graphs:
            unquoted = re.sub(r"\\.|'(?:\\.|[^'\\])*'", lambda m: ' ' * len(m[0]), graph)
            for match in re.finditer(r'\[(\d+):[^\]]+\]', unquoted):
                if int(match[1]) >= len(job['inputs']):
                    raise ValueError('FFmpeg filtergraph references a nonexistent input.')
        for output in job['outputs']:
            for option in output['options']:
                if option['name'] == '-map':
                    match = re.match(r'-?(\d+)(?::|\?|$)', str(option['value']))
                    if match and int(match[1]) >= len(job['inputs']):
                        raise ValueError('FFmpeg stream map references a nonexistent input.')
            names_ = {o['name'].split(':')[0] for o in output['options']}
            if '-t' in names_ and '-to' in names_:
                raise ValueError('Specify duration (-t) or end time (-to), not both for an output.')
            for codec, filters in [({'-c', '-codec', '-c:v', '-codec:v'}, {'-vf', '-filter:v'}),
                                   ({'-c', '-codec', '-c:a', '-codec:a'}, {'-af', '-filter:a'})]:
                effective_codec = next((o['value'] for o in reversed(output['options']) if o['name'] in codec), None)
                copied = effective_codec == 'copy'
                filtered = any(o['name'] in filters for o in output['options'])
                if copied and filtered:
                    raise ValueError('A filtered stream must be encoded, not stream-copied.')


def resolve_job(template, values, argument_types):
    validate_job(template, argument_types)
    if len(values) != len(argument_types):
        raise ValueError('Incorrect FFmpeg operand count.')
    for value, kind in zip(values, argument_types):
        if type(value) is not (str if kind == 'text' else int):
            raise ValueError('Incorrect FFmpeg operand type.')
    def replace(item):
        if isinstance(item, dict):
            if set(item) == {'operand'}:
                return values[item['operand']]
            return {k: replace(v) for k, v in item.items()}
        if isinstance(item, list):
            return [replace(v) for v in item]
        return item
    job = replace(template)
    validate_job(job)
    return job


def _url(value):
    # Preserve URLs, devices and lavfi expressions. Prefix a leading dash so a
    # relative filename can never become an FFmpeg option/extra output.
    return './' + value if value.startswith('-') else value


def build_arguments(job):
    validate_job(job)
    args = ['-nostdin', '-y' if job['overwrite'] else '-n']
    def options(items):
        for item in items:
            args.append(item['name'])
            if item['value'] is not None:
                args.append(str(item['value']))
    options(job['global_options'])
    for entry in job['inputs']:
        options(entry['options'])
        args.extend(['-i', _url(entry['url'])])
    for graph in job['filtergraphs']:
        args.extend(['-filter_complex', graph])
    for entry in job['outputs']:
        options(entry['options'])
        args.append(_url(entry['url']))
    return args


def executable_path(value, default):
    candidate = os.fspath(value) if value else default
    found = shutil.which(candidate)
    if not found:
        raise ValueError(f'{default} executable not found; install it or configure its path.')
    if Path(found).suffix.lower() in {'.cmd', '.bat'}:
        raise ValueError('Configure an FFmpeg executable, not a shell script.')
    return str(Path(found).resolve())


class FFmpegExecutionError(ValueError):
    def __init__(self, message, result=None):
        super().__init__(message)
        self.result = result or {}


class FFmpegExecutor:
    """Opt-in synchronous host operations. No subprocess is started by __init__."""
    def __init__(self, ffmpeg_path=None, ffprobe_path=None, base_dir=None, timeout=None, *, cancel_event=None, on_progress=None):
        if timeout is not None and (type(timeout) not in (int, float) or not 0 < timeout < float('inf')):
            raise ValueError('FFmpeg timeout must be a positive number of seconds.')
        self.ffmpeg_path = ffmpeg_path or os.environ.get('SHIPMB_FFMPEG_PATH')
        self.ffprobe_path = ffprobe_path or os.environ.get('SHIPMB_FFPROBE_PATH')
        self.base_dir = str(Path(base_dir or Path.cwd()).resolve())
        self.timeout, self.cancel_event, self.on_progress = timeout, cancel_event, on_progress

    def execute(self, job):
        args = build_arguments(job)
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise FFmpegExecutionError('FFmpeg cancelled.', {'kind': 'ffmpeg', 'status': 'cancelled', 'exit_code': None})
        binary = executable_path(self.ffmpeg_path, 'ffmpeg')
        from .ffmpeg_catalog import discover_catalog, validate_installed_options
        catalog = discover_catalog(binary)
        validate_installed_options(job, catalog)
        # stdout carries progress only; media pipe outputs would collide with it.
        if any(e['url'] in {'-', 'pipe:', 'pipe:0', 'pipe:1', 'pipe:2'} for e in job['inputs'] + job['outputs']):
            raise ValueError('Interactive/raw standard-stream media pipes require an external host adapter; use files or URLs.')
        args[0:0] = ['-progress', 'pipe:1', '-nostats']
        result = {'kind': 'ffmpeg', 'arguments': args, 'exit_code': None, 'stderr': '', 'progress': [], 'status': 'running'}
        def local_path(entry):
            url = entry['url']
            if any(o['name'] == '-f' and o['value'] in {'null', 'lavfi', 'dshow', 'avfoundation', 'v4l2', 'alsa', 'pulse', 'sdl', 'sdl2'} for o in entry['options']):
                return None
            if re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', url) and not re.match(r'^[A-Za-z]:[\\/]', url):
                return None
            path = Path(url)
            return (Path(self.base_dir) / path).resolve() if not path.is_absolute() else path.resolve()
        input_paths = {p for entry in job['inputs'] if (p := local_path(entry)) is not None}
        output_paths = set()
        for entry in job['outputs']:
            path = local_path(entry)
            if path is None:
                continue
            problem = None
            if path in input_paths:
                problem = 'FFmpeg cannot overwrite an input in place.'
            elif path in output_paths:
                problem = 'FFmpeg outputs must have distinct destinations.'
            elif path.exists() and not job['overwrite']:
                problem = f'Output already exists: {path}. Request Overwrite outputs explicitly.'
            if problem:
                result['status'] = 'failed'
                raise FFmpegExecutionError(problem, result)
            output_paths.add(path)
        stderr = bytearray()
        callback_errors = []
        try:
            process = subprocess.Popen([binary, *args], cwd=self.base_dir, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except OSError as error:
            raise FFmpegExecutionError(f'Cannot start FFmpeg: {error}', result) from error

        def drain_stderr():
            while chunk := process.stderr.read(4096):
                stderr.extend(chunk)
                if len(stderr) > 65536:
                    del stderr[:-65536]

        def drain_progress():
            fields = {}
            # Bounded readline also protects against unexpected executable output.
            while line := process.stdout.readline(4096):
                key, sep, value = line.decode('utf-8', 'replace').strip().partition('=')
                if sep and len(fields) < 64:
                    fields[key] = value
                if key == 'progress':
                    event = dict(fields)
                    fields.clear()
                    result['progress'].append(event)
                    del result['progress'][:-100]
                    if self.on_progress:
                        try:
                            self.on_progress(event)
                        except Exception as error:
                            callback_errors.append(str(error))
                            break

        threads = [threading.Thread(target=drain_stderr, daemon=True), threading.Thread(target=drain_progress, daemon=True)]
        for thread in threads:
            thread.start()
        reason = None
        started = time.monotonic()
        try:
            while process.poll() is None:
                if self.cancel_event is not None and self.cancel_event.is_set():
                    reason = 'cancelled'
                elif self.timeout is not None and time.monotonic() - started >= self.timeout:
                    reason = 'timed out'
                elif callback_errors:
                    reason = 'progress callback failed'
                if reason:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    break
                time.sleep(0.05)
            process.wait()
        except BaseException:
            process.kill()
            process.wait()
            raise
        finally:
            for thread in threads:
                thread.join(timeout=2)
            process.stdout.close()
            process.stderr.close()
        if callback_errors and not reason:
            reason = 'progress callback failed'
        # Some FFmpeg builds return zero for early output-open failures. The
        # managed progress channel must also report normal completion.
        if not reason and process.returncode == 0 and not any(p.get('progress') == 'end' for p in result['progress']):
            reason = 'failed before completion'
        result.update(exit_code=process.returncode, stderr=stderr.decode('utf-8', 'replace'),
                      status=reason or ('completed' if process.returncode == 0 else 'failed'))
        if reason or process.returncode:
            raise FFmpegExecutionError('FFmpeg ' + (reason or f'exited with status {process.returncode}') + '.', result)
        return result

    def probe(self, source):
        """Explicit metadata operation, never implicitly called by compilation."""
        if not isinstance(source, str) or not source or '\0' in source:
            raise ValueError('Probe source must be nonempty text without NUL bytes.')
        binary = executable_path(self.ffprobe_path, 'ffprobe')
        args = [binary, '-v', 'error', '-show_format', '-show_streams', '-of', 'json', _url(source)]
        try:
            completed = subprocess.run(args, cwd=self.base_dir, stdin=subprocess.DEVNULL,
                capture_output=True, timeout=self.timeout or 30, shell=False,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ValueError(f'ffprobe failed: {error}') from error
        if completed.returncode:
            raise ValueError('ffprobe failed: ' + completed.stderr[-65536:].decode('utf-8', 'replace'))
        if len(completed.stdout) > 4 * MAX_TEXT:
            raise ValueError('ffprobe metadata exceeds the supported size.')
        return json.loads(completed.stdout)
