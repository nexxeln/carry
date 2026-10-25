"""Check that each built font would install and be usable on macOS.

    uv run tests/check_install.py

Runs Apple's FontValidator (the check Font Book runs on install), then
registers each font for this process only and looks it up by PostScript name,
which is how apps find an installed font. Build tools/byname first:
swiftc -O tools/byname.swift -o tools/byname
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
VALIDATOR = "/System/Library/Frameworks/ApplicationServices.framework/Frameworks/ATS.framework/Support/FontValidator"
FONTS = {"Carry.ttf": "Carry-Regular", "Carry-Debug.ttf": "CarryDebug-Regular", "Carry-v0.ttf": "Carryv0-Regular"}

failed = False
for file, ps_name in FONTS.items():
    path = ROOT / "build" / file
    report = json.loads(subprocess.run([VALIDATOR, "-local", "-quiet", "-showWarnings", "-report", str(path)], capture_output=True, text=True).stdout)
    font = report["Details"][0]["validation"]["fonts"][0]
    lookup = subprocess.run([str(ROOT / "tools/byname"), str(path), ps_name], capture_output=True, text=True).stdout
    resolved = next((l.split(": ", 1)[1] for l in lookup.splitlines() if l.startswith("resolved:")), "")
    ok = not font["failures"] and not font["warnings"] and resolved.startswith(ps_name)
    failed |= not ok
    print(f"{file:16} validator failures={font['failures'] or 'none'} warnings={font['warnings'] or 'none'}; {ps_name} resolves to {resolved}")
sys.exit(1 if failed else 0)
