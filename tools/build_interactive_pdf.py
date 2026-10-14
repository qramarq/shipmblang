from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "output" / "pdf"
TMP_DIR = ROOT / "tmp" / "pdfs"
OUT_PDF = OUT_DIR / "shipmblang-interactive-workflows.pdf"
DRIP_IMAGE = ROOT / "assets" / "drip.png"

W, H = landscape(letter)
MARGIN = 42

INK = HexColor("#1b2430")
MUTED = HexColor("#5d6778")
LIGHT = HexColor("#f5f7fb")
LINE = HexColor("#d9e0ea")
NAVY = HexColor("#23395b")
TEAL = HexColor("#0f8b8d")
GREEN = HexColor("#3b8f5c")
AMBER = HexColor("#d99a27")
ROSE = HexColor("#c85168")
BLUE = HexColor("#3466af")
PURPLE = HexColor("#7257a9")
WHITE = colors.white


styles = {
    "body": ParagraphStyle(
        "body",
        fontName="Helvetica",
        fontSize=10.5,
        leading=14.2,
        textColor=INK,
        alignment=TA_LEFT,
    ),
    "small": ParagraphStyle(
        "small",
        fontName="Helvetica",
        fontSize=8.7,
        leading=11.3,
        textColor=MUTED,
        alignment=TA_LEFT,
    ),
    "tiny": ParagraphStyle(
        "tiny",
        fontName="Helvetica",
        fontSize=7.5,
        leading=9.2,
        textColor=MUTED,
        alignment=TA_LEFT,
    ),
    "card_title": ParagraphStyle(
        "card_title",
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=13.5,
        textColor=INK,
    ),
    "white": ParagraphStyle(
        "white",
        fontName="Helvetica",
        fontSize=10,
        leading=13,
        textColor=WHITE,
    ),
}


nav_items = [
    ("Start", "cover"),
    ("Map", "feature_map"),
    ("Pipeline", "pipeline"),
    ("Workflows", "workflow_debug"),
    ("Examples", "examples"),
    ("Checklist", "checklist"),
]


sections = [
    ("cover", "Start Here"),
    ("feature_map", "Feature Map"),
    ("pipeline", "Compiler Pipeline"),
    ("workflow_compile", "Workflow 1 - Describe A Program"),
    ("workflow_debug", "Workflow 2 - Debug A Real Error"),
    ("printurf_internals", "How printurf Works"),
    ("workflow_device", "Workflow 3 - Control Device Resources"),
    ("workflow_editor_mcp", "Workflow 4 - Editor And MCP"),
    ("examples", "Real World Examples"),
    ("onboarding", "ShipMB Onboarding"),
    ("checklist", "Interactive Checklist"),
]


def para(c: canvas.Canvas, text: str, x: float, y: float, w: float, h: float, style="body"):
    p = Paragraph(text, styles[style])
    _, used = p.wrap(w, h)
    p.drawOn(c, x, y + h - used)
    return used


def pill(c: canvas.Canvas, x: float, y: float, w: float, h: float, label: str, fill, stroke=None, text=WHITE):
    c.setFillColor(fill)
    c.setStrokeColor(stroke or fill)
    c.roundRect(x, y, w, h, 8, fill=1, stroke=1)
    c.setFillColor(text)
    c.setFont("Helvetica-Bold", 8.2)
    c.drawCentredString(x + w / 2, y + h / 2 - 3, label)


def card(c: canvas.Canvas, x: float, y: float, w: float, h: float, title: str, body: str, accent=TEAL):
    c.setFillColor(WHITE)
    c.setStrokeColor(LINE)
    c.roundRect(x, y, w, h, 8, fill=1, stroke=1)
    c.setFillColor(accent)
    c.roundRect(x, y + h - 7, w, 7, 4, fill=1, stroke=0)
    para(c, f"<b>{title}</b>", x + 14, y + h - 38, w - 28, 24, "card_title")
    para(c, body, x + 14, y + 15, w - 28, h - 56, "small")


def link_button(c: canvas.Canvas, x: float, y: float, w: float, h: float, label: str, dest: str, fill=WHITE, stroke=LINE, text=INK):
    c.setFillColor(fill)
    c.setStrokeColor(stroke)
    c.roundRect(x, y, w, h, 7, fill=1, stroke=1)
    c.setFillColor(text)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(x + w / 2, y + h / 2 - 3, label)
    c.linkRect("", dest, Rect=(x, y, x + w, y + h), relative=0, thickness=0)


