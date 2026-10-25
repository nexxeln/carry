"""Build the release files, and refuse to write them unless every check passes.

    uv run scripts/release.py

Runs on macOS with HarfBuzz (`hb-shape`), Xcode's `swiftc`, Node, and
Playwright's Chromium, Firefox, and WebKit installed. Writes dist/Carry.ttf,
dist/Carry.woff2, dist/Carry-Debug.woff2, and dist/SHA256SUMS.
"""

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DIST = ROOT / "dist"
CHECKS = [
    ["uv", "run", "generate.py"],
    ["uv", "run", "tests/test_shape.py", "--ops", "+-*×", "--cases", "20000", "--engines", "harfbuzz,coretext,textkit"],
    ["uv", "run", "tests/test_extended.py"],
    ["uv", "run", "tests/check_install.py"],
    ["node", "tests/browser_test.mjs"],
    ["node", "tests/typing_test.mjs"],
    ["node", "tests/hero_test.mjs"],
    ["env", "CARRY_PLAYGROUND_BUILD_FONTS=1", "node", "tests/playground_test.mjs"],
    ["uvx", "--quiet", "--from", "fontbakery", "fontbakery", "check-universal", "--loglevel", "FAIL", "build/Carry.ttf"],
]


def main() -> int:
    for tool in ("ctshape", "tkshape", "byname"):
        if not (ROOT / "tools" / tool).exists():
            subprocess.run(["swiftc", "-O", f"tools/{tool}.swift", "-o", f"tools/{tool}"], cwd=ROOT, check=True)

    for command in CHECKS:
        print(f"$ {' '.join(command)}", flush=True)
        if subprocess.run(command, cwd=ROOT).returncode != 0:
            print("release stopped: the check above failed, dist/ is unchanged")
            return 1

    DIST.mkdir(exist_ok=True)
    sums = []
    for name in ("Carry.ttf", "Carry.woff2", "Carry-Debug.woff2"):
        shutil.copy(ROOT / "build" / name, DIST / name)
        sums.append(f"{hashlib.sha256((DIST / name).read_bytes()).hexdigest()}  {name}")
    (DIST / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    print("\n".join(sums))
    return 0


if __name__ == "__main__":
    sys.exit(main())
