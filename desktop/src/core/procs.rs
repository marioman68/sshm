//! Remote process list over a multiplexed SSH connection (GNU procps, BusyBox fallback).
use super::model::Server;
use super::sshcmd::{self, Output};

const PS_SCRIPT: &str = r#"out=$(LC_ALL=C ps -eo pid=,user:32=,pcpu=,pmem=,rss=,etimes=,comm:64=,args= 2>/dev/null) && [ -n "$out" ] && { echo SSHM_GNU; printf "%s\n" "$out"; exit 0; }; echo SSHM_BB; ps -o pid,user,vsz,comm,args 2>/dev/null || ps"#;

#[derive(Clone, Debug)]
pub struct Process { pub pid: i64, pub user: String, pub name: String, pub command: String, pub cpu: Option<f64>, pub mem: Option<f64>, pub rss: u64, pub elapsed: Option<u64> }
impl Process {
    pub fn rss_label(&self) -> String { if self.rss > 0 { super::telemetry::human_bytes(self.rss as f64) } else { "--".into() } }
    pub fn elapsed_label(&self) -> String { self.elapsed.map(super::telemetry::format_duration).unwrap_or_else(|| "--".into()) }
}
pub fn parse(out: &str) -> Vec<Process> {
    let mut lines = out.lines(); let Some(flavour) = lines.next() else { return vec![] };
    let mut v = vec![];
    if flavour.trim() == "SSHM_GNU" {
        for l in lines {
            let p: Vec<&str> = l.split_whitespace().collect(); if p.len() < 7 || !p[0].chars().all(|c| c.is_ascii_digit()) { continue; }
            let args = if p.len() > 7 { p[7..].join(" ") } else { p[6].to_string() };
            v.push(Process { pid: p[0].parse().unwrap_or(0), user: p[1].into(), name: p[6].into(), command: args, cpu: p[2].parse().ok(), mem: p[3].parse().ok(), rss: p[4].parse::<u64>().map(|x| x * 1024).unwrap_or(0), elapsed: p[5].parse().ok() });
        }
    } else {
        for l in lines {
            let p: Vec<&str> = l.split_whitespace().collect(); if p.is_empty() || !p[0].chars().all(|c| c.is_ascii_digit()) { continue; }
            let (name, cmd) = if p.len() >= 5 { (p[3].to_string(), p[4..].join(" ")) } else { (p[p.len() - 1].to_string(), p[p.len() - 1].to_string()) };
            v.push(Process { pid: p[0].parse().unwrap_or(0), user: p.get(1).unwrap_or(&"?").to_string(), name, command: cmd, cpu: None, mem: None, rss: 0, elapsed: None });
        }
    }
    v
}
pub fn mux_options() -> Vec<String> {
    let cp = super::paths::runtime_dir().join("cm-%C");
    vec!["-o".into(), "ControlMaster=auto".into(), "-o".into(), format!("ControlPath={}", cp.display()), "-o".into(), "ControlPersist=120".into()]
}
pub fn remote_argv(s: &Server, remote: &str) -> Vec<String> { let mut a = vec!["ssh".to_string()]; a.extend(sshcmd::base_options(s, true)); a.extend(mux_options()); a.push(s.target()); a.push(remote.into()); a }
pub fn explain(o: &Output) -> String {
    let last = o.stderr.lines().rev().find(|l| !l.trim().is_empty()).map(|s| s.trim().to_string()).unwrap_or_else(|| format!("ssh exited with status {}", o.code.unwrap_or(-1)));
    if o.code == Some(255) && (last.contains("Permission denied") || last.contains("publickey") || last.contains("password")) {
        return format!("{last} — this needs key-based login (use Push SSH key), or open htop instead");
    }
    last
}
pub fn fetch(s: &Server) -> Result<Vec<Process>, String> {
    let o = sshcmd::run_capture(&remote_argv(s, &format!("sh -c {}", sshcmd::quote(PS_SCRIPT))), 12.0)?;
    if o.code != Some(0) && !o.stdout.starts_with("SSHM_") { return Err(explain(&o)); }
    let v = parse(&o.stdout); if v.is_empty() { Err("ps returned no processes".into()) } else { Ok(v) }
}
pub fn kill(s: &Server, pid: i64, force: bool) -> Result<String, String> {
    let sig = if force { "KILL" } else { "TERM" };
    let o = sshcmd::run_capture(&remote_argv(s, &format!("kill -s {sig} {pid}")), 10.0)?;
    if o.code != Some(0) { let mut m = explain(&o); if m.to_lowercase().contains("not permitted") { m.push_str(" — it belongs to another user (use sudo kill in a terminal)"); } return Err(m); }
    Ok(format!("Sent SIG{sig} to {pid} on {}", s.name))
}
pub fn sudo_kill_argv(s: &Server, pid: i64, force: bool, session: &str) -> Vec<String> { sshcmd::ssh_command(s, Some(false), Some(&format!("sudo kill -s {} {pid}", if force { "KILL" } else { "TERM" })), session) }
pub fn top_argv(s: &Server, session: &str) -> Vec<String> { sshcmd::ssh_command(s, Some(false), Some("if command -v htop >/dev/null 2>&1; then exec htop; else exec top; fi"), session) }
#[cfg(test)]
mod tests { use super::*;
    #[test] fn gnu() { let p = parse("SSHM_GNU\n  42 root   1.5  0.3  2048  3600 sshd /usr/sbin/sshd -D\n"); assert_eq!(p[0].pid, 42); assert_eq!(p[0].rss, 2097152); assert_eq!(p[0].command, "/usr/sbin/sshd -D"); }
}
