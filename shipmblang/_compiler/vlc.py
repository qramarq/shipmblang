"""Typed VLC operations and an explicit optional native LibVLC adapter.

Compilation uses the catalog only. Runtime loads the shared C++ adapter lazily;
this reuses exactly the native implementation's lifecycle and error handling.
"""
from __future__ import annotations
import ctypes
import json
import os
from pathlib import Path
import threading

OPERATIONS = {
    **{op: (['text'], None) for op in ('close','start','pause','resume','stop','next','previous')},
    'open': (['text','text'],None), 'playlist': (['text','list[text]'],None),
    **{op: (['text','integer'],None) for op in ('seek','volume','rate','parse','audio_track','subtitle_track')},
    **{op: (['text','boolean'],None) for op in ('mute','fullscreen','repeat')},
    'wait': (['text','text','integer'],None), 'delay': (['integer'],None),
    'subtitle': (['text','text'],None),
    'output': (['text','text','text','text','text','text','integer','integer'],None),
    'metadata': (['text','text'],'text'), 'state': (['text'],'text'),
    **{op: (['text'],'integer') for op in ('duration','position','width','height')},
    'seekable': (['text'],'boolean'),
    **{op: (['text'],'list[integer]') for op in ('audio_ids','subtitle_ids')},
    **{op: (['text'],'list[text]') for op in ('audio_names','subtitle_names')},
}

def validate_arguments(operation, values):
    def _value(v,t):
        if t=='text': return type(v) is str and len(v.encode('utf-8'))<=1000000
        if t=='integer': return type(v) is int and v.bit_length()<=4096
        if t=='boolean': return type(v) is bool
        return type(v) is list and len(v)<=10000 and all(_value(x,t[5:-1]) for x in v)
    if operation not in OPERATIONS or not isinstance(values,list):
        raise ValueError('Unknown VLC operation or arguments.')
    types,_=OPERATIONS[operation]
    if len(values)!=len(types) or any(not _value(v,t) for v,t in zip(values,types)):
        raise ValueError('VLC argument type mismatch.')
    for v,t in zip(values,types):
        strings = [v] if t=='text' else v if t=='list[text]' else []
        if any('\0' in s for s in strings): raise ValueError('VLC text cannot contain NUL.')
    ranges={'volume':(1,0,100),'rate':(1,1,3200),'seek':(1,0,2**63-1),
            'delay':(0,0,2**31-1),'parse':(1,1,2**31-1),'wait':(2,0,2**31-1),
            'audio_track':(1,-1,2**31-1),'subtitle_track':(1,-1,2**31-1)}
    if operation in ranges:
        i,lo,hi=ranges[operation]
        if not lo<=values[i]<=hi: raise ValueError('VLC integer out of range.')
    if operation=='playlist' and not values[1]: raise ValueError('Playlist cannot be empty.')
    if operation=='wait' and values[1] not in {'playing','paused','stopped','ended'}:
        raise ValueError('Invalid VLC wait state.')
    if operation=='output':
        import re
        if values[1] not in {'file','http','udp'}: raise ValueError('Invalid VLC output mode.')
        if not re.fullmatch('[A-Za-z0-9_]+',values[3]) or any(not re.fullmatch('[A-Za-z0-9_]*',v) for v in values[4:6]):
            raise ValueError('Invalid container/codec.')
        if any(not 0<=v<=1000000 for v in values[6:]): raise ValueError('VLC bitrate out of range.')

class VLCExecutor:
    def __init__(self, vlc_dir=None, base_dir=None, startup_timeout_ms=10000, headless=False,
                 cancel_event=None, on_event=None, windows=None, bridge_path=None):
        if type(startup_timeout_ms) is not int or not 0<startup_timeout_ms<=2**31-1:
            raise ValueError('Positive bounded startup timeout required.')
        self.config={'vlc_dir':str(vlc_dir or os.environ.get('SHIPMB_VLC_DIR','')),
                     'base_dir':str(Path(base_dir or Path.cwd()).resolve()),
                     'startup_timeout_ms':startup_timeout_ms,'headless':bool(headless),'windows':windows or {}}
        self.bridge_path=bridge_path or os.environ.get('SHIPMB_VLC_BRIDGE')
        self.cancel_event,self.on_event=cancel_event,on_event
        self._lib=self._handle=None
        self._lock=threading.Lock()
    def _load(self):
        if self._handle: return
        path=self.bridge_path or str(Path(__file__).with_name('native')/'shipmb_vlc.dll')
        if not Path(path).is_file():
            raise ValueError('VLC execution requires shipmb_vlc.dll; build the native shipmb_vlc target and set SHIPMB_VLC_BRIDGE. Compilation needs no DLL.')
        lib=ctypes.CDLL(str(Path(path).resolve()))
        lib.smb_vlc_create.argtypes=[ctypes.c_char_p];lib.smb_vlc_create.restype=ctypes.c_void_p
        lib.smb_vlc_last_error.argtypes=[];lib.smb_vlc_last_error.restype=ctypes.c_char_p
        lib.smb_vlc_invoke.argtypes=[ctypes.c_void_p,ctypes.c_char_p,ctypes.c_char_p];lib.smb_vlc_invoke.restype=ctypes.c_char_p
        lib.smb_vlc_cancel.argtypes=[ctypes.c_void_p];lib.smb_vlc_cancel.restype=None
        lib.smb_vlc_destroy.argtypes=[ctypes.c_void_p];lib.smb_vlc_destroy.restype=None
        handle=lib.smb_vlc_create(json.dumps(self.config).encode())
        if not handle: raise ValueError(lib.smb_vlc_last_error().decode('utf-8','replace'))
        self._lib,self._handle=lib,handle
    def invoke(self, operation, values):
        validate_arguments(operation,values)
        with self._lock:
            if self.cancel_event is not None and self.cancel_event.is_set(): raise ValueError('VLC execution cancelled.')
            self._load()
            done=threading.Event()
            def watch():
                while not done.wait(.01):
                    if self.cancel_event.is_set(): self._lib.smb_vlc_cancel(self._handle);return
            watcher=threading.Thread(target=watch,daemon=True) if self.cancel_event is not None else None
            if watcher: watcher.start()
            try:
                result=json.loads(self._lib.smb_vlc_invoke(self._handle,operation.encode(),json.dumps(values).encode()))
            finally:
                done.set()
                if watcher: watcher.join()
            if not result['ok']: raise ValueError(result['error'])
            if self.on_event:
                for event in result.get('events',[]):
                    try: self.on_event(event)
                    except Exception as error: raise ValueError('VLC event callback failed: '+str(error)) from error
            return result['value']
    def close(self):
        with self._lock:
            if self._handle: self._lib.smb_vlc_destroy(self._handle);self._handle=None
    def __enter__(self): return self
    def __exit__(self,*args): self.close()
