"""Remote process listing and control over SSH.

``fetch()`` runs ``ps`` on the server non-interactively (key auth) and parses
the result. Connections are multiplexed with an OpenSSH ControlMaster socket
in the runtime directory, so refreshing every few seconds reuses one session
instead of doing a full handshake each time.

Works with GNU procps (most distros) and falls back to BusyBox ``ps``
(Alpine, OpenWrt, many NAS boxes), where CPU/memory columns are unavailable.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import asdict, dataclass

from sshm.core import paths, sshcmd
from sshm.core.models import Server
from sshm.core.telemetry import format_duration

SORT_KEYS = ("cpu", "mem", "pid", "name", "user", "time")

# Markers tell the parser which ps flavour answered. Wrapped in `sh -c` so it
# also works when the remote login shell is fish, nushell, etc.
_PS_SCRIPT = (
    'out=$(LC_ALL=C ps -eo pid=,user:32=,pcpu=,pmem=,rss=,etimes=,comm:64=,args= 2>/dev/null) '
    '&& [ -n "$out" ] && { echo SSHM_GNU; printf "%s\\n" "$out"; exit 0; }; '
    "echo SSHM_BB; ps -o pid,user,vsz,comm,args 2>/dev/null || ps"
)
REMOTE_PS = "sh -c " + shlex.quote(_PS_SCRIPT)


class ProcError(RuntimeError):
    pass


@dataclass
class Process:
    pid: int
    user: str
    name: str
    command: str
    cpu: float | None = None      # percent of one core
    mem: float | None = None      # percent of RAM
    rss: int = 0                  # bytes
    elapsed: int | None = None    # seconds since start

    @property
    def rss_label(self) -> str:
        return human_bytes(self.rss) if self.rss else "--"

    @property
    def elapsed_label(self) -> str:
        return format_duration(self.elapsed) if self.elapsed is not None else "--"

    def to_dict(self) -> dict:
        return asdict(self)


def human_bytes(n: float) -> str:
    for unit in ("B", "K", "M", "G", "T"):
        if abs(n) < 1024 or unit == "T":
            return f"{n:.0f}{unit}" if unit in ("B", "K") else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}T"


def parse(output: str) -> list[Process]:
    lines = output.splitlines()
    if not lines:
        return []
    flavour, rows = lines[0].strip(), lines[1:]
    procs: list[Process] = []
    if flavour == "SSHM_GNU":
        for line in rows:
            parts = line.split(None, 7)
            if len(parts) < 7 or not parts[0].isdigit():
                continue
            pid, user, pcpu, pmem, rss, etimes, comm = parts[:7]
            args = parts[7] if len(parts) > 7 else comm
            procs.append(Process(int(pid), user, comm, args, _f(pcpu), _f(pmem),
                                 int(rss) * 1024 if rss.isdigit() else 0,
                                 int(etimes) if etimes.isdigit() else None))
    else:
        for line in rows:
            parts = line.split(None, 4)
            if not parts or not parts[0].isdigit():
                continue
            pid, user = int(parts[0]), parts[1] if len(parts) > 1 else "?"
            if len(parts) >= 5:      # pid user vsz comm args
                name, cmd = parts[3], parts[4]
            else:                    # bare `ps`: PID USER TIME COMMAND
                name = cmd = parts[-1]
            procs.append(Process(pid, user, name, cmd))
    return procs


def _f(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def sort(procs: list[Process], key: str = "cpu") -> list[Process]:
    if key == "pid":
        return sorted(procs, key=lambda p: p.pid)
    if key == "name":
        return sorted(procs, key=lambda p: (p.name.lower(), p.pid))
    if key == "user":
        return sorted(procs, key=lambda p: (p.user, p.pid))
    if key == "mem":
        return sorted(procs, key=lambda p: (-(p.mem or 0), -p.rss, p.pid))
    if key == "time":
        return sorted(procs, key=lambda p: (-(p.elapsed or 0), p.pid))
    return sorted(procs, key=lambda p: (-(p.cpu or 0), -(p.mem or 0), p.pid))


def filter_procs(procs: list[Process], query: str) -> list[Process]:
    q = query.strip().lower()
    if not q:
        return procs
    if q.isdigit():
        exact = [p for p in procs if p.pid == int(q)]
        if exact:
            return exact
    return [p for p in procs if q in p.command.lower() or q in p.name.lower() or q == str(p.pid) or q == p.user]


def _mux_options() -> list[str]:
    control = paths.runtime_dir() / "cm-%C"
    return ["-o", "ControlMaster=auto", "-o", f"ControlPath={control}", "-o", "ControlPersist=120"]


def remote_argv(server: Server, remote: str) -> list[str]:
    return ["ssh", *sshcmd.base_options(server, batch=True), *_mux_options(), server.target, remote]


def _run(server: Server, remote: str, timeout: float) -> subprocess.CompletedProcess:
    # run_capture (not pipes): the first call forks a ControlPersist master that
    # inherits stdout/stderr, and pipe reads would block until it exits.
    try:
        return sshcmd.run_capture(remote_argv(server, remote), timeout)
    except FileNotFoundError:
        raise ProcError("ssh is not installed") from None
    except subprocess.TimeoutExpired:
        raise ProcError(f"{server.name} did not answer within {timeout:.0f}s") from None


def _explain(res: subprocess.CompletedProcess) -> str:
    err = (res.stderr or "").strip().splitlines()
    last = next((ln for ln in reversed(err) if ln.strip()), f"ssh exited with status {res.returncode}")
    if res.returncode == 255 and ("Permission denied" in last or "publickey" in last or "password" in last):
        return f"{last} — live process lists need key-based login (use Push SSH key), or open htop instead"
    return last


def fetch(server: Server, timeout: float = 12.0) -> list[Process]:
    res = _run(server, REMOTE_PS, timeout)
    if res.returncode != 0 and not res.stdout.startswith("SSHM_"):
        raise ProcError(_explain(res))
    procs = parse(res.stdout)
    if not procs:
        raise ProcError("ps returned no processes")
    return procs


def kill(server: Server, pid: int, force: bool = False, timeout: float = 10.0) -> str:
    """Send SIGTERM (or SIGKILL). Returns a human message; raises ProcError on failure."""
    sig = "KILL" if force else "TERM"
    res = _run(server, f"kill -s {sig} {int(pid)}", timeout)
    if res.returncode != 0:
        msg = _explain(res)
        if "not permitted" in msg.lower():
            msg += " — the process belongs to another user (use 'sudo kill' in a terminal)"
        raise ProcError(msg)
    return f"Sent SIG{sig} to {pid} on {server.name}"


def sudo_kill_argv(server: Server, pid: int, force: bool = False) -> list[str]:
    return sshcmd.ssh_command(server, remote_command=f"sudo kill -s {'KILL' if force else 'TERM'} {int(pid)}")


def top_argv(server: Server) -> list[str]:
    """Interactive htop (or top) in a terminal."""
    remote = "if command -v htop >/dev/null 2>&1; then exec htop; else exec top; fi"
    return sshcmd.ssh_command(server, remote_command=remote)


def close_master(server: Server) -> None:
    """Shut down the multiplexed connection (best effort)."""
    argv = ["ssh", *sshcmd.base_options(server), *_mux_options(), "-O", "exit", server.target]
    try:
        subprocess.run(argv, capture_output=True, timeout=3, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        pass


def describe(p: Process) -> str:
    return f"{p.name} (pid {p.pid}, {p.user}): {shlex.quote(p.command)[:120]}"
