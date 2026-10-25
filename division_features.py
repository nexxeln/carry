"""Bounded decimal long division, scheduled entirely through GSUB."""

from dataclasses import dataclass

from font_model import ADVANCE, Glyph, Pass, cls, sv
from pixels import BITMAPS


@dataclass(frozen=True)
class DivisionSpec:
    digits: int = 4


class DivisionMachine:
    def __init__(self, spec: DivisionSpec):
        self.spec = spec
        self._glyphs = []
        self._classes = []
        self._lookups = []
        self._passes = []
        self._format = []
        self._shared = {}
        self._build()

    def inventory(self) -> list[Glyph]:
        return [
            Glyph("div.ready", "text", tuple(BITMAPS["="]), width=ADVANCE, meta={"text": "="}),
            *self._glyphs,
        ]

    def declarations(self) -> list[str]:
        return self._classes

    def lookups(self) -> list[str]:
        return self._lookups

    def passes(self) -> list[Pass]:
        return self._passes + self._format

    def _glyph(self, suffix: str, text: str | None = None) -> str:
        name = f"div.{suffix}"
        self._glyphs.append(Glyph(
            name,
            "result" if text is not None else "blank",
            tuple(BITMAPS[text]) if text is not None else (),
            width=ADVANCE if text is not None else 0,
            meta={"text": text} if text is not None else {},
        ))
        return name

    def _lookup(self, suffix: str, rules: list[str]) -> str:
        name = f"div.{suffix}"
        self._lookups.append(f"lookup {name} useExtension {{ lookupflag IgnoreLigatures; {' '.join(rules)} }} {name};")
        return name

    def _pass(self, suffix: str, rules: list[str], target: str | None = None, *, formatting: bool = False):
        if target is not None:
            body = " ".join(rules)
            # Each scheduled wrapper is distinct; arithmetic kernels are shared
            # to stay below HarfBuzz's contextual-subtable sanitizer limit.
            if body not in self._shared:
                self._shared[body] = self._lookup(f"shared{len(self._shared)}", rules)
            rules = [f"sub {target}' lookup {self._shared[body]};"]
        destination = self._format if formatting else self._passes
        destination.append(Pass(
            f"div.{suffix}", suffix, "ltr", "bounded integer division",
            ["lookupflag IgnoreLigatures;", *rules],
            use_extension=True,
        ))

    @staticmethod
    def _context(target: int, glyphs: str, lookup: str, conditions: dict[int, str]) -> str:
        cells = {**conditions, target: f"{glyphs}' lookup {lookup}"}
        return "sub " + " ".join(cells.get(i, "@ANY") for i in range(min(cells), max(cells) + 1)) + ";"

    def _build(self):
        n = self.spec.digits
        w = n + 1
        q = tuple(tuple(self._glyph(f"q{j}.{d}") for d in range(10)) for j in range(n))
        r = tuple(tuple(self._glyph(f"r{j}.{d}") for d in range(10)) for j in range(w))
        raw = {(j, v): self._glyph(f"s{j}.raw{sv(v)}") for j in range(w) for v in range(-9, 10)}
        settled = {(j, d, b): self._glyph(f"s{j}.d{d}.b{b}") for j in range(w) for d in range(10) for b in range(2)}
        qsign, qminus = self._glyph("qsign"), self._glyph("qminus", "-")
        rsign, rminus = self._glyph("rsign"), self._glyph("rminus", "-")
        sep, shown_sep = self._glyph("sep"), self._glyph("remainder")
        space, letter_r = self._glyph("outspace", " "), self._glyph("outr", "r")
        qzero, rzero, hidden = self._glyph("qzero"), self._glyph("rzero"), self._glyph("hidden")
        output = tuple(self._glyph(f"out{d}", str(d)) for d in range(10))
        for j in range(w):
            self._classes.append(f"@DIVR{j} = {cls(r[j])};")
            self._classes.append(f"@DIVS{j} = {cls([raw[j, v] for v in range(-9, 10)] + [settled[j, d, b] for d in range(10) for b in range(2)])};")
            for b in range(2):
                self._classes.append(f"@DIVS{j}B{b} = {cls(settled[j, d, b] for d in range(10))};")

        divisor_start = n + 1
        quotient_start = 2 * n + 3
        separator_position = quotient_start + n
        remainder_start = separator_position + 2
        scratch_start = remainder_start + w
        context = self._context
        operand = " ".join(["@PADDED"] * n)
        self._pass("validate", [
            "ignore sub equal' [@PADDED @WORD period comma @OP equal dec.equal answered.equal];",
            f"ignore sub [@DIGIT @WORD @OP equal dec.equal answered.equal period comma invalid.space invalid.uni00A0] {operand} @DIVOP {operand} equal';",
            f"ignore sub {operand} @DIVOP {' '.join(['@VAL0'] * n)} equal';",
            f"sub {operand} @DIVOP {operand} equal' by div.ready;",
        ])
        expansion = ["equal", qsign, *[row[0] for row in q], sep, rsign, *[row[0] for row in r], *[settled[j, 0, 0] for j in range(w)]]
        expand = self._lookup("expand", [f"sub div.ready by {' '.join(expansion)};"])
        self._pass("entry", [f"sub {operand} @DIVOP {operand} div.ready' lookup {expand};"])

        for j in range(w):
            for d in range(10):
                self._lookup(f"putR{j}D{d}", [f"sub @DIVR{j} by {r[j][d]};"])
            for v in range(-9, 10):
                self._lookup(f"putS{j}V{sv(v)}", [f"sub @DIVS{j} by {raw[j, v]};"])
            for b in range(2):
                self._lookup(f"settle{j}B{b}", [f"sub {raw[j, v]} by {settled[j, (v - b) % 10, int(v - b < 0)]};" for v in range(-9, 10)])
        for j in range(n):
            self._lookup(f"incQ{j}", [f"sub {q[j][d]} by {q[j][d + 1]};" for d in range(9)])

        for digit in range(n):
            for j in range(w):
                rules = [context(remainder_start + j, f"@DIVR{j}", f"div.putR{j}D{d}",
                                 {remainder_start + j + 1: r[j + 1][d]} if j < w - 1 else {digit: f"@VAL{d}"}) for d in range(10)]
                self._pass(f"shift{digit}C{j}", rules, f"@DIVR{j}")
            for trial in range(9):
                prefix = f"D{digit}T{trial}"
                for j in range(w):
                    rules = []
                    for a in range(10):
                        for b in ([0] if j == 0 else range(10)):
                            conditions = {remainder_start + j: r[j][a]}
                            if j:
                                conditions[divisor_start + j - 1] = f"@VAL{b}"
                            rules.append(context(scratch_start + j, f"@DIVS{j}", f"div.putS{j}V{sv(a - b)}", conditions))
                    self._pass(prefix + f"SUB{j}", rules, f"@DIVS{j}")
                for j in reversed(range(w)):
                    target = cls(raw[j, v] for v in range(-9, 10))
                    rules = [context(scratch_start + j, target, f"div.settle{j}B{b}",
                                     {} if j == w - 1 else {scratch_start + j + 1: f"@DIVS{j + 1}B{b}"}) for b in ([0] if j == w - 1 else range(2))]
                    self._pass(prefix + f"BORROW{j}", rules, target)
                for j in range(w):
                    rules = []
                    for d in range(10):
                        conditions = {scratch_start: "@DIVS0B0", scratch_start + j: cls(settled[j, d, b] for b in range(2))}
                        if j == 0:
                            conditions[scratch_start] = settled[0, d, 0]
                        rules.append(context(remainder_start + j, f"@DIVR{j}", f"div.putR{j}D{d}", conditions))
                    self._pass(prefix + f"COMMIT{j}", rules, f"@DIVR{j}")
                target = cls(q[digit][:9])
                self._pass(prefix + "QUOTIENT", [context(quotient_start + digit, target, f"div.incQ{digit}", {scratch_start: "@DIVS0B0"})], target)

        negative_q = self._lookup("negativeQ", [f"sub {qsign} by {qminus};"])
        negative_r = self._lookup("negativeR", [f"sub {rsign} by {rminus};"])
        signs = []
        for a, b in [("@NEGDIGIT", "@POSDIGIT"), ("@POSDIGIT", "@NEGDIGIT")]:
            for j, row in enumerate(q):
                signs.append(context(quotient_start - 1, qsign, negative_q, {n - 1: a, 2 * n: b, quotient_start + j: cls(row[1:])}))
        for j, row in enumerate(r):
            signs.append(context(remainder_start - 1, rsign, negative_r, {n - 1: "@NEGDIGIT", remainder_start + j: cls(row[1:])}))
        self._pass("signs", signs)

        show_remainder = self._lookup("showRemainder", [f"sub {sep} by {shown_sep};"])
        self._pass("remainder", [context(separator_position, sep, show_remainder, {remainder_start + j: cls(r[j][1:])}) for j in range(w)], formatting=True)
        for rows, blank, label in [(q, qzero, "Q"), (r, rzero, "R")]:
            for j in range(len(rows) - 1):
                rules = [f"sub {rows[j][0]} by {blank};"] if j == 0 else [f"sub {blank} {rows[j][0]}' by {blank};"]
                self._pass(f"strip{label}{j}", rules, formatting=True)
        hide_zero = self._lookup("hideZeroRemainder", [f"sub {r[-1][0]} by {rzero};"])
        self._pass("hideZero", [context(remainder_start + w - 1, r[-1][0], hide_zero, {separator_position: sep})], formatting=True)
        self._pass("display", [f"sub {row[d]} by {output[d]};" for row in (*q, *r) for d in range(10)]
                   + [f"sub @DIVS{j} by {hidden};" for j in range(w)], formatting=True)
        # A wide translated 'r' is not pixel-identical to three normal glyphs.
        self._pass("separator", [f"sub {shown_sep} by {space} {letter_r} {space};"], formatting=True)
