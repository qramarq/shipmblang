"""Real worker lifecycle, adapter boundaries and private-service ownership."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from shipmblang.media_jobs import MediaJobs, new_request_id, TERMINAL
from shipmblang.media_worker import LocalFFmpeg
from shipmblang.media_workspace import Workspace, conversion_starter, TITLE_STARTER, tool_status
from shipmblang.mobile_service import create_app
from shipmblang.notebook_runtime import compiler_snapshot


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.jobs = MediaJobs(self.root)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.jobs.close)

    def wait(self, job, timeout=15):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            result = self.jobs.get(job['project'], job['id'])
            if result['state'] in TERMINAL and job['project'] not in self.jobs.active:
                return result
            time.sleep(.05)
        self.fail('Media worker did not finish.')

    def test_check_is_tool_free_and_compiler_pinned(self):
        with patch.dict(os.environ, {'SHIPMB_FFMPEG_PATH': 'does-not-exist'}):
            job = self.jobs.submit('note', TITLE_STARTER, 'composition', new_request_id(), check=True)
            result = self.wait(job)
        self.assertEqual(result['state'], 'completed', result)
        self.assertEqual(result['compiler'], compiler_snapshot())
        self.assertEqual(result['outputs'], [])
        self.assertFalse((self.root / 'note/jobs' / job['id'] / 'outputs').exists())

    def test_idempotency_rejects_changed_source(self):
        request_id = new_request_id()
        one = self.jobs.submit('note', 'Show 5.', 'program', request_id)
        two = self.jobs.submit('note', 'Show 5.', 'program', request_id)
        self.assertEqual(one['id'], two['id'])
        with self.assertRaises(ValueError):
            self.jobs.submit('note', 'Show 6.', 'program', request_id)
        result = self.wait(one)
        self.assertEqual(result['state'], 'completed', result)
        self.assertEqual(result['stdout'], '5\n')

    def test_import_rejects_playlists_limits_and_path_escapes(self):
        workspace = self.jobs.workspace('note')
        with self.assertRaises(ValueError):
            workspace.import_stream(io.BytesIO(b'http://example.com/private'), 'renamed.mp4', 26)
        with self.assertRaises(ValueError):
            workspace.import_stream(io.BytesIO(b'x'), 'movie.mp4', 101 * 1024**2)
        for path in ('../secret.mp4', 'https://example.com/a.mp4', 'C:/file.mp4'):
            with self.assertRaises(ValueError):
                workspace.input_path(path)
        with self.assertRaises(ValueError):
            self.jobs.workspace('../escape')
        self.assertEqual(workspace.read()['assets'], [])

    def test_resolved_adapter_rejects_unsafe_options_and_collisions(self):
        workspace = self.jobs.workspace('note')
        asset = workspace.import_stream(io.BytesIO(b'\x89PNG\r\n\x1a\n' + b'x'*8), 'space café.png', 16)
        directory = workspace.root / 'jobs/probe'
        (directory / 'outputs').mkdir(parents=True)
        adapter = LocalFFmpeg(workspace, directory)
        base = {'global_options': [], 'filtergraphs': [], 'overwrite': False,
                'inputs': [{'name': 'clip', 'url': asset['path'], 'options': []}],
                'outputs': [{'name': 'result', 'url': 'outputs/test.mp4', 'options': []}]}
        import copy
        variants = []
        for key, value in [('url', '../escape.mp4'), ('url', 'https://example.com/x'),
                           ('options', [{'name': '-vf', 'value': 'movie=/private/file'}]),
                           ('options', [{'name': '-f', 'value': 'hls'}])]:
            variant = copy.deepcopy(base); variant['outputs'][0][key] = value; variants.append(variant)
        for variant in variants:
            with self.assertRaises(ValueError), patch('shipmblang._compiler.ffmpeg.FFmpegExecutor.execute') as native:
                adapter.execute(variant)
                native.assert_not_called()
        (directory / 'outputs/test.mp4').write_bytes(b'preserved')
        with self.assertRaises(ValueError):
            adapter.execute(base)
        self.assertEqual((directory / 'outputs/test.mp4').read_bytes(), b'preserved')

    def test_cancellation_owns_descendant_process(self):
        from shipmblang.media_process import spawn
        child_pid = self.root / 'pid.txt'
        command = [sys.executable, '-c',
                   'import sys,time,subprocess; sys.stdin.readline(); p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"]);open(sys.argv[1],"w").write(str(p.pid));time.sleep(60)', str(child_pid)]
        process, tree = spawn(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL)
        process.stdin.write(b'ready\n'); process.stdin.flush()
        deadline = time.monotonic() + 5
        while not child_pid.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertTrue(child_pid.exists())
        pid = int(child_pid.read_text())
        tree.close(); process.stdin.close()
        self.assertIsNotNone(process.poll())
        if os.name == 'nt':
            import ctypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.OpenProcess.restype = ctypes.c_void_p
            handle = kernel.OpenProcess(0x1000, False, pid)
            if handle:
                code = ctypes.c_ulong()
                kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
                kernel.GetExitCodeProcess(handle, ctypes.byref(code))
                kernel.CloseHandle.argtypes = [ctypes.c_void_p]; kernel.CloseHandle(handle)
                self.assertNotEqual(code.value, 259)

    def request(self, app, path, method='GET', body=b'', token='owner-token-for-local-tests-1234567890', **extra):
        headers = []
        environ = {'PATH_INFO': path, 'REQUEST_METHOD': method, 'CONTENT_LENGTH': str(len(body)),
                   'CONTENT_TYPE': 'application/json', 'HTTP_AUTHORIZATION': 'Bearer '+token,
                   'wsgi.input': io.BytesIO(body), **extra}
        result = b''.join(app(environ, lambda status, values: headers.extend([status, values])))
        return headers[0], result

    def test_service_ownership_snapshot_download_and_archive(self):
        app = create_app('owner-token-for-local-tests-1234567890', media_root=self.root / 'api')
        other = create_app('second-owner-token-local-tests-1234567890', media_root=self.root / 'api')
        self.addCleanup(app.close); self.addCleanup(other.close)
        base = '/v1/media/projects/note'
        for endpoint in ('jobs', 'copy-assets', 'archives'):
            self.assertEqual(self.request(app, base+'/'+endpoint, 'POST', b'[]')[0], '400 Bad Request')
        png = b'\x89PNG\r\n\x1a\n' + b'x'*8
        status, body = self.request(app, base+'/assets', 'POST', png, QUERY_STRING='name=test.png')
        self.assertEqual(status, '201 Created')
        asset = json.loads(body)
        self.assertEqual(self.request(app, base+'/assets/'+asset['id'])[1], png)
        self.assertEqual(self.request(app, base+'/assets/'+asset['id'], token='wrong')[0], '401 Unauthorized')
        self.assertEqual(self.request(other, base+'/assets/'+asset['id'], token='second-owner-token-local-tests-1234567890')[0], '400 Bad Request')
        status, _ = self.request(app, base+'/jobs', 'POST', json.dumps({'source': 'Show 5.', 'mode': 'program', 'request_id':new_request_id(), 'compiler':{}}).encode())
        self.assertEqual(status, '409 Conflict')
        status, body = self.request(app, base+'/archives','POST',json.dumps({'source':'Present "Keep this diary".'}).encode())
        self.assertEqual(status, '201 Created')
        status, archive = self.request(app, base+'/archives/'+json.loads(body)['id'])
        import zipfile
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            self.assertEqual(zipped.read('note.shipmb').decode(), 'Present "Keep this diary".')
            self.assertIn('media/'+asset['path'], zipped.namelist())

    def test_real_conversion_when_tools_available(self):
        tools = tool_status(self.root)['tools']
        if not tools['ffmpeg'] or not tools['ffprobe']:
            self.skipTest('FFmpeg not configured on this host.')
        fixture = self.root / 'space café.mp4'
        subprocess.run([tools['ffmpeg'], '-nostdin', '-n', '-f','lavfi','-i','testsrc2=size=160x90:rate=24',
                        '-t','1','-c:v','libx264',str(fixture)], check=True,capture_output=True)
        asset = self.jobs.workspace('note').import_file(fixture)
        job = self.jobs.submit('note', conversion_starter(asset), 'program',new_request_id())
        result = self.wait(job,30)
        self.assertEqual(result['state'],'completed',result)
        self.assertEqual(result['outputs'][0]['streams'][0]['width'],160)
        self.assertTrue(self.jobs.output('note',job['id'],result['outputs'][0]['id']).exists())
