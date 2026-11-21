//! Background ssh -L / -R / -D forwards, tracked in $XDG_RUNTIME_DIR/sshm/tunnels.json (shared with the Python TUI/CLI).
use super::model::{new_id, Server};
use super::{paths, sshcmd};
use serde_json::{json, Value};

#[derive(Clone, Debug, PartialEq)]
pub struct Spec { pub kind: char, pub listen_port: u16, pub dest_host: String, pub dest_port: u16, pub bind: String }
fn host_ok(h: &str) -> bool { !h.is_empty() && (h.chars().all(|c| c.is_alphanumeric() || "._-".contains(c)) || (h.starts_with('[') && h.ends_with(']'))) }
impl Spec {
    /// [bind:]port[:host:port]
    pub fn parse(kind: char, text: &str) -> Result<Spec, String> {
        let kind = kind.to_ascii_uppercase(); if !"LRD".contains(kind) { return Err("Tunnel type must be L, R or D".into()); }
        let t = text.trim(); let bad = || format!("Cannot parse forward '{t}' (expected [bind:]port[:host:port])");
        // split on ':' outside [ ]
        let mut parts = vec![]; let mut cur = String::new(); let mut depth = 0;
        for c in t.chars() { match c { '[' => { depth += 1; cur.push(c) } ']' => { depth -= 1; cur.push(c) } ':' if depth == 0 => parts.push(std::mem::take(&mut cur)), _ => cur.push(c) } }
        parts.push(cur);
        let num = |s: &str| s.parse::<u32>().ok().filter(|p| (1..=65535).contains(p)).map(|p| p as u16);
        let (bind, lport, dest) = match parts.len() {
            1 => (String::new(), parts[0].clone(), None), 2 => (parts[0].clone(), parts[1].clone(), None),
            3 => (String::new(), parts[0].clone(), Some((parts[1].clone(), parts[2].clone()))), 4 => (parts[0].clone(), parts[1].clone(), Some((parts[2].clone(), parts[3].clone()))),
            _ => return Err(bad()),
        };
        if !lport.chars().all(|c| c.is_ascii_digit()) || lport.is_empty() || (!bind.is_empty() && !host_ok(&bind)) { return Err(bad()); }
        let lp = num(&lport).ok_or("Ports must be 1-65535")?;
        if kind == 'D' { if dest.is_some() { return Err("Dynamic (SOCKS) forwards take only a port".into()); } return Ok(Spec { kind, listen_port: lp, dest_host: String::new(), dest_port: 0, bind }); }
        let (h, p) = dest.ok_or("Local/remote forwards need port:host:port")?;
        if !host_ok(&h) || !p.chars().all(|c| c.is_ascii_digit()) { return Err(bad()); }
        Ok(Spec { kind, listen_port: lp, dest_host: h, dest_port: num(&p).ok_or("Ports must be 1-65535")?, bind })
    }
    pub fn arg(&self) -> String { let b = if self.bind.is_empty() { String::new() } else { format!("{}:", self.bind) }; if self.kind == 'D' { format!("{b}{}", self.listen_port) } else { format!("{b}{}:{}:{}", self.listen_port, self.dest_host, self.dest_port) } }
    pub fn describe(&self, name: &str) -> String {
        match self.kind { 'D' => format!("SOCKS5 proxy on localhost:{} via {name}", self.listen_port), 'L' => format!("localhost:{} → {}:{} (via {name})", self.listen_port, self.dest_host, self.dest_port),
            _ => format!("{name}:{} → {}:{} (on this machine)", self.listen_port, self.dest_host, self.dest_port) }
    }
}
#[derive(Clone, Debug)]
pub struct Tunnel { pub id: String, pub server_id: String, pub server_name: String, pub kind: String, pub spec: String, pub pid: i32, pub started: f64 }
impl Tunnel { pub fn description(&self) -> String { Spec::parse(self.kind.chars().next().unwrap_or('L'), &self.spec).map(|s| s.describe(&self.server_name)).unwrap_or_else(|_| format!("-{} {}", self.kind, self.spec)) } }

