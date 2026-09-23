# Media integration setup: ShipMBLang 0.5.0

This release bundles Python compiler 0.5.0 from compiler commit
1d44e1d5f5feb4e1629008edc3a80c9246dcbca2. Its manifest hashes every included
source/resource. A compiler push alone never changes this language snapshot.

## Python language path

Install ShipMBLang with Python 3.11+. FFmpeg and HyperFrames retain their existing
commands; see ffmpeg.md and hyperframes.md. VLC has the same typed instructions
as native0.5.0. Supply a matching optional shipmb_vlc.dll runtime adapter built
from the compiler's shipmb_vlc CMake target plus installed x64 LibVLC3.x.
The platform-independent Python wheel does not embed a platform-specific DLL.

```powershell
$env:SHIPMB_VLC_BRIDGE = 'C:/private-tools/shipmb_vlc.dll'
python -m shipmblang run --file examples/vlc-playback.shipmb --vlc-dir 'C:/Program Files/VideoLAN/VLC' --memory off --no-english-model
```

You can also pass --vlc-bridge explicitly. --vlc-startup-timeout sets seconds;
--headless selects dummy audio/video output for automated testing. The CLI closes
the adapter after execution. Python API callers use a context manager:

```python
from shipmblang import VLCExecutor, run_direct_program
with VLCExecutor(bridge_path='C:/private-tools/shipmb_vlc.dll', base_dir='C:/media') as vlc:
    result = run_direct_program(source, vlc_executor=vlc, memory=False, model_provider=None)
```

Compile-only commands do not instantiate media executors. Runtime validates the
whole artifact and requires explicitly supplied capabilities. Mixed FFmpeg/VLC
programs use bytecode0.5; FFmpeg-only remains0.4 and pure computation remains0.3.
Package version0.5.0 and these bytecode schema numbers serve different purposes.

## Native path

The public language repository includes its native launcher, not compiler source
or executable/DLL binaries. Configure SHIPMB_NATIVE_COMPILER with the privately
supplied0.5.0 executable. VLC, FFmpeg and HyperFrames now have native integration.
Native model translation and persistent meaning memory are not part of this
media-parity update.

Use --ffmpeg-path and --ffmpeg-timeout for native FFmpeg programs. HyperFrames
accepts hyperframes compile and hyperframes render; its resource directory can
be set with --resources or SHIPMB_HYPERFRAMES_RESOURCES. Native builds supply
vendor assets plus pinned node source/package files next to the executable.
MP4 rendering additionally needs the explicit Node SDK/Chrome/FFmpeg toolchain.
No output is silently overwritten. Installed codecs and actual device capabilities
depend on the host's external media libraries/tools.

## Evidence

The compiler release passed Python/native grammar and VM tests, full HyperFrames
artifact comparisons, real LibVLC playback and FFmpeg output tests, and native
MP4 rendering. Language tests verify capability routing, adapter cleanup,
compile-only behavior, and the staged/installed bundled snapshot. Windows x64 is
the verified native platform.
