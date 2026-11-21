"""User preferences shared by every front-end (``~/.config/sshm/settings.json``)."""

from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from sshm.core import paths
from sshm.core.themes import DEFAULT_THEME, THEMES, get_theme

REFRESH_CHOICES = (5, 10, 30, 60, 0)


@dataclass
class Settings:
    theme: str = DEFAULT_THEME
    refresh_interval: int = 10          # seconds, 0 = manual only
    probe_timeout: float = 1.5          # seconds per TCP probe
    telemetry_port: int = 55889
    telemetry_secret: str = ""          # generated on first run
    accept_legacy_agents: bool = True   # unsigned packets from sshm 2.x agents
    notifications: bool = True          # tray: notify on online/offline changes
    terminal: str = ""                  # override, e.g. "kitty" or "konsole -e"
    mount_dir: str = "~/Network_Servers"
    close_to_tray: bool = True
    tmux_session: str = "sshm"
    # alerts (evaluated by the process that owns telemetry, usually the tray)
    alerts_enabled: bool = True
    alert_cpu: int = 90                 # % sustained for alert_sustain_minutes
    alert_mem: int = 90                 # % sustained
    alert_disk: int = 90                # % of / used
    alert_sustain_minutes: int = 5
    alert_offline_grace: int = 60       # seconds a server must be down before alerting

    _path: Path | None = None  # not serialised

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        path = path or paths.settings_file()
        data: dict = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8") or "{}")
            except (OSError, json.JSONDecodeError):
                data = {}
        known = {f.name for f in fields(cls)} - {"_path"}
        obj = cls(**{k: v for k, v in data.items() if k in known})
        obj._path = path
        dirty = not path.exists()
        if not path.exists():
            obj._import_legacy()
        if not obj.telemetry_secret:
            obj.telemetry_secret = secrets.token_hex(24)
            dirty = True
        obj.theme = get_theme(obj.theme).name
        if dirty:
            obj.save()
        return obj

    def save(self) -> None:
        path = self._path or paths.settings_file()
        data = {k: v for k, v in asdict(self).items() if k != "_path"}
        paths.atomic_write_text(path, json.dumps(data, indent=2) + "\n")

    @property
    def mount_path(self) -> Path:
        return Path(self.mount_dir).expanduser()

    def _import_legacy(self) -> None:
        try:
            idx = int(paths.legacy_theme_file().read_text().strip())
            if 0 <= idx < 8:
                self.theme = THEMES[idx].name
        except (OSError, ValueError):
            pass
        try:
            self.refresh_interval = max(0, int(paths.legacy_refresh_file().read_text().strip()))
        except (OSError, ValueError):
            pass
