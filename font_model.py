from dataclasses import dataclass, field

ADVANCE = 600
DOT = 86


@dataclass(frozen=True)
class Glyph:
    name: str
    role: str
    bitmap: tuple[str, ...] = ()
    dot: int = DOT
    width: int = 0
    char: str | None = None
    meta: dict = field(default_factory=dict, hash=False)


@dataclass(frozen=True)
class Pass:
    name: str
    title: str
    direction: str
    blurb: str
    body: list[str]
    distance: int | None = None
    use_extension: bool = False


def cls(names) -> str:
    return "[" + " ".join(names) + "]"


def sv(value: int) -> str:
    return f"m{-value}" if value < 0 else str(value)
