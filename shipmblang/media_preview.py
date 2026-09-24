"""Persistent VLC preview in an owned process, embedded in a Windows Tk frame."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time

from .media_process import spawn
from .media_workspace import write_json, tool_status


class Preview:
    def __init__(self, path, hwnd, media_root):
        if os.name != 'nt':
            raise ValueError('Embedded VLC preview currently requires Windows.')
        tools = tool_status(media_root)
        if not tools['playback']:
            raise ValueError('Install matching LibVLC 3.x and set SHIPMB_VLC_BRIDGE. See Media setup.')
        self.temp = tempfile.TemporaryDirectory(prefix='shipmb-preview-')
        self.status_path = Path(self.temp.name) / 'state.json'
        write_json(self.status_path, {'state': 'opening', 'position': 0, 'duration': 0})
        self.process, self.tree = spawn([sys.executable, '-X', 'utf8', '-m', 'shipmblang.media_preview', str(self.status_path)],
                                        cwd=Path(__file__).resolve().parents[1], stdin=subprocess.PIPE,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True, encoding='utf-8')
        self.send('open', [str(Path(path).resolve()), int(hwnd), tools['vlc_dir'], tools['vlc_bridge']])

    def send(self, operation, values=None):
        if self.process.poll() is not None:
            raise ValueError(self.state().get('error', 'Playback process stopped.'))
        self.process.stdin.write(json.dumps({'operation': operation, 'values': values or []}) + '\n')
        self.process.stdin.flush()

    def state(self):
        value = json.loads(self.status_path.read_text(encoding='utf-8'))
        if self.process.poll() is not None and value['state'] != 'error':
            value.update(state='error', error='Playback process stopped; check the VLC installation and architecture.')
        return value

    def close(self):
        try:
            if self.process.poll() is None:
                self.send('close')
                self.process.wait(timeout=2)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
        finally:
            self.tree.close()
            self.process.stdin.close()
            self.temp.cleanup()


def worker(status_path):
    from . import VLCExecutor
    commands = queue.Queue()
    def read():
        for line in sys.stdin:
            commands.put(json.loads(line))
        commands.put({'operation': 'close'})
    threading.Thread(target=read, daemon=True).start()
    executor = None
    try:
        first = commands.get(timeout=20)
        if first['operation'] != 'open':
            raise ValueError('Preview must begin with an imported local file.')
        path, hwnd, directory, bridge = first['values']
        executor = VLCExecutor(vlc_dir=directory, bridge_path=bridge, windows={'preview': hwnd})
        executor.invoke('open', ['preview', path])
        executor.invoke('start', ['preview'])
        while True:
            try:
                message = commands.get(timeout=.3)
                op = message['operation']
                if op == 'close':
                    break
                if op not in {'start', 'pause', 'resume', 'stop', 'seek', 'volume'}:
                    raise ValueError('Unsupported preview command.')
                executor.invoke(op, ['preview', *message['values']])
            except queue.Empty:
                pass
            write_json(status_path, {'state': executor.invoke('state', ['preview']),
                                     'position': executor.invoke('position', ['preview']),
                                     'duration': executor.invoke('duration', ['preview'])})
    except Exception as error:
        write_json(status_path, {'state': 'error', 'error': str(error), 'position': 0, 'duration': 0})
    finally:
        if executor:
            executor.close()


if __name__ == '__main__':
    worker(Path(sys.argv[1]))
