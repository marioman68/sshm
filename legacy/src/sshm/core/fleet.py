"""Run one command on many servers in parallel, and back up / restore the server list."""

from __future__ import annotations

import concurrent.futures
import json
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sshm import __version__
from sshm.core import procs, sshcmd
from sshm.core.models import Server
from sshm.core.store import ServerStore


@dataclass
class RunResult:
    server: Server
    returncode: int | None       # None = could not run (timeout / ssh missing)
    stdout: str
    stderr: str
    seconds: float

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def summary(self) -> str:
        if self.returncode is None:
            return self.stderr.strip().splitlines()[-1] if self.stderr.strip() else "did not run"
        if self.returncode == 255 and not self.stdout:
            return procs._explain(subprocess.CompletedProcess([], 255, "", self.stderr))
        last = (self.stdout.strip() or self.stderr.strip()).splitlines()
        return last[-1][:160] if last else f"exit {self.returncode}"


def run_one(server: Server, command: str, timeout: float = 120.0) -> RunResult:
    started = time.monotonic()
    try:
        res = sshcmd.run_capture(procs.remote_argv(server, command), timeout)
        return RunResult(server, res.returncode, res.stdout, res.stderr, time.monotonic() - started)
    except FileNotFoundError:
        return RunResult(server, None, "", "ssh is not installed", 0.0)
    except subprocess.TimeoutExpired:
        return RunResult(server, None, "", f"timed out after {timeout:.0f}s", time.monotonic() - started)


def run_many(servers: list[Server], command: str, *, timeout: float = 120.0, parallel: int = 8,
             on_result: Callable[[RunResult], None] | None = None,
             cancel: threading.Event | None = None) -> list[RunResult]:
    """Run *command* on every server (key auth, no TTY). Results come back in completion order."""
    results: list[RunResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(parallel, len(servers) or 1))) as pool:
        futures = [pool.submit(run_one, s, command, timeout) for s in servers]
        for fut in concurrent.futures.as_completed(futures):
            if cancel is not None and cancel.is_set():
                for f in futures:
                    f.cancel()
                break
            res = fut.result()
            results.append(res)
            if on_result:
                on_result(res)
    order = {s.id: i for i, s in enumerate(servers)}
    return sorted(results, key=lambda r: order.get(r.server.id, 0))


# ------------------------------------------------------------ backup/restore
BACKUP_FORMAT = "sshm-backup"


def export_backup(store: ServerStore, path: Path, servers: list[Server] | None = None) -> int:
    """Write servers (incl. saved commands, tags, MACs) to a JSON file. Secrets are never included."""
    items = servers if servers is not None else store.servers
    data = {"format": BACKUP_FORMAT, "version": 1, "sshm": __version__, "exported": int(time.time()),
            "servers": [s.to_dict() for s in items]}
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return len(items)


def import_backup(store: ServerStore, path: Path, replace: bool = False) -> tuple[int, int]:
    """Merge (default) or replace servers from a backup. Returns (added, updated)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from None
    if not isinstance(data, dict) or data.get("format") != BACKUP_FORMAT:
        raise ValueError(f"{path} is not an sshm backup")
    incoming = [Server.from_dict(d) for d in data.get("servers", []) if isinstance(d, dict)]
    incoming = [s for s in incoming if s.name and s.host]
    if replace:
        for s in store.servers:
            store.remove(s.id)
    added = updated = 0
    for srv in incoming:
        same = store.get(srv.id) or store.by_name(srv.name)
        if same is not None:
            srv.id = same.id
            store.update(srv)
            updated += 1
        else:
            store.add(srv)
            added += 1
    return added, updated
