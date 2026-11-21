"""Deploy / remove the telemetry agent on a remote host over SSH.

The installer is a plain bash script fed to ``ssh host bash -s`` on stdin, so
the shared secret never appears on a command line on either machine.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import tempfile
from importlib import resources

from sshm.core import paths, sshcmd
from sshm.core.models import Server
from sshm.core.settings import Settings

SERVICE = "sshm-agent.service"


def agent_source() -> str:
    return resources.files("sshm.data").joinpath("sshm_agent.py").read_text(encoding="utf-8")


def bundled_version() -> str:
    m = re.search(r'^AGENT_VERSION = "([^"]+)"', agent_source(), re.M)
    return m.group(1) if m else "0"


def _ver(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) or (0,)


def is_outdated(reported: str) -> bool:
    """True if a running agent (reported version, "" for pre-3.3 agents) is older than the bundled one."""
    return _ver(reported or "0") < _ver(bundled_version())


def hub_address_for(host: str) -> str:
    """Local IP that routes toward *host* (UDP connect trick, sends nothing)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect((host, 9))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def build_installer(server: Server, settings: Settings, hub: str = "", interval: int = 3) -> str:
    config = {
        "hub": [hub or hub_address_for(server.host)],
        "port": settings.telemetry_port,
        "id": server.host,
        "ssh_port": server.port,
        "secret": settings.telemetry_secret,
        "interval": interval,
    }
    return f"""#!/usr/bin/env bash
set -euo pipefail
if ! command -v python3 >/dev/null 2>&1; then
  echo "✖ python3 is required on the remote host" >&2; exit 3
fi
umask 077
mkdir -p "$HOME/.local/lib/sshm-agent" "$HOME/.config/sshm-agent" "$HOME/.config/systemd/user"
cat > "$HOME/.local/lib/sshm-agent/sshm_agent.py" <<'SSHM_AGENT_EOF'
{agent_source().rstrip()}
SSHM_AGENT_EOF
cat > "$HOME/.config/sshm-agent/agent.json" <<'SSHM_CONF_EOF'
{json.dumps(config, indent=2)}
SSHM_CONF_EOF
cat > "$HOME/.config/systemd/user/{SERVICE}" <<'SSHM_UNIT_EOF'
[Unit]
Description=sshm telemetry agent
After=network-online.target

[Service]
ExecStart=/usr/bin/env python3 %h/.local/lib/sshm-agent/sshm_agent.py %h/.config/sshm-agent/agent.json
Restart=always
RestartSec=5
Nice=10

[Install]
WantedBy=default.target
SSHM_UNIT_EOF
# remove files left behind by sshm 2.x agents
rm -f "$HOME/.local/bin/sshm-agent.py" "$HOME/.local/share/sshm/sshm-agent.py"
if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
  systemctl --user daemon-reload
  systemctl --user enable {SERVICE} >/dev/null 2>&1
  systemctl --user restart {SERVICE}
  loginctl enable-linger "$USER" >/dev/null 2>&1 || \\
    echo "note: could not enable lingering; the agent only runs while you are logged in"
  echo "✔ sshm agent installed and running (systemd user service)"
else
  pkill -f 'sshm-agent/sshm_agent.py' 2>/dev/null || true
  nohup python3 "$HOME/.local/lib/sshm-agent/sshm_agent.py" "$HOME/.config/sshm-agent/agent.json" >/dev/null 2>&1 &
  echo "✔ sshm agent started with nohup (no systemd user session; it will not survive a reboot)"
fi
"""


def build_remover() -> str:
    return f"""#!/usr/bin/env bash
systemctl --user disable --now {SERVICE} >/dev/null 2>&1 || true
pkill -f 'sshm-agent/sshm_agent.py' 2>/dev/null || true
rm -rf "$HOME/.local/lib/sshm-agent" "$HOME/.config/sshm-agent"
rm -f "$HOME/.config/systemd/user/{SERVICE}" "$HOME/.local/bin/sshm-agent.py" "$HOME/.local/share/sshm/sshm-agent.py"
systemctl --user daemon-reload >/dev/null 2>&1 || true
echo "✔ sshm agent removed"
"""


STATUS_COMMAND = f"systemctl --user status {SERVICE} --no-pager || true"


def write_script(text: str) -> str:
    """Write a script to a private temp file and return its path."""
    fd, path = tempfile.mkstemp(prefix="agent-", suffix=".sh", dir=paths.runtime_dir())
    with os.fdopen(fd, "w") as fh:
        fh.write(text)
    os.chmod(path, 0o600)
    return path


def remote_script_argv(server: Server, *, batch: bool = False) -> list[str]:
    return ["ssh", *sshcmd.base_options(server, batch=batch), server.target, "bash", "-s"]


def run_noninteractive(server: Server, script: str, timeout: float = 60) -> subprocess.CompletedProcess:
    """Try running *script* with BatchMode (key auth only). Return code 255 = auth/connect failure."""
    return subprocess.run(
        remote_script_argv(server, batch=True),
        input=script,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
