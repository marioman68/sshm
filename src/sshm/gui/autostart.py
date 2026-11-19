"""XDG autostart entry for the tray monitor."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from sshm.core import paths


def entry_path() -> Path:
    return paths.home() / ".config/autostart/sshm-tray.desktop"


def is_enabled() -> bool:
    return entry_path().exists()


def set_enabled(enabled: bool) -> None:
    path = entry_path()
    if not enabled:
        path.unlink(missing_ok=True)
        return
    exe = shutil.which("sshm-tray")
    cmd = exe if exe else f"{sys.executable} -m sshm gui --tray"
    paths.atomic_write_text(path, (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=sshm tray monitor\n"
        "Comment=Watch your SSH servers from the system tray\n"
        f"Exec={cmd}\n"
        "Icon=sshm\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
        "X-GNOME-Autostart-Delay=5\n"
        "X-KDE-autostart-after=panel\n"
    ), mode=0o644)