def header(c: canvas.Canvas, section: str, page_no: int):
    c.setFillColor(WHITE)
    c.rect(0, H - 48, W, 48, fill=1, stroke=0)
    c.setStrokeColor(LINE)
    c.line(MARGIN, H - 49, W - MARGIN, H - 49)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(MARGIN, H - 29, "ShipMBLang Interactive Workflow Guide")
    c.setFont("Helvetica", 8)
    c.setFillColor(MUTED)
    c.drawRightString(W - MARGIN, H - 29, f"{section} / page {page_no}")

    x = W / 2 - 138
    for label, dest in nav_items:
        link_button(c, x, H - 36, 45, 20, label, dest, fill=LIGHT, stroke=LINE, text=NAVY)
        x += 49


def footer(c: canvas.Canvas):
    c.setStrokeColor(LINE)
    c.line(MARGIN, 28, W - MARGIN, 28)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 7.2)
    c.drawString(MARGIN, 15, "Interactive PDF: use the top navigation, outline/bookmarks, linked workflow cards, and fillable checklist fields.")
    c.drawRightString(W - MARGIN, 15, "Generated from the local ShipMBLang repo.")


def start_page(c: canvas.Canvas, anchor: str, title: str, page_no: int, outline_level=0):
    c.bookmarkPage(anchor)
    c.addOutlineEntry(title, anchor, level=outline_level, closed=False)
    header(c, title, page_no)
    footer(c)


def code_box(c: canvas.Canvas, x: float, y: float, w: float, h: float, text: str, title: str | None = None):
    c.setFillColor(HexColor("#101820"))
    c.setStrokeColor(HexColor("#334155"))
    c.roundRect(x, y, w, h, 8, fill=1, stroke=1)
    top = y + h - 16
    if title:
        c.setFillColor(HexColor("#b7f7e4"))
        c.setFont("Helvetica-Bold", 8.4)
        c.drawString(x + 12, top, title)
        top -= 17
    c.setFillColor(HexColor("#e7eef9"))
    c.setFont("Courier", 7.0)
    max_chars = max(28, int((w - 24) / 4.1))
    line_y = top
    for raw_line in text.strip("\n").splitlines():
        line = raw_line
        while len(line) > max_chars:
            c.drawString(x + 12, line_y, line[:max_chars])
            line = "  " + line[max_chars:]
            line_y -= 9
            if line_y < y + 12:
                return
        c.drawString(x + 12, line_y, line)
        line_y -= 9
        if line_y < y + 12:
            return


def arrow(c: canvas.Canvas, x1: float, y1: float, x2: float, y2: float, color=LINE):
    c.setStrokeColor(color)
    c.setLineWidth(1.4)
    c.line(x1, y1, x2, y2)
    c.setFillColor(color)
    if x2 >= x1:
        pts = [(x2, y2), (x2 - 7, y2 + 4), (x2 - 7, y2 - 4)]
    else:
        pts = [(x2, y2), (x2 + 7, y2 + 4), (x2 + 7, y2 - 4)]
    p = c.beginPath()
    p.moveTo(*pts[0])
    p.lineTo(*pts[1])
    p.lineTo(*pts[2])
    p.close()
    c.drawPath(p, fill=1, stroke=0)


def labeled_box(c: canvas.Canvas, x: float, y: float, w: float, h: float, title: str, body: str, fill=WHITE, accent=TEAL):
    c.setFillColor(fill)
    c.setStrokeColor(LINE)
    c.roundRect(x, y, w, h, 8, fill=1, stroke=1)
    c.setFillColor(accent)
    c.rect(x, y, 5, h, fill=1, stroke=0)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(x + 14, y + h - 19, title)
    para(c, body, x + 14, y + 10, w - 25, h - 34, "tiny")


