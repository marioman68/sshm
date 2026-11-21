"""Docker / Podman awareness.

Two data sources feed the same :class:`Container` model:

* **SSH discovery** — run ``docker ps`` + ``docker stats`` (or podman, or
  ``sudo -n docker``) on a host over a multiplexed, key-authenticated session.
* **Agent** — the telemetry agent reads the Docker/Podman API socket and the
  containers' cgroups directly and pushes the result every few seconds.

:func:`link_servers` then recognises saved servers that are really containers:
a server whose port is published by a container on a host that shares its IP
(``Minecraft_server`` at ``192.168.4.100:2222`` → container ``mc`` on the
server at ``192.168.4.100:22``).
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

from sshm.core import procs, sshcmd
from sshm.core.models import Server

# --------------------------------------------------------------------- model
WELL_KNOWN = {
    22: "SSH", 25565: "Minecraft", 19132: "Minecraft Bedrock", 80: "HTTP", 443: "HTTPS", 8080: "HTTP",
    8443: "HTTPS", 3000: "Web", 8000: "Web", 8096: "Jellyfin", 32400: "Plex", 9000: "Portainer",
    9443: "Portainer", 3306: "MySQL", 5432: "PostgreSQL", 6379: "Redis", 27017: "MongoDB", 1883: "MQTT",
    8123: "Home Assistant", 53: "DNS", 51820: "WireGuard", 2049: "NFS", 445: "SMB", 25575: "RCON",
    27015: "Steam", 7777: "Game", 8384: "Syncthing", 9090: "Prometheus", 3001: "Uptime Kuma",
}
HTTP_PORTS = {80, 443, 8080, 8443, 3000, 8000, 8096, 32400, 9000, 9443, 8123, 8384, 9090, 3001, 5000, 8888}


@dataclass
class PortMap:
    host_port: int
    container_port: int
    proto: str = "tcp"
    host_ip: str = ""

    @property
    def label(self) -> str:
        return f"{self.host_port}→{self.container_port}/{self.proto}"

    @property
    def service(self) -> str:
        return WELL_KNOWN.get(self.container_port) or WELL_KNOWN.get(self.host_port, "")

    @property
    def is_web(self) -> bool:
        return self.proto == "tcp" and (self.container_port in HTTP_PORTS or self.host_port in HTTP_PORTS)


@dataclass
class Container:
    id: str
    name: str
    image: str = ""
    state: str = ""                  # running | exited | paused | restarting | created | dead
    status: str = ""                 # "Up 3 days (healthy)"
    ports: list[PortMap] = field(default_factory=list)
    cpu: float | None = None         # % of one core
    mem: int = 0                     # bytes
    mem_limit: int = 0
    project: str = ""                # docker compose project
    runtime: str = "docker"          # command prefix used on the host, e.g. "docker", "sudo -n podman"
    source: str = "ssh"              # "ssh" or "agent"

    @property
    def running(self) -> bool:
        return self.state == "running"

    @property
    def health(self) -> str:
        m = re.search(r"\((healthy|unhealthy|health: starting)\)", self.status)
        return m.group(1) if m else ""

    @property
    def mem_pct(self) -> float | None:
        return 100.0 * self.mem / self.mem_limit if self.mem_limit and self.mem else None

    @property
    def mem_label(self) -> str:
        if not self.mem:
            return "--"
        lim = f" / {procs.human_bytes(self.mem_limit)}" if self.mem_limit else ""
        return f"{procs.human_bytes(self.mem)}{lim}"

    @property
    def ports_label(self) -> str:
        return ", ".join(p.label for p in self.ports) or "none published"

    @property
    def short_id(self) -> str:
        return self.id[:12]

    @property
    def cli(self) -> str:
        """Runtime command for interactive use (sudo may prompt in a terminal)."""
        return self.runtime.replace("sudo -n ", "sudo ")

    @property
    def image_short(self) -> str:
        return self.image.split("@")[0]


@dataclass
class HostContainers:
    host_id: str
    containers: list[Container]
    runtime: str = "docker"
    source: str = "ssh"
    error: str = ""
    fetched: float = 0.0

    def by_port(self, port: int) -> Container | None:
        return next((c for c in self.containers if any(p.host_port == port for p in c.ports)), None)


@dataclass
class ContainerLink:
    host: Server
    container: Container


# ------------------------------------------------------------------- parsing
_PORT_RE = re.compile(r"(?:(?P<ip>[\d.:\[\]a-fA-F]*):)?(?P<hp>\d+)(?:-\d+)?->(?P<cp>\d+)(?:-\d+)?/(?P<proto>\w+)")
_SIZE_RE = re.compile(r"([\d.]+)\s*([KMGTP]?i?B)", re.I)
_UNITS = {"b": 1, "kb": 1000, "kib": 1024, "mb": 1000**2, "mib": 1024**2, "gb": 1000**3, "gib": 1024**3,
          "tb": 1000**4, "tib": 1024**4}


def parse_ports(value: Any) -> list[PortMap]:
    """Docker string form ("0.0.0.0:2222->22/tcp, :::2222->22/tcp") or podman/API list form."""
    out: list[PortMap] = []
    seen: set[tuple] = set()
    if isinstance(value, str):
        for m in _PORT_RE.finditer(value):
            key = (int(m["hp"]), int(m["cp"]), m["proto"])
            if key not in seen:
                seen.add(key)
                out.append(PortMap(key[0], key[1], key[2], (m["ip"] or "").strip("[]")))
    elif isinstance(value, list):
        for p in value:
            if not isinstance(p, dict):
                continue
            hp = p.get("PublicPort") or p.get("host_port") or p.get("hostPort")
            cp = p.get("PrivatePort") or p.get("container_port") or p.get("containerPort")
            proto = p.get("Type") or p.get("protocol") or "tcp"
            if hp and cp:
                key = (int(hp), int(cp), str(proto))
                if key not in seen:
                    seen.add(key)
                    out.append(PortMap(key[0], key[1], key[2], str(p.get("IP") or p.get("host_ip") or "")))
    return out


def parse_size(text: str) -> int:
    m = _SIZE_RE.search(text or "")
    if not m:
        return 0
    return int(float(m.group(1)) * _UNITS.get(m.group(2).lower(), 1))


def _labels(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items()}
    out = {}
    for part in str(value or "").split(","):
        k, _, v = part.partition("=")
        if k:
            out[k.strip()] = v.strip()
    return out


def _name(value: Any) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value or "").lstrip("/").split(",")[0]


def parse_ps_line(obj: dict, runtime: str) -> Container | None:
    cid = str(obj.get("ID") or obj.get("Id") or "")
    name = _name(obj.get("Names") or obj.get("Name"))
    if not cid or not name:
        return None
    state = str(obj.get("State") or "").lower()
    status = str(obj.get("Status") or "")
    if not state:  # very old docker: derive from status text
        state = "running" if status.startswith("Up") else "exited"
    labels = _labels(obj.get("Labels"))
    return Container(
        id=cid, name=name, image=str(obj.get("Image") or ""), state=state, status=status,
        ports=parse_ports(obj.get("Ports")), project=labels.get("com.docker.compose.project", ""),
        runtime=runtime, source="ssh",
    )


def parse_discovery(output: str) -> HostContainers:
    """Parse the output of :data:`DISCOVERY_SCRIPT`."""
    lines = output.splitlines()
    if not lines or lines[0].startswith("SSHM_NODOCKER"):
        reason = lines[0].partition(" ")[2] if lines else ""
        return HostContainers("", [], error=reason or "no docker or podman found")
    runtime = lines[0].partition(" ")[2].strip() if lines[0].startswith("SSHM_RT") else "docker"
    containers: dict[str, Container] = {}
    stats_mode = False
    for line in lines[1:]:
        if line.strip() == "SSHM_STATS":
            stats_mode = True
            continue
        line = line.strip()
        if not line.startswith(("{", "[")):
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        items = data if isinstance(data, list) else [data]
        for obj in items:
            if not isinstance(obj, dict):
                continue
            if not stats_mode:
                c = parse_ps_line(obj, runtime)
                if c:
                    containers[c.id] = c
                continue
            sid = str(obj.get("ID") or obj.get("ContainerID") or obj.get("id") or "")
            target = next((c for cid, c in containers.items() if sid and (cid.startswith(sid) or sid.startswith(cid))),
                          None)
            if target is None:
                target = next((c for c in containers.values() if c.name == _name(obj.get("Name"))), None)
            if target is None:
                continue
            cpu = str(obj.get("CPUPerc") or obj.get("cpu_percent") or obj.get("CPU") or "").rstrip("%")
            try:
                target.cpu = float(cpu)
            except ValueError:
                pass
            usage = str(obj.get("MemUsage") or obj.get("mem_usage") or "")
            used, _, limit = usage.partition("/")
            target.mem, target.mem_limit = parse_size(used), parse_size(limit)
    ordered = sorted(containers.values(), key=lambda c: (not c.running, c.name.lower()))
    return HostContainers("", ordered, runtime=runtime, source="ssh", fetched=time.time())


def from_agent(entries: list, runtime: str = "docker") -> list[Container]:
    """Agent packet rows: [id, name, image, state, status, ports, cpu, mem, mem_limit, project]."""
    out = []
    for row in entries or []:
        if not isinstance(row, list) or len(row) < 10:
            continue
        cid, name, image, state, status, ports, cpu, mem, limit, project = row[:10]
        out.append(Container(
            id=str(cid), name=str(name), image=str(image), state=str(state), status=str(status),
            ports=parse_ports(str(ports)), cpu=float(cpu) if isinstance(cpu, (int, float)) else None,
            mem=int(mem or 0), mem_limit=int(limit or 0), project=str(project), runtime=runtime, source="agent",
        ))
    return sorted(out, key=lambda c: (not c.running, c.name.lower()))


# ---------------------------------------------------------------- discovery
_FMT = shlex.quote("{{json .}}")
DISCOVERY_SCRIPT = (
    "rt=''; for c in docker podman; do command -v $c >/dev/null 2>&1 || continue; "
    f"if out=$($c ps -a --no-trunc --format {_FMT} 2>/dev/null); then rt=$c; break; "
    f"elif out=$(sudo -n $c ps -a --no-trunc --format {_FMT} 2>/dev/null); then rt=\"sudo -n $c\"; break; "
    "else err=\"$c found but permission denied (add your user to the $c group)\"; fi; done; "
    "if [ -z \"$rt\" ]; then echo \"SSHM_NODOCKER ${err:-no docker or podman}\"; exit 0; fi; "
    "echo \"SSHM_RT $rt\"; printf '%s\\n' \"$out\"; echo SSHM_STATS; "
    f"$rt stats --no-stream --no-trunc --format {_FMT} 2>/dev/null || true"
)
REMOTE_DISCOVERY = "sh -c " + shlex.quote(DISCOVERY_SCRIPT)


class ContainerError(RuntimeError):
    pass


def discover(host: Server, timeout: float = 25.0) -> HostContainers:
    try:
        res = sshcmd.run_capture(procs.remote_argv(host, REMOTE_DISCOVERY), timeout)
    except FileNotFoundError:
        raise ContainerError("ssh is not installed") from None
    except subprocess.TimeoutExpired:
        raise ContainerError(f"{host.name} did not answer within {timeout:.0f}s") from None
    if not res.stdout.startswith("SSHM_"):
        raise ContainerError(procs._explain(res))
    hc = parse_discovery(res.stdout)
    hc.host_id = host.id
    return hc


ACTIONS = ("start", "stop", "restart", "pause", "unpause")


def run_action(host: Server, container: Container, action: str, timeout: float = 60.0) -> str:
    if action not in ACTIONS:
        raise ContainerError(f"unknown action {action}")
    remote = f"{container.runtime} {action} {shlex.quote(container.name)}"
    try:
        res = sshcmd.run_capture(procs.remote_argv(host, remote), timeout)
    except subprocess.TimeoutExpired:
        raise ContainerError(f"{action} timed out after {timeout:.0f}s") from None
    if res.returncode != 0:
        raise ContainerError(procs._explain(res))
    done = {"start": "Started", "stop": "Stopped", "restart": "Restarted", "pause": "Paused", "unpause": "Resumed"}
    return f"{done[action]} {container.name}"


def logs_argv(host: Server, container: Container, tail: int = 200) -> list[str]:
    remote = f"{container.cli} logs -f --tail {tail} {shlex.quote(container.name)}"
    return sshcmd.ssh_command(host, remote_command=remote)


def shell_argv(host: Server, container: Container) -> list[str]:
    inner = shlex.quote("command -v bash >/dev/null 2>&1 && exec bash || exec sh")
    return sshcmd.ssh_command(host, remote_command=f"{container.cli} exec -it {shlex.quote(container.name)} "
                                                   f"sh -c {inner}")


def stats_argv(host: Server, container: Container | None = None) -> list[str]:
    target = shlex.quote(container.name) if container else ""
    runtime = container.cli if container else "docker"
    return sshcmd.ssh_command(host, remote_command=f"{runtime} stats {target}".strip())


# ------------------------------------------------------------------ linking
def link_servers(servers: list[Server], hosts: dict[str, HostContainers],
                 addresses: dict[str, str] | None = None) -> dict[str, ContainerLink]:
    """Map server id → (docker host, container) for servers that are published container ports."""
    addresses = addresses or {}
    by_id = {s.id: s for s in servers}
    links: dict[str, ContainerLink] = {}

    def same_machine(a: Server, b: Server) -> bool:
        if a.host.lower() == b.host.lower():
            return True
        aa, ba = addresses.get(a.id), addresses.get(b.id)
        return bool(aa and ba and aa == ba)

    for host_id, hc in hosts.items():
        host = by_id.get(host_id)
        if host is None:
            continue
        for srv in servers:
            if srv.id == host_id or srv.id in links or (srv.port == host.port and same_machine(srv, host)):
                continue
            if not same_machine(srv, host):
                continue
            c = hc.by_port(srv.port)
            if c:
                links[srv.id] = ContainerLink(host, c)
    return links


def candidate_hosts(servers: list[Server], addresses: dict[str, str] | None = None) -> list[Server]:
    """Servers worth asking for containers: another profile points at the same machine on a different port.

    Ordered so the likeliest docker host (port 22, then lowest port) is asked first.
    """
    addresses = addresses or {}
    out = []
    for s in servers:
        key = addresses.get(s.id) or s.host.lower()
        siblings = [o for o in servers if o.id != s.id and (addresses.get(o.id) or o.host.lower()) == key]
        if any(o.port != s.port for o in siblings):
            out.append(s)
    return sorted(out, key=lambda s: (s.port != 22, s.port))
