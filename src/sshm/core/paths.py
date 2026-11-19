"""Filesystem locations and small file helpers.

All paths follow the XDG base-directory spec. Every location can be
redirected with an environment variable, which keeps tests hermetic:

    SSHM_CONFIG_DIR   (default: $XDG_CONFIG_HOME/sshm)
    SSHM_RUNTIME_DIR  (default: $XDG_RUNTIME_DIR/sshm, or /tmp/sshm-$UID)
    SSHM_STATE_DIR    (default: $XDG_STATE_HOME/sshm)
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path


def home() -> Path:
    return Path(os.environ.get("HOME") or Path.home())


def config_dir() -> Path:
    override = os.environ.get("SSHM_CONFIG_DIR")
    if override:
        return Path(override)
    base = os.environ.get("XDG_CONFIG_HOME")
    return (Path(base) if base else home() / ".config") / "sshm"


def state_dir() -> Path:
    """History and event log ($XDG_STATE_HOME/sshm, i.e. ~/.local/state/sshm)."""
    override = os.environ.get("SSHM_STATE_DIR")
    if override:
        return Path(override)
    base = os.environ.get("XDG_STATE_HOME")
    return (Path(base) if base else home() / ".local/state") / "sshm"


def history_file() -> Path:
    return state_dir() / "history.db"


def runtime_dir() -> Path:
    override = os.environ.get("SSHM_RUNTIME_DIR")
    if override:
        path = Path(override)
    else:
        base = os.environ.get("XDG_RUNTIME_DIR")
        path = Path(base) / "sshm" if base and os.path.isdir(base) else Path(f"/tmp/sshm-{os.getuid()}")
    ensure_dir(path)
    return path


def servers_file() -> Path:
    return config_dir() / "servers.json"


def settings_file() -> Path:
    return config_dir() / "settings.json"


def telemetry_cache_file() -> Path:
    return runtime_dir() / "telemetry.json"


def tunnels_file() -> Path:
    return runtime_dir() / "tunnels.json"


def ipc_socket_name() -> str:
    return f"sshm-{os.getuid()}"


# Legacy (v1/v2) locations, read once during migration and never written.
def legacy_servers_file() -> Path:
    return home() / ".ssh_servers"


def legacy_commands_file() -> Path:
    return home() / ".ssh_custom_commands.json"


def legacy_tray_hidden_file() -> Path:
    return home() / ".ssh_tray_hidden.json"


def legacy_theme_file() -> Path:
    return home() / ".ssh_hub_theme"


def legacy_refresh_file() -> Path:
    return home() / ".ssh_hub_refresh"


def ensure_dir(path: Path, mode: int = 0o700) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=mode)
    return path


def atomic_write_text(path: Path, text: str, mode: int = 0o600) -> None:
    """Write *text* to *path* atomically (tmp file + rename) with *mode*."""
    ensure_dir(path.parent)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


@contextlib.contextmanager
def file_lock(path: Path) -> Iterator[None]:
    """Exclusive advisory lock so the GUI, tray and TUI never clobber each other."""
    lock_path = path.with_name(f".{path.name}.lock")
    ensure_dir(lock_path.parent)
    with open(lock_path, "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
