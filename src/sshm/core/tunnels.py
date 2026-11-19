"""Background SSH port forwards (-L / -R / -D) tracked across processes."""

from __future__ import annotations

import contextlib
import json
import os
import re
import signal
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from sshm.core import paths, sshcmd
from sshm.core.models import Server, new_id

_HOST = r"[\w.\-]+|\[[0-9a-fA-F:]+\]"
_SPEC_RE = re.compile(rf"^(?:(?P<bind>{_HOST}):)?(?P<lport>\d+)(?::(?P<host>{_HOST}):(?P<rport>\d+))?$")


class TunnelError(RuntimeError):
    pass


@dataclass
class TunnelSpec:
    kind: str              # "L" local, "R" remote, "D" dynamic SOCKS
    listen_port: int
    dest_host: str = ""
    dest_port: int = 0
    bind: str = ""

    @classmethod
    def parse(cls, kind: str, text: str) -> TunnelSpec:
        kind = kind.upper().lstrip("-")
        if kind not in ("L", "R", "D"):
            raise TunnelError("Tunnel type must be L, R or D")
        m = _SPEC_RE.match(text.strip())
        if not m:
            raise TunnelError(f"Cannot parse forward '{text}' (expected [bind:]port[:host:port])")
        lport = int(m["lport"])
        if kind == "D":
            if m["host"]:
                raise TunnelError("Dynamic (SOCKS) forwards take only a port")
            spec = cls("D", lport, bind=m["bind"] or "")
        else:
            if not m["host"]:
                raise TunnelError("Local/remote forwards need port:host:port")
            spec = cls(kind, lport, m["host"], int(m["rport"]), m["bind"] or "")
        for port in (spec.listen_port, spec.dest_port or 1):
            if not 1 <= port <= 65535:
                raise TunnelError("Ports must be 1-65535")
        return spec

    @property
    def arg(self) -> str:
        bind = f"{self.bind}:" if self.bind else ""
        if self.kind == "D":
            return f"{bind}{self.listen_port}"
        return f"{bind}{self.listen_port}:{self.dest_host}:{self.dest_port}"

    def describe(self, server_name: str = "remote") -> str:
        if self.kind == "D":
            return f"SOCKS5 proxy on localhost:{self.listen_port} via {server_name}"
        if self.kind == "L":
            return f"localhost:{self.listen_port} → {self.dest_host}:{self.dest_port} (via {server_name})"
        return f"{server_name}:{self.listen_port} → {self.dest_host}:{self.dest_port} (on this machine)"


@dataclass
class Tunnel:
    id: str
    server_id: str
    server_name: str
    kind: str
    spec: str
    pid: int
    started: float

    @property
    def spec_obj(self) -> TunnelSpec:
        return TunnelSpec.parse(self.kind, self.spec)

    @property
    def description(self) -> str:
        return self.spec_obj.describe(self.server_name)


def tunnel_argv(server: Server, spec: TunnelSpec) -> list[str]:
    return [
        "ssh", *sshcmd.base_options(server, batch=True),
        "-N", "-T",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=3",
        f"-{spec.kind}", spec.arg,
        server.target,
    ]


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return False
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except OSError:
        return True
    return bool(cmdline) and os.path.basename(cmdline[0].decode(errors="ignore")) == "ssh"


class TunnelManager:
    def __init__(self, state_file: Path | None = None) -> None:
        self.state_file = state_file or paths.tunnels_file()
        self._children: dict[int, subprocess.Popen] = {}  # reaped so they never linger as zombies

    def _read(self) -> list[Tunnel]:
        try:
            data = json.loads(self.state_file.read_text())
            return [Tunnel(**t) for t in data if isinstance(t, dict)]
        except (OSError, json.JSONDecodeError, TypeError):
            return []

    def _write(self, tunnels: list[Tunnel]) -> None:
        paths.atomic_write_text(self.state_file, json.dumps([asdict(t) for t in tunnels], indent=1))

    def list(self, server_id: str | None = None) -> list[Tunnel]:
        for pid, proc in list(self._children.items()):
            if proc.poll() is not None:
                del self._children[pid]
        with paths.file_lock(self.state_file):
            tunnels = self._read()
            alive = [t for t in tunnels if _alive(t.pid)]
            if len(alive) != len(tunnels):
                self._write(alive)
        return [t for t in alive if server_id is None or t.server_id == server_id]

    def start(self, server: Server, spec: TunnelSpec, wait: float = 3.0) -> Tunnel:
        for t in self.list():
            if t.kind == spec.kind and t.spec_obj.listen_port == spec.listen_port and spec.kind != "R":
                raise TunnelError(f"Port {spec.listen_port} is already forwarded ({t.server_name})")
        with tempfile.TemporaryFile() as err:
            proc = subprocess.Popen(
                tunnel_argv(server, spec),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=err,
                start_new_session=True,
            )
            deadline = time.monotonic() + wait
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    err.seek(0)
                    lines = err.read().decode(errors="replace").strip().splitlines()
                    hint = lines[-1] if lines else f"ssh exited with status {proc.returncode}"
                    if "Permission denied" in hint or "publickey" in hint:
                        hint += " — background tunnels need key authentication (push your key first)"
                    raise TunnelError(hint)
                time.sleep(0.1)
        self._children[proc.pid] = proc
        tunnel = Tunnel(new_id(), server.id, server.name, spec.kind, spec.arg, proc.pid, time.time())
        with paths.file_lock(self.state_file):
            self._write([*self._read(), tunnel])
        return tunnel

    def stop(self, tunnel_id: str) -> bool:
        with paths.file_lock(self.state_file):
            tunnels = self._read()
            target = next((t for t in tunnels if t.id == tunnel_id or t.id.startswith(tunnel_id)), None)
            if not target:
                return False
            if _alive(target.pid):
                with contextlib.suppress(ProcessLookupError):
                    os.kill(target.pid, signal.SIGTERM)
            self._write([t for t in tunnels if t.id != target.id])
        return True

    def stop_all(self) -> int:
        count = 0
        for t in self.list():
            count += self.stop(t.id)
        return count
