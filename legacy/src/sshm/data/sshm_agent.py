#!/usr/bin/env python3
"""sshm telemetry agent — stdlib only, runs as a systemd *user* service.

Every few seconds it sends a signed UDP packet to the sshm hub with CPU,
memory, swap, disk, load, uptime and whether the local sshd is accepting
connections. Configuration lives in ~/.config/sshm-agent/agent.json (0600):

    {"hub": ["192.168.1.10"], "port": 55889, "id": "nas", "ssh_port": 22,
     "secret": "...", "interval": 3}
"""

import hashlib
import hmac
import http.client
import json
import os
import platform
import re
import signal
import socket
import sys
import time

PROTOCOL = 2
AGENT_VERSION = "3.3.0"
CONF = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/.config/sshm-agent/agent.json")


def load_config():
    with open(CONF, encoding="utf-8") as fh:
        cfg = json.load(fh)
    hubs = cfg["hub"] if isinstance(cfg["hub"], list) else [cfg["hub"]]
    return {
        "hubs": [(h, int(cfg.get("port", 55889))) for h in hubs],
        "id": str(cfg.get("id") or socket.gethostname()),
        "ssh_port": int(cfg.get("ssh_port", 22)),
        "secret": str(cfg["secret"]),
        "interval": max(1.0, float(cfg.get("interval", 3))),
    }


def cpu_times():
    with open("/proc/stat") as fh:
        vals = [float(x) for x in fh.readline().split()[1:]]
    idle = vals[3] + (vals[4] if len(vals) > 4 else 0.0)
    return idle, sum(vals[:8])


def meminfo():
    info = {}
    with open("/proc/meminfo") as fh:
        for line in fh:
            key, _, rest = line.partition(":")
            parts = rest.split()
            if parts:
                info[key] = int(parts[0]) * 1024
    total = info.get("MemTotal", 0)
    avail = info.get("MemAvailable", info.get("MemFree", 0))
    swap_total = info.get("SwapTotal", 0)
    return total - avail, total, swap_total - info.get("SwapFree", 0), swap_total


def disk():
    st = os.statvfs("/")
    total = st.f_blocks * st.f_frsize
    return total - st.f_bavail * st.f_frsize, total


def uptime():
    with open("/proc/uptime") as fh:
        return int(float(fh.readline().split()[0]))


def os_name():
    try:
        with open("/etc/os-release") as fh:
            for line in fh:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')[:80]
    except OSError:
        pass
    return platform.system()


def _kver(name):
    return tuple(int(x) for x in re.findall(r"\d+", name.split("-")[0])[:4])


def reboot_required():
    """Debian/Ubuntu flag file, or a newer kernel installed than the one running (Fedora, Arch, ...)."""
    if os.path.exists("/run/reboot-required") or os.path.exists("/var/run/reboot-required"):
        return 1
    try:
        running = platform.release()
        installed = [d for d in os.listdir("/lib/modules") if os.path.isdir(f"/lib/modules/{d}/kernel")]
        newest = max(installed, key=_kver) if installed else running
        return int(_kver(newest) > _kver(running))
    except (OSError, ValueError):
        return 0


def ssh_alive(port):
    for host in ("127.0.0.1", "::1"):
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return 1
        except OSError:
            continue
    return 0


CLK_TCK = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
PAGE = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096


def proc_sample():
    """{pid: (name, user_ticks + system_ticks, rss_bytes)} for every process."""
    out = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat") as fh:
                raw = fh.read()
            name = raw[raw.index("(") + 1 : raw.rindex(")")]
            fields = raw[raw.rindex(")") + 2 :].split()
            ticks = int(fields[11]) + int(fields[12])   # utime + stime
            rss = int(fields[21]) * PAGE
        except (OSError, ValueError, IndexError):
            continue
        out[int(entry)] = (name[:32], ticks, rss)
    return out


