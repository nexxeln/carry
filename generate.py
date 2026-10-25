"""Generate Carry, a font that does arithmetic with GSUB substitutions and nothing else.

    uv run generate.py                              # writes build/Carry.ttf, Carry-Debug.ttf, Carry-v0.ttf, carry.json
    uv run generate.py --digits 6 --mul-digits 4    # narrower operands
"""

import argparse
import json
import math
from pathlib import Path

from fontTools.agl import UV2AGL
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.misc.timeTools import timestampFromString
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib.tables import ttProgram
from fontTools.ttLib import TTFont, newTable

from decimal_features import DecimalMachine, DecimalSpec
from division_features import DivisionMachine, DivisionSpec
from font_model import ADVANCE, DOT, Glyph, Pass, cls, sv
from pixels import BITMAPS

UPM = 1000
CELL = 100
GHOST_DOT = 36

# CoreText (macOS 27) re-applies a multiple substitution that a contextual rule
# calls when it puts more than 64 glyphs in front of the matched glyph, and the
# line fills with hundreds of copies. Plain multiple substitutions, and ones
# that append after the matched glyph, are fine at any length. So padding
# inserts at most 63 pads (plus the digit itself) per pass. See JOURNAL.md.
PADS_PER_PASS = 63

VERSION = "1.000"
AUTHOR = "Shoubhit Dash"
LICENSE = "This Font Software is licensed under the SIL Open Font License, Version 1.1. This license is available with a FAQ at: https://openfontlicense.org"

# A fixed head timestamp, so rebuilding from the same source gives identical bytes.
BUILT = timestampFromString("Sat Oct 24 00:00:00 2026")

DIGITS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
SYMBOLS = {
    "plus": "+",
    "hyphen": "-",
    "minus": "−",
    "equal": "=",
    "asterisk": "*",
    "multiply": "×",
    "divide": "÷",
    "period": ".",
    "comma": ",",
    "space": " ",
    "uni00A0": "\u00a0",
}
DRAWING = {"minus": "-", "uni00A0": " "}
DIVISION_SPEC = DivisionSpec()

B_VALUES = range(-9, 10)
COL_VALUES = range(-18, 19)
SIGNS = ("z", "p", "n")
CARRIES = (-1, 0, 1)
VAL_VALUES = range(0, 91)


def b_name(v: int) -> str:
    return f"b.{sv(v)}"


def col_name(v: int) -> str:
    return f"col.{sv(v)}"


def sig_name(v: int, s: str) -> str:
    return f"col.{sv(v)}.{s}"


def dig_name(d: int, c: int, s: str) -> str:
    return f"d{d}.c{ {-1: 'm', 0: '0', 1: '1'}[c] }.{s}"


def sign_of(v: int) -> str:
    return "z" if v == 0 else "p" if v > 0 else "n"


