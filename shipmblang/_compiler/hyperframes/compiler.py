"""Defined English -> validated, frame-aligned HyperFrames composition."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import html
import json
import re

from ..limits import MAX_SOURCE_CHARS

VERSION = "1"
Q = r'"(?:[^"\\\r\n]|\\["\\/bfnrt]|\\u[0-9a-fA-F]{4})*"'
N = r'-?\d+(?:\.\d+)?'
RULES = [
    ("composition", rf'Create a video at (\d+) by (\d+) pixels and (\d+) frames per second'),
    ("scene", rf'Add scene ({Q}) lasting ({N}) seconds?'),
    ("background", rf'Set the background of scene ({Q}) to ({Q})'),
    ("element", rf'(Show text|Show image|Show video|Play audio) ({Q}) as ({Q}) in scene ({Q})(?: starting at ({N}) seconds?)?(?: lasting ({N}) seconds?)?'),
    ("position", rf'Place ({Q}) at ({N}) by ({N}) pixels'),
    ("size", rf'Set the size of ({Q}) to ({N}) by ({N}) pixels'),
    ("color", rf'Set the color of ({Q}) to ({Q})'),
    ("font", rf'Set the font size of ({Q}) to ({N}) pixels'),
    ("volume", rf'Set the volume of ({Q}) to ({N})'),
    ("fade", rf'Fade (in|out) ({Q}) over ({N}) seconds?'),
]
RULES = [(kind, re.compile(pattern, re.I)) for kind, pattern in RULES]


def diagnostic(message, span=None, *, level="error", code="SMBHF001"):
    return {"level": level, "code": code, "message": message, "span": span}


def _sentences(source):
    """Split on unquoted periods/newlines; retain decimals and source spans."""
    start = 0
    quoted = escaped = False
    for i, char in enumerate(source):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quoted:
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif not quoted and (char in "\r\n" or (char == "." and not (
                i > 0 and source[i - 1].isdigit() and i + 1 < len(source) and source[i + 1].isdigit()))):
            raw = source[start:i]
            if raw.strip():
                left = start + len(raw) - len(raw.lstrip())
                yield raw.strip(), {"start": left, "end": i - len(raw) + len(raw.rstrip())}
            start = i + 1
    raw = source[start:]
    if raw.strip():
        yield raw.strip(), {"start": start + len(raw) - len(raw.lstrip()), "end": len(source.rstrip())}


def compile_hyperframes(source):
    """Compile without I/O, model calls, execution, or persistent memory writes."""
    if not isinstance(source, str):
        raise TypeError("source must be a string")
    if len(source) > MAX_SOURCE_CHARS:
        raise ValueError(f"Source exceeds {MAX_SOURCE_CHARS} characters.")
    diagnostics, nodes = [], []
    for text, span in _sentences(source):
        for kind, rule in RULES:
            match = rule.fullmatch(text)
            if match:
                args = [json.loads(v) if v and v.startswith('"') else v for v in match.groups()]
                nodes.append({"kind": kind, "args": args, "span": span})
                break
        else:
            diagnostics.append(diagnostic("Unsupported video instruction.", span))
        if len(nodes) + len(diagnostics) > 2000:
            diagnostics.append(diagnostic("At most 2000 video instructions are supported."))
            break
    spec = {"width": 1920, "height": 1080, "fps": 30, "scenes": [], "elements": []}
    scenes, elements = {}, {}

    def error(message, node):
        diagnostics.append(diagnostic(message, node["span"]))

    declarations = [n for n in nodes if n["kind"] == "composition"]
    if len(declarations) > 1:
        error("Declare the video dimensions and frame rate only once.", declarations[1])
    if declarations:
        w, h, fps = map(int, declarations[0]["args"])
        if not (2 <= w <= 7680 and 2 <= h <= 7680 and w % 2 == h % 2 == 0 and 1 <= fps <= 120):
            error("Dimensions must be even integers from 2 to 7680; fps must be 1 to 120.", declarations[0])
        else:
            spec.update(width=w, height=h, fps=fps)

    def frames(value, node):
        number = Decimal(value) * spec["fps"]
        rounded = number.to_integral_value(rounding=ROUND_HALF_UP)
        if number != rounded:
            diagnostics.append(diagnostic(f"Timing {value}s rounded to frame {rounded} at {spec['fps']} fps.", node["span"], level="warning", code="SMBHF002"))
        return int(rounded)

    offset = 0
    for node in nodes:
        if node["kind"] != "scene":
            continue
        name, seconds = node["args"]
        duration = frames(seconds, node)
        if not name or name in scenes:
            error("Scene names must be nonempty and unique.", node)
            continue
        if duration <= 0 or Decimal(seconds) <= 0:
            error("Scene duration must be positive and at least one frame.", node)
            continue
        scene = {"name": name, "id": f"scene-{len(scenes)}", "start": offset, "duration": duration, "background": "#000000", "span": node["span"]}
        scenes[name] = scene
        spec["scenes"].append(scene)
        offset += duration
    spec["duration"] = offset
    if not scenes:
        diagnostics.append(diagnostic("At least one scene is required."))
    if offset > spec["fps"] * 3600:
        diagnostics.append(diagnostic("Composition duration cannot exceed one hour."))

    for node in nodes:
        if node["kind"] != "element":
            continue
        verb, value, name, scene_name, start, duration = node["args"]
        scene = scenes.get(scene_name)
        if not name or name in elements:
            error("Element names must be nonempty and unique.", node)
            continue
        if scene is None:
            error(f"Unknown scene {scene_name!r}.", node)
            continue
        local_start = frames(start or "0", node)
        length = frames(duration, node) if duration is not None else scene["duration"] - local_start
        if Decimal(start or "0") < 0 or local_start < 0 or length <= 0 or local_start + length > scene["duration"]:
            error("Element timing must fit inside its scene and last at least one frame.", node)
            continue
        kind = verb.lower().split()[1]
        if not value or (kind != "text" and (":" in value or value.startswith(("/", "\\")) or ".." in value.replace("\\", "/").split("/"))):
            error("Content must be nonempty; media requires a relative local path without traversal.", node)
            continue
        element = {"id": f"element-{len(elements)}", "name": name, "kind": kind, "value": value, "scene": scene_name,
                   "start": scene["start"] + local_start, "duration": length, "x": spec["width"] / 2,
                   "y": spec["height"] / 2, "width": spec["width"], "height": spec["height"],
                   "color": "#ffffff", "font_size": 72, "volume": 1, "fades": {}, "span": node["span"]}
        elements[name] = element
        spec["elements"].append(element)

    assigned = set()
    for node in nodes:
        kind, args = node["kind"], node["args"]
        if kind in {"composition", "scene", "element"}:
            continue
        name = args[1] if kind == "fade" else args[0]
        obj = scenes.get(name) if kind == "background" else elements.get(name)
        if obj is None:
            error(f"Unknown {'scene' if kind == 'background' else 'element'} {name!r}.", node)
            continue
        key = ("scene" if kind == "background" else "element", name, kind, args[0].lower() if kind == "fade" else "")
        if key in assigned:
            error("Each property may be specified only once.", node)
            continue
        assigned.add(key)
        if kind in {"background", "color"}:
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", args[1]):
                error("Colors must be six-digit hex strings such as \"#102030\".", node)
            elif kind == "color" and obj["kind"] != "text":
                error("Text color applies only to text.", node)
            else:
                obj[kind] = args[1].lower()
        elif kind in {"position", "size"}:
            values = list(map(float, args[1:]))
            if obj["kind"] == "audio" or any(abs(v) > 7680 for v in values) or (kind == "size" and min(values) <= 0):
                error("Visual coordinates must be within +/-7680 and sizes must be positive.", node)
            else:
                obj.update(zip(("x", "y") if kind == "position" else ("width", "height"), values))
        elif kind == "font":
            size = float(args[1])
            if obj["kind"] != "text" or not 1 <= size <= 1000:
                error("Font size applies to text and must be 1 to 1000 pixels.", node)
            else:
                obj["font_size"] = size
        elif kind == "volume":
            volume = float(args[1])
            if obj["kind"] != "audio" or not 0 <= volume <= 1:
                error("Volume applies to audio and must be between 0 and 1.", node)
            else:
                obj["volume"] = volume
        elif kind == "fade":
            length = frames(args[2], node)
            if obj["kind"] == "audio" or length <= 0 or length > obj["duration"]:
                error("Visual fades must last at least one frame and fit inside the element.", node)
            else:
                obj["fades"][args[0].lower()] = length
    for element in spec["elements"]:
        if sum(element["fades"].values()) > element["duration"]:
            diagnostics.append(diagnostic("Fade-in and fade-out may not overlap.", element["span"]))
    failed = any(d["level"] == "error" for d in diagnostics)
    artifact = None if failed else {"producer": "shipmbcompiler", "target": "hyperframes", "version": VERSION, "source": source,
                                   "composition": spec, "files": {"index.html": emit_html(spec)}}
    return {"status": "error" if failed else "compiled", "syntax_tree": {"kind": "VideoProgram", "children": nodes},
            "diagnostics": diagnostics, "target_code": artifact}


def media_path(element):
    # Preserve an extension for decoder selection; source paths never become markup.
    suffix = element["value"].replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)
    extension = suffix[-1].lower() if len(suffix) == 2 and re.fullmatch(r"[a-zA-Z0-9]{1,10}", suffix[-1]) else "bin"
    return f"assets/{element['id']}.{extension}"


def emit_html(spec):
    fps = spec["fps"]
    sec = lambda frame: format(frame / fps, ".9f").rstrip("0").rstrip(".") or "0"
    w, h = spec["width"], spec["height"]
    lines = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
             f'<meta name="viewport" content="width={w}, height={h}">',
             '<title>ShipMBLang video</title><script src="vendor/gsap.min.js"></script>',
             '<style>@font-face{font-family:Inter;src:url("vendor/inter-latin-400-normal.woff2")}*{box-sizing:border-box}body{margin:0;font-family:Inter,sans-serif} .clip{position:absolute} .text{display:flex;align-items:center;justify-content:center;text-align:center;white-space:pre-wrap;overflow-wrap:anywhere}</style></head><body>',
             f'<div id="main" data-composition-id="main" data-width="{w}" data-height="{h}" data-duration="{sec(spec["duration"])}" style="position:relative;width:{w}px;height:{h}px;overflow:hidden">']
    for scene in spec["scenes"]:
        lines.append(f'<div id="{scene["id"]}" class="clip" data-start="{sec(scene["start"])}" data-duration="{sec(scene["duration"])}" data-track-index="0" style="inset:0;background:{scene["background"]}"></div>')
    animations = []
    for track, e in enumerate(spec["elements"], 1):
        attrs = f'id="{e["id"]}" class="clip{ " text" if e["kind"] == "text" else ""}" data-start="{sec(e["start"])}" data-duration="{sec(e["duration"])}" data-track-index="{track}"'
        style = f'left:{e["x"] - e["width"] / 2}px;top:{e["y"] - e["height"] / 2}px;width:{e["width"]}px;height:{e["height"]}px;object-fit:contain'
        if e["kind"] == "text":
            lines.append(f'<div {attrs} style="{style};color:{e["color"]};font-size:{e["font_size"]}px">{html.escape(e["value"])}</div>')
        elif e["kind"] == "image":
            lines.append(f'<img {attrs} src="{media_path(e)}" style="{style}" alt="">')
        elif e["kind"] == "video":
            lines.append(f'<video {attrs} src="{media_path(e)}" style="{style}" muted playsinline></video>')
        else:
            lines.append(f'<audio {attrs} src="{media_path(e)}" data-volume="{e["volume"]}"></audio>')
        for direction, length in e["fades"].items():
            when = e["start"] if direction == "in" else e["start"] + e["duration"] - length
            method = "fromTo" if direction == "in" else "to"
            initial = '{opacity:0},' if direction == "in" else ""
            animations.append(f'tl.{method}("#{e["id"]}",{initial}{{opacity:{1 if direction == "in" else 0},duration:{sec(length)},ease:"none",immediateRender:false}},{sec(when)});')
        if e["kind"] == "video":
            # Producer 0.8.66 includes the last video frame at the end boundary.
            # Make our [start, end) contract explicit on its injected visual layer.
            animations.append(f'tl.to("#{e["id"]}",{{opacity:0,duration:0,immediateRender:false}},{sec(e["start"] + e["duration"])});')
    lines.extend(['</div><script>window.__timelines=window.__timelines||{};const tl=gsap.timeline({paused:true});',
                  *animations, 'window.__timelines.main=tl;</script></body></html>'])
    return "\n".join(lines) + "\n"
