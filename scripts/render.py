"""Render the README images from what HarfBuzz draws for text typed into the real font.

    uv run scripts/render.py

Writes docs/images/hero.svg, an LED panel that types 128+256= one key at a
time. Each frame lights the dots of the glyphs `hb-shape` returns for the
text typed so far, at the advances it returns. Also writes
hidden-{dark,light}.svg with `hb-view` and the debug font, and
passes-{dark,light}.svg from `hb-shape --trace` on a 4-digit build.
"""

import subprocess
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from generate import build_carry, inventory  # noqa: E402

IMAGES = ROOT / "docs/images"
THEMES = {
    "dark": {"fg": "ecebe8", "dim": "6b6b6b", "work": "7dd3fc", "accent": "ff6b35", "chip": "1c1c1c", "line": "2e2e2e"},
    "light": {"fg": "161616", "dim": "a3a3a3", "work": "0369a1", "accent": "e8501d", "chip": "f4f4f4", "line": "e2e2e2"},
}
TYPED = "128+256="
PITCH, RADIUS, MARGIN = 12, 4.4, 2


def hb_view(font: Path, lines: list[str], theme: dict, out: Path, size: int) -> None:
    text = ROOT / "build/render.txt"
    text.write_text("\n".join(lines) + "\n")
    subprocess.run(
        ["hb-view", "-O", "svg", f"--font-size={size}", "--background=none", f"--foreground={theme['fg']}",
         "--margin=48 56", "--line-space=40", f"--text-file={text}", f"--output-file={out}", str(font)],
        check=True,
    )


def shaped(font: Path, text: str) -> list[tuple[str, int]]:
    out = subprocess.run(["hb-shape", "--no-clusters", str(font), text], capture_output=True, text=True, check=True).stdout
    return [(name, int(adv)) for name, adv in (g.split("+") for g in out.strip()[1:-1].split("|"))]


def lit_cells(font: Path, text: str, bitmaps: dict[str, tuple[str, ...]]) -> set[tuple[int, int]]:
    """(column, row) of every lit dot, on a grid of 100-unit cells."""
    cells, x = set(), 0
    for name, advance in shaped(font, text):
        for row, line in enumerate(bitmaps.get(name, ())):
            for col, dot in enumerate(line):
                if dot == "#":
                    cells.add((x // 100 + col, row))
        x += advance
    return cells


def hero_svg(font: Path) -> str:
    bitmaps = {g.name: g.bitmap for g in inventory(debug=False)}
    prefixes = [TYPED[: i + 1] for i in range(len(TYPED))]
    frames = [lit_cells(font, p, bitmaps) for p in prefixes]
    ends = [len(p) * 6 for p in prefixes]
    ends[-1] = max(c for c, _ in frames[-1]) + 2
    cols = ends[-1] + 3 + 2 * MARGIN
    rows = 7 + 2 * MARGIN
    width, height = cols * PITCH, rows * PITCH

    def dots(cells) -> str:
        return "".join(
            f"M{(c + MARGIN) * PITCH + PITCH / 2 - RADIUS:.1f} {(r + MARGIN) * PITCH + PITCH / 2:.1f}a{RADIUS} {RADIUS} 0 1 0 {2 * RADIUS} 0a{RADIUS} {RADIUS} 0 1 0 {-2 * RADIUS} 0"
            for c, r in sorted(cells)
        )

    # Timeline: one key every 0.16 s, the finished sum held, a short blank, repeat.
    key, hold, rest = 0.16, 3.2, 0.5
    total = key * len(frames) + hold + rest
    css, groups = [], []
    for i, cells in enumerate(frames):
        start = key * (i + 1) / total * 100
        stop = (key * (i + 2) if i < len(frames) - 1 else key * len(frames) + hold) / total * 100
        css.append(f"@keyframes f{i}{{0%,{start - 0.01:.2f}%{{opacity:0}}{start:.2f}%,{stop - 0.01:.2f}%{{opacity:1}}{stop:.2f}%,100%{{opacity:0}}}}"
                   f".f{i}{{animation:f{i} {total:.2f}s infinite}}")
        groups.append(f'<path class="lit f{i}{" last" if i == len(frames) - 1 else ""}" d="{dots(cells)}"/>')
    caret = {(ends[-1] + 1, r) for r in range(7)}
    css.append(f"@keyframes caret{{0%,49%{{opacity:1}}50%,100%{{opacity:0}}}}.caret{{animation:caret 1s steps(1) infinite}}")
    css.append("@media (prefers-reduced-motion:reduce){.lit{animation:none;opacity:0}.last{opacity:1}.caret{animation:none}}")
    unlit = {(c, r) for c in range(cols - 2 * MARGIN) for r in range(7)}
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="An LED display typing 128+256= in Carry. When the = is typed, 384 appears.">
<style>.lit{{fill:#f7f2e4;opacity:0}}{"".join(css)}</style>
<defs><filter id="glow" x="-5%" y="-20%" width="110%" height="140%"><feGaussianBlur stdDeviation="2.2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>
<rect width="{width}" height="{height}" rx="14" fill="#0c0c0c"/>
<path fill="#1d1d1d" d="{dots(unlit)}"/>
<g filter="url(#glow)">{"".join(groups)}<path class="caret" fill="#f7f2e4" fill-opacity="0.55" d="{dots(caret)}"/></g>
</svg>
"""


def label(name: str) -> tuple[str, str]:
    """(big text, tone) for a glyph name in the trace."""
    digits = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
    symbols = {"plus": "+", "hyphen": "-", "minus": "−", "equal": "=", "asterisk": "*", "multiply": "×", "space": "␣"}
    if name in digits:
        return str(digits.index(name)), "fg"
    if name in symbols:
        return symbols[name], "fg"
    if name in ("pad", "blank"):
        return "0", "dim"
    if name.startswith("res."):
        return ("-" if name == "res.minus" else name[4:]), "accent"
    if name.startswith("slot."):
        return "_", "work"
    if name.startswith(("b.", "col.")):
        return name.split(".")[1].replace("m", "-"), "work"
    if name.startswith("d"):
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

    fonts = {}
    for name, n, m, debug in (("Carry", 16, 8, False), ("Carry-Debug", 16, 8, True), ("Carry-4", 4, 2, False)):
        font, fea, passes, glyphs = build_carry(n, m, debug)
        fonts[name] = build / f"{name}.ttf"
        font.save(fonts[name])
        if name == "Carry-4":
            calt = next(f for f in font["GSUB"].table.FeatureList.FeatureRecord if f.FeatureTag == "calt")
            names = dict(zip(calt.Feature.LookupListIndex, (p.name.replace("_", " ") for p in passes)))

    (IMAGES / "hero.svg").write_text(hero_svg(fonts["Carry"]))
    rows = trace_rows(fonts["Carry-4"], "128+256=", names)
    for theme_name, theme in THEMES.items():
        hb_view(fonts["Carry-Debug"], ["128+256="], theme, IMAGES / f"hidden-{theme_name}.svg", 48)
        (IMAGES / f"passes-{theme_name}.svg").write_text(passes_svg(rows, theme))
    for path in sorted(IMAGES.iterdir()):
        print(f"{path.stat().st_size:>8}  {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
