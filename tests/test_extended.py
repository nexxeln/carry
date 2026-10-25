"""Check extended arithmetic against exact integer arithmetic in real shaping engines."""

import argparse
import json
import random
from pathlib import Path

from test_shape import ADVANCE, ROOT, number, shape, visible


def scaled(text: str) -> tuple[int, int]:
    text = text.replace("−", "-")
    whole, dot, fraction = text.partition(".")
    return int(whole + fraction), len(fraction) if dot else 0


def decimal_text(value: int, places: int) -> str:
    sign = "-" if value < 0 else ""
    digits = str(abs(value)).zfill(places + 1)
    if places:
        digits = (digits[:-places] + "." + digits[-places:]).rstrip("0").rstrip(".")
    return sign + digits


def result(a: str, op: str, b: str) -> str:
    left, ls = scaled(a)
    right, rs = scaled(b)
    if op in "*/×÷":
        if op in "*×":
            return decimal_text(left * right, ls + rs)
        assert ls == rs == 0 and right != 0
        quotient = abs(left) // abs(right) * (-1 if (left < 0) != (right < 0) else 1)
        remainder = left - quotient * right
        return str(quotient) + (f" r {remainder}" if remainder else "")
    places = max(ls, rs)
    left *= 10 ** (places - ls)
    right *= 10 ** (places - rs)
    return decimal_text(left + right if op == "+" else left - right, places)


