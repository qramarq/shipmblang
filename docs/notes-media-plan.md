# ShipMB Notes: media integration with ShipMBLang 0.5.0

Prepared September 23, 2026. This is an implementation plan; the media controls
described below have not been added to the app in this update.

Baseline: language commit `4540943ee833d56241a389cd017dbad347a1e51b`, bundling
compiler `1d44e1d5f5feb4e1629008edc3a80c9246dcbca2` (0.5.0). The app has a Python/Tk
desktop interface and an Expo mobile interface backed by a Python service.

## Product direction

Keep writing the center of the app. A new note asks “What would you like to make?”
and offers a few working starters. Check explains problems without executing;
Run displays results. Media adds an optional Assets panel, preview, and export
controls to this same workflow instead of a separate complex editor.

Start with three concrete workflows:

1. Choose a clip, write supported instructions to convert it, run, and play the
   result inside the app (FFmpeg).
2. Choose audio/video, then play, pause, seek, and adjust volume in an embedded
   player (VLC on Windows desktop).
3. Write a title-card composition, check it, render a short MP4, preview and
   export it (HyperFrames).

Present natural-language goals separately from executable templates. Every
starter inserted into the editor must compile against the bundled snapshot.
Do not imply arbitrary prose can express operations the grammar does not support.

## What 0.5.0 already provides

`shipmblang.compile_direct_program` compiles general/FFmpeg/VLC instructions.
`run_direct_program` accepts explicit `FFmpegExecutor` and `VLCExecutor` adapters.
Compiled artifacts declare required capabilities; use those declarations to
select adapters rather than inferring capabilities from the version string.

The public HyperFrames functions are `compile_hyperframes`,
`write_hyperframes_project`, and `render_hyperframes_project`. HyperFrames is a
separate composition target, not automatically another general-program opcode.
Select Program or Video composition explicitly; avoid silently switching parser
after a failed compile. Combined workflows may use linked steps later.

FFmpeg already supports progress and cancellation callbacks. VLC has typed
operations, event delivery, cancellation, and a Windows host-window map. Its
bridge loads only on execution. HyperFrames writes a validated project with
copied assets and renders MP4 through its optional Node bridge.

Relevant current limitations:

- Desktop execution invokes the CLI through stdin, with package-directory cwd
  and a 20-second timeout. That is unsuitable as a media workspace or render
  lifecycle. The CLI closes VLC on completion, so playback cannot outlive it.
- The mobile service runs synchronous requests, with a 20-second execution
  timeout. It currently has no asset upload, job status, cancellation, or result
  download endpoints. The client uses a 25-second request timeout.
- Python HyperFrames rendering has timeout cleanup but no public progress or
  cancellation parameter. Its renderer resources are resolved beside the
  installed module; a user-writable renderer installation is a packaging change
  to design and verify, not an existing option to advertise.
- VLC events are drained through operations; do not assume an independent live
  event subscription. The app needs modest state polling or a bridge extension.
- A Windows DLL cannot run inside an iOS/Android JavaScript app.

## Phase 1 — assets and background jobs

Create an app-managed workspace per note/project. Keep note text and existing
SQLite/AsyncStorage data intact; store media beside it and reference it by asset
ID and a safe relative filename. Import files explicitly. Provide Save as for
exports. Notes and assets need a documented backup/export path together.

Compile first and display diagnostics with original source positions. At Run,
use an immutable source revision plus compiler manifest identity. Worker output
belongs to that revision even if the user edits the note while it runs.

Run media jobs in owned worker processes so writing stays responsive and native
failures do not close the notes interface. Use structured messages for job ID,
state, progress, diagnostics, and output IDs. Begin with one active media job per
project; a broker, distributed queue, and scheduling cluster are unnecessary.
Own the process tree, enforce bounded output/time/resource limits, and stop all
children on cancellation, timeout, app close, or worker failure. A UI Stop button
must cancel work, not merely stop waiting for its result.

Constrain execution at the actual adapter/file boundary to imported input assets
and designated output locations, including paths computed inside the program.
Do not rely on cwd alone or a scan of source text. Initially allow local assets;
network streaming and arbitrary device sources require a later explicit workflow.
Existing output files are preserved by default.

Add a small Media setup screen listing readiness separately for playback,
conversion, and rendering. Show an actionable missing-tool message; do not
download or launch dependencies when the app starts or when Check is pressed.

Acceptance: a long job leaves editing responsive; cancelling leaves no media
child process; stale output is labelled; path escapes and output collisions fail;
existing notes still open, save, and back up.

## Phase 2 — FFmpeg conversion and export

Connect `FFmpegExecutor` to the job worker, setting its explicit `base_dir`,
tool paths, timeout, cancellation event, and progress callback. Preserve its
structured argument construction. Reuse its probe support for input/output
metadata. Derive percentage only when duration/progress permits it; otherwise
show elapsed time and activity rather than an invented percentage.

UI: Add media -> choose a tested conversion starter -> Check -> Run -> result
card with format/duration and Play/Save as. Implement extraction or trimming
starters only after their exact grammar and execution are verified.