fn alive(pid: i32) -> bool {
    if unsafe { libc::kill(pid, 0) } != 0 { return false; }
    match std::fs::read(format!("/proc/{pid}/cmdline")) { Ok(b) => b.split(|c| *c == 0).next().map(|a| std::path::Path::new(&*String::from_utf8_lossy(a)).file_name().map_or(false, |n| n == "ssh")).unwrap_or(false), Err(_) => true }
}
fn read() -> Vec<Tunnel> {
    let v: Vec<Value> = std::fs::read_to_string(paths::tunnels_file()).ok().and_then(|t| serde_json::from_str(&t).ok()).unwrap_or_default();
    v.iter().filter_map(|t| Some(Tunnel { id: t["id"].as_str()?.into(), server_id: t["server_id"].as_str()?.into(), server_name: t["server_name"].as_str().unwrap_or("").into(), kind: t["kind"].as_str()?.into(),
        spec: t["spec"].as_str()?.into(), pid: t["pid"].as_i64()? as i32, started: t["started"].as_f64().unwrap_or(0.0) })).collect()
}
fn write(ts: &[Tunnel]) {
    let v: Vec<Value> = ts.iter().map(|t| json!({"id": t.id, "server_id": t.server_id, "server_name": t.server_name, "kind": t.kind, "spec": t.spec, "pid": t.pid, "started": t.started})).collect();
    let _ = paths::atomic_write(&paths::tunnels_file(), serde_json::to_string_pretty(&v).unwrap_or_default().as_bytes(), 0o600);
}
pub fn list() -> Vec<Tunnel> {
    let f = paths::tunnels_file(); let _l = paths::lock(&f);
    let all = read(); let live: Vec<Tunnel> = all.iter().filter(|t| alive(t.pid)).cloned().collect();
    if live.len() != all.len() { write(&live); }
    live
}
pub fn start(s: &Server, spec: &Spec) -> Result<Tunnel, String> {
    if spec.kind != 'R' { if let Some(t) = list().iter().find(|t| t.kind.starts_with(spec.kind) && Spec::parse(spec.kind, &t.spec).map_or(false, |x| x.listen_port == spec.listen_port)) { return Err(format!("Port {} is already forwarded ({})", spec.listen_port, t.server_name)); } }
    let mut argv = vec!["ssh".to_string()]; argv.extend(sshcmd::base_options(s, true));
    argv.extend(["-N", "-T", "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3"].map(String::from));
    argv.push(format!("-{}", spec.kind)); argv.push(spec.arg()); argv.push(s.target());
    let errp = paths::runtime_dir().join(format!(".tun-{}", paths::random_hex(4)));
    let ef = std::fs::File::create(&errp).map_err(|e| e.to_string())?;
    use std::os::unix::process::CommandExt;
    let mut c = std::process::Command::new("ssh"); c.args(&argv[1..]).stdin(std::process::Stdio::null()).stdout(std::process::Stdio::null()).stderr(ef);
    unsafe { c.pre_exec(|| { libc::setsid(); Ok(()) }); }
    let mut child = c.spawn().map_err(|e| format!("could not run ssh: {e}"))?;
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(3);
    while std::time::Instant::now() < deadline {
        if let Ok(Some(st)) = child.try_wait() {
            let err = std::fs::read_to_string(&errp).unwrap_or_default(); let _ = std::fs::remove_file(&errp);
            let mut hint = err.trim().lines().last().map(|s| s.to_string()).unwrap_or_else(|| format!("ssh exited with status {}", st.code().unwrap_or(-1)));
            if hint.contains("Permission denied") || hint.contains("publickey") { hint.push_str(" — background tunnels need key authentication (push your key first)"); }
            return Err(hint);
        }
        std::thread::sleep(std::time::Duration::from_millis(100));
    }
    let _ = std::fs::remove_file(&errp);
    let pid = child.id() as i32; std::thread::spawn(move || { let _ = child.wait(); });   // reap when it ends
    let t = Tunnel { id: new_id(), server_id: s.id.clone(), server_name: s.name.clone(), kind: spec.kind.to_string(), spec: spec.arg(), pid, started: paths::now() };
    let f = paths::tunnels_file(); let _l = paths::lock(&f); let mut all = read(); all.push(t.clone()); write(&all);
    Ok(t)
}
pub fn stop(id: &str) -> bool {
    let f = paths::tunnels_file(); let _l = paths::lock(&f);
    let all = read(); let Some(t) = all.iter().find(|t| t.id == id).cloned() else { return false };
    if alive(t.pid) { unsafe { libc::kill(t.pid, libc::SIGTERM); } }
    write(&all.into_iter().filter(|x| x.id != t.id).collect::<Vec<_>>()); true
}
#[cfg(test)]
mod tests { use super::*;
    #[test] fn specs() { assert_eq!(Spec::parse('L', "8080:localhost:80").unwrap().arg(), "8080:localhost:80"); assert_eq!(Spec::parse('D', "1080").unwrap().arg(), "1080");
        assert_eq!(Spec::parse('L', "127.0.0.1:8080:db:5432").unwrap().bind, "127.0.0.1"); assert!(Spec::parse('D', "1080:h:1").is_err()); assert!(Spec::parse('L', "8080").is_err()); }
}
