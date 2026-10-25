"""Fixed-radix layouts layered over the font's signed integer columns.

Each decimal operand stays in the source run: its digits retain their outlines,
its point becomes a skippable ligature, and hidden zeros align it to scale two.
Addition uses n+2 coefficient columns; multiplication uses m+2 coefficient
digits, padded to twice that width. A result end marker fixes the output radix
without depending on which leading or trailing zeros will eventually disappear.
Expressions without a point continue through the original integer layout.
"""

from dataclasses import dataclass

from font_model import ADVANCE, Glyph, Pass, cls, sv
from pixels import BITMAPS


@dataclass(frozen=True)
class DecimalSpec:
    integer_digits: int
    mul_integer_digits: int
    fraction_digits: int = 2

    @property
    def add_width(self) -> int:
        return self.integer_digits + self.fraction_digits

    @property
    def mul_digits(self) -> int:
        return self.mul_integer_digits + self.fraction_digits

    @property
    def mul_width(self) -> int:
        return 2 * self.mul_digits

    @property
    def layouts(self):
        return (
            ("add", self.integer_digits, self.add_width, "@DECADDOP"),
            ("mul", self.mul_integer_digits, self.mul_width, "@DECMULOP"),
        )


class DecimalMachine:
    def __init__(
        self,
        spec: DecimalSpec,
        digits: list[str],
        digit_states: dict[str, tuple[int, int, str]],
        pads_per_pass: int = 63,
    ):
        self.spec = spec
        self.digits = digits
        self.digit_states = digit_states
        self.pads_per_pass = pads_per_pass

    def mc(self, d, c):
        return f"dec.mc{d}.c{c}"

    def acc(self, r, b):
        return f"dec.acc{r}.b{b}"

    def value(self, v):
        return f"dec.val{v}"

    def inventory(self) -> list[Glyph]:
        out = []
        for name, char in (
            ("period", "."),
            ("plus", "+"),
            ("hyphen", "-"),
            ("minus", "−"),
            ("asterisk", "*"),
            ("multiply", "×"),
            ("equal", "="),
        ):
            out.append(
                Glyph(
                    f"dec.{name}",
                    "text",
                    tuple(BITMAPS["-" if char == "−" else char]),
                    width=ADVANCE,
                    meta={"text": char},
                )
            )
        for name in ("dec.slot.add", "dec.slot.sub", "dec.radix", "dec.mul.negative"):
            out.append(Glyph(name, "slot"))
        for name in ("dec.end.add", "dec.end.mul", "dec.fracblank"):
            out.append(Glyph(name, "blank"))
        out += [
            Glyph(f"dec.b{sv(v)}", "colb", meta={"value": v}) for v in range(-9, 10)
        ]
        out += [
            Glyph(self.mc(d, c), "carry", meta={"value": d, "carry": c})
            for c in range(10)
            for d in range(10)
        ]
        out += [
            Glyph(self.acc(r, b), "accb", meta={"value": r, "b": b})
            for b in range(10)
            for r in range(10)
        ]
        out += [Glyph(self.value(v), "val", meta={"value": v}) for v in range(91)]
        out += [
            Glyph(f"dec.out.{kind}{d}", "slot", meta={"value": d})
            for kind in ("i", "u", "f")
            for d in range(10)
        ]
        out.append(
            Glyph(
                "res.period",
                "result",
                tuple(BITMAPS["."]),
                width=ADVANCE,
                meta={"text": "."},
            )
        )
        return out

    def declarations(self) -> list[str]:
        return [
            "@DECADDOP = [dec.plus dec.hyphen dec.minus];",
            "@DECMULOP = [dec.asterisk dec.multiply];",
            "@DECOP = [@DECADDOP @DECMULOP];",
            "@DECCOLB = " + cls(f"dec.b{sv(v)}" for v in range(-9, 10)) + ";",
            "@DECMC = "
            + cls(self.mc(d, c) for c in range(10) for d in range(10))
            + ";",
            "@DECACC = "
            + cls(self.acc(r, b) for b in range(10) for r in range(10))
            + ";",
            "@DECVAL = " + cls(self.value(v) for v in range(91)) + ";",
            "@DECOUT = "
            + cls(f"dec.out.{kind}{d}" for kind in ("i", "u", "f") for d in range(10))
            + ";",
            "@DECRESULT = [@DIG @DECMC @DECOUT];",
        ]

    def lookups(self) -> list[str]:
        out = []

        def lookup(name, rules):
            out.append(f"lookup {name} {{ {' '.join(rules)} }} {name};")

        def single(name, pairs):
            lookup(name, [f"sub {a} by {b};" for a, b in pairs])

        single(
            "dec_operator",
            [
                (name, "dec." + name)
                for name in ("plus", "hyphen", "minus", "asterisk", "multiply")
            ],
        )
        single("dec_equal", [("equal", "dec.equal")])
        single("dec_period", [("period", "dec.period")])
        single("dec_mul_minus", [("dec.mul.negative", "res.minus")])
        single("dec_mul_blank", [("dec.mul.negative", "blank")])
        for count in range(self.spec.fraction_digits + 1):
            lookup(
                f"dec_tail{count}",
                [
                    f"sub {d} by {' '.join([d] + ['pad'] * count)};"
                    for d in self.digits + ["neg." + d for d in self.digits]
                ],
            )
        for count in range(
            min(max(self.spec.add_width, self.spec.mul_width), self.pads_per_pass + 1)
        ):
            lookup(
                f"dec_pad{count}",
                [
                    f"sub {d} by {' '.join(['pad'] * count + [d])};"
                    for d in self.digits + ["neg." + d for d in self.digits]
                ],
            )
        for op in ("add", "sub"):
            lookup(
                f"dec_expand_{op}",
                [
                    f"sub dec.equal by dec.equal col.0 {' '.join([f'dec.slot.{op}'] * self.spec.add_width)} dec.end.add;"
                ],
            )
        for polarity in ("positive", "negative"):
            sign = "dec.mul.negative " if polarity == "negative" else ""
            lookup(
                f"dec_expand_mul_{polarity}",
                [
                    f"sub dec.equal by dec.equal {sign}{' '.join([self.mc(0, 0)] * self.spec.mul_width)} dec.end.mul;"
                ],
            )
        for d in range(10):
            for polarity, value in (("p", d), ("n", -d)):
                single(
                    f"dec_take_{polarity}{d}",
                    [
                        ("dec.slot.add", f"dec.b{sv(value)}"),
                        ("dec.slot.sub", f"dec.b{sv(-value)}"),
                    ],
                )
        for a in range(-9, 10):
            single(
                f"dec_add_{sv(a)}",
                [(f"dec.b{sv(b)}", f"col.{sv(a + b)}") for b in range(-9, 10)],
            )
        for b in range(10):
            single(
                f"dec_with_b{b}",
                [(self.mc(d, c), self.acc(d, b)) for c in range(10) for d in range(10)],
            )
        for a in range(10):
            single(
                f"dec_times_a{a}",
                [
                    (self.acc(r, b), self.value(r + a * b))
                    for b in range(10)
                    for r in range(10)
                ],
            )
        states = [(name, state[0]) for name, state in self.digit_states.items()] + [
            (self.mc(d, c), d) for c in range(10) for d in range(10)
        ]
        for kind in ("i", "u", "f"):
            single(
                f"dec_as_{kind}", [(name, f"dec.out.{kind}{d}") for name, d in states]
            )
        lookup(
            "dec_insert_minus",
            [
                f"sub {name} by res.minus {name};"
                for name, state in self.digit_states.items()
                if state[2] == "n"
            ],
        )
        single("dec_blank_integer", [("dec.out.i0", "blank")])
        return out

    def normalization_passes(self) -> list[Pass]:
        digits = lambda k: " ".join(["@DIGIT"] * k)
        pads = lambda k: " ".join(["pad"] * k)
        identify = []
        for frac in range(1, self.spec.fraction_digits + 1):
            identify.append(
                f"sub @DIGIT period {digits(frac)} @OP' lookup dec_operator;"
            )
            for whole in range(
                1, max(self.spec.integer_digits, self.spec.mul_integer_digits) + 1
            ):
                identify.append(
                    f"sub @OP' lookup dec_operator {digits(whole)} period {digits(frac)} equal;"
                )
        equal = []
        for length in range(
            1, max(self.spec.integer_digits, self.spec.mul_integer_digits) + 1
        ):
            equal.append(f"sub @DECOP {digits(length)} equal' lookup dec_equal;")
            for frac in range(1, self.spec.fraction_digits + 1):
                equal.append(
                    f"sub @DECOP {digits(length)} period {digits(frac)} equal' lookup dec_equal;"
                )
        tails = []
        for frac in range(self.spec.fraction_digits, 0, -1):
            tails.append(
                f"sub period {digits(frac - 1)} @DIGIT' lookup dec_tail{self.spec.fraction_digits - frac} [@DECOP dec.equal];"
            )
        tails.append(
            f"sub @DIGIT' lookup dec_tail{self.spec.fraction_digits} [@DECOP dec.equal];"
        )
        padding_passes = []
        longest = max(self.spec.add_width, self.spec.mul_width) - 1
        for chunk in range(max(1, -(-longest // self.pads_per_pass))):
            already = chunk * self.pads_per_pass
            normalization = (
                ["ignore sub [@DIGIT @WORD period comma] @DIGIT';"]
                if chunk == 0
                else []
            )
            for _, limit, width, ops in self.spec.layouts:
                for whole in range(1, limit + 1):
                    remaining = width - whole - self.spec.fraction_digits - already
                    if remaining < 0 or (chunk and remaining == 0):
                        continue
                    count = min(remaining, self.pads_per_pass)
                    for frac in range(self.spec.fraction_digits, -1, -1):
                        extra = self.spec.fraction_digits - frac
                        rest = (
                            f"{digits(whole - 1)} period {digits(frac)}"
                            if frac
                            else digits(whole - 1)
                        )
                        for left, right in (("", ops), (ops, "dec.equal")):
                            normalization.append(
                                f"sub {left} {pads(already)} @DIGIT' lookup dec_pad{count} {rest} {pads(extra)} {right};"
                            )
            if normalization:
                padding_passes.append(
                    Pass(
                        "dec_normalize" if chunk == 0 else f"dec_normalize{chunk + 1}",
                        "pad decimal operands",
                        "ltr",
                        "validate each operand format independently and prepend at most 63 hidden zeros",
                        normalization,
                    )
                )
        slotrules = [
            "ignore sub dec.equal' [@PADDED @WORD period comma @OP @DECOP equal dec.equal answered.equal];",
        ]
        for _, _, width, ops in self.spec.layouts:
            operand = " ".join(["@PADDED"] * width)
            slotrules.append(
                f"ignore sub [@DIGIT @WORD @OP @DECOP equal dec.equal period comma invalid.space invalid.uni00A0] {operand} {ops} {operand} dec.equal';"
            )
        add_operand = " ".join(["@PADDED"] * self.spec.add_width)
        slotrules += [
            f"sub {add_operand} dec.plus {add_operand} dec.equal' lookup dec_expand_add;",
            f"sub {add_operand} [dec.hyphen dec.minus] {add_operand} dec.equal' lookup dec_expand_sub;",
        ]
        m = self.spec.mul_digits
        def signed_operand(negative, trailing_zeros):
            signed_padding = "@NEGPAD" if negative else "@POSPAD"
            last_source_digit = "@NEGDIGIT" if negative else "@POSDIGIT"
            return " ".join(
                ["pad"] * m
                + [signed_padding] * (m - trailing_zeros - 1)
                + [last_source_digit]
                + ["pad"] * trailing_zeros
            )

        mulslots = []
        for az in range(self.spec.fraction_digits + 1):
            for bz in range(self.spec.fraction_digits + 1):
                for an, bn in (
                    (False, False),
                    (True, True),
                    (False, True),
                    (True, False),
                ):

                    mulslots.append(
                        f"sub {signed_operand(an, az)} @DECMULOP {signed_operand(bn, bz)} dec.equal' lookup dec_expand_mul_{'negative' if an != bn else 'positive'};"
                    )
        slotrules += mulslots
        return [
            Pass(
                "dec_identify",
                "recognize decimal operators",
                "ltr",
                "either operand selects the decimal layout",
                identify,
            ),
            Pass(
                "dec_equal",
                "recognize decimal expressions",
                "ltr",
                "carry the decimal layout to the equals sign",
                equal,
            ),
            Pass(
                "dec_tails",
                "align decimal coefficients",
                "ltr",
                "append hidden zeros to give each operand two fractional columns",
                tails,
            ),
            *padding_passes,
            Pass(
                "dec_points",
                "retain decimal points",
                "ltr",
                "skip the visible radix only after operand padding",
                [
                    f"sub @DIGIT period' lookup dec_period {digits(frac)} {pads(self.spec.fraction_digits - frac)} [@DECOP dec.equal];"
                    for frac in range(1, self.spec.fraction_digits + 1)
                ],
            ),
            Pass(
                "dec_slots",
                "allocate decimal results",
                "ltr",
                "only two complete bounded operands allocate an answer",
                slotrules,
            ),
        ]

    def addition_passes(self) -> list[Pass]:
        n = self.spec.add_width
        wild = lambda k: " ".join(["@ANY"] * k)
        b = []
        a = []
        for d in range(1, 10):
            b += [
                f"sub neg.{self.digits[d]} {wild(n + 1)} [dec.slot.add dec.slot.sub]' lookup dec_take_n{d};",
                f"sub @VAL{d} {wild(n + 1)} [dec.slot.add dec.slot.sub]' lookup dec_take_p{d};",
            ]
            a += [
                f"sub neg.{self.digits[d]} {wild(2 * n + 2)} @DECCOLB' lookup dec_add_{sv(-d)};",
                f"sub @VAL{d} {wild(2 * n + 2)} @DECCOLB' lookup dec_add_{d};",
            ]
        b.append("sub [dec.slot.add dec.slot.sub]' lookup dec_take_p0;")
        a.append("sub @DECCOLB' lookup dec_add_0;")
        return [
            Pass(
                "dec_read_b",
                "read decimal B",
                "ltr",
                "read aligned signed B columns",
                b,
                n + 2,
            ),
            Pass(
                "dec_read_a",
                "add decimal A",
                "ltr",
                "produce the shared signed column states",
                a,
                2 * n + 3,
            ),
        ]

    def multiplication_passes(self) -> list[Pass]:
        out = []
        m = self.spec.mul_digits
        wild = lambda k: " ".join(["@ANY"] * k)
        for j in range(m):
            broadcast = [
                f"sub @VAL{b} {wild(j)} dec.equal @DECMC' lookup dec_with_b{b};"
                for b in range(10)
            ]
            broadcast += [
                f"sub {cls(self.acc(r, b) for r in range(10))} @DECMC' lookup dec_with_b{b};"
                for b in range(10)
            ]
            multiply = [
                f"sub @VAL{a} {wild(4 * m + 1 - j)} @DECACC' lookup dec_times_a{a};"
                for a in range(1, 10)
            ]
            multiply.append("sub @DECACC' lookup dec_times_a0;")
            normalize = [
                f"rsub @DECVAL' {cls(self.mc(d, c) for d in range(10))} by {cls(self.mc((v + c) % 10, (v + c) // 10) for v in range(91))};"
                for c in range(1, 10)
            ]
            normalize.append(
                f"rsub @DECVAL' by {cls(self.mc(v % 10, v // 10) for v in range(91))};"
            )
            out += [
                Pass(
                    f"dec_row{j}_b",
                    "spread decimal B",
                    "ltr",
                    "broadcast one coefficient digit",
                    broadcast,
                ),
                Pass(
                    f"dec_row{j}_mul",
                    "multiply decimal row",
                    "ltr",
                    "accumulate exact coefficient products",
                    multiply,
                ),
                Pass(
                    f"dec_row{j}_carry",
                    "carry decimal row",
                    "rtl",
                    "settle coefficient digits",
                    normalize,
                ),
            ]
        return out

    def presentation_passes(self) -> list[Pass]:
        negatives = cls(
            name for name, state in self.digit_states.items() if state[2] == "n"
        )
        tagging = []
        for op, width, scale in (
            ("add", self.spec.add_width + 1, self.spec.fraction_digits),
            ("mul", self.spec.mul_width, 2 * self.spec.fraction_digits),
        ):
            for pos in range(width - 1, -1, -1):
                kind = "f" if pos < scale else "u" if pos == scale else "i"
                tagging.append(
                    f"sub [@DIG @DECMC]' lookup dec_as_{kind} {' '.join(['@DECRESULT'] * pos)} dec.end.{op};"
                )
        product_sign = [
            f"sub dec.mul.negative' lookup dec_mul_minus {' '.join([self.mc(0, 0)] * k)} {cls(self.mc(d, c) for c in range(10) for d in range(1, 10))};"
            for k in range(self.spec.mul_width)
        ]
        product_sign.append("sub dec.mul.negative' lookup dec_mul_blank;")
        return [
            Pass(
                "dec_product_sign",
                "sign decimal products",
                "ltr",
                "zero products never get a minus",
                product_sign,
            ),
            Pass(
                "dec_result_sign",
                "sign decimal sums",
                "ltr",
                "preserve the full magnitude after its sign",
                [f"sub dec.equal {negatives}' lookup dec_insert_minus;"],
            ),
            Pass(
                "dec_tag_output",
                "locate the radix",
                "ltr",
                "tag digits by their distance from the fixed end marker",
                tagging,
            ),
            Pass(
                "dec_leading_zero",
                "trim integer zeros",
                "ltr",
                "retain the units digit even for fractions",
                [
                    "sub [dec.equal res.minus blank] dec.out.i0' lookup dec_blank_integer;"
                ],
            ),
            Pass(
                "dec_trailing_zero",
                "trim fractional zeros",
                "rtl",
                "drop only the zero suffix of the fractional part",
                [
                    "rsub dec.out.f0' [dec.end.add dec.end.mul dec.fracblank] by dec.fracblank;"
                ],
            ),
            Pass(
                "dec_insert_radix",
                "insert the decimal point",
                "ltr",
                "the units column owns the radix",
                [f"sub dec.out.u{d} by dec.out.u{d} dec.radix;" for d in range(10)],
            ),
            Pass(
                "dec_hide_radix",
                "hide an empty fractional part",
                "ltr",
                "integers have no decimal point",
                ["sub dec.radix' dec.fracblank by blank;"],
            ),
            Pass(
                "dec_draw",
                "draw decimal results",
                "ltr",
                "show only significant exact digits",
                [
                    f"sub dec.out.{kind}{d} by res.{d};"
                    for kind in ("i", "u", "f")
                    for d in range(10)
                ]
                + ["sub dec.radix by res.period;"],
            ),
        ]
