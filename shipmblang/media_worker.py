"""Isolated media execution. Never executes before the parent owns the tree."""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

from . import FFmpegExecutor, compile_direct_program, compile_hyperframes, write_hyperframes_project, render_hyperframes_project
from .media_workspace import Workspace, write_json, tool_status, EXTENSIONS
from .notebook_runtime import compiler_snapshot

DEMUXERS = {'.mp4': 'mov', '.mov': 'mov', '.m4a': 'mov', '.mkv': 'matroska', '.webm': 'matroska',
            '.wav': 'wav', '.mp3': 'mp3', '.ogg': 'ogg', '.png': 'png_pipe', '.jpg': 'jpeg_pipe', '.jpeg': 'jpeg_pipe'}


class LocalFFmpeg(FFmpegExecutor):
    """Validate resolved operands at the adapter boundary, not source strings."""
    def __init__(self, workspace, directory, **options):
        super().__init__(base_dir=directory, **options)
        self.workspace, self.directory = workspace, Path(directory)

    def execute(self, job):
        job = copy.deepcopy(job)
        if job['overwrite'] or job['filtergraphs'] or job['global_options']:
            raise ValueError('Notes supports local conversion only: no overwrite, global options or filtergraphs.')
        if not job['inputs'] or len(job['inputs']) > 8 or len(job['outputs']) > 8:
            raise ValueError('Use one to eight imported inputs and outputs.')
        for entry in job['inputs']:
            source = self.workspace.input_path(entry['url'])
            for option in entry['options']:
                if option['name'] != '-ss' or not re.fullmatch(r'\d+(?:\.\d+)?', str(option['value'])):
                    raise ValueError('Notes input options currently support only a numeric -ss offset.')
            # Explicit demuxers and file-only protocols exclude playlists, devices and URL inputs.
            entry['url'] = str(source)
            entry['options'] += [{'name': '-protocol_whitelist', 'value': 'file'},
                                 {'name': '-f', 'value': DEMUXERS[source.suffix.lower()]}]
        codecs = {'libx264', 'libvpx-vp9', 'aac', 'libopus', 'libmp3lame', 'pcm_s16le', 'copy'}
        for entry in job['outputs']:
            relative = entry['url']
            if not re.fullmatch(r'outputs/[a-zA-Z0-9_-]{1,80}\.(mp4|webm|mp3|wav|ogg)', relative):
                raise ValueError('Use outputs/name.mp4 (or webm, mp3, wav, ogg) for results.')
            target = self.directory / relative
            if target.exists():
                raise ValueError('That output already exists; choose a different result name.')
            for option in entry['options']:
                name, value = option['name'], option['value']
                good = (name in {'-c:v', '-c:a', '-c'} and value in codecs or
                        name in {'-t', '-ss', '-r', '-ar', '-ac', '-crf'} and re.fullmatch(r'\d+(?:\.\d+)?', str(value)) or
                        name in {'-an', '-vn', '-shortest'} and value is None or
                        name == '-pix_fmt' and value in {'yuv420p', 'yuv444p'} or
                        name == '-preset' and value in {'ultrafast', 'fast', 'medium', 'slow'})
                if not good:
                    raise ValueError(f'{name} is not enabled in Notes conversion. Use the tested starter options.')
            entry['url'] = str(target)
        return super().execute(job)

    def probe(self, source):
        return super().probe(str(self.workspace.input_path(source)))


