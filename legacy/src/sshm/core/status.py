"""Reachability probing: TCP connect latency + SSH banner, merged with telemetry."""

from __future__ import annotations

import concurrent.futures
import socket
import time
from collections.abc import Iterable
from dataclasses import dataclass

from sshm.core import telemetry
from sshm.core.models import Server


@dataclass
class HostStatus:
    online: bool
    latency_ms: float | None = None
    banner: str = ""
    address: str = ""
    error: str = ""
    checked_at: float = 0.0
    telemetry: telemetry.Telemetry | None = None

    @property
    def latency_label(self) -> str:
        if not self.online or self.latency_ms is None:
            return "--"
        return f"{self.latency_ms:.0f} ms" if self.latency_ms >= 1 else "<1 ms"

    @property
    def state(self) -> str:
        """'online', 'degraded' (host up, sshd down) or 'offline'."""
        if self.online:
            return "online"
        if self.telemetry and self.telemetry.fresh:
            return "degraded"
        return "offline"

    @property
    def summary(self) -> str:
        if self.online:
            return f"Online · {self.latency_label}"
        if self.state == "degraded":
            return "Host up · SSH not reachable"
        return f"Offline{' · ' + self.error if self.error else ''}"


def probe(host: str, port: int, timeout: float = 1.5) -> HostStatus:
    started = time.monotonic()
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return HostStatus(False, error="DNS lookup failed", checked_at=time.time())
    last_err = "unreachable"
    for family, socktype, proto, _canon, sockaddr in infos[:4]:
        sock = socket.socket(family, socktype, proto)
        sock.settimeout(timeout)
        try:
            t0 = time.monotonic()
            sock.connect(sockaddr)
            latency = (time.monotonic() - t0) * 1000.0
            banner = ""
            try:
                sock.settimeout(min(0.8, timeout))
                raw = sock.recv(256).decode("utf-8", "replace").strip().splitlines()
                if raw and raw[0].startswith("SSH-"):
                    banner = raw[0].split("-", 2)[-1][:60]
            except OSError:
                pass
            return HostStatus(True, latency, banner, sockaddr[0], checked_at=time.time())
        except TimeoutError:
            last_err = "timed out"
        except ConnectionRefusedError:
            last_err = "connection refused"
        except OSError as exc:
            last_err = exc.strerror or "unreachable"
        finally:
            sock.close()
        if time.monotonic() - started > timeout * 2:
            break
    return HostStatus(False, error=last_err, checked_at=time.time())


def probe_many(servers: Iterable[Server], timeout: float = 1.5, workers: int = 32) -> dict[str, HostStatus]:
    servers = list(servers)
    results: dict[str, HostStatus] = {}
    if not servers:
        return results
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(workers, len(servers))) as pool:
        futures = {pool.submit(probe, s.host, s.port, timeout): s for s in servers}
        for fut in concurrent.futures.as_completed(futures):
            srv = futures[fut]
            try:
                results[srv.id] = fut.result()
            except Exception as exc:
                results[srv.id] = HostStatus(False, error=str(exc), checked_at=time.time())
    attach_telemetry(servers, results)
    return results


def attach_telemetry(
    servers: Iterable[Server], statuses: dict[str, HostStatus], cache: dict | None = None
) -> None:
    cache = telemetry.read_cache() if cache is None else cache
    for srv in servers:
        st = statuses.get(srv.id)
        if st is None:
            continue
        tel = telemetry.lookup(cache, srv.host, srv.port, st.address)
        st.telemetry = tel
        if tel and not tel.ssh_alive:
            st.online = False
            st.error = "agent reports sshd stopped"
