"""Render the README images from what HarfBuzz draws for text typed into the real font.

    uv run scripts/render.py

Writes docs/images/hero.svg, an LED panel cycling through integer arithmetic,
exact decimals, and division one key at a time. Each frame lights the dots of the glyphs `hb-shape` returns for the
text typed so far, at the advances it returns. Also writes
hidden-{dark,light}.svg with `hb-view` and the debug font, and
passes-{dark,light}.svg from `hb-shape --trace` on a 4-digit build.
"""

import subprocess
import sys
from dataclasses import dataclass
from html import escape
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from generate import build_carry  # noqa: E402

IMAGES = ROOT / "docs/images"
THEMES = {
    "dark": {"fg": "ecebe8", "dim": "6b6b6b", "work": "7dd3fc", "accent": "ff6b35", "chip": "1c1c1c", "line": "2e2e2e"},
    "light": {"fg": "161616", "dim": "a3a3a3", "work": "0369a1", "accent": "e8501d", "chip": "f4f4f4", "line": "e2e2e2"},
}
SCENES = [
    ("Integer addition", "128+256="),
    ("Signed subtraction", "5 - 7 ="),
    ("Signed multiplication", "-5×-7="),
    ("Decimal addition", "12.50+3.75="),
    ("Exact decimals", "0.1+0.2="),
    ("Decimal multiplication", "19.99×3="),
    ("Four fractional places", "0.01×0.01="),
    ("Exact division", "84÷7="),
    ("Quotient + remainder", "-17/5="),
]
PITCH, RADIUS, MARGIN = 12, 4.4, 2
HEADER = 32


@dataclass(frozen=True)
class HeroFrame:
    scene: int
    typed: str
    cells: set[tuple[int, int]]
    end: int
    start: float
    stop: float


def hb_view(font: Path, lines: list[str], theme: dict, out: Path, size: int) -> None:
    text = ROOT / "build/render.txt"
    text.write_text("\n".join(lines) + "\n")
    subprocess.run(
        ["hb-view", "-O", "svg", f"--font-size={size}", "--background=none", f"--foreground={theme['fg']}",
         "--margin=48 56", "--line-space=40", f"--text-file={text}", f"--output-file={out}", str(font)],
        check=True,
    )


def shaped(font: Path, text: str) -> list[tuple[str, int]]:
    out = subprocess.run(["hb-shape", "--no-clusters", "--", str(font), text], capture_output=True, text=True, check=True).stdout
    return [(name, int(adv)) for name, adv in (g.split("+") for g in out.strip()[1:-1].split("|"))]


