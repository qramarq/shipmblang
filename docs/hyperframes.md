# HyperFrames video projects

The `hyperframes` commands use the bundled compiler's deterministic video
grammar. They do not translate prompts with a language model. Normal `compile`
and `run` commands continue to produce and execute ShipMB bytecode.

Save supported video instructions in a UTF-8 file, then compile it:

```powershell
python -m shipmblang hyperframes compile clip.shipmb --out output/clip
```

For an included example, use `examples/hyperframes-title.shipmb`. A minimal
source file is:

```text
Create a video at 320 by 180 pixels and 24 frames per second.
Add scene "intro" lasting 1 second.
Show text "Hello" as "title" in scene "intro".
```

Compilation writes a standalone HTML project. Local media paths resolve relative
to the source file's directory; use `--asset-root DIRECTORY` to select another
root. Compiler diagnostics are returned as JSON. A failed compile does not call
the project writer. Compilation does not launch Node, FFmpeg or a renderer.

Rendering is a separate, explicit command and requires the optional Node
HyperFrames producer dependencies:

Install Node.js 22 or newer, FFmpeg and ffprobe on PATH. Install the renderer's pinned Node
dependencies explicitly in the bundled bridge directory (PowerShell):

```powershell
$bridge = python -c "from pathlib import Path; import shipmblang._compiler.hyperframes as h; print(Path(h.__file__).parent / 'node')"
npm ci --prefix "$bridge"
```

Dependency installation needs network access. The generated projects include
their JavaScript and font resources; writing them does not need that install.
The initial renderer produces MP4 files. Compilation refuses an existing project
directory, and rendering refuses an existing output file.

```powershell
python -m shipmblang hyperframes render output/clip --out output/clip.mp4 --timeout 300
```

Both commands accept `--output` and `-o` as aliases for `--out`. They print JSON
and return a nonzero exit code on failure. The compiler reports missing render
dependencies and render errors in its diagnostics. It does not install packages
automatically. Only render locally trusted projects.

The same APIs are available from Python:

```python
from shipmblang import (
    compile_hyperframes, write_hyperframes_project, render_hyperframes_project,
)

artifact = compile_hyperframes(source)
if artifact["status"] == "compiled":
    project = write_hyperframes_project(artifact, "output/clip", asset_root=".")
    # Rendering is optional and explicit after inspecting the written project.
    if project["status"] == "written":
        result = render_hyperframes_project("output/clip", "output/clip.mp4", timeout=300)
```

Python adapters preserve the compiler's results, including syntax trees,
diagnostics and target code. Older snapshots without HyperFrames support report
an actionable installation error.
