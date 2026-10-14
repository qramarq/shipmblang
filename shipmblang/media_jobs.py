"""Small persistent job manager shared by desktop and the private mobile service."""
from __future__ import annotations
import atexit
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

from .media_process import spawn
from .media_workspace import Workspace, identifier, write_json, tool_status, MAX_WORKSPACE, disk_size
from .notebook_runtime import compiler_snapshot

TERMINAL = {'completed', 'failed', 'cancelled'}


class MediaJobs:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.active = {}
        self.closed = False
        # An interrupted service never claims an orphan job is still running.
        for file in self.root.glob('*/jobs/*/status.json'):
            value = json.loads(file.read_text(encoding='utf-8'))
            if value['state'] not in TERMINAL:
                value.update(state='failed', message='Service stopped before this job finished.')
                write_json(file, value)
        atexit.register(self.close)

    def workspace(self, project):
        return Workspace(self.root, project)

    def submit(self, project, source, mode, request_id, *, check=False):
        if not isinstance(source, str) or not source.strip() or len(source.encode('utf-8')) > 60000:
            raise ValueError('Write a program below 60 KiB.')
        if mode not in {'program', 'composition'}:
            raise ValueError('Choose Program or Video composition.')
        identifier(request_id)
        workspace = self.workspace(project)
        revision = hashlib.sha256(source.encode()).hexdigest()
        with self.lock:
            if self.closed:
                raise ValueError('Media service is shutting down.')
            path = workspace.root / 'jobs' / request_id
            if path.exists():
                previous = json.loads((path / 'request.json').read_text(encoding='utf-8'))
                if (previous['source'], previous['mode'], previous['check']) != (source, mode, check):
                    raise ValueError('This request ID already belongs to different text.')
                return self.get(project, request_id)
            if project in self.active:
                raise ValueError('Stop or finish this note’s current job first.')
            if len(self.active) >= 2:
                raise ValueError('Two media jobs are already running. Wait or stop one first.')
            if disk_size(workspace.root) >= MAX_WORKSPACE:
                raise ValueError('This project has reached its 1 GiB limit. Export and archive it first.')
            path.mkdir()
            request = {'project': project, 'source': source, 'mode': mode, 'check': check,
                       'compiler': compiler_snapshot(), 'root': str(self.root), 'timeout': 600}
            write_json(path / 'request.json', request)
            status = {'id': request_id, 'project': project, 'state': 'running', 'phase': 'checking',
                      'source_revision': revision, 'compiler': request['compiler'], 'created': time.time(),
                      'message': 'Checking instructions…', 'outputs': [], 'diagnostics': []}
            write_json(path / 'status.json', status)
            command = [sys.executable, '-X', 'utf8', '-m', 'shipmblang.media_worker', str(path)]
            try:
                process, tree = spawn(command, cwd=Path(__file__).resolve().parents[1],
                                      stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except BaseException:
                status.update(state='failed', message='Could not start the media worker.')
                write_json(path / 'status.json', status)
                raise
            self.active[project] = (request_id, tree)
            (path / 'ready').touch()  # only allow native children after tree containment
            threading.Thread(target=self._watch, args=(project, request_id, path, tree), daemon=True).start()
            return status

    def _watch(self, project, job_id, path, tree):
        deadline = time.monotonic() + 600
        reason = None
        while tree.process.poll() is None:
            if time.monotonic() > deadline:
                reason = 'Stopped after the 10-minute media limit.'
                break
            if disk_size(path.parents[1]) > MAX_WORKSPACE:
                reason = 'Stopped after the 1 GiB project media limit.'
                break
            time.sleep(.2)
        with self.lock:
            if project not in self.active or self.active[project][0] != job_id:
                return
            tree.close()
            status = self.get(project, job_id)
            if reason or status['state'] not in TERMINAL:
                status.update(state='failed', message=reason or 'The media worker stopped unexpectedly.')
                write_json(path / 'status.json', status)
            del self.active[project]

    def get(self, project, job_id):
        path = self.workspace(project).root / 'jobs' / identifier(job_id) / 'status.json'
        if not path.is_file():
            raise ValueError('Job not found in this note.')
        return json.loads(path.read_text(encoding='utf-8'))

    def latest(self, project):
        paths = list((self.workspace(project).root / 'jobs').glob('*/status.json'))
        return json.loads(max(paths, key=lambda p: p.stat().st_mtime).read_text(encoding='utf-8')) if paths else None

    def cancel(self, project, job_id):
        with self.lock:
            status = self.get(project, job_id)
            if status['state'] in TERMINAL:
                return status
            current = self.active.get(project)
            if current and current[0] == job_id:
                current[1].close()
                del self.active[project]
            status.update(state='cancelled', message='Stopped. No media processes remain.', outputs=[])
            write_json(self.workspace(project).root / 'jobs' / job_id / 'status.json', status)
            return status

    def output(self, project, job_id, output_id):
        status = self.get(project, job_id)
        if status['state'] != 'completed':
            raise ValueError('This job has no completed output.')
        output = next((item for item in status['outputs'] if item['id'] == output_id), None)
        if output is None:
            raise ValueError('Output not found in this note.')
        root = self.workspace(project).root / 'jobs' / job_id / 'outputs'
        path = (root / output['name']).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError('Invalid output path.')
        return path

    def close(self):
        with self.lock:
            self.closed = True
            for project, (job_id, _) in list(self.active.items()):
                self.cancel(project, job_id)


def new_request_id():
    return uuid.uuid4().hex
