# Media programs

Media instructions use the default general English pipeline. Install FFmpeg and
ffprobe separately to execute them; compilation does not process media or require
those executables. ShipMBLang does not download either tool.

Compile the [transcoding example](../examples/ffmpeg-transcode.shipmb):

```powershell
python -m shipmblang compile --file examples/ffmpeg-transcode.shipmb --memory off --no-english-model
```

Place `input.mp4` beside the source file, then explicitly run it:

```powershell
python -m shipmblang compile --file examples/ffmpeg-transcode.shipmb --run --ffmpeg-path C:/tools/ffmpeg/bin/ffmpeg.exe --ffprobe-path C:/tools/ffmpeg/bin/ffprobe.exe --ffmpeg-timeout 120 --memory off --no-english-model
```

The `run` command also opts into execution. Relative media paths resolve from the
source file's directory; inline programs and standard input use the current
directory. The positive timeout in seconds limits execution. The FFmpeg path also
selects command help when model translation needs it. Without explicit paths, the executor reads
`SHIPMB_FFMPEG_PATH` and `SHIPMB_FFPROBE_PATH`, then searches `PATH`.
FFmpeg and ffprobe must be available when their operations execute.

## Canonical instructions

```text
Let source be "input.mp4".
Run FFmpeg:
Input clip from source.
Input option "-ss" for clip with 2.
Output result to "preview.mp4".
Output option "-c:v" for result with "libx264".
Output option "-t" for result with 5.
Map "0:v:0" to result.
Global option "-loglevel" with "warning".
End FFmpeg.
```

Input/output names identify option scopes. Options without values omit `with`.
Use `Filter graph "[0:v]scale=320:240[v]".` with `Map "[v]" to result.`
for a named filtered stream. Add `Overwrite outputs.` only when replacing existing
output files is intended. Text and integer expressions can supply option values.
Media blocks can use variables and appear inside loops and functions.

Supported canonical English compiles offline. Broader wording uses the configured
English model, followed by compiler validation, just like computation. Review the
interpretation when the wording needs translation; compilation alone does not
authorize execution.

## Python

```python
from shipmblang import FFmpegExecutor, compile_direct_program, run_direct_program

source = open("examples/ffmpeg-transcode.shipmb", encoding="utf-8").read()
compiled = compile_direct_program(source, memory=False, model_provider=None)
executor = FFmpegExecutor(base_dir="examples", timeout=120)
executed = run_direct_program(
    source, memory=False, model_provider=None, ffmpeg_executor=executor,
)
```

Media programs emit bytecode 0.4; computation-only programs retain bytecode 0.3.
Python callers must explicitly pass an executor for media execution; omitting it
produces a runtime diagnostic before the program executes. `executor.probe(path)`
is an explicit Python operation returning ffprobe JSON. There is currently no
probe instruction in the English grammar.

General English translation includes the compiler's reference FFmpeg command
knowledge. `compile_direct_program(..., ffmpeg_catalog=catalog)` can also forward
an already obtained installed-build catalogue to the configured model frontend.
When media wording needs model translation, the frontend may query the installed
FFmpeg's help for command knowledge, using the CLI's explicit executable path
when supplied. It falls back to reference knowledge when unavailable. This metadata
lookup does not process media. Deterministic compilation needs no executable.

The compiler owns grammar, job validation, executable invocation, and diagnostics.
ShipMBLang forwards those results and supplies CLI configuration.