def draw_cover(c: canvas.Canvas):
    c.bookmarkPage("cover")
    c.addOutlineEntry("Start Here", "cover", level=0, closed=False)
    c.setFillColor(HexColor("#f7fafc"))
    c.rect(0, 0, W, H, fill=1, stroke=0)
    c.setFillColor(NAVY)
    c.rect(0, 0, W, 120, fill=1, stroke=0)
    c.setFillColor(TEAL)
    c.rect(0, 120, W, 12, fill=1, stroke=0)
    c.setFillColor(AMBER)
    c.rect(0, 132, W, 5, fill=1, stroke=0)

    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 42)
    c.drawString(MARGIN, H - 122, "ShipMBLang")
    c.setFont("Helvetica-Bold", 18)
    c.setFillColor(TEAL)
    c.drawString(MARGIN, H - 154, "Interactive feature and workflow guide")
    para(
        c,
        "A visual walkthrough of how natural language syntax becomes ShipMBLangCore, "
        "bytecode, local runtime actions, editor commands, MCP tools, and real-world debugging or device workflows.",
        MARGIN,
        H - 230,
        440,
        54,
        "body",
    )
    quote = (
        "If the user can explain the program end to end in natural language syntax, "
        "ShipMB should be able to understand and convert that into runnable program form."
    )
    c.setFillColor(WHITE)
    c.setStrokeColor(LINE)
    c.roundRect(MARGIN, H - 318, 405, 70, 8, fill=1, stroke=1)
    para(c, quote, MARGIN + 16, H - 304, 373, 46, "body")

    if DRIP_IMAGE.exists():
        c.drawImage(str(DRIP_IMAGE), W - 310, H - 330, 220, 220, preserveAspectRatio=True, mask="auto")
    card(
        c,
        W - 330,
        146,
        265,
        105,
        "What this PDF does",
        "Use it as a product explainer, implementation walkthrough, and onboarding playbook. "
        "The top nav, outline, workflow cards, and checklist fields are clickable or fillable.",
        accent=ROSE,
    )

    x = MARGIN
    for label, dest in [("Feature Map", "feature_map"), ("Compiler Pipeline", "pipeline"), ("Real Examples", "examples"), ("Checklist", "checklist")]:
        link_button(c, x, 78, 108, 30, label, dest, fill=WHITE, stroke=HexColor("#7b8aa3"), text=NAVY)
        x += 118