Acceptance: generate a small input fixture, convert through the app, inspect the
output with ffprobe, test a missing tool, a failed conversion, cancellation,
spaces/Unicode in filenames, and refusal to overwrite an existing result.

## Phase 3 — VLC playback inside Windows desktop

Create a real native preview surface, then pass its Windows handle through
`VLCExecutor(windows={player_alias: hwnd}, ...)`. Keep the player owned by the
preview session until Stop/Close; do not use the short-lived CLI Run process as
the player. Serialize player commands and move UI updates onto the UI thread.

The first implementation can use a dedicated preview worker which owns its
native playback window/session. Prototype embedding into the Tk surface early;
cross-process HWND lifetime, focus, resize, and shutdown behavior must be proven
before committing to that arrangement. If embedding needs a same-process owner,
isolate compilation/conversion workers and document the native crash boundary.

Expose play/pause, seek, volume, elapsed/duration, and clear ended/error states.
Link converted/rendered results to this same player. Distinguish preview controls
from an explicitly running VLC program: closing a scripted player ends that
script's player; the app may open the resulting asset in its own preview session.

Acceptance: visible video and audible audio; pause/seek/volume match state;
repeated open/close frees handles; closing a note stops its preview; a missing or
wrong-architecture DLL produces an actionable message. Test the app binary path
with separately installed matching LibVLC 3.x, not only a developer checkout.

## Phase 4 — HyperFrames compositions

Add an explicit Video composition mode with tested text/image/audio/video
starters. Check calls `compile_hyperframes` without launching media tools.
Project creation calls `write_hyperframes_project` with the note's assets root
and a fresh output directory. A compact scene/timing summary can help users
understand what their prose describes.

Render through a background job, then play the MP4 in the common preview area.
Initially use rendered video as the faithful preview. Live HTML preview would
require an embedded browser, controlled project origin, and renderer/timing
integration; it is a separate follow-up, not a Tk feature already available.

Resolve the current renderer-resource installation constraint before packaging:
use a pinned app-managed Node renderer directory and a tested resource override
or adapter boundary. Keep dependency setup explicit. Add true worker-tree
cancellation and phase reporting; show indeterminate progress where the bridge
does not report a measurable percentage.

Acceptance: render a known 24-frame composition through the app, verify dimensions,
duration/frame count and sound, handle missing assets and tools, cancel cleanly,
and preserve existing project/output files.

## Phase 5 — mobile media workflow

Keep the same 0.5.0 compiler snapshot handshake. Upload selected assets explicitly
to a paired desktop/private service and return opaque IDs; phone-local paths are
not server paths. Extend the service with bounded uploads, asynchronous job
creation/status/cancel, and authorized output downloads. Polling is sufficient
for the first version. Add per-user ownership before multi-user deployment.

Mobile playback uses a player supported by the project's Expo SDK for downloaded
or streamed results. This does not embed Windows LibVLC on the phone. Distinguish
“Play on this device” from “Run VLC on connected computer.” Device-side VLC
execution would be a separate native-platform implementation and validation
project. Editing remains offline; remote media execution needs the service.

The current app uses Expo SDK 57. Verify matching SDK documentation and package
versions before adding any player/file-picker modules; older SDK examples are
not evidence of SDK 57 compatibility.

Acceptance: selected-file upload, run, progress, cancel, download and playback on
real iOS/Android devices; reject snapshot mismatch and cross-user asset access;
recover from disconnect/retry without duplicate jobs; preserve offline notes.

## Delivery order and scope

Finish the 0.5.0 default runtime and writing-oriented interface first. Then ship
assets/jobs with one FFmpeg conversion, followed by Windows VLC preview, then
HyperFrames rendering, then the mobile job workflow. Each phase should stand on
its own and include a small reproducible end-to-end example.

No media integration is claimed complete by the interface refresh. Current
Windows x64 compiler validation does not establish mobile or macOS/Linux media
runtime support. User-facing copy should describe the installed capabilities.

## Evidence

Source inspected at the baseline commit: `shipmblang/notebook.py`,
`mobile_service.py`, `pipelines.py`, `hyperframes.py`, `_compiler/vlc.py`,
`_compiler/ffmpeg.py`, `_compiler/hyperframes/project.py`, and
`apps/mobile/src/compiler-snapshot.json`. Compiler native sources inspected at
`1d44e1d`: `cpp/src/vlc.cpp` and `cpp/src/vlc_bridge.cpp`.

- [Language baseline](https://github.com/qramarq/shipmblang/commit/4540943ee833d56241a389cd017dbad347a1e51b)
- [Compiler 0.5.0](https://github.com/qramarq/shipmblang-compiler/commit/1d44e1d5f5feb4e1629008edc3a80c9246dcbca2)
- [LibVLC 3.0 media-player API](https://videolan.videolan.me/vlc-3.0/libvlc__media__player_8h.html) documents Windows host-window embedding.
- [FFmpeg CLI documentation](https://www.ffmpeg.org/ffmpeg.html) documents machine-readable progress reporting.