def top_processes(prev, cur, dt, n=5):
    """Top *n* by CPU plus top *n* by memory, as [name, pid, cpu%, rss] lists."""
    rows = []
    for pid, (name, ticks, rss) in cur.items():
        before = prev.get(pid)
        cpu = 0.0
        if before and dt > 0:
            cpu = max(0.0, (ticks - before[1]) / CLK_TCK / dt * 100.0)
        rows.append([name, pid, round(cpu, 1), rss])
    by_cpu = sorted((r for r in rows if r[2] > 0), key=lambda r: -r[2])[:n]
    by_mem = sorted(rows, key=lambda r: -r[3])[:n]
    seen, merged = set(), []
    for r in by_cpu + by_mem:
        if r[1] not in seen:
            seen.add(r[1])
            merged.append(r)
    return merged


# ------------------------------------------------------------- containers
class UnixHTTP(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__("localhost", timeout=2)
        self.unix_path = path

    def connect(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(2)
        sock.connect(self.unix_path)
        self.sock = sock


def container_sockets():
    uid = os.getuid()
    xdg = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{uid}"
    return [("docker", "/var/run/docker.sock"), ("docker", f"{xdg}/docker.sock"),
            ("podman", f"{xdg}/podman/podman.sock"), ("podman", "/run/podman/podman.sock")]


def list_containers():
    """(runtime, [api objects], error). Uses the Docker-compatible REST API on a unix socket."""
    errors = []
    for runtime, path in container_sockets():
        if not os.path.exists(path):
            continue
        try:
            conn = UnixHTTP(path)
            conn.request("GET", "/containers/json?all=1")
            resp = conn.getresponse()
            body = resp.read()
            conn.close()
            if resp.status == 200:
                return runtime, json.loads(body), ""
            errors.append(f"{path}: HTTP {resp.status}")
        except PermissionError:
            errors.append(f"no permission for {path} (add this user to the {runtime} group)")
        except (OSError, ValueError) as exc:
            errors.append(f"{path}: {exc}")
    return None, [], "; ".join(errors)


def cgroup_paths(cid):
    uid = os.getuid()
    v2 = [f"/sys/fs/cgroup/system.slice/docker-{cid}.scope", f"/sys/fs/cgroup/docker/{cid}",
          f"/sys/fs/cgroup/machine.slice/libpod-{cid}.scope",
          f"/sys/fs/cgroup/user.slice/user-{uid}.slice/user@{uid}.service/user.slice/libpod-{cid}.scope"]
    for d in v2:
        if os.path.isdir(d):
            return ("v2", d)
    if os.path.isdir(f"/sys/fs/cgroup/cpuacct/docker/{cid}"):
        return ("v1", cid)
    return None


def _read(path):
    with open(path) as fh:
        return fh.read()


def cgroup_usage(cid):
    """(cpu_seconds, mem_bytes) for a container, or None."""
    found = cgroup_paths(cid)
    if not found:
        return None
    kind, where = found
    try:
        if kind == "v2":
            cpu = 0.0
            for line in _read(f"{where}/cpu.stat").splitlines():
                if line.startswith("usage_usec"):
                    cpu = int(line.split()[1]) / 1e6
            mem = int(_read(f"{where}/memory.current"))
            for line in _read(f"{where}/memory.stat").splitlines():
                if line.startswith("inactive_file "):   # match `docker stats` (excludes page cache)
                    mem = max(0, mem - int(line.split()[1]))
            return cpu, mem
        cpu = int(_read(f"/sys/fs/cgroup/cpuacct/docker/{where}/cpuacct.usage")) / 1e9
        mem = int(_read(f"/sys/fs/cgroup/memory/docker/{where}/memory.usage_in_bytes"))
        return cpu, mem
    except (OSError, ValueError, IndexError):
        return None


def container_rows(prev, dt, mem_total):
    """Compact rows for the packet plus the cpu sample map for the next round."""
    runtime, items, error = list_containers()
    if runtime is None:
        return None, [], error, prev
    rows, sample = [], {}
    for c in items[:40]:
        cid = str(c.get("Id", ""))
        ports = sorted({f"{p.get('PublicPort')}->{p.get('PrivatePort')}/{p.get('Type', 'tcp')}"
                        for p in c.get("Ports") or [] if p.get("PublicPort")})
        cpu, mem = None, 0
        usage = cgroup_usage(cid) if c.get("State") == "running" else None
        if usage:
            sample[cid] = usage[0]
            mem = usage[1]
            if cid in prev and dt > 0:
                cpu = round(max(0.0, (usage[0] - prev[cid]) / dt * 100.0), 1)
        labels = c.get("Labels") or {}
        rows.append([cid[:12], (c.get("Names") or ["?"])[0].lstrip("/")[:48], str(c.get("Image", ""))[:60],
                     str(c.get("State", "")), str(c.get("Status", ""))[:40], ",".join(ports)[:120],
                     cpu, mem, mem_total, str(labels.get("com.docker.compose.project", ""))[:32]])
    return runtime, rows, error, sample


def sign(payload, secret):
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def main():
    cfg = load_config()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    seq = 0
    static = {"os": os_name(), "kernel": platform.release(), "agent": AGENT_VERSION}
    reboot_checked, reboot = 0.0, 0

    def send(extra):
        nonlocal seq
        seq += 1
        payload = {"v": PROTOCOL, "id": cfg["id"], "port": cfg["ssh_port"], "ts": round(time.time(), 3),
                   "seq": seq, **extra}
        payload["sig"] = sign(payload, cfg["secret"])
        data = json.dumps(payload).encode()
        for hub in cfg["hubs"]:
            try:
                sock.sendto(data, hub)
            except OSError:
                pass

    def on_stop(_sig, _frame):
        send({"state": "stopping", "ssh": 0})
        sys.exit(0)

    signal.signal(signal.SIGTERM, on_stop)
    signal.signal(signal.SIGINT, on_stop)

    prev_idle, prev_total = cpu_times()
    prev_procs, prev_t = proc_sample(), time.monotonic()
    prev_ctr = {}
    time.sleep(1.0)
    while True:
        try:
            cur_procs, now = proc_sample(), time.monotonic()
            top = top_processes(prev_procs, cur_procs, now - prev_t)
            prev_procs, prev_t = cur_procs, now
            idle, total = cpu_times()
            dt = total - prev_total
            cpu = 100.0 * (1.0 - (idle - prev_idle) / dt) if dt > 0 else 0.0
            prev_idle, prev_total = idle, total
            mem_used, mem_total, swap_used, swap_total = meminfo()
            disk_used, disk_total = disk()
            extra = {}
            if time.monotonic() - reboot_checked > 300:   # cheap, but no need to stat /lib/modules every 3s
                reboot_checked, reboot = time.monotonic(), reboot_required()
            extra["reboot"] = reboot
            runtime, ctr_rows, ctr_err, prev_ctr = container_rows(prev_ctr, cfg["interval"], mem_total)
            if runtime:
                extra.update({"rt": runtime, "containers": ctr_rows})
            elif ctr_err:
                extra["containers_error"] = ctr_err[:200]
            send({
                **extra,
                "cpu": round(max(0.0, min(100.0, cpu)), 1),
                "mem_used": mem_used, "mem_total": mem_total,
                "swap_used": swap_used, "swap_total": swap_total,
                "disk_used": disk_used, "disk_total": disk_total,
                "load": [round(x, 2) for x in os.getloadavg()],
                "uptime": uptime(),
                # the hub may reach us through a forwarded port, so also accept a local sshd on 22
                "ssh": ssh_alive(cfg["ssh_port"]) or (ssh_alive(22) if cfg["ssh_port"] != 22 else 0),
                "procs": top,
                **static,
            })
        except Exception as exc:  # keep running no matter what
            print(f"sshm-agent: {exc}", file=sys.stderr)
        time.sleep(cfg["interval"])


if __name__ == "__main__":
    main()