def settle(v: int, sign: str, carry_in: int) -> tuple[int, int, str]:
    """A column holding v, with carry_in from the right, becomes one digit and a carry out.

    A negative answer negates every column, so the carry stays between -1 and 1.
    """
    e = (-v if sign == "n" else v) + carry_in
    return e % 10, max(-1, min(1, e // 10)), sign


SIG_STATES = [(0, "z")] + [(v, s) for s in ("p", "n") for v in COL_VALUES]
DIG_STATES = sorted(
    {settle(v, s, c) for v in COL_VALUES for s in ("p", "n") for c in CARRIES},
    key=lambda t: (t[2] == "n", t[1], t[0]),
)


def accb_name(r: int, b: int) -> str:
    return f"acc{r}.b{b}"


def val_name(v: int) -> str:
    return f"val.{v}"


def mc_name(d: int, c: int) -> str:
    return f"mc{d}.c{c}"


def inventory(debug: bool) -> list[Glyph]:
    """Every glyph in the font, in glyph-ID order. Each stage of the machine owns one family."""
    glyphs = [Glyph(".notdef", "text", tuple(["#####", "#...#", "#...#", "#...#", "#...#", "#...#", "#####"]), width=ADVANCE)]
    for d, name in enumerate(DIGITS):
        glyphs.append(Glyph(name, "digit", tuple(BITMAPS[str(d)]), width=ADVANCE, char=str(d), meta={"value": d}))
    for name, char in SYMBOLS.items():
        glyphs.append(Glyph(name, "text", tuple(BITMAPS[DRAWING.get(name, char)]), width=ADVANCE, char=char, meta={"text": char}))

    # Syntax glyphs keep their outlines and advances. GDEF ligatures, unlike
    # marks, can be skipped without HarfBuzz zeroing their advances.
    for name in ("space", "uni00A0", "plus", "hyphen", "minus"):
        char = SYMBOLS[name]
        glyphs.append(Glyph(f"syntax.{name}", "text", tuple(BITMAPS[DRAWING.get(name, char)]), width=ADVANCE, meta={"text": char}))
    for d, name in enumerate(DIGITS):
        glyphs.append(Glyph(f"neg.{name}", "digit", tuple(BITMAPS[str(d)]), width=ADVANCE, meta={"value": d}))
    glyphs.append(Glyph("mul.negative", "slot"))
    for name in ("space", "uni00A0"):
        glyphs.append(Glyph(f"boundary.{name}", "text", width=ADVANCE, meta={"text": SYMBOLS[name]}))
        glyphs.append(Glyph(f"invalid.{name}", "text", width=ADVANCE, meta={"text": SYMBOLS[name]}))
    for prefix, originals in (("pending", DIGITS + ["space", "uni00A0", "period"]), ("tail", ["space", "uni00A0", "plus", "hyphen", "minus"]), ("answered", ["equal"])):
        for name in originals:
            char = str(DIGITS.index(name)) if name in DIGITS else SYMBOLS[name]
            glyphs.append(Glyph(f"{prefix}.{name}", "text", tuple(BITMAPS[DRAWING.get(name, char)]), width=ADVANCE, meta={"text": char}))

    ghost_zero = tuple(BITMAPS["0"]) if debug else ()
    hidden_width = ADVANCE if debug else 0
    glyphs.append(Glyph("pad", "pad", ghost_zero, GHOST_DOT, hidden_width, meta={"value": 0}))
    glyphs.append(Glyph("blank", "blank", ghost_zero, GHOST_DOT, hidden_width, meta={"value": 0}))

    for op in ("add", "sub"):
        glyphs.append(Glyph(f"slot.{op}", "slot", meta={"op": op}))
    glyphs += [Glyph(b_name(v), "colb", meta={"value": v}) for v in B_VALUES]
    glyphs += [Glyph(col_name(v), "col", meta={"value": v}) for v in COL_VALUES]
    glyphs += [Glyph(sig_name(v, s), "sign", meta={"value": v, "sign": s}) for v, s in SIG_STATES]
    glyphs += [Glyph(dig_name(d, c, s), "carry", meta={"value": d, "carry": c, "sign": s}) for d, c, s in DIG_STATES]
    glyphs += [Glyph(accb_name(r, b), "accb", meta={"value": r, "b": b}) for b in range(10) for r in range(10)]
    glyphs += [Glyph(val_name(v), "val", meta={"value": v}) for v in VAL_VALUES]
    glyphs += [Glyph(mc_name(d, c), "mc", meta={"value": d, "carry": c}) for c in range(10) for d in range(10)]
    glyphs += [Glyph(f"res.{d}", "result", tuple(BITMAPS[str(d)]), width=ADVANCE, meta={"value": d}) for d in range(10)]
    glyphs.append(Glyph("res.minus", "result", tuple(BITMAPS["-"]), width=ADVANCE, meta={"text": "-"}))
    # The rest of printable ASCII. Without letters, macOS decides the font
    # supports no language, and font pickers that filter by language hide it.
    drawn = set(SYMBOLS.values()) | {str(d) for d in range(10)}
    glyphs += [
        Glyph(UV2AGL[ord(ch)], "text", tuple(BITMAPS[ch]), width=ADVANCE, char=ch, meta={"text": ch})
        for ch in map(chr, range(0x21, 0x7F))
        if ch not in drawn
    ]
    return glyphs


def rule(*parts: str) -> str:
    return " ".join(p for p in parts if p)


def features(n: int, m: int, names: list[str]) -> tuple[str, list[Pass]]:
    """Feature code for sums and differences of up to `n` digits and products of up to `m` digits.

    Addition and subtraction pad both operands to exactly n glyphs. After PAD and
    SLOTS have run, the line always looks like this:

        A[n-1] .. A[0]  op  B[n-1] .. B[0]  =  C  R[n-1] .. R[0]

    so slot R[j] finds B[j] n+2 glyphs to its left and A[j] 2n+3 glyphs to its
    left, whatever the operands' real lengths. That turns "fetch the matching
    digit" into a fixed-length context, which one contextual lookup can express.

    Multiplication pads both operands to 2m glyphs and makes 2m slots:

        A[2m-1] .. A[0]  ×  B[2m-1] .. B[0]  =  R[2m-1] .. R[0]

    Row j adds A[k-j] × B[j] into every slot R[k]. A[k-j] sits 4m+2-j glyphs to
    the left of R[k] for every k. When k-j is out of range, that position holds
    a pad or the operator, so it reads as zero. That is why both operands are
    padded to twice their real width.
    """
    any_glyph = "@ANY"
    decimal = DecimalMachine(DecimalSpec(n, m), DIGITS, {dig_name(*s): s for s in DIG_STATES}, PADS_PER_PASS)
    division = DivisionMachine(DIVISION_SPEC)
    wildcards = lambda count: " ".join([any_glyph] * count)
    lookups: list[str] = ["lookup keep { sub @JOINED by @JOINED; } keep;"]
    lookups += decimal.lookups()
    lookups += division.lookups()

    for k in range(1, min(max(n, 2 * m, division.spec.digits), PADS_PER_PASS + 1)):
        rules = " ".join(f"sub {d} by {' '.join(['pad'] * k)} {d};" for d in DIGITS + [f"neg.{d}" for d in DIGITS])
        lookups.append(f"lookup pad{k} {{ {rules} }} pad{k};")
    for op in ("add", "sub"):
        lookups.append(f"lookup expand_{op} {{ sub equal by equal col.0 {' '.join([f'slot.{op}'] * n)}; }} expand_{op};")
    lookups.append(f"lookup expand_mul {{ sub equal by equal {' '.join([mc_name(0, 0)] * (2 * m))}; }} expand_mul;")
    lookups.append(f"lookup expand_mul_negative {{ sub equal by equal mul.negative {' '.join([mc_name(0, 0)] * (2 * m))}; }} expand_mul_negative;")
    lookups.append("lookup syntax_space { sub [space uni00A0] by [syntax.space syntax.uni00A0]; } syntax_space;")
    lookups.append("lookup syntax_sign { sub [plus hyphen minus] by [syntax.plus syntax.hyphen syntax.minus]; } syntax_sign;")
    lookups.append(f"lookup negate {{ sub {cls(DIGITS)} by {cls('neg.' + d for d in DIGITS)}; }} negate;")
    lookups.append("lookup mul_minus { sub mul.negative by res.minus; } mul_minus;")
    lookups.append("lookup mul_blank { sub mul.negative by blank; } mul_blank;")
    lookups.append("lookup answered { sub equal by answered.equal; } answered;")
    for b in range(10):
        lookups.append(f"lookup take_b{b} {{ sub slot.add by {b_name(b)}; sub slot.sub by {b_name(-b)}; }} take_b{b};")
        lookups.append(f"lookup take_bn{b} {{ sub slot.add by {b_name(-b)}; sub slot.sub by {b_name(b)}; }} take_bn{b};")
    for a in range(-9, 10):
        rules = " ".join(f"sub {b_name(v)} by {col_name(v + a)};" for v in B_VALUES)
        lookups.append(f"lookup add_a{sv(a)} {{ {rules} }} add_a{sv(a)};")
    lookups.append(
        "lookup sign_z { " + " ".join(f"sub {col_name(v)} by {sig_name(v, sign_of(v))};" for v in COL_VALUES) + " } sign_z;"
    )
    for s in ("p", "n"):
        rules = " ".join(f"sub {col_name(v)} by {sig_name(v, s)};" for v in COL_VALUES)
        lookups.append(f"lookup sign_{s} {{ {rules} }} sign_{s};")
    every_mc = [mc_name(d, c) for c in range(10) for d in range(10)]
    for b in range(10):
        rules = " ".join(f"sub {mc_name(d, c)} by {accb_name(d, b)};" for c in range(10) for d in range(10))
        lookups.append(f"lookup with_b{b} {{ {rules} }} with_b{b};")
    for a in range(10):
        rules = " ".join(f"sub {accb_name(r, b)} by {val_name(r + a * b)};" for b in range(10) for r in range(10))
        lookups.append(f"lookup times_a{a} {{ {rules} }} times_a{a};")
    every_dig = [dig_name(*state) for state in DIG_STATES]
    negative_zeros = [dig_name(0, c, "n") for c in CARRIES if (0, c, "n") in DIG_STATES]
    negative_nonzeros = [dig_name(d, c, s) for d, c, s in DIG_STATES if d and s == "n"]
    lookups.append("lookup overflow_minus { " + " ".join(f"sub {g} by res.minus {g};" for g in negative_nonzeros) + " } overflow_minus;")
    shown = every_dig + every_mc
    lookups.append("lookup to_result { " + " ".join(f"sub {g} by res.{g[2] if g.startswith('mc') else g[1]};" for g in shown) + " } to_result;")
    zeros = [g for g in every_dig if g[1] == "0"] + [mc_name(0, c) for c in range(10)]
    lookups.append("lookup to_blank { " + " ".join(f"sub {g} by blank;" for g in zeros) + " } to_blank;")
    lookups.append(
        "lookup to_minus { " + " ".join(f"sub {g} by res.minus;" for g in negative_zeros) + " } to_minus;"
    )

    padded = lambda width: " ".join(["@PADDED"] * width)
    digits = lambda count: " ".join(["@DIGIT"] * count)
    # (operator class, padded width, longest operand that fits)
    layouts = [("@ADDOP", n, n), ("@MULOP", 2 * m, m), ("@DIVOP", division.spec.digits, division.spec.digits)]
    pad_passes = []
    longest_pad = max(width - 1 for _, width, _ in layouts)
    for chunk in range(max(1, -(-longest_pad // PADS_PER_PASS))):
        rules = ["ignore sub [@DIGIT @WORD period comma] @DIGIT';"] if chunk == 0 else []
        already = " ".join(["pad"] * (chunk * PADS_PER_PASS))
        for ops, width, longest in layouts:
            for k in range(longest):
                pads = min(width - 1 - k - chunk * PADS_PER_PASS, PADS_PER_PASS)
                if pads <= 0:
                    continue
                rules.append(rule("sub", "" if chunk == 0 else "pad", f"@DIGIT' lookup pad{pads}", digits(k), f"{ops};"))
                rules.append(rule("sub", ops, already, f"@DIGIT' lookup pad{pads}", digits(k), "equal;"))
        pad_passes.append(rules)

    mul_operand = " ".join(["pad"] * m + ["@PADDED"] * m)
    mul_positive = " ".join(["pad"] * m + ["@POSPAD"] * (m - 1) + ["@POSDIGIT"])
    mul_negative = " ".join(["pad"] * m + ["@NEGPAD"] * (m - 1) + ["@NEGDIGIT"])
    slot_rules = [
        "ignore sub equal' [@PADDED @WORD period comma @OP equal dec.equal answered.equal];",
        f"ignore sub [@DIGIT @WORD @OP equal dec.equal answered.equal period comma invalid.space invalid.uni00A0] {padded(n)} @ADDOP {padded(n)} equal';",
        f"ignore sub [@DIGIT @WORD @OP equal dec.equal answered.equal period comma invalid.space invalid.uni00A0] {padded(2 * m)} @MULOP {padded(2 * m)} equal';",
        f"sub {padded(n)} plus {padded(n)} equal' lookup expand_add;",
        f"sub {padded(n)} [hyphen minus] {padded(n)} equal' lookup expand_sub;",
        # An operand of up to m digits always starts with at least m pads. Requiring
        # them rejects a 2m-digit operand, which would fill the block unpadded.
        f"sub {mul_negative} @MULOP {mul_negative} equal' lookup expand_mul;",
        f"sub {mul_negative} @MULOP {mul_positive} equal' lookup expand_mul_negative;",
        f"sub {mul_positive} @MULOP {mul_negative} equal' lookup expand_mul_negative;",
        f"sub {mul_operand} @MULOP {mul_operand} equal' lookup expand_mul;",
    ]

    # Zero needs no context: anything that is not a nonzero digit at that
    # distance is a pad, so a context-free fallback reads it as 0. Long
    # contexts cost HarfBuzz shaping budget only when they match.
    read_b = [f"sub @VAL{b} {wildcards(n + 1)} [slot.add slot.sub]' lookup take_b{b};" for b in range(1, 10)]
    read_b = [f"sub neg.{DIGITS[b]} {wildcards(n + 1)} [slot.add slot.sub]' lookup take_bn{b};" for b in range(1, 10)] + read_b
    read_b.append("sub [slot.add slot.sub]' lookup take_b0;")
    read_a = [f"sub @VAL{a} {wildcards(2 * n + 2)} @COLB' lookup add_a{a};" for a in range(1, 10)]
    read_a = [f"sub neg.{DIGITS[a]} {wildcards(2 * n + 2)} @COLB' lookup add_a{sv(-a)};" for a in range(1, 10)] + read_a
    read_a.append("sub @COLB' lookup add_a0;")

    sign_rules = [
        "sub [equal dec.equal @SIGZ] @COL' lookup sign_z;",
        "sub @SIGP @COL' lookup sign_p;",
        "sub @SIGN @COL' lookup sign_n;",
    ]

    every_sig = [sig_name(v, s) for v, s in SIG_STATES]
    carry_rules = []
    for s in ("p", "n"):
        for c in CARRIES:
            incoming = cls(dig_name(*state) for state in DIG_STATES if state[1:] == (c, s))
            out = cls(dig_name(*settle(v, s, c)) for v, _ in SIG_STATES)
            carry_rules.append(f"rsub @SIG' {incoming} by {out};")
    out = cls(dig_name(*settle(v, "n" if own == "n" else "p", 0)) for v, own in SIG_STATES)
    carry_rules.append(f"rsub @SIG' by {out};")

    every_val = [val_name(v) for v in VAL_VALUES]
    row_passes = []
    for j in range(m):
        broadcast = [rule("sub", f"@VAL{b}", wildcards(j), f"equal @MC' lookup with_b{b};") for b in range(10)]
        broadcast += [f"sub {cls(accb_name(r, b) for r in range(10))} @MC' lookup with_b{b};" for b in range(10)]
        multiply = [f"sub @VAL{a} {wildcards(4 * m + 1 - j)} @ACCB' lookup times_a{a};" for a in range(1, 10)]
        multiply.append("sub @ACCB' lookup times_a0;")
        normalize = [
            f"rsub @VALS' {cls(mc_name(d, c) for d in range(10))} by {cls(mc_name((v + c) % 10, (v + c) // 10) for v in VAL_VALUES)};"
            for c in range(1, 10)
        ]
        normalize.append(f"rsub @VALS' by {cls(mc_name(v % 10, v // 10) for v in VAL_VALUES)};")
        row_passes += [
            Pass(f"row{j}_b", f"row {j + 1}: spread B digit {j + 1}", "ltr",
                 f"the first slot reads the digit {j + 2} glyphs to its left, digit {j + 1} of B counting from the right. every later slot copies it from its left neighbour.",
                 broadcast, j + 2),
            Pass(f"row{j}_mul", f"row {j + 1}: multiply", "ltr",
                 f"every slot reads the digit {4 * m + 2 - j} glyphs to its left, the A digit that lines up with it for this row, and adds A digit × B digit to the digit it already holds. totals run from 0 to 90.",
                 multiply, 4 * m + 2 - j),
            Pass(f"row{j}_carry", f"row {j + 1}: carry", "rtl",
                 "right to left, each slot adds the carry from its right neighbour, keeps the last digit, and hands the rest (0 to 9) to its left neighbour.",
                 normalize),
        ]

    mul_sign_rules = [
        *[f"sub mul.negative' lookup mul_minus {' '.join([mc_name(0, 0)] * k)} {cls(mc_name(d, c) for c in range(10) for d in range(1, 10))};" for k in range(2 * m)],
        "sub mul.negative' lookup mul_blank;",
    ]
    show_rules = [
        f"sub equal {cls(negative_zeros)}' lookup to_minus;",
        f"sub [equal blank res.minus] {cls(zeros)}' lookup to_blank [@DIG @MC];",
        "sub [@DIG @MC]' lookup to_result;",
    ]

    # HarfBuzz marks a boundary unsafe to break only where a rule matched across
    # it. Before the = is typed, nothing matches across the digits of B, so
    # Chromium keeps the old shaping of the text before an edit and reshapes
    # only the tail, which never sees the whole sum. Replacing each glyph with
    # itself across every digit, operator, =, and space marks the whole run,
    # including an answer typed after =. This must run before syntax tagging.
    join_rules = ["sub @JOINED @JOINED' lookup keep;"]

    syntax_passes = [
        Pass("answer_tail", "recognize an existing answer", "rtl", "distinguish a spaced answer from the next complete expression", [
            f"rsub @POSDIGIT' [@OP equal @PENDING] by {cls('pending.' + d for d in DIGITS)};",
            "rsub period' @PENDING by pending.period;",
            "rsub [space uni00A0]' [@OP equal @PENDING] by [pending.space pending.uni00A0];",
            "rsub @ADDOP' [@POSDIGIT @TAIL period] by [tail.plus tail.hyphen tail.minus];",
            "rsub [space uni00A0]' [@POSDIGIT @WORD @TAIL period] by [tail.space tail.uni00A0];",
        ]),
        Pass("answered", "leave answered expressions alone", "ltr", "an existing signed or spaced answer blocks expansion", [
            "sub equal' lookup answered [@POSDIGIT @TAIL];",
        ]),
        Pass("restore_tail", "restore lexical probes", "ltr", "the lookahead leaves all original text untouched", [
            *[f"sub pending.{name} by {name};" for name in DIGITS + ["space", "uni00A0", "period"]],
            *[f"sub tail.{name} by {name};" for name in ["space", "uni00A0", "plus", "hyphen", "minus"]],
        ]),
        Pass("spaces_left", "recognize spaces before punctuation", "rtl", "only operator-adjacent spaces can be skipped", [
            "rsub [space uni00A0]' [@OP equal syntax.space syntax.uni00A0] by [syntax.space syntax.uni00A0];",
        ]),
        Pass("spaces_right", "recognize spaces after operators", "ltr", "preserve spaces within numbers as boundaries", [
            "sub [@OP syntax.space syntax.uni00A0] [space uni00A0]' lookup syntax_space;",
        ]),
        Pass("unary", "recognize one unary sign", "ltr", "a sign after a digit remains a binary operator", [
            "ignore sub @DIGIT @ADDOP' @POSDIGIT;",
            "sub [hyphen minus]' lookup syntax_sign @POSDIGIT' lookup negate;",
            "sub plus' lookup syntax_sign @POSDIGIT;",
        ]),
        Pass("unary_boundary", "retain the boundary before a signed operand", "rtl", "spaces before the first unary sign delimit the expression", [
            "rsub [syntax.space syntax.uni00A0]' [syntax.plus syntax.hyphen syntax.minus boundary.space boundary.uni00A0] by [boundary.space boundary.uni00A0];",
        ]),
        Pass("unary_spacing", "skip spacing inside the expression", "ltr", "a binary operator makes the following sign spacing internal", [
            "sub [@OP syntax.space syntax.uni00A0] [boundary.space boundary.uni00A0]' by [syntax.space syntax.uni00A0];",
        ]),
        Pass("negative_digits", "retain operand polarity", "ltr", "propagate the unary minus through contiguous digits", [
            "sub @NEGDIGIT period @POSDIGIT' lookup negate;",
            "sub @NEGDIGIT @POSDIGIT' lookup negate;",
        ]),
        Pass("number_boundaries", "reject a split first operand", "ltr", "a completed right operand may delimit the next expression, but a bare number may not", [
            *[f"ignore sub @OP {digits(k)} [space uni00A0]';" for k in range(1, max(n, m, division.spec.digits) + 1)],
            *[f"ignore sub @OP {digits(k)} period {digits(f)} [space uni00A0]';" for k in range(1, max(n, m, division.spec.digits) + 1) for f in range(1, decimal.spec.fraction_digits + 1)],
            "sub [@DIGIT invalid.space invalid.uni00A0] [space uni00A0]' by [invalid.space invalid.uni00A0];",
        ]),
    ]
    passes = [
        Pass("join", "hold the expression together", "ltr",
              "adjacent digits, operators, equals signs, and ASCII/NBSP spaces are replaced by themselves before parsing. the engine must reshape the whole expression when an answer is typed or edited.",
             join_rules),
    ] + syntax_passes + decimal.normalization_passes() + [
        Pass("pad" if i == 0 else f"pad{i + 1}", "pad both operands", "ltr",
             f"each operand's first digit looks ahead to count its own length, then a multiple substitution inserts zero-width zeros so every operand is exactly {n} glyphs long ({2 * m} for multiplication).",
             rules)
        for i, rules in enumerate(pad_passes)
    ] + [
        *division.passes(),
        Pass("slots", "make room for the answer", "ltr",
             f"an = that follows two padded operands becomes = plus a carry slot plus {n} blank answer slots ({2 * m} slots for multiplication).",
             slot_rules),
        Pass("read_b", "fetch the B digit", "ltr",
             f"every answer slot grabs the digit exactly {n + 2} glyphs to its left, which is always the matching digit of B (negated for subtraction).",
             read_b, n + 2),
        Pass("read_a", "add the A digit", "ltr",
             f"every slot grabs the digit {2 * n + 3} glyphs to its left, the matching digit of A, and adds it. now each slot holds a column total from -18 to 18.",
             read_a, 2 * n + 3),
        *decimal.addition_passes(),
        Pass("sign", "find the sign", "ltr",
             "left to right, each slot copies the sign of the first nonzero column before it. the last slot ends up knowing whether the whole answer is negative.",
             sign_rules),
        Pass("carry", "ripple the carries", "rtl",
             "a reverse chaining lookup walks right to left. each slot reads the carry its right neighbour just produced, settles into one digit, and passes its own carry left.",
             carry_rules),
        *row_passes,
        *decimal.multiplication_passes(),
        *decimal.presentation_passes(),
        Pass("mul_sign", "draw the product sign", "ltr", "negative zero remains zero", mul_sign_rules),
        Pass("overflow_sign", "draw a full-width negative sum", "ltr", "a negative sum may need both a leading digit and a minus", [
            f"sub equal {cls(negative_nonzeros)}' lookup overflow_minus;",
        ]),
        Pass("show", "draw the answer", "ltr",
             "leading zeros become zero-width blanks, a negative answer gets its minus sign, and every other slot becomes a visible digit.",
             show_rules),
    ]

    classes = [
        f"@ANY = {cls(names[1:])};",
        f"@POSDIGIT = {cls(DIGITS)};",
        f"@NEGDIGIT = {cls('neg.' + d for d in DIGITS)};",
        "@DIGIT = [@POSDIGIT @NEGDIGIT];",
        "@POSPAD = [@POSDIGIT pad];",
        "@NEGPAD = [@NEGDIGIT pad];",
        f"@PENDING = {cls('pending.' + d for d in DIGITS + ['space', 'uni00A0', 'period'])};",
        "@TAIL = [tail.space tail.uni00A0 tail.plus tail.hyphen tail.minus];",
        "@PADDED = [@DIGIT pad];",
        "@ADDOP = [plus hyphen minus];",
        "@MULOP = [asterisk multiply];",
        "@DIVOP = [slash divide];",
        "@OP = [@ADDOP @MULOP @DIVOP dec.plus dec.hyphen dec.minus dec.asterisk dec.multiply];",
        "@JOINED = [@DIGIT @OP equal space uni00A0 period];",
        # A digit glued to a letter or underscore is part of a name like x2 or 0x1F, not a number.
        f"@WORD = {cls([UV2AGL[c] for c in [*range(0x41, 0x5B), *range(0x61, 0x7B), 0x5F]])};",
        *[f"@VAL{d} = [{DIGITS[d]} neg.{DIGITS[d]}{' pad' if d == 0 else ''}];" for d in range(10)],
        f"@COLB = {cls(b_name(v) for v in B_VALUES)};",
        f"@COL = {cls(col_name(v) for v in COL_VALUES)};",
        *[f"@SIG{s.upper()} = {cls(sig_name(v, own) for v, own in SIG_STATES if own == s)};" for s in SIGNS],
        f"@SIG = {cls(every_sig)};",
        f"@DIG = {cls(every_dig)};",
        f"@MC = {cls(every_mc)};",
        f"@ACCB = {cls(accb_name(r, b) for b in range(10) for r in range(10))};",
        f"@VALS = {cls(every_val)};",
    ]
    classes += decimal.declarations()
    classes += division.declarations()

    fea = ["languagesystem DFLT dflt;", "languagesystem latn dflt;", "", *classes, ""]
    fea += lookups
    fea.append("table GDEF { GlyphClassDef , [syntax.space syntax.uni00A0 syntax.plus syntax.hyphen syntax.minus mul.negative dec.period dec.mul.negative], , ; } GDEF;")
    fea += ["", "feature calt {"]
    for p in passes:
        fea.append(f"  # {p.title}: {p.blurb}")
        extension = " useExtension" if p.use_extension else ""
        fea.append(f"  lookup {p.name.upper()}{extension} {{")
        if p.name not in ("answer_tail", "answered", "restore_tail", "spaces_left", "spaces_right", "unary_boundary", "unary_spacing", "mul_sign", "dec_product_sign"):
            fea.append("    lookupflag IgnoreLigatures;")
        else:
            fea.append("    lookupflag 0;")
        fea += [f"    {rule}" for rule in p.body]
        fea.append(f"  }} {p.name.upper()};")
    fea.append("} calt;")
    return "\n".join(fea) + "\n", passes


def draw(glyph: Glyph, x_offset: int = 0, pen: TTGlyphPen | None = None) -> TTGlyphPen:
    """Draw each lit cell of the bitmap as a round dot, like an LED matrix."""
    pen = pen or TTGlyphPen(None)
    radius = glyph.dot / 2
    # Eight off-curve points on an octagon around the dot. TrueType puts an
    # on-curve point midway between each pair, which lands on the circle.
    reach = radius / math.cos(math.pi / 8)
    ring = [(math.cos(-math.pi / 8 - i * math.pi / 4), math.sin(-math.pi / 8 - i * math.pi / 4)) for i in range(8)]
    for row, line in enumerate(glyph.bitmap):
        for col, lit in enumerate(line):
            if lit != "#":
                continue
            cx = x_offset + 50 + col * CELL + CELL / 2
            cy = (6 - row) * CELL + CELL / 2
            pen.qCurveTo(*[(round(cx + reach * dx), round(cy + reach * dy)) for dx, dy in ring], None)
            pen.closePath()
    return pen


def assemble(family: str, glyphs: list[Glyph], drawings: dict, fea: str) -> TTFont:
    fb = FontBuilder(UPM, isTTF=True)
    fb.setupGlyphOrder([g.name for g in glyphs])
    fb.setupCharacterMap({ord(g.char): g.name for g in glyphs if g.char})
    fb.setupGlyf({g.name: drawings[g.name].glyph() for g in glyphs})
    glyf = fb.font["glyf"]
    fb.setupHorizontalMetrics({g.name: (g.width, getattr(glyf[g.name], "xMin", 0)) for g in glyphs})
    fb.setupHorizontalHeader(ascent=900, descent=-250)
    # macOS lists and picks fonts by PostScript name. Without one, CoreText
    # invents a placeholder, Font Book fails validation, and apps can't use it.
    ps_name = family.replace(" ", "") + "-Regular"
    fb.setupNameTable({
        "copyright": f"Copyright 2026 {AUTHOR}",
        "familyName": family,
        "styleName": "Regular",
        "uniqueFontIdentifier": f"{VERSION};{ps_name}",
        "fullName": f"{family} Regular",
        "version": f"Version {VERSION}",
        "psName": ps_name,
        "designer": AUTHOR,
        "licenseDescription": LICENSE,
        "licenseInfoURL": "https://openfontlicense.org",
    }, mac=False)
    fb.setupOS2(sTypoAscender=900, sTypoDescender=-250, sTypoLineGap=0, usWinAscent=900, usWinDescent=250, fsType=0, fsSelection=0x40)
    # Every glyph that a character maps to is 600 units wide; only glyphs that
    # exist in the middle of shaping have zero width.
    fb.setupPost(isFixedPitch=1)
    fb.font["OS/2"].panose.bFamilyType = 2
    fb.font["OS/2"].panose.bProportion = 9
    addOpenTypeFeaturesFromString(fb.font, fea)
    fb.font["OS/2"].recalcUnicodeRanges(fb.font)
    fb.font["OS/2"].recalcCodePageRanges(fb.font)
    # The outlines have no hinting, so ask for smoothing at every size.
    fb.font["gasp"] = gasp = newTable("gasp")
    gasp.version = 1
    gasp.gaspRange = {0xFFFF: 0x000F}
    # Smart dropout control, so thin dots don't vanish when rasterized small.
    fb.font["prep"] = prep = newTable("prep")
    prep.program = ttProgram.Program()
    prep.program.fromAssembly(["PUSHW[]", "511", "SCANCTRL[]", "PUSHB[]", "4", "SCANTYPE[]"])
    fb.font["head"].created = fb.font["head"].modified = BUILT
    fb.font.recalcTimestamp = False
    return fb.font


def build_carry(n: int, m: int, debug: bool) -> tuple[TTFont, str, list[Pass], list[Glyph]]:
    glyphs = inventory(debug)
    glyphs += DecimalMachine(DecimalSpec(n, m), DIGITS, {dig_name(*s): s for s in DIG_STATES}).inventory()
    glyphs += DivisionMachine(DIVISION_SPEC).inventory()
    fea, passes = features(n, m, [g.name for g in glyphs])
    family = "Carry Debug" if debug else "Carry"
    font = assemble(family, glyphs, {g.name: draw(g) for g in glyphs}, fea)
    return font, fea, passes, glyphs


def build_v0() -> TTFont:
    """The baseline: one ligature per single-digit sum, 100 of them."""
    glyphs = inventory(debug=False)[: 1 + len(DIGITS) + len(SYMBOLS)]
    drawings = {g.name: draw(g) for g in glyphs}
    rules = []
    for a in range(10):
        for b in range(10):
            text = f"{a}+{b}={a + b}"
            name = f"sum_{a}_{b}"
            pen = TTGlyphPen(None)
            for i, char in enumerate(text):
                draw(Glyph(name, "text", tuple(BITMAPS[char])), x_offset=i * ADVANCE, pen=pen)
            glyphs.append(Glyph(name, "ligature", width=len(text) * ADVANCE))
            drawings[name] = pen
            rules.append(f"  sub {DIGITS[a]} plus {DIGITS[b]} equal by {name};")
    fea = "languagesystem DFLT dflt;\nlanguagesystem latn dflt;\nfeature liga {\n" + "\n".join(rules) + "\n} liga;\n"
    return assemble("Carry v0", glyphs, drawings, fea)


def stats(path: Path, n: int) -> dict:
    font = TTFont(path)
    gsub = font["GSUB"].table
    calt = next(f for f in gsub.FeatureList.FeatureRecord if f.FeatureTag in ("calt", "liga"))
    rules = 0
    for lookup in gsub.LookupList.Lookup:
        for sub in lookup.SubTable:
            kind = lookup.LookupType
            if kind == 7:
                kind, sub = sub.ExtensionLookupType, sub.ExtSubTable
            if kind == 8 or (kind == 6 and sub.Format == 3):
                rules += 1
            elif kind == 6 and sub.Format == 1:
                rules += sum(len(rs.ChainSubRule) for rs in sub.ChainSubRuleSet if rs)
            elif kind == 6:
                rules += sum(len(cs.ChainSubClassRule) for cs in sub.ChainSubClassSet if cs)
    return {
        "maxDigits": n,
        "glyphs": len(font.getGlyphOrder()),
        "lookups": len(gsub.LookupList.Lookup),
        "passes": len(calt.Feature.LookupListIndex),
        "contextRules": rules,
        "gsubBytes": len(font.getTableData("GSUB")),
        "fileBytes": path.stat().st_size,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--digits", type=int, default=16, help="longest operand for + and -")
    parser.add_argument("--mul-digits", type=int, default=8, help="longest operand for × and *")
    parser.add_argument("--out", type=Path, default=Path("build"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    font, fea, passes, glyphs = build_carry(args.digits, args.mul_digits, debug=False)
    (args.out / "carry.fea").write_text(fea)
    font.save(args.out / "Carry.ttf")
    font.flavor = "woff2"
    font.save(args.out / "Carry.woff2")
    font.flavor = None
    debug_font, *_ = build_carry(args.digits, args.mul_digits, debug=True)
    debug_font.save(args.out / "Carry-Debug.ttf")
    debug_font.flavor = "woff2"
    debug_font.save(args.out / "Carry-Debug.woff2")
    build_v0().save(args.out / "Carry-v0.ttf")

    calt = next(f for f in font["GSUB"].table.FeatureList.FeatureRecord if f.FeatureTag == "calt")
    meta = {
        "stats": {**stats(args.out / "Carry.ttf", args.digits), "maxMulDigits": args.mul_digits, "arithmeticStage": "division", "maxFractionDigits": DecimalSpec(args.digits, args.mul_digits).fraction_digits, "maxDivDigits": DIVISION_SPEC.digits},
        "passes": [
            {"lookup": index, "name": p.name, "title": p.title, "direction": p.direction, "blurb": p.blurb, "distance": p.distance}
            for index, p in zip(calt.Feature.LookupListIndex, passes)
        ],
        "glyphs": [{"name": g.name, "role": g.role, "width": g.width, **g.meta} for g in glyphs],
    }
    (args.out / "carry.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta["stats"]))


if __name__ == "__main__":
    main()
