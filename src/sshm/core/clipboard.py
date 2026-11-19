"""Copy text to the clipboard: Wayland, X11, then the OSC 52 terminal escape."""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys


def copy(text: str, allow_osc52: bool = True) -> str:
    """Returns the mechanism used, or ``""`` if nothing worked."""
    tools = []
    if os.environ.get("WAYLAND_DISPLAY"):
        tools.append(["wl-copy"])
    if os.environ.get("DISPLAY"):
        tools += [["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]
    for tool in tools:
        if shutil.which(tool[0]):
            try:
                subprocess.run(tool, input=text.encode(), timeout=2, check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return tool[0]
            except (OSError, subprocess.SubprocessError):
                continue
    if allow_osc52 and sys.stdout.isatty():
        payload = base64.b64encode(text.encode()).decode()
        sys.stdout.write(f"\033]52;c;{payload}\a")
        sys.stdout.flush()
        return "terminal (OSC 52)"
    return ""
