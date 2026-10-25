"""Throwaway fonts that check which GSUB behaviours HarfBuzz and CoreText support.

    uv run probe/probe.py     # builds probe/*.ttf and prints what each engine drew

Run `swiftc -O tools/ctshape.swift -o tools/ctshape` first.
"""

import subprocess
from pathlib import Path

from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

HERE = Path(__file__).parent
LENGTHS = [10, 30, 62, 63, 64, 65, 100]


def box():
    pen = TTGlyphPen(None)
    pen.moveTo((50, 0))
    pen.lineTo((50, 700))
    pen.lineTo((550, 700))
    pen.lineTo((550, 0))
    pen.closePath()
    return pen.glyph()


def font(name: str, glyphs: list[str], chars: str, fea: str) -> Path:
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder([".notdef", *glyphs])
    fb.setupCharacterMap({ord(c): c for c in chars})
    fb.setupGlyf({g: box() for g in [".notdef", *glyphs]})
    fb.setupHorizontalMetrics({g: (600, 50) for g in [".notdef", *glyphs]})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": f"Probe {name}", "styleName": "Regular"})
    fb.setupOS2()
    fb.setupPost()
    addOpenTypeFeaturesFromString(fb.font, "languagesystem DFLT dflt;\n" + fea)
    path = HERE / f"{name}.ttf"
    fb.save(path)
    return path


def shape(path: Path, text: str) -> dict[str, str]:
    hb = subprocess.run(["hb-shape", "--no-positions", "--no-clusters", str(path), text], capture_output=True, text=True, check=True).stdout
    ct = subprocess.run([str(HERE.parent / "tools/ctshape"), str(path)], input=text + "\n", capture_output=True, text=True, check=True).stdout
    return {"harfbuzz": hb.strip(), "coretext": "[" + "|".join(g.split("+")[0] for g in ct.strip()[1:-1].split("|")) + "]"}


def summary(glyphs: str) -> str:
    names = glyphs[1:-1].split("|")
    counts = {}
    for n in names:
        counts[n] = counts.get(n, 0) + 1
    return " ".join(f"{n}×{c}" if c > 1 else n for n, c in counts.items())


letters = list("abcefst")
every = letters + ["x", "u"] + [f"ok{n}" for n in LENGTHS] + [f"la{n}" for n in LENGTHS]
any_glyph = "[" + " ".join(every) + "]"
fea = ["lookup EXPAND { sub e by e x x x; } EXPAND;"]
fea += [f"lookup BACK{n} {{ sub t by ok{n}; }} BACK{n};" for n in LENGTHS]
fea += [f"lookup AHEAD{n} {{ sub t by la{n}; }} AHEAD{n};" for n in LENGTHS]
fea.append("feature calt {")
fea.append("  lookup REVERSE { rsub a' b by b; } REVERSE;")
fea.append("  lookup FORWARD { sub c a' by c; } FORWARD;")
fea.append("  lookup MULTI { sub e' lookup EXPAND; } MULTI;")
fea.append("  lookup LONGBACK {\n" + "\n".join(f"    sub s {' '.join([any_glyph] * (n - 1))} t' lookup BACK{n};" for n in LENGTHS) + "\n  } LONGBACK;")
fea.append("  lookup LONGAHEAD {\n" + "\n".join(f"    sub t' lookup AHEAD{n} {' '.join(['f'] * (n - 1))} s;" for n in LENGTHS) + "\n  } LONGAHEAD;")
fea.append("} calt;")
behaviours = font("behaviours", every, "abcefst", "\n".join(fea))

checks = [
    ("reverse chaining sees its own output", behaviours, "aaaab"),
    ("chaining backtrack sees its own output", behaviours, "caaaa"),
    ("contextual rule calls a multiple substitution", behaviours, "ae"),
    *[(f"backtrack of {n} glyphs", behaviours, "s" + "f" * (n - 1) + "t") for n in LENGTHS],
    *[(f"lookahead of {n} glyphs", behaviours, "t" + "f" * (n - 1) + "s") for n in LENGTHS],
]

# CoreText re-applies a contextual multiple substitution that puts more than
# 64 glyphs in front of the matched glyph. These four shapes isolate it.
for out in (64, 65, 100):
    xs = " ".join(["x"] * (out - 1))
    shapes = {
        "contextual, inserts before": (f"lookup E {{ sub a by {xs} a; }} E;\nfeature calt {{ lookup C {{ sub a' lookup E b; }} C; }} calt;", "ab"),
        "contextual, inserts after": (f"lookup E {{ sub e by e {xs}; }} E;\nfeature calt {{ lookup C {{ sub b e' lookup E; }} C; }} calt;", "be"),
        "plain, inserts before": (f"feature calt {{ lookup D {{ sub a by {xs} a; }} D; }} calt;", "ab"),
        "plain, inserts after": (f"feature calt {{ lookup D {{ sub e by e {xs}; }} D; }} calt;", "be"),
    }
    for label, (rules, text) in shapes.items():
        path = font(f"multiple-{label.replace(', ', '-').replace(' ', '-')}-{out}", ["a", "b", "e", "x"], "abe", rules)
        checks.append((f"{label}, {out} output glyphs", path, text))

# The first suspect for the CoreText bug was extension lookups (type 7), which
# fontTools switches to past 64 KB of GSUB. Extensions alone are fine.
xs = " ".join(["x"] * 63)
path = font("multiple-in-extension-64", ["a", "b", "x"], "ab", f"lookup E useExtension {{ sub a by {xs} a; }} E;\nfeature calt {{ lookup C useExtension {{ sub a' lookup E b; }} C; }} calt;")
checks.append(("contextual, inserts before, 64 glyphs, extension lookups", path, "ab"))

for label, path, text in checks:
    result = shape(path, text)
    verdict = "same" if result["harfbuzz"] == result["coretext"] else "DIFFERENT"
    print(f"{label:55} {verdict:9} harfbuzz: {summary(result['harfbuzz']):24} coretext: {summary(result['coretext'])}")