def draw_contents(c: canvas.Canvas, page_no: int):
    start_page(c, "feature_map", "Feature Map", page_no)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 25)
    c.drawString(MARGIN, H - 94, "Feature Map")
    para(
        c,
        "ShipMBLang v0.1 is a natural programming layer with a deterministic compiler, a readable Core preview, a bytecode runtime, "
        "codebase-aware debugging, device-family libraries, and integration surfaces for editors and MCP clients.",
        MARGIN,
        H - 139,
        W - 2 * MARGIN,
        36,
        "body",
    )

    cards = [
        ("Natural source", "Users write normal instructions in `.shipmb`, `.shiplang`, the CLI, or editor selections.", TEAL, "workflow_compile"),
        ("Compiler trace", "Tokens, syntax tree, semantic model, declaration resolution, IR, optimized IR, target code, Core, and bytecode.", BLUE, "pipeline"),
        ("Core preview", "Readable ShipMBLangCore shows what the compiler understood before supported bytecode runs locally.", GREEN, "pipeline"),
        ("printurf()", "Raw errors, source files, stack traces, or diagnostics become structured Error / Cause / Fix explanations.", ROSE, "printurf_internals"),
        ("Device families", "`host`, `cuda`, `mps`, `browser`, and `embedded` resources can be selected from natural syntax or MCP.", AMBER, "workflow_device"),
        ("Integration surface", "VS Code commands, CLI commands, onboarding readiness JSON, and MCP tools expose the same local runtime.", PURPLE, "workflow_editor_mcp"),
    ]
    x0, y0 = MARGIN, H - 260
    w, h = 224, 104
    for i, (title, body, color, dest) in enumerate(cards):
        x = x0 + (i % 3) * (w + 22)
        y = y0 - (i // 3) * (h + 28)
        card(c, x, y, w, h, title, body, accent=color)
        c.linkRect("", dest, Rect=(x, y, x + w, y + h), relative=0, thickness=0)

    c.setFillColor(LIGHT)
    c.setStrokeColor(LINE)
    c.roundRect(MARGIN, 74, W - 2 * MARGIN, 96, 8, fill=1, stroke=1)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(MARGIN + 18, 142, "Best mental model")
    para(
        c,
        "The prose is source. ShipMBLangCore is the preview. ShipMBLang bytecode is the current machine target. "
        "The local runtime executes supported operations now and records future native run intent safely.",
        MARGIN + 18,
        90,
        W - 2 * MARGIN - 36,
        42,
        "body",
    )


def draw_pipeline(c: canvas.Canvas, page_no: int):
    start_page(c, "pipeline", "Compiler Pipeline", page_no)
    c.setFont("Helvetica-Bold", 25)
    c.setFillColor(INK)
    c.drawString(MARGIN, H - 94, "Natural Language To Runtime")
    para(
        c,
        "The compiler is deterministic: it parses known natural-language programming forms, resolves declarations, emits bytecode, "
        "and renders the same operation list as readable Core for review.",
        MARGIN,
        H - 134,
        W - 2 * MARGIN,
        34,
        "body",
    )

    steps = [
        ("English prose", "Ordinary instructions from editor, CLI, file, or MCP client", TEAL),
        ("Lexical analysis", "Words, numbers, strings, punctuation, spans, keywords", BLUE),
        ("Syntax analysis", "Sentence-level statement nodes and editor roles", PURPLE),
        ("Semantic analysis", "Declarations, references, diagnostics, operations", ROSE),
        ("IR", "Stable intermediate instructions", AMBER),
        ("Optimization", "Normalize, dedupe, insert required setup", GREEN),
        ("Target code", "shipmblang-bytecode with native_machine_code false", NAVY),
        ("Runtime", "Execute supported bytecode locally", TEAL),
    ]
    x, y = MARGIN, H - 222
    bw, bh, gap = 158, 62, 18
    positions = []
    for i, (title, body, color) in enumerate(steps):
        if i < 4:
            col = i
            by = y
        else:
            col = 7 - i
            by = y - 112
        bx = x + col * (bw + gap)
        positions.append((bx, by, color))
        labeled_box(c, bx, by, bw, bh, title, body, fill=WHITE, accent=color)

    for i in range(3):
        bx, by, color = positions[i]
        arrow(c, bx + bw + 2, by + bh / 2, bx + bw + gap - 4, by + bh / 2, color)
    sx, sy, scolor = positions[3]
    ix, iy, _ = positions[4]
    arrow(c, sx + bw / 2, sy - 4, sx + bw / 2, iy + bh + 18, scolor)
    arrow(c, sx + bw / 2, iy + bh + 18, ix + bw / 2, iy + bh + 18, scolor)
    arrow(c, ix + bw / 2, iy + bh + 18, ix + bw / 2, iy + bh + 4, scolor)
    for i in range(4, 7):
        bx, by, color = positions[i]
        nx, ny, _ = positions[i + 1]
        arrow(c, bx - 2, by + bh / 2, nx + bw + 4, ny + bh / 2, color)

    code_box(
        c,
        MARGIN,
        74,
        350,
        136,
        """Use ShipMB. Open the current project and scan the codebase.
When an error happens, explain it with printurf, suggest a fix,
and show the report.""",
        "Natural source",
    )
    code_box(
        c,
        MARGIN + 375,
        74,
        350,
        136,
        """use shipmb
project = open "."
project |> index
on error:
  error |> printurf |> suggest_fix |> show""",
        "Rendered ShipMBLangCore",
    )


def draw_workflow_compile(c: canvas.Canvas, page_no: int):
    start_page(c, "workflow_compile", "Workflow 1 - Describe A Program", page_no)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 24)
    c.drawString(MARGIN, H - 92, "Workflow 1: Describe A Program End To End")
    para(
        c,
        "Real-world fit: a product builder, educator, or automation author describes a small program in plain language, checks the Core preview, "
        "then lets the runtime execute supported bytecode or record future native run intent.",
        MARGIN,
        H - 135,
        W - 2 * MARGIN,
        36,
        "body",
    )
    code_box(
        c,
        MARGIN,
        H - 333,
        335,
        164,
        """Use Python. Import math.
Declare an integer variable total set to 0.
Define a function add_item that takes price
and returns total plus price.
Create a class Cart with property items
and method add_item that takes item and returns items.
For each item in items then call add_item with item.
Show program.""",
        "Natural source",
    )
    code_box(
        c,
        MARGIN + 375,
        H - 333,
        350,
        164,
        """use shipmb
target language "python"
import "math"
let total: int = 0
fn add_item(price) -> total plus price:
  pass
class Cart:
property Cart.items
method Cart.add_item(item) -> items:
  pass
for item in items:
  call add_item with item
program |> show""",
        "Core preview",
    )
    lane_y = 118
    lane = [
        ("Write", "Plain `.shipmb` paragraph", TEAL),
        ("Compile", "`python -m shipmblang compile`", BLUE),
        ("Inspect", "Core plus JSON compiler trace", AMBER),
        ("Run", "Supported bytecode executes locally", GREEN),
    ]
    for i, (t, b, col) in enumerate(lane):
        x = MARGIN + i * 184
        labeled_box(c, x, lane_y, 150, 70, t, b, accent=col)
        if i < len(lane) - 1:
            arrow(c, x + 152, lane_y + 35, x + 178, lane_y + 35, col)


