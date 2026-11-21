"""Build argv lists for ssh/sftp/ssh-copy-id. Never builds shell strings."""

from __future__ import annotations

import os
import shlex
import subprocess
import tempfile

from sshm.core.models import Server

# Shell snippet used to keep a terminal open on failure and to reset mouse
# reporting modes that a crashed TUI might have left enabled. Arguments are
# passed positionally, so no user value is ever interpolated into the script.
_HOLD_SCRIPT = r"""
title=$1; pause=$2; shift 2
if [ -n "$title" ]; then printf '\033[1;36m━━ %s ━━\033[0m\n\n' "$title"; fi
"$@"; rc=$?
printf '\033[?1000l\033[?1002l\033[?1003l\033[?1006l\033[?1015l'
if [ "$rc" -ne 0 ] || [ "$pause" = 1 ]; then
  if [ "$rc" -ne 0 ]; then printf '\n\033[1;31m✖ exited with status %s\033[0m' "$rc"; fi
  printf '\n\033[2mPress Enter to close…\033[0m'; read -r _
fi
exit "$rc"
"""


def base_options(server: Server, *, batch: bool = False) -> list[str]:
    opts = ["-p", str(server.port)]
    if server.key_path:
        opts += ["-i", server.key_path]
    if server.jump:
        opts += ["-J", server.jump]
    if batch:
        opts += ["-o", "BatchMode=yes", "-o", "ConnectTimeout=8"]
    return opts


def tmux_remote_command(session: str = "sshm") -> str:
    s = shlex.quote(session)
    return (
        f"if command -v tmux >/dev/null 2>&1; then exec tmux new-session -A -s {s}; "
        'else echo "tmux not installed on remote host - starting a normal shell"; exec "${SHELL:-sh}" -l; fi'
    )


def ssh_command(
    server: Server,
    *,
    tmux: bool | None = None,
    remote_command: str | None = None,
    tmux_session: str = "sshm",
    batch: bool = False,
) -> list[str]:
    use_tmux = server.tmux if tmux is None else tmux
    argv = ["ssh", *base_options(server, batch=batch)]
    if remote_command:
        argv += ["-t", server.target, "--", remote_command]
    elif use_tmux:
        argv += ["-t", server.target, "--", tmux_remote_command(tmux_session)]
    else:
        argv.append(server.target)
    return argv


def sftp_command(server: Server) -> list[str]:
    argv = ["sftp", "-P", str(server.port)]
    if server.key_path:
        argv += ["-i", server.key_path]
    if server.jump:
        argv += ["-J", server.jump]
    argv.append(server.target)
    return argv


def public_key_for(server: Server) -> str:
    """Pick the public key to push: <key>.pub if it exists, else ssh-copy-id's default."""
    if server.key_path and os.path.isfile(server.key_path + ".pub"):
        return server.key_path + ".pub"
    if server.key and server.key.endswith(".pub"):
        path = os.path.expanduser(server.key)
        if os.path.isfile(path):
            return path
    return ""


def copy_id_command(server: Server, pubkey: str = "") -> list[str]:
    argv = ["ssh-copy-id", "-p", str(server.port)]
    pub = pubkey or public_key_for(server)
    if pub:
        argv += ["-i", os.path.expanduser(pub)]
    if server.jump:
        argv += ["-o", f"ProxyJump={server.jump}"]
    argv.append(server.target)
    return argv


def hold(argv: list[str], title: str = "", pause: bool = False) -> list[str]:
    """Wrap *argv* so its terminal window stays open if it fails."""
    return ["sh", "-c", _HOLD_SCRIPT, "sshm", title, "1" if pause else "0", *argv]


def with_stdin_file(argv: list[str], path: str, *, delete: bool = True) -> list[str]:
    """Run *argv* with stdin redirected from *path* (optionally deleting it after)."""
    script = 'f=$1; shift; "$@" < "$f"; rc=$?; [ "$DEL" = 1 ] && rm -f "$f"; exit $rc'
    script = script.replace("$DEL", "1" if delete else "0")
    return ["sh", "-c", script, "sshm", path, *argv]


def run_capture(argv: list[str], timeout: float, input_text: str | None = None) -> subprocess.CompletedProcess:
    """Like ``subprocess.run(capture_output=True)`` but safe with programs that leave
    background children holding stdout/stderr (ssh ControlPersist masters, sshfs).

    Output goes to temp files, so we return as soon as *argv* itself exits.
    Raises ``FileNotFoundError`` / ``subprocess.TimeoutExpired`` like ``run``.
    """
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        if input_text is None:
            proc = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=err, timeout=timeout)
        else:
            proc = subprocess.run(argv, input=input_text.encode(), stdout=out, stderr=err, timeout=timeout)
        out.seek(0)
        err.seek(0)
        return subprocess.CompletedProcess(argv, proc.returncode, out.read().decode("utf-8", "replace"),
                                           err.read().decode("utf-8", "replace"))


def display(argv: list[str]) -> str:
    """Human-readable, copy-pasteable rendering of an argv list."""
    return shlex.join(argv)
