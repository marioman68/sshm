"""Persistent server store with transparent migration from the v1/v2 formats.

The store lives at ``~/.config/sshm/servers.json``. All front-ends share it;
writers hold an advisory lock and replace the file atomically, readers call
:meth:`ServerStore.reload_if_changed` to pick up edits from other processes.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from sshm.core import paths
from sshm.core.models import CustomCommand, Server, fuzzy_score

log = logging.getLogger(__name__)
FORMAT_VERSION = 1


class StoreError(Exception):
    pass


class ServerStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or paths.servers_file()
        self._servers: list[Server] = []
        self._mtime: float | None = None
        self.migrated_from_legacy = False
        self.load()

    # ------------------------------------------------------------------ io
    def load(self) -> None:
        if not self.path.exists():
            legacy = migrate_legacy()
            if legacy:
                self._servers = legacy
                self.migrated_from_legacy = True
                self.save()
                log.info("Migrated %d server(s) from legacy ~/.ssh_servers", len(legacy))
            else:
                self._servers = []
                self._mtime = None
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8") or "{}")
        except (OSError, json.JSONDecodeError) as exc:
            raise StoreError(f"Could not read {self.path}: {exc}") from exc
        items = raw.get("servers", []) if isinstance(raw, dict) else raw
        self._servers = [Server.from_dict(item) for item in items if isinstance(item, dict)]
        self._servers = [s for s in self._servers if s.name and s.host]
        self._mtime = self._stat_mtime()

    def save(self) -> None:
        payload = {
            "version": FORMAT_VERSION,
            "servers": [s.to_dict() for s in self._servers],
        }
        with paths.file_lock(self.path):
            paths.atomic_write_text(self.path, json.dumps(payload, indent=2) + "\n")
        self._mtime = self._stat_mtime()

    def reload_if_changed(self) -> bool:
        mtime = self._stat_mtime()
        if mtime != self._mtime:
            self.load()
            return True
        return False

    def _stat_mtime(self) -> float | None:
        try:
            return self.path.stat().st_mtime_ns / 1e9
        except FileNotFoundError:
            return None

    # -------------------------------------------------------------- queries
    @property
    def servers(self) -> list[Server]:
        return list(self._servers)

    def __len__(self) -> int:
        return len(self._servers)

    def get(self, server_id: str) -> Server | None:
        return next((s for s in self._servers if s.id == server_id), None)

    def by_name(self, name: str) -> Server | None:
        lname = name.strip().lower()
        return next((s for s in self._servers if s.name.lower() == lname), None)

    def find(self, query: str) -> Server:
        """Resolve a user-typed name: exact > prefix > unique fuzzy match."""
        exact = self.by_name(query)
        if exact:
            return exact
        q = query.lower()
        prefix = [s for s in self._servers if s.name.lower().startswith(q)]
        if len(prefix) == 1:
            return prefix[0]
        candidates = prefix or [s for s in self._servers if fuzzy_score(q, s.search_text) > 0]
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            raise StoreError(f"No server matches '{query}'")
        names = ", ".join(s.name for s in candidates[:8])
        raise StoreError(f"'{query}' is ambiguous: {names}")

    def tags(self) -> list[str]:
        return sorted({s.tag for s in self._servers if s.tag}, key=str.lower)

    # ------------------------------------------------------------ mutations
    def add(self, server: Server) -> Server:
        self._check(server)
        self._servers.append(server)
        self.save()
        return server

    def update(self, server: Server) -> Server:
        self._check(server)
        for i, existing in enumerate(self._servers):
            if existing.id == server.id:
                self._servers[i] = server
                self.save()
                return server
        raise StoreError(f"Unknown server id {server.id}")

    def remove(self, server_id: str) -> None:
        before = len(self._servers)
        self._servers = [s for s in self._servers if s.id != server_id]
        if len(self._servers) != before:
            self.save()

    def move(self, server_id: str, delta: int) -> None:
        idx = next((i for i, s in enumerate(self._servers) if s.id == server_id), None)
        if idx is None:
            return
        new = max(0, min(len(self._servers) - 1, idx + delta))
        if new != idx:
            self._servers.insert(new, self._servers.pop(idx))
            self.save()

    def mark_connected(self, server_id: str) -> None:
        srv = self.get(server_id)
        if srv:
            srv.last_connected = time.time()
            self.save()

    def unique_name(self, base: str) -> str:
        name, n = base, 2
        while self.by_name(name):
            name = f"{base}-{n}"
            n += 1
        return name

    def _check(self, server: Server) -> None:
        errors = server.validate()
        if errors:
            raise StoreError("; ".join(errors))
        clash = self.by_name(server.name)
        if clash and clash.id != server.id:
            raise StoreError(f"A server named '{server.name}' already exists")


# ---------------------------------------------------------------------------
# Legacy migration (~/.ssh_servers + friends from sshm 1.x/2.x)
# ---------------------------------------------------------------------------
def parse_legacy_line(line: str) -> Server | None:
    line = line.strip().rstrip("\r")
    if not line or line.startswith("#"):
        return None
    name, user, host, port, tag, mac, key = ((line.split("|") + [""] * 7)[:7])
    if not name.strip() or not host.strip():
        return None
    return Server.from_dict(
        {"name": name, "user": user, "host": host, "port": port or 22, "tag": tag, "mac": mac, "key": key}
    )


def migrate_legacy() -> list[Server]:
    src = paths.legacy_servers_file()
    if not src.exists():
        return []
    servers: list[Server] = []
    seen: set[str] = set()
    for line in src.read_text(errors="ignore").splitlines():
        srv = parse_legacy_line(line)
        if srv and srv.name.lower() not in seen:
            seen.add(srv.name.lower())
            servers.append(srv)

    commands: dict = {}
    try:
        commands = json.loads(paths.legacy_commands_file().read_text())
    except (OSError, json.JSONDecodeError):
        pass
    hidden: set[str] = set()
    try:
        hidden = set(json.loads(paths.legacy_tray_hidden_file().read_text()))
    except (OSError, json.JSONDecodeError, TypeError):
        pass

    for srv in servers:
        for item in commands.get(srv.name, []) if isinstance(commands, dict) else []:
            if isinstance(item, dict):
                cmd = CustomCommand.from_dict(item)
                if cmd.label and cmd.command:
                    srv.commands.append(cmd)
        srv.tray = srv.name not in hidden
    return servers