def extended_cases(n: int, m: int, stage: str, count: int = 1000, seed: int = 42, fraction_digits: int = 2, division_digits: int = 4) -> list[tuple[str, str]]:
    nines, mul_nines = "9" * n, "9" * m
    suite = [
        ("128 + 256 =", "128 + 256 =384"),
        ("1  +  2  =", "1  +  2  =3"),
        ("1\u00a0+\u00a02\u00a0=", "1\u00a0+\u00a02\u00a0=3"),
        ("-5+7=", "-5+7=2"),
        ("+5+7=", "+5+7=12"),
        ("5+-7=", "5+-7=-2"),
        ("-5--7=", "-5--7=2"),
        ("-5+-7=", "-5+-7=-12"),
        ("−5−−7=", "−5−−7=2"),
        ("-0+-0=", "-0+-0=0"),
        ("5 × -7 =", "5 × -7 =-35"),
        ("-5 * -7 =", "-5 * -7 =35"),
        ("-12 + +3 =", "-12 + +3 =-9"),
        ("x = -2 + 3 =", "x = -2 + 3 =1"),
        ("1 + 2 = 3", "1 + 2 = 3"),
        ("1 + 2 + 3 =", "1 + 2 + 3 ="),
        ("1 2+3=", "1 2+3="),
        ("1+2 3=", "1+2 3="),
        ("--2+3=", "--2+3="),
        ("1+--2=", "1+--2="),
        ("1++=", "1++="),
        ("x2 + 3 =", "x2 + 3 ="),
        ("x-2+3=", "x-2+3="),
        ("1,5+2=", "1,5+2="),
        ("1+2=3+4=", "1+2=3+4="),
        (f"-{nines}+-{nines}=", f"-{nines}+-{nines}=-{2 * int(nines)}"),
        (f"{nines}--{nines}=", f"{nines}--{nines}={2 * int(nines)}"),
        (f"-{mul_nines}×{mul_nines}=", f"-{mul_nines}×{mul_nines}=-{int(mul_nines) ** 2}"),
    ]
    if stage in ("decimals", "division"):
        suite += [
            ("12.50+3.75=", "12.50+3.75=16.25"),
            ("0.1+0.2=", "0.1+0.2=0.3"),
            ("1.20+1.30=", "1.20+1.30=2.5"),
            ("1.5+2=", "1.5+2=3.5"),
            ("1.25×0.4=", "1.25×0.4=0.5"),
            ("19.99×3=", "19.99×3=59.97"),
            ("-0.1-0.2=", "-0.1-0.2=-0.3"),
            ("0.01×0.01=", "0.01×0.01=0.0001"),
            ("0.01-0.02=", "0.01-0.02=-0.01"),
            ("0.10-0.1=", "0.10-0.1=0"),
            ("99.99+0.01=", "99.99+0.01=100"),
            ("0.99+0.02=", "0.99+0.02=1.01"),
            ("1.00-1.01=", "1.00-1.01=-0.01"),
            ("99.99×99.99=", "99.99×99.99=9998.0001"),
            ("-0.00×19.99=", "-0.00×19.99=0"),
            ("1.20 + +1.30 =", "1.20 + +1.30 =2.5"),
            ("−1.2 × -0.5 =", "−1.2 × -0.5 =0.6"),
            ("1.2+3.4= -4.6", "1.2+3.4= -4.6"),
            ("1.2+3.4= .3", "1.2+3.4= .3"),
            ("1.2+3.4= -.3", "1.2+3.4= -.3"),
            ("1.2+3.4= +.3", "1.2+3.4= +.3"),
            ("1.2+3.4= ", "1.2+3.4=4.6 "),
            (f"{nines}.99+0.01=", f"{nines}.99+0.01={10 ** n}"),
            (f"-{nines}.99+-{nines}.99=", f"-{nines}.99+-{nines}.99=" + decimal_text(-2 * (int(nines) * 100 + 99), 2)),
            (f"{mul_nines}.99×{mul_nines}.99=", f"{mul_nines}.99×{mul_nines}.99=" + decimal_text((int(mul_nines) * 100 + 99) ** 2, 4)),
            (f"1{'0' * n}.00+1=", f"1{'0' * n}.00+1="),
            ("1.2.3+4=", "1.2.3+4="),
            ("1.+2=", "1.+2="),
            (".1+2=", ".1+2="),
            ("x1.2+3=", "x1.2+3="),
            ("1.2+3=4.2", "1.2+3=4.2"),
            (f"0.{'1' * (fraction_digits + 1)}+1=", f"0.{'1' * (fraction_digits + 1)}+1="),
        ]
    else:
        suite += [("1.5+2=", "1.5+2=")]
    suite.append((" ".join(["-9 + -9 ="] * 64), " ".join(["-9 + -9 =-18"] * 64)))
    if stage in ("decimals", "division"):
        suite.append((" ".join(["0.1+0.2="] * 64), " ".join(["0.1+0.2=0.3"] * 64)))
    if stage == "division":
        suite += [
            ("84÷7=", "84÷7=12"),
            ("17/5=", "17/5=3 r 2"),
            ("-17÷5=", "-17÷5=-3 r -2"),
            ("17÷-5=", "17÷-5=-3 r 2"),
            ("-17÷-5=", "-17÷-5=3 r -2"),
            ("0/7=", "0/7=0"),
            ("3/7=", "3/7=0 r 3"),
            ("-1/5=", "-1/5=0 r -1"),
            ("1/-5=", "1/-5=0 r 1"),
            ("-1/-5=", "-1/-5=0 r -1"),
            ("-0/-7=", "-0/-7=0"),
            ("0097/0007=", "0097/0007=13 r 6"),
            ("5/0=", "5/0="),
            ("0/0=", "0/0="),
            ("1.5/2=", "1.5/2="),
            ("12/3=4", "12/3=4"),
            ("12/3= 4", "12/3= 4"),
            ("1/2/3=", "1/2/3="),
            ("1/2+3=", "1/2+3="),
            ("1/2*3=", "1/2*3="),
            ("1+2/3=", "1+2/3="),
            (f"1{'0' * division_digits}/2=", f"1{'0' * division_digits}/2="),
            (f"1/1{'0' * division_digits}=", f"1/1{'0' * division_digits}="),
            (" ".join(["17/5="] * 16), " ".join(["17/5=3 r 2"] * 16)),
        ]
    rng = random.Random(seed)
    for _ in range(count):
        op = rng.choice("+-−*×/÷" if stage == "division" else "+-−*×")
        width = division_digits if op in "/÷" else m if op in "*×" else n
        operands = []
        for _ in range(2):
            sign = rng.choice(["", "", "+", "-", "−"])
            digits = number(rng, width)
            if stage != "syntax" and op not in "/÷" and rng.random() < 0.65:
                places = rng.randint(1, min(fraction_digits, max(1, width - 1)))
                whole = number(rng, max(1, width - places))
                digits = whole + "." + "".join(str(rng.randrange(10)) for _ in range(places))
            operands.append(sign + digits)
        a, b = operands
        spaces = [rng.choice(["", " ", "  ", "\u00a0"]) for _ in range(3)]
        text = f"{a}{spaces[0]}{op}{spaces[1]}{b}{spaces[2]}="
        want = text if op in "/÷" and scaled(b)[0] == 0 else text + result(a, op, b)
        suite.append((text, want))
    return suite


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--font", type=Path, default=ROOT / "build/Carry.ttf")
    parser.add_argument("--meta", type=Path, default=ROOT / "build/carry.json")
    parser.add_argument("--stage", choices=["syntax", "decimals", "division"])
    parser.add_argument("--engines", default="harfbuzz,coretext,textkit")
    parser.add_argument("--cases", type=int, default=3000)
    parser.add_argument("--fraction-digits", type=int)
    parser.add_argument("--division-digits", type=int)
    args = parser.parse_args()
    meta = json.loads(args.meta.read_text())
    names = {g["name"]: g for g in meta["glyphs"]}
    stats = meta["stats"]
    stage = args.stage or stats.get("arithmeticStage", "syntax")
    fraction_digits = args.fraction_digits or stats.get("maxFractionDigits", 2)
    division_digits = args.division_digits or stats.get("maxDivDigits", 4)
    suite = extended_cases(stats["maxDigits"], stats["maxMulDigits"], stage, args.cases, fraction_digits=fraction_digits, division_digits=division_digits)
    failed = False
    for engine in args.engines.split(","):
        rows = shape(engine, args.font, [text for text, _ in suite])
        failures = []
        for (text, want), glyphs in zip(suite, rows):
            got, width = visible(glyphs, names)
            if got != want or width != ADVANCE * len(want):
                failures.append(f"{text!r}: drew {got!r} ({width / ADVANCE:g} cells), want {want!r}")
        print(f"{engine}: {len(suite) - len(failures)}/{len(suite)} extended {stage} cases pass")
        for failure in failures[:20]:
            print("  " + failure)
        failed |= bool(failures)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
