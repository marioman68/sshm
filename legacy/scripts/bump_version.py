#!/usr/bin/env python3
"""Bump the sshm version everywhere it appears.

    scripts/bump_version.py patch "Fix tray icon on GNOME"     # 3.1.0 -> 3.1.1
    scripts/bump_version.py minor "Add Proxmox support"        # 3.1.1 -> 3.2.0
    scripts/bump_version.py 4.0.0 "Breaking config change"

The single source of truth is ``src/sshm/__init__.py``; pyproject.toml reads it
dynamically. This script also updates the RPM spec (Version + %changelog) and
adds a section to CHANGELOG.md, then prints the new version.
"""

from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INIT = ROOT / "src/sshm/__init__.py"
SPEC = ROOT / "packaging/sshm.spec"
CHANGELOG = ROOT / "CHANGELOG.md"
AUTHOR = "Lucas Dunham"


def current() -> str:
    m = re.search(r'^__version__ = "(\d+)\.(\d+)\.(\d+)"', INIT.read_text(), re.M)
    if not m:
        raise SystemExit("could not find __version__ in src/sshm/__init__.py")
    return ".".join(m.groups())


def bumped(version: str, part: str) -> str:
    if re.fullmatch(r"\d+\.\d+\.\d+", part):
        return part
    major, minor, patch = map(int, version.split("."))
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise SystemExit(f"unknown bump '{part}' (use major, minor, patch or X.Y.Z)")


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    old = current()
    new = bumped(old, argv[0])
    notes = argv[1:] or ["Maintenance release"]
    today = dt.date.today()

    INIT.write_text(re.sub(r'^__version__ = ".*"', f'__version__ = "{new}"', INIT.read_text(), count=1, flags=re.M))

    spec = SPEC.read_text()
    spec = re.sub(r"^Version:(\s+).*$", rf"Version:\g<1>{new}", spec, count=1, flags=re.M)
    entry = f"* {today:%a %b %d %Y} {AUTHOR} - {new}-1\n" + "".join(f"- {n}\n" for n in notes) + "\n"
    spec = spec.replace("%changelog\n", "%changelog\n" + entry, 1)
    SPEC.write_text(spec)

    log = CHANGELOG.read_text()
    if f"## {new} " not in log:
        section = f"## {new} — {today.isoformat()}\n\n" + "".join(f"- {n}\n" for n in notes) + "\n"
        log = log.replace("# Changelog\n\n", "# Changelog\n\n" + section, 1)
        CHANGELOG.write_text(log)

    print(f"{old} -> {new}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