def draw_workflow_debug(c: canvas.Canvas, page_no: int):
    start_page(c, "workflow_debug", "Workflow 2 - Debug A Real Error", page_no)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 24)
    c.drawString(MARGIN, H - 92, "Workflow 2: Debug A Real Error With printurf()")
    para(
        c,
        "Real-world fit: an editor, test runner, CLI, or MCP client catches an exception, sends the stack trace and relevant paths, "
        "and gets a structured explanation that a developer can act on.",
        MARGIN,
        H - 135,
        W - 2 * MARGIN,
        36,
        "body",
    )
    code_box(
        c,
        MARGIN,
        H - 335,
        330,
        165,
        """from totals import add_item

def main():
    prices = [12, 8, 5]
    for price in prices:
        add_item(price)
    print(f"total: {total}")""",
        "Buggy app.py",
    )
    code_box(
        c,
        MARGIN + 360,
        H - 335,
        365,
        165,
        """NameError: name 'total' is not defined

Error: `total` is referenced in main but is not
defined in the local or imported namespace.
Cause: add_item(price) is called for side effects,
but no variable named total is assigned before print.
Fix: return the value from totals.add_item or import
and read the module-level total explicitly.""",
        "printurf-style report",
    )
    swim_y = 76
    actors = [
        ("Developer", "Sees diagnostic or pasted traceback", TEAL),
        ("ShipMBLang", "Indexes nearby files and normalizes error context", BLUE),
        ("printurf()", "Builds Error / Cause / Fix report", ROSE),
        ("Editor/MCP", "Shows report, suggests fix, writes JSON if requested", GREEN),
    ]
    for i, (t, b, col) in enumerate(actors):
        x = MARGIN + i * 184
        labeled_box(c, x, swim_y, 155, 82, t, b, accent=col)
        if i < len(actors) - 1:
            arrow(c, x + 158, swim_y + 41, x + 178, swim_y + 41, col)
    link_button(c, W - MARGIN - 128, 178, 128, 24, "How printurf works", "printurf_internals", fill=LIGHT, stroke=LINE, text=NAVY)


def draw_printurf_internals(c: canvas.Canvas, page_no: int):
    start_page(c, "printurf_internals", "How printurf Works", page_no)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 24)
    c.drawString(MARGIN, H - 92, "How printurf() Works")
    para(
        c,
        "printurf() is ShipMBLang's codebase-aware debugging primitive. It accepts a raw error, traceback, diagnostics, direct code context, "
        "and/or project paths, then returns a structured diagnostic report for terminals, editors, MCP clients, and JSON workflows.",
        MARGIN,
        H - 135,
        W - 2 * MARGIN,
        36,
        "body",
    )

    flow = [
        ("Inputs", "raw_error, paths, code_context, root, line, max_files", TEAL),
        ("Project context", "build index, rank files, focus traceback location, clip source safely", BLUE),
        ("Prompt or fallback", "use local checkpoint when available; otherwise classify common error families deterministically", AMBER),
        ("Diagnostic", "parse Error / Cause / Fix, attach file, line, context, suggestion", ROSE),
        ("Outputs", "dict, JSON, terminal text, editor report, MCP response", GREEN),
    ]
    y = H - 252
    for i, (title, body, col) in enumerate(flow):
        x = MARGIN + i * 145
        labeled_box(c, x, y, 124, 90, title, body, accent=col)
        if i < len(flow) - 1:
            arrow(c, x + 126, y + 45, x + 140, y + 45, col)

    code_box(
        c,
        MARGIN,
        H - 440,
        342,
        144,
        """from shipmblang import printurf

report = printurf(
    raw_error="NameError: name 'total' is not defined",
    paths=["examples/printurf_sandbox/app.py"],
    root=".",
    output="dict",
)""",
        "Python API",
    )
    code_box(
        c,
        MARGIN + 382,
        H - 440,
        342,
        144,
        """{
  "status": "error",
  "diagnostic_count": 1,
  "diagnostics": [{
    "error": "`total` is used before Python knows what it is",
    "file": ".../app.py",
    "line": 8,
    "cause": "...current code path...",
    "suggestion": "define `total` before this line..."
  }]
}""",
        "Structured report",
    )

    cards = [
        ("Context selection", "If paths are supplied, printurf builds a lightweight codebase index, extracts the last traceback file/line, and prioritizes nearby source around the failing line.", TEAL),
        ("Engine path", "When a ShipMBLang-compatible checkpoint and tokenizer exist, the prompt forces one concise paragraph: Error, Cause, and Fix.", BLUE),
        ("Fallback path", "When model weights are missing, printurf still works by recognizing NameError, ModuleNotFoundError, TypeError, AttributeError, KeyError, IndexError, and SyntaxError.", AMBER),
        ("Consumer path", "The same report can render as terminal text, JSON, editor output, or an MCP response with project index metadata attached.", GREEN),
    ]
    for i, (title, body, col) in enumerate(cards):
        x = MARGIN + i * 182
        labeled_box(c, x, 64, 162, 86, title, body, accent=col)


