import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.render import label  # noqa: E402


cases = [
    ("one", ("1", "fg")),
    ("pending.one", ("1", "work")),
    ("pending.period", (".", "work")),
    ("tail.hyphen", ("-", "work")),
    ("syntax.plus", ("+", "work")),
    ("boundary.uni00A0", ("␣", "work")),
    ("invalid.space", ("␣", "work")),
    ("answered.equal", ("=", "work")),
    ("neg.five", ("5", "work")),
    ("dec.period", (".", "work")),
    ("divide", ("÷", "fg")),
    ("res.minus", ("-", "accent")),
    ("res.period", (".", "accent")),
    ("d3.c0.p", ("3", "work")),
]
for name, expected in cases:
    assert label(name) == expected, (name, label(name), expected)
print(f"{len(cases)} render labels pass")
