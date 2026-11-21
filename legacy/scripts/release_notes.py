#!/usr/bin/env python3
"""Print the CHANGELOG.md section for a version (used for GitHub release notes).

    scripts/release_notes.py 3.2.0
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parents[1] / "CHANGELOG.md"


def section(version: str, text: str) -> str:
    m = re.search(rf"^## {re.escape(version)}\b.*?$(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not m:
        raise SystemExit(f"no CHANGELOG section for {version}")
    return m.group(1).strip() + "\n"


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    sys.stdout.write(section(sys.argv[1], CHANGELOG.read_text()))