def draw_workflow_device(c: canvas.Canvas, page_no: int):
    start_page(c, "workflow_device", "Workflow 3 - Control Device Resources", page_no)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 24)
    c.drawString(MARGIN, H - 92, "Workflow 3: Device Families And Agentic Controls")
    para(
        c,
        "Real-world fit: a ShipMB client targets a machine, GPU, browser, embedded board, or home device, then exposes only the resources "
        "declared by the selected family and capability map.",
        MARGIN,
        H - 135,
        W - 2 * MARGIN,
        36,
        "body",
    )
    families = [
        ("host", "filesystem, process, env, clock", TEAL),
        ("cuda", "tensors, GPU memory, kernels", GREEN),
        ("mps", "unified memory, Metal kernels", BLUE),
        ("browser", "DOM, viewport, storage, network", PURPLE),
        ("embedded", "GPIO, serial, I2C, SPI, flash", AMBER),
    ]
    for i, (name, body, col) in enumerate(families):
        x = MARGIN + i * 144
        labeled_box(c, x, H - 247, 124, 78, name, body, accent=col)

    code_box(
        c,
        MARGIN,
        H - 425,
        345,
        132,
        """Use the embedded device family.
Expose the gpio resource.
Show device resources.

Use raspberry pi. Read gpio. Show resources.""",
        "Natural syntax",
    )
    code_box(
        c,
        MARGIN + 380,
        H - 425,
        345,
        132,
        """use shipmb
device = family "embedded"
device |> resource "gpio"
device_resources |> show""",
        "Expected Core",
    )
    card(
        c,
        MARGIN,
        74,
        226,
        104,
        "Roku-style remote workflow",
        "Use `tv_pack` from ShipMBLang, target Roku, expose remote-control, search/open/close app capabilities, install intent, and voice/chat client interfaces.",
        accent=ROSE,
    )
    card(
        c,
        MARGIN + 250,
        74,
        226,
        104,
        "Factory bench workflow",
        "Use embedded resources, require interlocks for moving devices, map providers by priority, and surface command errors through printurf.",
        accent=AMBER,
    )
    card(
        c,
        MARGIN + 500,
        74,
        226,
        104,
        "GPU lab workflow",
        "Select CUDA or MPS family, inspect tensor or memory resources, and keep hardware assumptions explicit in natural source.",
        accent=GREEN,
    )


def draw_workflow_editor_mcp(c: canvas.Canvas, page_no: int):
    start_page(c, "workflow_editor_mcp", "Workflow 4 - Editor And MCP", page_no)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 24)
    c.drawString(MARGIN, H - 92, "Workflow 4: Editor, CLI, MCP, And Runtime")
    para(
        c,
        "The same package powers terminal commands, VS Code commands, Python calls, and MCP clients. That makes ShipMBLang portable across local developer workflows and agent clients.",
        MARGIN,
        H - 132,
        W - 2 * MARGIN,
        34,
        "body",
    )
    nodes = [
        ("VS Code", "CodeLens, quick fix, hover link, command palette", TEAL),
        ("CLI", "compile, run, printurf, mcp, onboarding", BLUE),
        ("Python API", "compile_natural_program(), printurf()", GREEN),
        ("MCP Server", "index, explain error, list/select/get device resources", ROSE),
    ]
    for i, (t, b, col) in enumerate(nodes):
        x = MARGIN + i * 184
        labeled_box(c, x, H - 238, 154, 86, t, b, accent=col)
        arrow(c, x + 77, H - 242, W / 2, H - 315, col)

    c.setFillColor(NAVY)
    c.setStrokeColor(NAVY)
    c.roundRect(W / 2 - 98, H - 384, 196, 88, 8, fill=1, stroke=1)
    para(c, "<b>ShipMBLang local runtime</b><br/>Compiles natural source, emits bytecode, executes supported operations, and returns structured output.", W / 2 - 81, H - 372, 162, 64, "white")

    code_box(
        c,
        MARGIN,
        74,
        330,
        145,
        """python -m shipmblang compile "<natural source>"
python -m shipmblang run --file program.shipmb
python -m shipmblang printurf src/app.py --error "..."
python -m shipmblang mcp""",
        "Local commands",
    )
    code_box(
        c,
        MARGIN + 365,
        74,
        360,
        145,
        """printurf
shipmblang_explain_error
shipmblang_index_codebase
shipmblang_list_device_families
shipmblang_select_device_family
shipmblang_get_device_resource""",
        "MCP tools",
    )


