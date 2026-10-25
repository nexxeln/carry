"""Build Carry at several operand widths, test each one, and record what it costs.

    uv run scripts/sweep.py                          # writes build/sweep/ and build/budget.json
    uv run scripts/sweep.py --digits 64,128 --mul-cap 4  # wide sums, small products
"""

import argparse
import json
import random
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

from generate import build_carry, stats  # noqa: E402
from test_shape import answer, shape, visible  # noqa: E402


def shape_seconds(engine: str, font: Path, lines: list[str]) -> float:
    """Wall time to shape `lines` in one process, minus the time to start that process and load the font."""
    def run(batch: list[str]) -> float:
        path = ROOT / "build/sweep/timing.txt"
        path.write_text("\n".join(batch) + "\n")
        cmd = ["hb-shape", "--no-clusters", f"--text-file={path}", str(font)] if engine == "harfbuzz" else [str(ROOT / "tools/ctshape"), str(font)]
        start = time.perf_counter()
        with open(path) as stdin:
            subprocess.run(cmd, stdin=stdin if engine == "coretext" else None, capture_output=True, check=True)
        return time.perf_counter() - start

    baseline = min(run(lines[:1]) for _ in range(3))
    return max(0.0, min(run(lines) for _ in range(3)) - baseline)


def per_line(engine: str, font: Path, names: dict, expr: str) -> int:
    """Largest K (of 1, 2, 4, ... 256) for which a line of K copies of `expr` draws every answer."""
    best = 0
    for k in (1, 2, 4, 8, 16, 32, 64, 128, 256):
        line = " ".join([expr] * k)
        glyphs = shape(engine, font, [line])[0]
        if visible(glyphs, names)[0] != " ".join([expr + answer(expr)] * k):
            break
        best = k
    return best


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--digits", default="1,2,4,8,12,16,24,32,48,64")
    parser.add_argument("--cases", type=int, default=400)
    parser.add_argument("--mul-cap", type=int, default=24, help="multiplication cost grows with width cubed, so wide sweeps cap it")
    parser.add_argument("--out", type=Path, default=ROOT / "build/budget.json")
    args = parser.parse_args()
    out = ROOT / "build/sweep"
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    for n in [int(d) for d in args.digits.split(",")]:
        m = min(n, args.mul_cap)
        font, fea, passes, glyphs = build_carry(n, m, debug=False)
        path = out / f"Carry-{n}.ttf"
        font.save(path)
        meta = {"stats": {**stats(path, n), "maxMulDigits": m}, "glyphs": [{"name": g.name, "role": g.role, "width": g.width, **g.meta} for g in glyphs]}
        meta_path = out / f"carry-{n}.json"
        meta_path.write_text(json.dumps(meta))
        names = {g["name"]: g for g in meta["glyphs"]}

        test = subprocess.run(
            ["uv", "run", "tests/test_shape.py", "--font", str(path), "--meta", str(meta_path), "--cases", str(args.cases), "--ops", "+-*×"],
            capture_output=True, text=True, cwd=ROOT,
        )
        rng = random.Random(n)
        operand = lambda: "".join(str(rng.randint(1, 9)) for _ in range(n))
        sums = [f"{operand()}+{operand()}=" for _ in range(1000)]
        products = [f"{operand()[:m]}*{operand()[:m]}=" for _ in range(1000)]
        row = {
            **meta["stats"],
            "harness": test.stdout.strip().splitlines()[:2],
            "green": test.returncode == 0,
            "usPerSumHarfBuzz": round(shape_seconds("harfbuzz", path, sums) * 1000, 1),
            "usPerSumCoreText": round(shape_seconds("coretext", path, sums) * 1000, 1),
            "usPerProductHarfBuzz": round(shape_seconds("harfbuzz", path, products) * 1000, 1),
            "usPerProductCoreText": round(shape_seconds("coretext", path, products) * 1000, 1),
            "sumsPerLineHarfBuzz": per_line("harfbuzz", path, names, "9+9="),
            "sumsPerLineCoreText": per_line("coretext", path, names, "9+9="),
            "productsPerLineHarfBuzz": per_line("harfbuzz", path, names, "9*9="),
            "productsPerLineCoreText": per_line("coretext", path, names, "9*9="),
        }
        rows.append(row)
        print(json.dumps(row), flush=True)
    args.out.write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
