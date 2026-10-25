"""Shape thousands of expressions with real engines and compare what they draw against real arithmetic.

    uv run tests/test_shape.py                    # HarfBuzz (hb-shape) and CoreText (tools/ctshape), 4000 random cases
    uv run tests/test_shape.py --engines textkit  # TextKit 1 layout, as in TextEdit (tools/tkshape)
    uv run tests/test_shape.py --cases 20000 --engines harfbuzz
    uv run tests/test_shape.py --font build/sweep/Carry-8.ttf --meta build/sweep/carry-8.json
"""

import argparse
import json
import random
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
ADVANCE = 600
GLYPH = re.compile(r"([^|\[\]+@=]+)(?:=\d+)?(?:@-?\d+,-?\d+)?\+(-?\d+)")


def answer(expr: str) -> str:
    a, op, b = re.fullmatch(r"(\d+)([+\-−*×])(\d+)=", expr).groups()
    a, b = int(a), int(b)
    return str({"+": a + b, "-": a - b, "−": a - b, "*": a * b, "×": a * b}[op])


def number(rng: random.Random, max_len: int) -> str:
    length = rng.randint(1, max_len)
    digits = [str(rng.randint(0, 9)) for _ in range(length)]
    if length > 1 and rng.random() < 0.85:
        digits[0] = str(rng.randint(1, 9))
    return "".join(digits)


def cases(n: int, m: int, ops: str, count: int, seed: int) -> list[tuple[str, str]]:
    """(text typed, text the font should draw)."""
    rng = random.Random(seed)
    nines = "9" * n
    out = [
        ("0+0=", "0+0=0"),
        ("1+1=", "1+1=2"),
        (f"{nines}+{nines}=", f"{nines}+{nines}={int(nines) * 2}"),
        (f"{nines}+1=", f"{nines}+1={int(nines) + 1}"),
        ("12+3", "12+3"),
        ("12+3=15", "12+3=15"),
        ("1+2+3=", "1+2+3="),
        ("1+2=3+4=", "1+2=3+4="),
        ("007+3=", "007+3=10" if n >= 3 else "007+3="),
        ("5=", "5="),
        ("=", "="),
        ("+=", "+="),
        ("1.5+2=", "1.5+2="),
        ("= 1+2=", "= 1+2=3"),
        ("x = 2+3=", "x = 2+3=5"),
        ("(2+3=", "(2+3=5"),
        ("x2+3=", "x2+3="),
        ("0x1+1=", "0x1+1="),
        ("a_1+1=", "a_1+1="),
        (f"x{nines}+1=", f"x{nines}+1="),
        ("1+2= 3+4=", "1+2=3 3+4=7"),
        (f"1{'0' * n}+1=", f"1{'0' * n}+1="),
        (f"1+1{'0' * n}=", f"1+1{'0' * n}="),
    ]
    if "-" in ops:
        out += [
            ("5-7=", "5-7=-2"),
            ("42-42=", "42-42=0" if n >= 2 else "42-42="),
            (f"0-{nines}=", f"0-{nines}=-{nines}"),
            (f"1{'0' * (n - 1)}-1=", f"1{'0' * (n - 1)}-1={10 ** (n - 1) - 1}"),
            ("10−3=", "10−3=7" if n >= 2 else "10−3="),
            ("3-4 5", "3-4 5"),
        ]
    if "*" in ops or "×" in ops:
        out += [
            ("0*0=", "0*0=0"),
            ("12×0=", "12×0=0" if m >= 2 else "12×0="),
            ("7*8=", "7*8=56"),
            (f"{nines[:m]}×{nines[:m]}=", f"{nines[:m]}×{nines[:m]}={int(nines[:m]) ** 2}"),
            (f"1{'0' * m}*2=", f"1{'0' * m}*2="),
            (f"{'1' * 2 * m}*2=", f"{'1' * 2 * m}*2="),
            (f"2*{'1' * 2 * m}=", f"2*{'1' * 2 * m}="),
            ("2*3 4*5=", "2*3 4*5=20"),
            ("3+4= 5*6=", "3+4=7 5*6=30"),
        ]
    for _ in range(count):
        op = rng.choice(ops)
        width = m if op in "*×" else n
        expr = f"{number(rng, width)}{op}{number(rng, width)}="
        out.append((expr, expr + answer(expr)))
    return out


def visible(glyphs: list[tuple[str, int]], names: dict[str, dict]) -> tuple[str, int]:
    text = []
    for name, _ in glyphs:
        glyph = names[name]
        if glyph["role"] in ("digit", "result", "text"):
            text.append(glyph.get("text", str(glyph.get("value"))))
        elif glyph["width"] == 0 and glyph["role"] in ("pad", "blank"):
            continue
        else:
            text.append(f"<{name}>")
    return "".join(text), sum(advance for _, advance in glyphs)


def shape(engine: str, font: Path, lines: list[str]) -> list[list[tuple[str, int]]]:
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("\n".join(lines) + "\n")
    if engine == "harfbuzz":
        cmd = ["hb-shape", "--no-clusters", f"--text-file={f.name}", str(font)]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    else:
        tool = {"coretext": "tools/ctshape", "textkit": "tools/tkshape"}[engine]
        with open(f.name) as stdin:
            result = subprocess.run([str(ROOT / tool), str(font)], stdin=stdin, capture_output=True, text=True, check=True).stdout
    rows = result.strip("\n").split("\n")
    assert len(rows) == len(lines), f"{engine}: {len(rows)} rows for {len(lines)} lines"
    return [[(m[1], int(m[2])) for m in GLYPH.finditer(row)] for row in rows]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--font", type=Path, default=ROOT / "build/Carry.ttf")
    parser.add_argument("--meta", type=Path, default=ROOT / "build/carry.json")
    parser.add_argument("--engines", default="harfbuzz,coretext")
    parser.add_argument("--ops", default="+-")
    parser.add_argument("--cases", type=int, default=4000)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()

    meta = json.loads(args.meta.read_text())
    names = {g["name"]: g for g in meta["glyphs"]}
    n = meta["stats"]["maxDigits"]
    m = meta["stats"].get("maxMulDigits", n)
    suite = cases(n, m, args.ops, args.cases, args.seed)
    typed = [t for t, _ in suite]

    failed = False
    for engine in args.engines.split(","):
        results = shape(engine, args.font, typed)
        failures = []
        for (text, want), glyphs in zip(suite, results):
            got, width = visible(glyphs, names)
            if got != want or width != ADVANCE * len(want):
                failures.append(f"  {text!r}: drew {got!r} ({width / ADVANCE:g} cells), want {want!r}")
        print(f"{engine}: {len(suite) - len(failures)}/{len(suite)} pass (n={n}, ops={args.ops})")
        for line in failures[:15]:
            print(line)
        failed |= bool(failures)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
