"""Find the user's preferred terminal emulator and launch commands in it."""

from __future__ import annotations

import configparser
import os
import shlex
import shutil
import subprocess
from pathlib import Path

from sshm.core import paths

# How each known emulator expects "run this argv": the prefix goes before argv.
_PREFIX = {
    "xdg-terminal-exec": [],
    "konsole": ["-e"],
    "yakuake": None,  # cannot run commands
    "ghostty": ["-e"],
    "alacritty": ["-e"],
    "foot": [],
    "footclient": [],
    "kitty": [],
    "wezterm": ["start", "--"],
    "ptyxis": ["--"],
    "gnome-terminal": ["--"],
    "kgx": ["--"],
    "gnome-console": ["--"],
    "tilix": ["-e"],
    "terminator": ["-x"],
    "xfce4-terminal": ["-x"],
    "mate-terminal": ["-x"],
    "lxterminal": ["-e"],
    "qterminal": ["-e"],
    "cosmic-term": ["-e"],
    "contour": [],
    "rio": ["-e"],
    "st": ["-e"],
    "urxvt": ["-e"],
    "xterm": ["-e"],
    "x-terminal-emulator": ["-e"],
}

_FALLBACK_ORDER = [
    "xdg-terminal-exec", "konsole", "ptyxis", "kgx", "gnome-terminal", "ghostty", "kitty",
    "wezterm", "alacritty", "foot", "cosmic-term", "xfce4-terminal", "tilix", "terminator",
    "mate-terminal", "lxterminal", "qterminal", "x-terminal-emulator", "xterm",
]


class TerminalNotFound(RuntimeError):
    pass


def _normalize(parts: list[str]) -> list[str] | None:
    if not parts or not shutil.which(parts[0]):
        return None
    name = Path(parts[0]).name
    if len(parts) > 1:  # user supplied explicit flags, trust them
        return parts
    prefix = _PREFIX.get(name, ["-e"])
    return None if prefix is None else [parts[0], *prefix]


def _kde_terminal() -> list[str] | None:
    cfg_path = paths.home() / ".config/kdeglobals"
    if not cfg_path.exists():
        return None
    cfg = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        cfg.read(cfg_path)
        value = cfg.get("General", "TerminalApplication", fallback="").strip()
    except configparser.Error:
        return None
    return _normalize(shlex.split(value)[:1]) if value else None


def _gsettings_terminal() -> list[str] | None:
    if not shutil.which("gsettings"):
        return None
    for schema in (
        "org.gnome.desktop.default-applications.terminal",
        "org.cinnamon.desktop.default-applications.terminal",
        "org.mate.applications-terminal",
    ):
        try:
            res = subprocess.run(["gsettings", "get", schema, "exec"], capture_output=True, text=True, timeout=1)
        except (OSError, subprocess.TimeoutExpired):
            continue
        value = res.stdout.strip().strip("'")
        if res.returncode == 0 and value:
            found = _normalize(shlex.split(value)[:1])
            if found:
                return found
    return None


def resolve(override: str = "") -> list[str]:
    """Return the argv prefix used to run a command in a new terminal window."""
    if override.strip():
        found = _normalize(shlex.split(override))
        if found:
            return found
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
    env_term = os.environ.get("TERMINAL", "").strip()
    candidates = []
    if env_term:
        candidates.append(lambda: _normalize(shlex.split(env_term)))
    if "KDE" in desktop:
        candidates.append(_kde_terminal)
    if any(d in desktop for d in ("GNOME", "CINNAMON", "MATE", "BUDGIE", "UNITY", "PANTHEON")):
        candidates.append(_gsettings_terminal)
    candidates.append(_kde_terminal)
    for get in candidates:
        found = get()
        if found:
            return found
    for name in _FALLBACK_ORDER:
        found = _normalize([name])
        if found:
            return found
    raise TerminalNotFound("No terminal emulator found. Set one in Settings → Terminal.")


def launch(argv: list[str], override: str = "") -> None:
    prefix = resolve(override)
    env = dict(os.environ)
    env.pop("SSHM_TUI", None)
    subprocess.Popen(
        [*prefix, *argv],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env=env,
    )
