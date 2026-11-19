"""Signed UDP telemetry: packet format, receiver and shared on-disk cache.

Agents (see ``sshm/data/sshm_agent.py``) push a small JSON packet every few
seconds. Protocol v2 packets carry an HMAC-SHA256 signature made with the
hub's shared secret, plus a timestamp to limit replays. Unsigned v1 packets
from sshm 2.x agents are accepted when ``accept_legacy_agents`` is enabled.

The receiver keeps an in-memory map and mirrors it to
``$XDG_RUNTIME_DIR/sshm/telemetry.json`` so other processes (TUI, CLI) can
read the data without running their own listener.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sshm.core import paths

log = logging.getLogger(__name__)

PROTOCOL = 2
MAX_CLOCK_SKEW = 300.0  # seconds
FRESH_AFTER = 12.0      # entries older than this are considered stale
HISTORY = 60            # samples kept per host for sparklines


# ---------------------------------------------------------------- signing
def canonical(payload: dict[str, Any]) -> bytes:
    body = {k: v for k, v in payload.items() if k != "sig"}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()


def sign(payload: dict[str, Any], secret: str) -> str:
    return hmac.new(secret.encode(), canonical(payload), hashlib.sha256).hexdigest()


def verify(payload: dict[str, Any], secret: str) -> bool:
    sig = payload.get("sig")
    if not isinstance(sig, str) or not secret:
        return False
    return hmac.compare_digest(sig, sign(payload, secret))


# ------------------------------------------------------------------ model
@dataclass
class TopProcess:
    name: str
    pid: int
    cpu: float
    rss: int

    @property
    def rss_label(self) -> str:
        n = float(self.rss)
        for unit in ("B", "K", "M", "G"):
            if n < 1024:
                return f"{n:.0f}{unit}" if unit in ("B", "K") else f"{n:.1f}{unit}"
            n /= 1024
        return f"{n:.1f}T"


@dataclass
class Telemetry:
    received: float
    cpu: float | None = None
    mem_used: int = 0
    mem_total: int = 0
    swap_used: int = 0
    swap_total: int = 0
    disk_used: int = 0
    disk_total: int = 0
    load: tuple[float, float, float] | None = None
    uptime: int = 0
    uptime_text: str = ""
    ssh_alive: bool = True
    os_name: str = ""
    kernel: str = ""
    signed: bool = False
    history: list[float] = field(default_factory=list)
    procs: list[TopProcess] = field(default_factory=list)
    containers: list[list] | None = None      # raw agent rows; see containers.from_agent
    runtime: str = ""
    containers_error: str = ""
    agent_version: str = ""             # "" for agents older than 3.3
    reboot_required: bool | None = None  # None = agent does not report it

    def top(self, key: str = "cpu", n: int = 5) -> list[TopProcess]:
        if key == "mem":
            return sorted(self.procs, key=lambda p: -p.rss)[:n]
        return sorted(self.procs, key=lambda p: (-p.cpu, -p.rss))[:n]

    @property
    def age(self) -> float:
        return time.time() - self.received

    @property
    def fresh(self) -> bool:
        return self.age <= FRESH_AFTER

    @property
    def mem_pct(self) -> float | None:
        return 100.0 * self.mem_used / self.mem_total if self.mem_total else None

    @property
    def disk_pct(self) -> float | None:
        return 100.0 * self.disk_used / self.disk_total if self.disk_total else None

    @property
    def mem_label(self) -> str:
        return f"{_gib(self.mem_used)} / {_gib(self.mem_total)}" if self.mem_total else "--"

    @property
    def disk_label(self) -> str:
        return f"{_gib(self.disk_used)} / {_gib(self.disk_total)}" if self.disk_total else "--"

    @property
    def load_label(self) -> str:
        return " ".join(f"{x:.2f}" for x in self.load) if self.load else "--"

    @property
    def uptime_label(self) -> str:
        if self.uptime_text:
            return self.uptime_text
        return format_duration(self.uptime) if self.uptime else "--"

    @classmethod
    def from_entry(cls, entry: dict[str, Any]) -> Telemetry:
        load = entry.get("load")
        return cls(
            received=float(entry.get("ts", 0)),
            cpu=_float(entry.get("cpu")),
            mem_used=int(entry.get("mem_used") or 0),
            mem_total=int(entry.get("mem_total") or 0),
            swap_used=int(entry.get("swap_used") or 0),
            swap_total=int(entry.get("swap_total") or 0),
            disk_used=int(entry.get("disk_used") or 0),
            disk_total=int(entry.get("disk_total") or 0),
            load=tuple(load[:3]) if isinstance(load, list) and len(load) >= 3 else None,
            uptime=int(entry.get("uptime") or 0),
            uptime_text=str(entry.get("uptime_text") or ""),
            ssh_alive=bool(entry.get("ssh", 1)),
            os_name=str(entry.get("os") or ""),
            kernel=str(entry.get("kernel") or ""),
            signed=bool(entry.get("signed")),
            history=[float(x) for x in entry.get("hist", []) if isinstance(x, (int, float))],
            procs=[TopProcess(*p) for p in entry.get("procs", []) if isinstance(p, list) and len(p) == 4],
            containers=entry.get("containers") if isinstance(entry.get("containers"), list) else None,
            runtime=str(entry.get("rt") or ""),
            containers_error=str(entry.get("containers_error") or ""),
            agent_version=str(entry.get("agent") or ""),
            reboot_required=bool(entry["reboot"]) if "reboot" in entry else None,
        )


def _clean_procs(raw: Any) -> list[list]:
    out: list[list] = []
    if not isinstance(raw, list):
        return out
    for item in raw[:12]:
        try:
            name, pid, cpu, rss = item
            out.append([str(name)[:32], int(pid), round(float(cpu), 1), int(rss)])
        except (TypeError, ValueError):
            continue
    return out


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _gib(n: int) -> str:
    return f"{n / 1024**3:.1f} GiB"


def format_duration(seconds: float) -> str:
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


# ---------------------------------------------------------------- parsing
_LEGACY_RAM = re.compile(r"([\d.]+)\s*/\s*([\d.]+)\s*G")


def parse_packet(
    data: bytes, addr_ip: str, secret: str, accept_legacy: bool
) -> tuple[list[str], dict[str, Any]] | None:
    """Validate a datagram and return (cache keys, cache entry) or ``None``."""
    try:
        msg = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(msg, dict):
        return None

    now = time.time()
    port = str(msg.get("port", "22"))
    if msg.get("v") == PROTOCOL:
        if not verify(msg, secret):
            return None
        ts = _float(msg.get("ts")) or 0.0
        if abs(now - ts) > MAX_CLOCK_SKEW:
            return None
        entry: dict[str, Any] = {
            "ts": now,
            "signed": True,
            "cpu": _float(msg.get("cpu")),
            "ssh": 0 if msg.get("state") == "stopping" else int(bool(msg.get("ssh", 1))),
        }
        for key in ("mem_used", "mem_total", "swap_used", "swap_total", "disk_used", "disk_total", "uptime"):
            if isinstance(msg.get(key), (int, float)):
                entry[key] = int(msg[key])
        if isinstance(msg.get("load"), list):
            entry["load"] = [float(x) for x in msg["load"][:3]]
        for key in ("os", "kernel", "agent"):
            if isinstance(msg.get(key), str):
                entry[key] = msg[key][:80]
        if "reboot" in msg:
            entry["reboot"] = int(bool(msg.get("reboot")))
        entry["procs"] = _clean_procs(msg.get("procs"))
        if isinstance(msg.get("containers"), list):
            entry["containers"] = [r for r in msg["containers"][:40] if isinstance(r, list) and len(r) >= 10]
            entry["rt"] = str(msg.get("rt") or "docker")[:16]
        if isinstance(msg.get("containers_error"), str):
            entry["containers_error"] = msg["containers_error"][:200]
        label = str(msg.get("id") or "")
    elif accept_legacy and "cpu" in msg and "v" not in msg:
        entry = {"ts": now, "signed": False, "cpu": _float(msg.get("cpu")), "ssh": int(bool(msg.get("ssh", 1)))}
        m = _LEGACY_RAM.search(str(msg.get("ram", "")))
        if m:
            entry["mem_used"] = int(float(m.group(1)) * 1024**3)
            entry["mem_total"] = int(float(m.group(2)) * 1024**3)
        if msg.get("up"):
            entry["uptime_text"] = str(msg["up"])[:20]
        label = str(msg.get("host") or "")
    else:
        return None

    keys = [f"{addr_ip}:{port}"]
    if label and label != addr_ip:
        keys.append(f"{label}:{port}")
    return keys, entry


# ------------------------------------------------------------------ cache
def read_cache() -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(paths.telemetry_cache_file().read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def lookup(cache: dict[str, dict[str, Any]], host: str, port: int, ip: str = "") -> Telemetry | None:
    for key in (f"{host}:{port}", f"{ip}:{port}" if ip else None, host if port == 22 else None):
        if key and key in cache:
            tel = Telemetry.from_entry(cache[key])
            if tel.fresh:
                return tel
    return None


# --------------------------------------------------------------- listener
class TelemetryListener(threading.Thread):
    """Background UDP receiver. ``on_update(keys, alive_changed)`` runs on this thread."""

    def __init__(
        self,
        port: int,
        secret: str,
        accept_legacy: bool = True,
        on_update: Callable[[list[str], bool], None] | None = None,
        on_command: Callable[[dict], None] | None = None,
    ) -> None:
        super().__init__(name="sshm-telemetry", daemon=True)
        self.port = port
        self.secret = secret
        self.accept_legacy = accept_legacy
        self.on_update = on_update
        self.on_command = on_command
        self.cache: dict[str, dict[str, Any]] = read_cache()
        self.error = ""
        self._sock: socket.socket | None = None
        self._stop = threading.Event()
        self._last_flush = 0.0
        self._dirty = False

    def bind(self) -> bool:
        """Bind the socket. Returns False if another sshm process already owns the port."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind(("0.0.0.0", self.port))
        except OSError as exc:
            sock.close()
            self.error = str(exc)
            return False
        sock.settimeout(1.0)
        self._sock = sock
        return True

    def run(self) -> None:
        if self._sock is None and not self.bind():
            return
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                data, addr = self._sock.recvfrom(65535)
            except TimeoutError:
                self._flush()
                continue
            except OSError:
                break
            parsed = parse_packet(data, addr[0], self.secret, self.accept_legacy)
            if not parsed:
                continue
            keys, entry = parsed
            changed = False
            for key in keys:
                prev = self.cache.get(key, {})
                hist = list(prev.get("hist", []))
                if entry.get("cpu") is not None:
                    hist = [*hist, round(entry["cpu"], 1)][-HISTORY:]
                stale = time.time() - float(prev.get("ts", 0)) > FRESH_AFTER
                if prev.get("ssh") != entry["ssh"] or stale:
                    changed = True
                self.cache[key] = {**entry, "hist": hist}
            self._dirty = True
            self._flush()
            if self.on_update:
                try:
                    self.on_update(keys, changed)
                except Exception:
                    log.exception("telemetry callback failed")
        self._flush(force=True)

    def _flush(self, force: bool = False) -> None:
        now = time.monotonic()
        if self._dirty and (force or now - self._last_flush > 0.5):
            cutoff = time.time() - 3600
            self.cache = {k: v for k, v in self.cache.items() if float(v.get("ts", 0)) > cutoff}
            try:
                paths.atomic_write_text(paths.telemetry_cache_file(), json.dumps(self.cache))
            except OSError:
                log.warning("could not write telemetry cache", exc_info=True)
            self._last_flush = now
            self._dirty = False

    def stop(self) -> None:
        self._stop.set()
        if self._sock:
            self._sock.close()