def render_bridge(resources, args, timeout):
    # Inherit the worker's owned process tree; do not create detached sessions.
    process = subprocess.run([shutil.which('node'), str(resources / 'node/bridge.mjs'), *args],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout,
                             encoding='utf-8', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    value = json.loads(process.stdout)
    if process.returncode or value.get('status') != 'rendered':
        raise ValueError(value.get('error', 'Rendering failed.'))
    return value


def run(path):
    deadline = time.monotonic() + 20
    while not (path / 'ready').exists():
        if time.monotonic() > deadline:
            return
        time.sleep(.02)
    request = json.loads((path / 'request.json').read_text(encoding='utf-8'))
    status = json.loads((path / 'status.json').read_text(encoding='utf-8'))
    def update(**values):
        status.update(values)
        write_json(path / 'status.json', status)
    try:
        if request['compiler'] != compiler_snapshot():
            raise ValueError('Compiler snapshot changed; reconnect before running.')
        workspace = Workspace(request['root'], request['project'])
        source = request['source']
        if request['mode'] == 'composition':
            result = compile_hyperframes(source)
        else:
            result = compile_direct_program(source, memory=False, model_provider=None, profile='general', ffmpeg_catalog={})
        if result.get('status') != 'compiled' or not result.get('target_code'):
            update(state='failed', message='Check the highlighted instructions.', diagnostics=result.get('diagnostics', []),
                   clarifications=result.get('clarifications', []))
            return
        if request['check']:
            update(state='completed', phase='checked', message='Check passed. Nothing executed.', diagnostics=result.get('diagnostics', []))
            return
        tools = tool_status(request['root'])
        (path / 'outputs').mkdir()
        if request['mode'] == 'composition':
            if not tools['rendering']:
                raise ValueError('Rendering is not set up. Open Media setup for the explicit installation command.')
            spec = result['target_code']['composition']
            if spec['width'] > 1920 or spec['height'] > 1920 or spec['duration'] / spec['fps'] > 120:
                raise ValueError('Notes compositions are limited to 1920 pixels per side and 120 seconds.')
            for element in spec['elements']:
                if element['kind'] != 'text':
                    workspace.input_path(element['value'])
            update(phase='preparing', message='Preparing composition and imported assets…')
            from ._compiler.hyperframes import project
            project.RESOURCES = Path(tools['renderer'])
            project._run_bridge = lambda args, timeout: render_bridge(project.RESOURCES, args, timeout)
            for key in ('ffmpeg', 'ffprobe', 'node'):
                os.environ['PATH'] = str(Path(tools['tools'][key]).parent) + os.pathsep + os.environ.get('PATH', '')
            written = write_hyperframes_project(result, path / 'composition', asset_root=workspace.root)
            if written['status'] != 'written':
                raise ValueError(written['diagnostics'][0]['message'])
            update(phase='rendering', message='Rendering video…')
            rendered = render_hyperframes_project(path / 'composition', path / 'outputs/title.mp4', timeout=580)
            if rendered['status'] != 'rendered':
                raise ValueError(rendered['diagnostics'][0]['message'])
            stdout = ''
        else:
            capabilities = set(result['target_code'].get('runtime_contract', {}).get('required_capabilities', []))
            if capabilities - {'ffmpeg'}:
                raise ValueError('Use Play for a persistent VLC preview. Scripted VLC and other host capabilities are not enabled in background jobs.')
            if 'ffmpeg' in capabilities and not tools['conversion']:
                raise ValueError('FFmpeg/ffprobe are missing. Open Media setup to configure their paths.')
            last_progress = [0.0]
            def progress(value):
                if time.monotonic() - last_progress[0] > .3 or value.get('progress') == 'end':
                    last_progress[0] = time.monotonic()
                    update(phase='converting', message='Converting media…', progress={k: str(v)[:100] for k, v in value.items() if k in {'out_time', 'speed', 'frame', 'progress'}})
            executor = LocalFFmpeg(workspace, path, ffmpeg_path=tools['tools']['ffmpeg'], ffprobe_path=tools['tools']['ffprobe'], timeout=580, on_progress=progress)
            update(phase='running', message='Running this revision…')
            from ._compiler.runtime import run_artifact
            runtime, diagnostics = run_artifact(result['target_code'], ffmpeg_executor=executor)
            if diagnostics:
                update(state='failed', message='Program needs attention.', diagnostics=[d.to_dict() for d in diagnostics])
                return
            stdout = runtime.get('stdout', '')
        outputs = []
        for file in (path / 'outputs').iterdir():
            if file.is_file():
                media = FFmpegExecutor(ffprobe_path=tools['tools']['ffprobe'], timeout=20).probe(str(file))
                outputs.append({'id': uuid.uuid4().hex, 'name': file.name, 'size': file.stat().st_size,
                                'duration': media.get('format', {}).get('duration'),
                                'streams': [{k: s[k] for k in ('codec_type', 'codec_name', 'width', 'height') if k in s} for s in media.get('streams', [])]})
        update(state='completed', phase='finished', message='Finished.', stdout=stdout, outputs=outputs)
    except Exception as error:
        update(state='failed', message=str(error), diagnostics=[{'level': 'error', 'message': str(error)}])


if __name__ == '__main__':
    run(Path(sys.argv[1]).resolve())