def lit_cells(font: Path, text: str, bitmaps: dict[str, tuple[str, ...]]) -> tuple[set[tuple[int, int]], int]:
    """Lit dots and final advance, on a grid of 100-unit cells."""
    cells, x = set(), 0
    for name, advance in shaped(font, text):
        for row, line in enumerate(bitmaps.get(name, ())):
            for col, dot in enumerate(line):
                if dot == "#":
                    cells.add((x // 100 + col, row))
        x += advance
    return cells, x // 100


def hero_svg(font: Path, bitmaps: dict[str, tuple[str, ...]]) -> str:
    key, hold, rest = 0.16, 2.4, 0.4
    frames, clock = [], 0.0
    for scene, (_, expression) in enumerate(SCENES):
        frames.append(HeroFrame(scene, "", set(), 0, clock, clock + key))
        for i in range(len(expression)):
            typed = expression[:i + 1]
            cells, end = lit_cells(font, typed, bitmaps)
            start = clock + key * (i + 1)
            stop = clock + key * (i + 2) if i < len(expression) - 1 else start + hold
            frames.append(HeroFrame(scene, typed, cells, end, start, stop))
        clock = frames[-1].stop
        frames.append(HeroFrame(scene, "", set(), 0, clock, clock + rest))
        clock += rest
    total = clock
    cols = max(frame.end for frame in frames) + 7 + 2 * MARGIN
    rows = 7 + 2 * MARGIN
    width, height = cols * PITCH, rows * PITCH + HEADER

    def dots(cells) -> str:
        return "".join(
            f"M{(c + MARGIN) * PITCH + PITCH / 2 - RADIUS:.1f} {HEADER + (r + MARGIN) * PITCH + PITCH / 2:.1f}a{RADIUS} {RADIUS} 0 1 0 {2 * RADIUS} 0a{RADIUS} {RADIUS} 0 1 0 {-2 * RADIUS} 0"
            for c, r in sorted(cells)
        )

    css, groups = [], []
    caret = f'class="caret" fill="#ff6b35" y="{HEADER + MARGIN * PITCH + PITCH / 2 - RADIUS:.1f}" width="{4 * PITCH + 2 * RADIUS}" height="{6 * PITCH + 2 * RADIUS}"'
    for i, frame in enumerate(frames):
        start, stop = frame.start / total * 100, frame.stop / total * 100
        css.append(f"@keyframes f{i}{{0%,100%{{opacity:0}}{start:.6f}%{{opacity:1}}{stop:.6f}%{{opacity:0}}}}"
                   f".f{i}{{animation:f{i} {total:.2f}s steps(1,end) infinite}}")
        caption, expression = SCENES[frame.scene]
        last = frame.scene == len(SCENES) - 1 and frame.typed == expression
        cursor = frame.end + 1 if frame.typed else 0
        groups.append(f'<g class="frame f{i}{" last" if last else ""}" data-scene="{frame.scene}" data-typed="{escape(frame.typed, quote=True)}" data-start="{frame.start:.4f}" data-stop="{frame.stop:.4f}">'
                      f'<text class="caption" x="24" y="26">{escape(caption)}</text>'
                      f'<g filter="url(#glow)"><path class="lit" d="{dots(frame.cells)}"/>'
                      f'<rect {caret} x="{(cursor + MARGIN) * PITCH + PITCH / 2 - RADIUS:.1f}"/></g></g>')
    css.append("@media (prefers-reduced-motion:reduce){.frame{animation:none;opacity:0}.last{opacity:1}}")
    unlit = {(c, r) for c in range(cols - 2 * MARGIN) for r in range(7)}
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" data-duration="{total:.2f}" role="img" aria-label="Carry types integer arithmetic, signed and spaced expressions, exact decimals, multiplication, and division with remainders. An orange block caret follows the typing.">
<style>.frame{{fill:#f7f2e4;opacity:0}}.caption{{fill:#a6a89a;font:20px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;letter-spacing:2px;text-transform:uppercase}}{"".join(css)}</style>
<defs><filter id="glow" x="-5%" y="-20%" width="110%" height="140%"><feGaussianBlur stdDeviation="2.2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>
<rect width="{width}" height="{height}" rx="14" fill="#0c0c0c"/>
<path fill="#1d1d1d" d="{dots(unlit)}"/>
{"".join(groups)}
</svg>
"""


def label(name: str) -> tuple[str, str]:
    """(big text, tone) for a glyph name in the trace."""
    digits = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
    symbols = {"plus": "+", "hyphen": "-", "minus": "−", "equal": "=", "asterisk": "*", "multiply": "×", "slash": "/", "divide": "÷", "period": ".", "comma": ",", "space": "␣", "uni00A0": "␣"}
    if name.startswith(("pending.", "tail.", "syntax.", "boundary.", "invalid.", "answered.", "neg.")):
        text, _ = label(name.split(".", 1)[1])
        return text, "work"
    if name.startswith("dec.") and name[4:] in symbols:
        return symbols[name[4:]], "work"
    if name in digits:
        return str(digits.index(name)), "fg"
    if name in symbols:
        return symbols[name], "fg"
    if name in ("pad", "blank"):
        return "0", "dim"
    if name.startswith("res."):
        return ("-" if name == "res.minus" else symbols.get(name[4:], name[4:])), "accent"
    if name.startswith("slot."):
        return "_", "work"
    if name.startswith(("b.", "col.")):
        return name.split(".")[1].replace("m", "-"), "work"
    if name.startswith("d") and name[1:2].isdigit():
        return name[1], "work"
    return name, "work"


def passes_svg(rows: list[tuple[str, list[str]]], theme: dict) -> str:
    chip, gap, left, top, row_h = 30, 4, 168, 24, 46
    width = left + max(len(g) for _, g in rows) * (chip + gap) + 24
    height = top + len(rows) * row_h + 8
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<g font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace">',
    ]
    for r, (title, glyphs) in enumerate(rows):
        y = top + r * row_h
        out.append(f'<text x="24" y="{y + 20}" font-size="13" fill="#{theme["dim"]}">{escape(title)}</text>')
        for i, name in enumerate(glyphs):
            text, tone = label(name)
            x = left + i * (chip + gap)
            stroke = theme["line"] if tone != "accent" else theme["accent"]
            dash = ' stroke-dasharray="3 3"' if tone == "dim" else ""
            out.append(f'<rect x="{x}" y="{y}" width="{chip}" height="{chip}" rx="4" fill="#{theme["chip"]}" stroke="#{stroke}"{dash}/>')
            out.append(f'<text x="{x + chip / 2}" y="{y + 20}" font-size="13" text-anchor="middle" fill="#{theme[tone]}">{escape(text)}</text>')
            parts = name.split(".")
            if parts[0] == "col" and len(parts) == 3:
                mark = {"z": "?", "p": "+", "n": "−"}[parts[2]]
                out.append(f'<text x="{x + chip - 4}" y="{y + 9}" font-size="8" text-anchor="end" fill="#{theme["dim"]}">{mark}</text>')
    out.append("</g></svg>")
    return "\n".join(out) + "\n"


def trace_rows(font: Path, text: str, passes: dict[int, str]) -> list[tuple[str, list[str]]]:
    trace = subprocess.run(["hb-shape", "--trace", "--no-positions", "--no-clusters", str(font), text],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=True).stdout
    rows, last = [], None
    for line in trace.splitlines():
        if not line.startswith("trace: "):
            continue
        message, _, buffer = line[7:].partition("\tbuffer: ")
        glyphs = buffer.strip("[]").split("|")
        if last is None and message.startswith("start table GSUB"):
            rows.append(("typed", glyphs))
            last = glyphs
        elif message.startswith("end lookup"):
            lookup = int(message.split()[2])
            if lookup in passes and glyphs != last:
                rows.append((passes[lookup], glyphs))
                last = glyphs
    return rows


def main() -> None:
    IMAGES.mkdir(parents=True, exist_ok=True)
    build = ROOT / "build/render"
    build.mkdir(parents=True, exist_ok=True)

    fonts, bitmaps = {}, {}
    for name, n, m, debug in (("Carry", 16, 8, False), ("Carry-Debug", 16, 8, True), ("Carry-4", 4, 2, False)):
        font, fea, passes, glyphs = build_carry(n, m, debug)
        fonts[name] = build / f"{name}.ttf"
        bitmaps[name] = {g.name: g.bitmap for g in glyphs}
        font.save(fonts[name])
        if name == "Carry-4":
            calt = next(f for f in font["GSUB"].table.FeatureList.FeatureRecord if f.FeatureTag == "calt")
            names = dict(zip(calt.Feature.LookupListIndex, (p.name.replace("_", " ") for p in passes)))

    (IMAGES / "hero.svg").write_text(hero_svg(fonts["Carry"], bitmaps["Carry"]))
    rows = trace_rows(fonts["Carry-4"], "128+256=", names)
    for theme_name, theme in THEMES.items():
        hb_view(fonts["Carry-Debug"], ["128+256="], theme, IMAGES / f"hidden-{theme_name}.svg", 48)
        (IMAGES / f"passes-{theme_name}.svg").write_text(passes_svg(rows, theme))
    for path in sorted(IMAGES.iterdir()):
        print(f"{path.stat().st_size:>8}  {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