def draw_examples(c: canvas.Canvas, page_no: int):
    start_page(c, "examples", "Real World Examples", page_no)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 24)
    c.drawString(MARGIN, H - 92, "Real World Examples")
    examples = [
        ("1. Codebase triage", "A test run fails with a traceback. The agent calls `shipmblang_index_codebase`, then `printurf`, and returns a precise Error / Cause / Fix report with relevant file paths.", ROSE),
        ("2. Natural program preview", "A teammate writes a feature spec as prose. ShipMBLang compiles it to Core and JSON so reviewers can inspect declarations, unresolved references, and final bytecode before running.", TEAL),
        ("3. Device automation", "A local client selects `embedded`, exposes GPIO, adds safety interlocks for a robot arm, then shows command errors through printurf if execution fails.", AMBER),
        ("4. Editor learning loop", "A beginner writes `.shipmb` instructions in VS Code, uses Compile Natural Program to see Core, then Run Natural Program to execute supported runtime operations.", BLUE),
        ("5. ShipMB onboarding", "ShipMB installs this checkout editable, runs the readiness command, stores `SHIPMBLANG_HOME` and MCP args, and records the compiler contract from JSON.", GREEN),
        ("6. Future native path", "The v0.1 bytecode backend stays stable while native CPU code, process execution, or hardware runtimes can arrive behind the same pipeline later.", PURPLE),
    ]
    x0, y0 = MARGIN, H - 192
    for i, (title, body, col) in enumerate(examples):
        x = x0 + (i % 2) * 372
        y = y0 - (i // 2) * 112
        card(c, x, y, 340, 86, title, body, accent=col)
    c.setFillColor(HexColor("#fff8e8"))
    c.setStrokeColor(HexColor("#efd39a"))
    c.roundRect(MARGIN, 58, W - 2 * MARGIN, 54, 8, fill=1, stroke=1)
    para(
        c,
        "<b>Important v0.1 boundary:</b> ShipMBLang bytecode is the concrete machine target today. "
        "Selecting Python, Rust, browser, or embedded updates the program model; it does not yet emit native source files or CPU assembly.",
        MARGIN + 16,
        72,
        W - 2 * MARGIN - 32,
        28,
        "small",
    )


def draw_onboarding(c: canvas.Canvas, page_no: int):
    start_page(c, "onboarding", "ShipMB Onboarding", page_no)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 24)
    c.drawString(MARGIN, H - 92, "ShipMB Onboarding Flow")
    para(
        c,
        "ShipMB can treat ShipMBLang as a local Python package with one install step, one readiness command, and one MCP command. "
        "The CLI readiness manifest is authoritative after Python is available.",
        MARGIN,
        H - 132,
        W - 2 * MARGIN,
        34,
        "body",
    )
    steps = [
        ("1", "Locate checkout", "Use explicit SHIPMBLANG_HOME or discover beside ShipMB", TEAL),
        ("2", "Install editable", "python -m pip install -e <shipmblang_root>", BLUE),
        ("3", "Verify readiness", "python -m shipmblang onboarding --format json --check --root <project>", GREEN),
        ("4", "Store env", "Record HOME, PYTHON, DEVICE, checkpoint, tokenizer values", AMBER),
        ("5", "Register MCP", "command: <python>, args: ['-m', 'shipmblang', 'mcp']", ROSE),
    ]
    for i, (n, t, b, col) in enumerate(steps):
        x = MARGIN + i * 145
        c.setFillColor(col)
        c.circle(x + 18, H - 193, 15, fill=1, stroke=0)
        c.setFillColor(WHITE)
        c.setFont("Helvetica-Bold", 12)
        c.drawCentredString(x + 18, H - 198, n)
        labeled_box(c, x, H - 318, 124, 96, t, b, accent=col)
        if i < len(steps) - 1:
            arrow(c, x + 123, H - 270, x + 142, H - 270, col)

    code_box(
        c,
        MARGIN,
        90,
        350,
        150,
        """{
  "target": "shipmblang-bytecode",
  "core": "ShipMBLangCore",
  "declaration_resolution": "order-insensitive",
  "declaration_pass": "collect declarations before resolving",
  "effectful_action_order": "preserve bytecode order"
}""",
        "Compiler contract",
    )
    card(
        c,
        MARGIN + 385,
        90,
        340,
        150,
        "Readiness checks",
        "The onboarding command reports ready, blocked, or metadata and includes checks for import, compiler, runtime, printurf, and MCP. "
        "ShipMB can fail fast when local tooling is incomplete.",
        accent=GREEN,
    )


