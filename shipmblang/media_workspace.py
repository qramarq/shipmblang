"""Local-only imported assets, immutable jobs and explicit tool setup."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time
import uuid

MAX_ASSET = 100 * 1024 * 1024
MAX_WORKSPACE = 1024 * 1024 * 1024
EXTENSIONS = {'.mp4', '.mov', '.webm', '.mkv', '.wav', '.mp3', '.m4a', '.ogg', '.png', '.jpg', '.jpeg'}


def disk_size(root):
    total = 0
    for file in Path(root).rglob('*'):
        try:
            if file.is_file():
                total += file.stat().st_size
        except FileNotFoundError:  # atomic progress writes can disappear between scan and stat
            pass
    return total


def validate_media_header(path):
    with Path(path).open('rb') as stream:
        header = stream.read(16)
    extension = Path(path).suffix.lower()
    valid = (extension in {'.mp4', '.mov', '.m4a'} and header[4:8] == b'ftyp' or
             extension in {'.mkv', '.webm'} and header[:4] == b'\x1aE\xdf\xa3' or
             extension == '.wav' and header[:4] == b'RIFF' and header[8:12] == b'WAVE' or
             extension == '.ogg' and header[:4] == b'OggS' or
             extension == '.mp3' and (header[:3] == b'ID3' or len(header) > 1 and header[0] == 255 and header[1] & 224 == 224) or
             extension == '.png' and header[:8] == b'\x89PNG\r\n\x1a\n' or
             extension in {'.jpg', '.jpeg'} and header[:3] == b'\xff\xd8\xff')
    if not valid:
        raise ValueError('File contents do not match a supported local media format. Playlists and URL files are not accepted.')


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', value):
        raise ValueError('Invalid project or asset identifier.')
    return value


def write_json(path, value):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    try:
        # Windows readers can briefly deny replacement of an open status file.
        for attempt in range(20):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(.01)
    finally:
        temporary.unlink(missing_ok=True)


class Workspace:
    def __init__(self, root, project):
        self.root = Path(root).resolve() / identifier(project)
        self.root.mkdir(parents=True, exist_ok=True)
        for name in ('assets', 'jobs'):
            (self.root / name).mkdir(exist_ok=True)
        self.manifest = self.root / 'media.json'
        if not self.manifest.exists():
            write_json(self.manifest, {'mode': 'program', 'assets': []})

    def read(self):
        return json.loads(self.manifest.read_text(encoding='utf-8'))

    def mode(self, value=None):
        data = self.read()
        if value is not None:
            if value not in {'program', 'composition'}:
                raise ValueError('Choose Program or Video composition.')
            data['mode'] = value
            write_json(self.manifest, data)
        return data['mode']

    def import_stream(self, stream, filename, length):
        if not 0 < length <= MAX_ASSET:
            raise ValueError('Choose a media file between 1 byte and 100 MiB.')
        extension = Path(filename).suffix.lower()
        if extension not in EXTENSIONS:
            raise ValueError('Choose a supported video, audio or image file.')
        used = disk_size(self.root)
        if used + length > MAX_WORKSPACE:
            raise ValueError('This project has reached its 1 GiB media limit.')
        asset_id = uuid.uuid4().hex
        relative = 'assets/' + asset_id + extension
        destination = self.root / relative
        digest = hashlib.sha256()
        try:
            with destination.open('xb') as output:
                remaining = length
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError('Upload ended before the complete file arrived.')
                    output.write(chunk)
                    digest.update(chunk)
                    remaining -= len(chunk)
            validate_media_header(destination)
            asset = {'id': asset_id, 'name': Path(filename.replace('\\', '/')).name[:180],
                     'path': relative, 'size': length, 'sha256': digest.hexdigest()}
            data = self.read()
            data['assets'].append(asset)
            write_json(self.manifest, data)
            return asset
        except BaseException:
            destination.unlink(missing_ok=True)
            raise

    def import_file(self, path):
        path = Path(path)
        with path.open('rb') as stream:
            return self.import_stream(stream, path.name, path.stat().st_size)

    def input_path(self, relative):
        if relative not in {a['path'] for a in self.read()['assets']}:
            raise ValueError('Use an imported asset from this note.')
        path = (self.root / relative).resolve(strict=True)
        if not path.is_relative_to(self.root / 'assets') or not path.is_file():
            raise ValueError('Asset path escapes this note.')
        return path

    def asset(self, asset_id):
        identifier(asset_id)
        for item in self.read()['assets']:
            if item['id'] == asset_id:
                return item, self.input_path(item['path'])
        raise ValueError('Asset not found in this note.')


def renderer_root(root):
    configured = os.environ.get('SHIPMB_RENDERER_ROOT')
    return Path(configured).resolve() if configured else Path(root).resolve() / '_renderer' / '0.5.0'


def tool_status(root):
    vlc_dir = Path(os.environ.get('SHIPMB_VLC_DIR', 'C:/Program Files/VideoLAN/VLC'))
    bridge = Path(os.environ.get('SHIPMB_VLC_BRIDGE', 'missing-shipmb_vlc.dll'))
    tools = {key: shutil.which(os.environ.get(env, name)) for key, env, name in
             [('ffmpeg', 'SHIPMB_FFMPEG_PATH', 'ffmpeg'), ('ffprobe', 'SHIPMB_FFPROBE_PATH', 'ffprobe'), ('node', 'SHIPMB_NODE_PATH', 'node')]}
    renderer = renderer_root(root)
    return {'conversion': bool(tools['ffmpeg'] and tools['ffprobe']),
            'playback': os.name == 'nt' and (vlc_dir / 'libvlc.dll').is_file() and bridge.is_file(),
            'rendering': bool(tools['ffmpeg'] and tools['ffprobe'] and tools['node'] and
                              (renderer / 'node/node_modules/@hyperframes/producer').is_dir()),
            'tools': tools, 'vlc_dir': str(vlc_dir), 'vlc_bridge': str(bridge.resolve()),
            'renderer': str(renderer),
            'help': 'Set SHIPMB_FFMPEG_PATH / SHIPMB_FFPROBE_PATH and SHIPMB_VLC_DIR / SHIPMB_VLC_BRIDGE. For rendering run python -m shipmblang.media_setup --root <media-root>. Nothing installs during Check.'}


def conversion_starter(asset):
    return (f'Let source be "{asset["path"]}".\nLet destination be "outputs/converted.mp4".\n'
            'Run FFmpeg:\nInput clip from source.\nOutput result to destination.\n'
            'Output option "-c:v" for result with "libx264".\n'
            'Output option "-c:a" for result with "aac".\nEnd FFmpeg.')


TITLE_STARTER = '''Create a video at 640 by 360 pixels and 24 frames per second.
Add scene "intro" lasting 1 seconds.
Set the background of scene "intro" to "#24362b".
Show text "My first little film" as "title" in scene "intro".
Place "title" at 320 by 180 pixels.
Set the font size of "title" to 36 pixels.
Set the color of "title" to "#fff6ce".
Fade in "title" over 0.25 seconds.'''


def composition_starter(asset):
    extension = Path(asset['path']).suffix.lower()
    kind = 'image' if extension in {'.png', '.jpg', '.jpeg'} else 'audio' if extension in {'.wav', '.mp3', '.m4a', '.ogg'} else 'video'
    verb = 'Play' if kind == 'audio' else 'Show'
    source = ('Create a video at 640 by 360 pixels and 24 frames per second.\n'
              'Add scene "intro" lasting 1 seconds.\n'
              'Set the background of scene "intro" to "#24362b".\n'
              f'{verb} {kind} "{asset["path"]}" as "media" in scene "intro" lasting 1 seconds.\n')
    if kind != 'audio':
        source += 'Place "media" at 320 by 180 pixels.\nSet the size of "media" to 640 by 360 pixels.\n'
    source += ('Show text "Made with my media" as "title" in scene "intro".\n'
               'Place "title" at 320 by 50 pixels.\nSet the font size of "title" to 28 pixels.\n'
               'Set the color of "title" to "#ffffff".')
    return source
