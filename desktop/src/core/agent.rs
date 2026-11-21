//! Deploy / remove the telemetry agent. The agent itself stays the Python file the Python package ships
//! (it runs on the remote host); the installer script goes over `ssh host bash -s` stdin, so the secret never hits a command line.
use super::model::Server;
use super::settings::Settings;
use super::{paths, sshcmd};

pub const SERVICE: &str = "sshm-agent.service";
pub const AGENT_SOURCE: &str = include_str!("../../../src/sshm/data/sshm_agent.py");
pub const STATUS_COMMAND: &str = "systemctl --user status sshm-agent.service --no-pager || true";

pub fn bundled_version() -> String { AGENT_SOURCE.lines().find_map(|l| l.strip_prefix("AGENT_VERSION = \"").map(|r| r.trim_end_matches('"').to_string())).unwrap_or_else(|| "0".into()) }
fn ver(v: &str) -> Vec<u32> { let n: Vec<u32> = v.split(|c: char| !c.is_ascii_digit()).filter(|s| !s.is_empty()).take(3).filter_map(|s| s.parse().ok()).collect(); if n.is_empty() { vec![0] } else { n } }
pub fn is_outdated(reported: &str) -> bool { ver(if reported.is_empty() { "0" } else { reported }) < ver(&bundled_version()) }
pub fn hub_address_for(host: &str) -> String {
    std::net::UdpSocket::bind("0.0.0.0:0").ok().and_then(|s| { s.connect((host, 9)).ok()?; s.local_addr().ok() }).map(|a| a.ip().to_string()).unwrap_or_else(|| "127.0.0.1".into())
}
pub fn build_installer(s: &Server, st: &Settings) -> String {
    let cfg = serde_json::json!({"hub": [hub_address_for(&s.host)], "port": st.telemetry_port, "id": s.host, "ssh_port": s.port, "secret": st.telemetry_secret, "interval": 3});
    format!(r#"#!/usr/bin/env bash
set -euo pipefail
if ! command -v python3 >/dev/null 2>&1; then
  echo "✖ python3 is required on the remote host" >&2; exit 3
fi
umask 077
mkdir -p "$HOME/.local/lib/sshm-agent" "$HOME/.config/sshm-agent" "$HOME/.config/systemd/user"
cat > "$HOME/.local/lib/sshm-agent/sshm_agent.py" <<'SSHM_AGENT_EOF'
{agent}
SSHM_AGENT_EOF
cat > "$HOME/.config/sshm-agent/agent.json" <<'SSHM_CONF_EOF'
{conf}
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
rm -f "$HOME/.local/bin/sshm-agent.py" "$HOME/.local/share/sshm/sshm-agent.py"
if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
  systemctl --user daemon-reload
  systemctl --user enable {SERVICE} >/dev/null 2>&1
  systemctl --user restart {SERVICE}
  loginctl enable-linger "$USER" >/dev/null 2>&1 || \
    echo "note: could not enable lingering; the agent only runs while you are logged in"
  echo "✔ sshm agent installed and running (systemd user service)"
else
  pkill -f 'sshm-agent/sshm_agent.py' 2>/dev/null || true
  nohup python3 "$HOME/.local/lib/sshm-agent/sshm_agent.py" "$HOME/.config/sshm-agent/agent.json" >/dev/null 2>&1 &
  echo "✔ sshm agent started with nohup (no systemd user session; it will not survive a reboot)"
fi
"#, agent = AGENT_SOURCE.trim_end(), conf = serde_json::to_string_pretty(&cfg).unwrap_or_default())
}
pub fn build_remover() -> String {
    format!("#!/usr/bin/env bash\nsystemctl --user disable --now {SERVICE} >/dev/null 2>&1 || true\npkill -f 'sshm-agent/sshm_agent.py' 2>/dev/null || true\nrm -rf \"$HOME/.local/lib/sshm-agent\" \"$HOME/.config/sshm-agent\"\nrm -f \"$HOME/.config/systemd/user/{SERVICE}\" \"$HOME/.local/bin/sshm-agent.py\" \"$HOME/.local/share/sshm/sshm-agent.py\"\nsystemctl --user daemon-reload >/dev/null 2>&1 || true\necho \"✔ sshm agent removed\"\n")
}
pub fn remote_script_argv(s: &Server, batch: bool) -> Vec<String> { let mut a = vec!["ssh".to_string()]; a.extend(sshcmd::base_options(s, batch)); a.push(s.target()); a.push("bash".into()); a.push("-s".into()); a }
/// private temp file for the terminal fallback (deleted by the shell wrapper after use)
pub fn write_script(text: &str) -> Result<String, String> {
    let p = paths::runtime_dir().join(format!("agent-{}.sh", paths::random_hex(6)));
    paths::atomic_write(&p, text.as_bytes(), 0o600).map_err(|e| e.to_string())?; Ok(p.to_string_lossy().into_owned())
}
pub fn run_noninteractive(s: &Server, script: &str) -> Result<sshcmd::Output, String> { sshcmd::run_capture_input(&remote_script_argv(s, true), 60.0, Some(script)) }
