# Media in ShipMB Notes

Implemented locally September 23, 2026 against the unchanged bundled compiler
0.5.0 (`1d44e1d5f5feb4e1629008edc3a80c9246dcbca2`).

## Use it

Open **Media…** on desktop or **Media & files** on mobile. Add a selected clip,
sound or image. Conversion and composition starters create a new note and copy
its selected asset; your original text stays saved. Choose **Program** for
conversion or **Video composition** for a film. Check compiles without running
media tools. Run submits that exact revision; editing afterward labels the result
as earlier text. Stop cancels the owned worker and its child processes.

The title-card starter needs no imported assets. With rendering configured, it
produces a one-second, 640×360, 24-fps MP4. Play a completed result, save/share a
copy, or export the note and media together as a ZIP. Desktop SQLite backups
alone do not contain media: also preserve the adjacent `media` directory.

Windows preview embeds VLC in a persistent player with play, pause, stop, seek,
and volume. Mobile downloads authorized media and plays it on the device using
Expo Video. Image previews use the native Image component. Scripted VLC commands
are not enabled in background jobs; use the preview controls.

## Configure tools explicitly

Use Python 3.11+, FFmpeg/ffprobe, and Node 22+ for rendering. Set these environment
variables in the process that launches Notes or its private service:

```powershell
$env:SHIPMB_FFMPEG_PATH = 'C:\tools\ffmpeg\bin\ffmpeg.exe'
$env:SHIPMB_FFPROBE_PATH = 'C:\tools\ffmpeg\bin\ffprobe.exe'
$env:SHIPMB_NODE_PATH = 'C:\Program Files\nodejs\node.exe'
$env:SHIPMB_VLC_DIR = 'C:\Program Files\VideoLAN\VLC'
$env:SHIPMB_VLC_BRIDGE = 'C:\tools\shipmb\shipmb_vlc.dll'
$env:SHIPMB_RENDERER_ROOT = 'C:\tools\shipmb-notes-renderer\0.5.0'
python -m shipmblang.media_setup --root 'C:\tools\shipmb-notes-media'
python -m shipmblang.notebook
```

Replace example paths with your installed binaries. The VLC bridge must match
the compiler 0.5.0 Windows x64 build and installed LibVLC 3.x. Setup installs
the bundled renderer lockfile into the writable renderer root, using `npm ci`.
It leaves package resources unchanged. Nothing installs during app launch or
Check. Media setup reports conversion, desktop playback, and rendering separately.
If `SHIPMB_RENDERER_ROOT` is omitted, the setup destination is
`<root>/_renderer/0.5.0`; use the same media root as the app or service.

For mobile, configure the existing private service token and origin as described
in [the mobile README](../apps/mobile/README.md), plus `SHIPMB_MEDIA_ROOT` for
persistent server files. The renderer override can be shared with desktop Notes.
Each token gets a separate hashed storage namespace; changing tokens does not
automatically migrate its media. Every upload, status, cancellation, archive,
and download route requires authentication. Notes remain local until explicitly
sent by Check/Run or selected-file upload. Running jobs survive a phone disconnect;
Refresh retrieves the latest job. Retrying an uncertain submission reuses its ID.

This is a paired private service, not a public multi-user hosting platform.
Use HTTPS for release clients. Authentication, account recovery, deployment
isolation, and shared-host quotas need a production service design before public
store distribution. Do not publish this development server directly.

## Execution limits

- Imported files: 100 MiB each; supported containers are MP4/MOV, WebM/MKV,
  WAV/MP3/M4A/OGG and PNG/JPEG. Names are replaced with opaque IDs; original names
  remain in the manifest. Container signatures are checked, not full validity.
- One active job per note and two per service manager. Jobs time out after ten
  minutes. Project media has a monitored 1 GiB limit; monitoring may overshoot
  briefly before termination. Windows workers also have a 4 GiB job memory limit
  and a 64-process ceiling. Old results are retained; export/archive them manually.
- FFmpeg operates only on imported files and fresh `outputs/name.ext` results.
  Explicit demuxers and file-only protocols reject URL/playlist/device inputs.
  Supported options cover codecs, numeric timing/rate parameters, audio/video
  suppression, preset, and pixel format. Arbitrary filters, global options and
  overwriting are intentionally unavailable in Notes.
- Compositions are limited to 1920 pixels per side and 120 seconds. They use
  imported media only. Rendering reports phases rather than a fabricated percent.
- Browser downloads are capped at 100 MiB. Use desktop export for larger archives.
  Native temporary previews are removed after replacement/closing; operating
  system cache eviction can also remove downloaded previews.
- Check validates compiler grammar. Runtime tool availability, paths, and Notes
  adapter restrictions may still reject a program that compiles successfully.

These boundaries constrain supported operations; they are not an OS sandbox
against vulnerabilities in native media decoders. Use a dedicated service account
for a remotely reachable deployment.

## Verification and remaining acceptance

Automated checks cover compile-only behavior, snapshot matching, idempotency,
owned-process cancellation, imported-path and option restrictions, malformed
requests, authenticated downloads, token ownership, and ZIP contents. A real
FFmpeg test converts a clip whose original name contains spaces and Unicode.
Run them with configured FFmpeg/ffprobe:

```powershell
$env:SHIPMB_MEMORY = 'off'
python -X utf8 -m unittest discover -s tests -q
cd apps/mobile
npm run lint
npm run typecheck
npm test
npm run export
```

All 133 Python tests passed, along with nine mobile tests.
On this Windows host, real conversion and title-card rendering completed.
A clean installed-wheel smoke test independently converted an imported clip
and rendered a 640×360 one-second composition containing exactly 24 frames.
Desktop panel startup, Check, status display, and close passed a Tk smoke test.
A separate audio composition produced H.264 video with AAC audio. Cancelling an
active render terminated its owned process tree. A native VLC test accepted the
Tk host window and reported playing, paused, sought/resumed, and stopped states;
human visual/audio confirmation of desktop playback remains outstanding.

In the browser UI, Check, render, authorized result download, and playback passed
in Brave. The in-app browser crashed during playback, so it is not accepted as
a playback target. Automated file picking in Brave was blocked by extension file
access; the upload API was tested directly, but picker acceptance remains manual.

Lint, TypeScript checks, mobile persistence tests, and iOS/Android/web JavaScript
exports passed. These exports are not signed native apps. Real iOS and Android
upload, playback/audio, sharing, cancellation, disconnect recovery, and offline
editing acceptance still need development builds and physical devices. No store
submission, public deployment, or GitHub push is part of this local delivery.

SDK references used: [Expo 57 filesystem](https://docs.expo.dev/versions/v57.0.0/sdk/filesystem-legacy/),
[Expo 57 video](https://docs.expo.dev/versions/v57.0.0/sdk/video/),
[Expo 57 document picker](https://docs.expo.dev/versions/v57.0.0/sdk/document-picker/).
