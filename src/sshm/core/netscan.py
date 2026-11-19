"""LAN discovery: parallel TCP probe with SSH banner verification, ARP and rDNS."""

from __future__ import annotations

import concurrent.futures
import ipaddress
import json
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PORTS = "22, 2222, 2200, 22222, 8022"
MAX_HOSTS = 4096


@dataclass
class Discovered:
    ip: str
    port: int
    banner: str = ""
    hostname: str = ""
    mac: str = ""
    latency_ms: float = 0.0

    @property
    def suggested_name(self) -> str:
        base = self.hostname.split(".")[0] if self.hostname else f"host-{self.ip.split('.')[-1]}"
        return base if self.port == 22 else f"{base}-{self.port}"


def parse_ports(spec: str) -> list[int]:
    ports: set[int] = set()
    for part in spec.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            if a.isdigit() and b.isdigit():
                lo, hi = sorted((int(a), int(b)))
                ports.update(p for p in range(lo, min(hi, lo + 512) + 1) if 1 <= p <= 65535)
        elif part.isdigit() and 1 <= int(part) <= 65535:
            ports.add(int(part))
    if not ports:
        raise ValueError(f"No valid ports in '{spec}'")
    return sorted(ports)


def parse_targets(spec: str) -> list[str]:
    """Accepts ``192.168.1.0/24``, ``192.168.1`` (=/24), ``10.0.0.5-40`` or a single IP."""
    spec = spec.strip()
    if not spec:
        raise ValueError("Empty target")
    parts = spec.split(".")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        spec = f"{spec}.0/24"
    if "-" in spec and "/" not in spec:
        base, _, end = spec.rpartition("-")
        start_ip = ipaddress.IPv4Address(base)
        prefix = str(start_ip).rsplit(".", 1)[0]
        last = int(end)
        first = int(str(start_ip).rsplit(".", 1)[1])
        if not 0 <= first <= last <= 255:
            raise ValueError(f"Bad range '{spec}'")
        return [f"{prefix}.{i}" for i in range(first, last + 1)]
    net = ipaddress.ip_network(spec, strict=False)
    if net.num_addresses > MAX_HOSTS + 2:
        raise ValueError(f"{net} has {net.num_addresses} addresses; the limit is {MAX_HOSTS}")
    hosts = [str(h) for h in net.hosts()] or [str(net.network_address)]
    return hosts


def local_network() -> str:
    """Best guess at the primary IPv4 network, e.g. ``192.168.4.0/24``."""
    ip = ""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("1.1.1.1", 9))
            ip = s.getsockname()[0]
    except OSError:
        pass
    prefix_len = 24
    if ip and shutil.which("ip"):
        try:
            out = subprocess.run(["ip", "-j", "-4", "addr"], capture_output=True, text=True, timeout=2).stdout
            for iface in json.loads(out or "[]"):
                for addr in iface.get("addr_info", []):
                    if addr.get("local") == ip:
                        prefix_len = int(addr.get("prefixlen", 24))
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    if not ip:
        return "192.168.1.0/24"
    prefix_len = max(prefix_len, 22)  # keep the default scan quick
    return str(ipaddress.ip_network(f"{ip}/{prefix_len}", strict=False))


def read_arp() -> dict[str, str]:
    table: dict[str, str] = {}
    try:
        lines = Path("/proc/net/arp").read_text().splitlines()[1:]
    except OSError:
        return table
    for line in lines:
        parts = line.split()
        if len(parts) >= 4 and parts[3] != "00:00:00:00:00:00":
            table[parts[0]] = parts[3].lower()
    return table


def mac_for(host: str) -> str:
    """Resolve *host* and look its MAC up in the ARP cache (after a nudge)."""
    try:
        ip = socket.gethostbyname(host)
    except OSError:
        return ""
    try:  # any packet populates the neighbour table
        with socket.create_connection((ip, 22), timeout=0.6):
            pass
    except OSError:
        pass
    return read_arp().get(ip, "")


def _probe(ip: str, port: int, timeout: float) -> Discovered | None:
    t0 = time.monotonic()
    try:
        with socket.create_connection((ip, port), timeout=timeout) as sock:
            latency = (time.monotonic() - t0) * 1000
            sock.settimeout(timeout + 0.3)
            try:
                banner = sock.recv(128).decode("utf-8", "replace").strip().splitlines()[0]
            except (OSError, IndexError):
                banner = ""
    except OSError:
        return None
    if not banner.startswith("SSH-"):
        return None
    return Discovered(ip, port, banner.split("-", 2)[-1][:48], latency_ms=latency)


def _rdns(ip: str) -> str:
    try:
        return socket.gethostbyaddr(ip)[0]
    except OSError:
        return ""


def scan(
    targets: list[str],
    ports: list[int],
    *,
    timeout: float = 0.5,
    workers: int = 128,
    progress: Callable[[int, int], None] | None = None,
    cancel: threading.Event | None = None,
) -> list[Discovered]:
    jobs = [(ip, p) for ip in targets for p in ports]
    found: list[Discovered] = []
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_probe, ip, p, timeout) for ip, p in jobs]
        for fut in concurrent.futures.as_completed(futures):
            done += 1
            if progress and (done % 32 == 0 or done == len(jobs)):
                progress(done, len(jobs))
            if cancel is not None and cancel.is_set():
                for f in futures:
                    f.cancel()
                break
            res = fut.result()
            if res:
                found.append(res)
    arp = read_arp()
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        ips = sorted({d.ip for d in found})
        names = dict(zip(ips, pool.map(_rdns, ips), strict=True))
    for d in found:
        d.mac = arp.get(d.ip, "")
        d.hostname = names.get(d.ip, "")
    found.sort(key=lambda d: (tuple(int(x) for x in d.ip.split(".")), d.port))
    return found
