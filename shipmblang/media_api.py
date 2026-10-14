"""Authenticated private-service media routes. Caller authenticates every request."""
import json
import shutil
import uuid
import zipfile
import mimetypes
from pathlib import Path
from urllib.parse import parse_qs

from .media_workspace import MAX_ASSET, MAX_WORKSPACE, tool_status, write_json, disk_size, identifier


def route(jobs, snapshot, environ, reply, start_response, headers):
    parts = environ['PATH_INFO'].strip('/').split('/')
    method = environ['REQUEST_METHOD']
    try:
        if parts == ['v1', 'media', 'setup'] and method == 'GET':
            return reply('200 OK', {'compiler': snapshot, **tool_status(jobs.root)})
        if len(parts) < 4 or parts[:3] != ['v1', 'media', 'projects']:
            return reply('404 Not Found', {'error': 'Unknown media endpoint.'})
        project = parts[3]
        workspace = jobs.workspace(project)
        tail = parts[4:]
        if not tail and method == 'GET':
            return reply('200 OK', {**workspace.read(), 'job': jobs.latest(project), 'compiler': snapshot})
        if tail == ['assets'] and method == 'POST':
            length = int(environ.get('CONTENT_LENGTH') or '0')
            if not 0 < length <= MAX_ASSET:
                return reply('413 Content Too Large', {'error': 'Uploads must be below 100 MiB.'})
            name = parse_qs(environ.get('QUERY_STRING', '')).get('name', ['asset.mp4'])[0]
            with jobs.lock:
                asset = workspace.import_stream(environ['wsgi.input'], name, length)
            return reply('201 Created', asset)
        if len(tail) == 2 and tail[0] == 'assets' and method == 'GET':
            _, file = workspace.asset(tail[1])
            return download(file, environ, start_response, headers)
        if tail == ['archives'] and method == 'POST':
            length = int(environ.get('CONTENT_LENGTH') or '0')
            if not 0 < length <= 65536:
                raise ValueError('Keep note exports below 64 KiB of source.')
            value = json.loads(environ['wsgi.input'].read(length))
            if not isinstance(value, dict):
                raise ValueError('Provide a JSON object.')
            if not isinstance(value.get('source'), str):
                raise ValueError('Provide the current note text.')
            with jobs.lock:
                if project in jobs.active:
                    raise ValueError('Stop or finish the job before exporting the note.')
                if disk_size(workspace.root) * 2 > MAX_WORKSPACE:
                    raise ValueError('This project is too large for a server-side archive. Export files individually.')
                directory = workspace.root / 'exports'
                directory.mkdir(exist_ok=True)
                archive_id = uuid.uuid4().hex
                target = directory / (archive_id + '.zip')
                try:
                    with zipfile.ZipFile(target, 'x', zipfile.ZIP_STORED) as archive:
                        archive.writestr('note.shipmb', value['source'])
                        for file in workspace.root.rglob('*'):
                            if file.is_file() and not file.is_relative_to(directory):
                                archive.write(file, 'media/' + file.relative_to(workspace.root).as_posix())
                except BaseException:
                    target.unlink(missing_ok=True)
                    raise
            return reply('201 Created', {'id': archive_id, 'name': 'note-and-media.zip'})
        if len(tail) == 2 and tail[0] == 'archives' and method == 'GET':
            return download(workspace.root / 'exports' / (identifier(tail[1]) + '.zip'), environ, start_response, headers)
        if tail == ['copy-assets'] and method == 'POST':
            length = int(environ.get('CONTENT_LENGTH') or '0')
            if not 0 < length <= 4096:
                raise ValueError('Invalid copy request.')
            value = json.loads(environ['wsgi.input'].read(length))
            if not isinstance(value, dict):
                raise ValueError('Provide a JSON object.')
            with jobs.lock:
                original = jobs.workspace(value['project'])
                asset, source = original.asset(value['asset_id'])
                destination = workspace.root / asset['path']
                data = workspace.read()
                if any(a['id'] == asset['id'] for a in data['assets']):
                    return reply('200 OK', asset)
                used = disk_size(workspace.root)
                if used + asset['size'] > MAX_WORKSPACE:
                    raise ValueError('Project media limit exceeded.')
                with destination.open('xb') as target, source.open('rb') as stream:
                    shutil.copyfileobj(stream, target)
                data['assets'].append(asset)
                write_json(workspace.manifest, data)
            return reply('201 Created', asset)
        if tail == ['jobs'] and method == 'POST':
            length = int(environ.get('CONTENT_LENGTH') or '0')
            if not 0 < length <= 65536:
                raise ValueError('Keep job requests below 64 KiB.')
            value = json.loads(environ['wsgi.input'].read(length))
            if not isinstance(value, dict):
                raise ValueError('Provide a JSON object.')
            if value.get('compiler') != snapshot:
                return reply('409 Conflict', {'error': 'Compiler snapshot mismatch. Update the app and service together.'})
            if type(value.get('check', False)) is not bool:
                raise ValueError('Check must be a boolean.')
            job = jobs.submit(project, value.get('source'), value.get('mode'), value.get('request_id'), check=value.get('check', False))
            workspace.mode(value['mode'])
            return reply('202 Accepted', job)
        if len(tail) == 2 and tail[0] == 'jobs' and method == 'GET':
            return reply('200 OK', jobs.get(project, tail[1]))
        if len(tail) == 3 and tail[0] == 'jobs' and tail[2] == 'cancel' and method == 'POST':
            return reply('200 OK', jobs.cancel(project, tail[1]))
        if len(tail) == 4 and tail[0] == 'jobs' and tail[2] == 'outputs' and method == 'GET':
            return download(jobs.output(project, tail[1], tail[3]), environ, start_response, headers)
        return reply('404 Not Found', {'error': 'Unknown media endpoint.'})
    except (ValueError, KeyError, TypeError, OSError) as error:
        return reply('400 Bad Request', {'error': str(error)})


def download(path, environ, start_response, headers):
    size = path.stat().st_size
    start_response('200 OK', [*[(k, v) for k, v in headers if k != 'Content-Type'],
        ('Content-Type', mimetypes.guess_type(path.name)[0] or 'application/octet-stream'),
        ('Content-Length', str(size)), ('Content-Disposition', 'attachment; filename="' + path.name + '"'),
        ('X-Content-Type-Options', 'nosniff')])
    def body():
        with path.open('rb') as stream:
            while chunk := stream.read(1024 * 1024):
                yield chunk
    return body()