def draw_checklist(c: canvas.Canvas, page_no: int):
    start_page(c, "checklist", "Interactive Checklist", page_no)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 24)
    c.drawString(MARGIN, H - 92, "Interactive Adoption Checklist")
    para(
        c,
        "Use these fillable fields to mark a workflow for a real project. Most PDF readers support the checkboxes and note fields.",
        MARGIN,
        H - 130,
        W - 2 * MARGIN,
        28,
        "body",
    )
    items = [
        ("compile_preview", "Natural source can compile to readable Core."),
        ("json_trace", "JSON trace exposes tokens, syntax, semantic model, IR, target code, Core, and bytecode."),
        ("printurf_flow", "printurf is wired to CLI, editor command, or MCP client."),
        ("printurf_internals", "printurf context collection, fallback behavior, and structured outputs are understood."),
        ("device_family", "A target family is selected explicitly when device resources are needed."),
        ("safety_policy", "Safety interlocks and user communication policy are explicit where relevant."),
        ("onboarding", "ShipMB onboarding stores install, verify, environment, and MCP command metadata."),
    ]
    y = H - 185
    form = c.acroForm
    for name, label in items:
        form.checkbox(
            name=name,
            tooltip=label,
            x=MARGIN,
            y=y - 4,
            size=13,
            borderColor=LINE,
            fillColor=WHITE,
            textColor=TEAL,
            buttonStyle="check",
            forceBorder=True,
        )
        para(c, label, MARGIN + 24, y - 8, 500, 22, "body")
        y -= 31

    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(MARGIN, y - 4, "Workflow notes")
    form.textfield(
        name="workflow_notes",
        tooltip="Notes for the ShipMBLang workflow",
        x=MARGIN,
        y=y - 86,
        width=W - 2 * MARGIN,
        height=58,
        borderColor=LINE,
        fillColor=WHITE,
        textColor=INK,
        forceBorder=True,
        fontName="Helvetica",
        fontSize=9,
    )

    c.setFillColor(NAVY)
    c.roundRect(MARGIN, 58, W - 2 * MARGIN, 48, 8, fill=1, stroke=0)
    para(
        c,
        "<b>Recommended first demo:</b> compile the printurf workflow, run it against `examples/printurf_sandbox/app.py`, "
        "then open the JSON compiler trace so stakeholders can see the full deterministic path from prose to runtime behavior.",
        MARGIN + 18,
        70,
        W - 2 * MARGIN - 36,
        24,
        "white",
    )


def build():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(OUT_PDF), pagesize=landscape(letter), pageCompression=1)
    c.setTitle("ShipMBLang Interactive Feature And Workflow Guide")
    c.setAuthor("ShipMBLang")
    c.setSubject("Interactive PDF describing ShipMBLang features and end-to-end workflows")

    draw_cover(c)
    c.showPage()
    draw_contents(c, 2)
    c.showPage()
    draw_pipeline(c, 3)
    c.showPage()
    draw_workflow_compile(c, 4)
    c.showPage()
    draw_workflow_debug(c, 5)
    c.showPage()
    draw_printurf_internals(c, 6)
    c.showPage()
    draw_workflow_device(c, 7)
    c.showPage()
    draw_workflow_editor_mcp(c, 8)
    c.showPage()
    draw_examples(c, 9)
    c.showPage()
    draw_onboarding(c, 10)
    c.showPage()
    draw_checklist(c, 11)
    c.save()
    return OUT_PDF


if __name__ == "__main__":
    pdf = build()
    print(pdf)
