//! Run one command on many servers, back up / restore servers, and ~/.ssh/config import / export.
use super::model::Server;
use super::store::Store;
use super::{paths, procs, sshcmd};
use serde_json::{json, Value};

#[derive(Clone, Debug)]
pub struct RunResult { pub server: Server, pub code: Option<i32>, pub stdout: String, pub stderr: String, pub seconds: f64 }
impl RunResult {
    pub fn ok(&self) -> bool { self.code == Some(0) }
    pub fn summary(&self) -> String {
        match self.code {
            None => self.stderr.trim().lines().last().unwrap_or("did not run").to_string(),
            Some(255) if self.stdout.is_empty() => procs::explain(&sshcmd::Output { code: Some(255), stdout: String::new(), stderr: self.stderr.clone() }),
            Some(c) => { let t = if self.stdout.trim().is_empty() { self.stderr.trim() } else { self.stdout.trim() }; t.lines().last().map(|l| l.chars().take(160).collect()).unwrap_or_else(|| format!("exit {c}")) }
        }
    }
}
pub fn run_one(s: &Server, cmd: &str, timeout: f64) -> RunResult {
    let t0 = std::time::Instant::now();
    match sshcmd::run_capture(&procs::remote_argv(s, cmd), timeout) {
        Ok(o) => RunResult { server: s.clone(), code: o.code, stdout: o.stdout, stderr: o.stderr, seconds: t0.elapsed().as_secs_f64() },
        Err(e) => RunResult { server: s.clone(), code: None, stdout: String::new(), stderr: e, seconds: t0.elapsed().as_secs_f64() },
    }
}
pub const BACKUP_FORMAT: &str = "sshm-backup";
pub fn export_backup(servers: &[Server], path: &std::path::Path) -> Result<usize, String> {
    let d = json!({"format": BACKUP_FORMAT, "version": 1, "sshm": format!("desktop {}", env!("CARGO_PKG_VERSION")), "exported": paths::now() as i64, "servers": servers.iter().map(|s| s.to_json()).collect::<Vec<_>>()});
    std::fs::write(path, serde_json::to_string_pretty(&d).unwrap_or_default() + "\n").map_err(|e| e.to_string())?; Ok(servers.len())
}
/// merge (or replace) servers from a backup: (added, updated)
pub fn import_backup(store: &mut Store, path: &std::path::Path, replace: bool) -> Result<(usize, usize), String> {
    let d: Value = serde_json::from_str(&std::fs::read_to_string(path).map_err(|e| format!("cannot read {}: {e}", path.display()))?).map_err(|e| format!("cannot read {}: {e}", path.display()))?;
    if d["format"].as_str() != Some(BACKUP_FORMAT) { return Err(format!("{} is not an sshm backup", path.display())); }
    let incoming: Vec<Server> = d["servers"].as_array().map(|a| a.iter().filter_map(Server::from_json).filter(|s| !s.name.is_empty() && !s.host.is_empty()).collect()).unwrap_or_default();
    if replace { store.servers.clear(); }
    let (mut added, mut updated) = (0, 0);
    for mut s in incoming {
        let same = store.get(&s.id).or_else(|| store.by_name(&s.name)).map(|x| x.id.clone());
        match same { Some(id) => { s.id = id.clone(); if let Some(x) = store.servers.iter_mut().find(|x| x.id == id) { *x = s; } updated += 1; } None => { store.servers.push(s); added += 1; } }
    }
    store.save()?; Ok((added, updated))
}
fn tokens(line: &str) -> Option<(String, Vec<String>)> {
    let l = line.trim(); if l.is_empty() || l.starts_with('#') { return None; }
    let (k, rest) = match l.find(|c: char| c == '=' || c.is_whitespace()) { Some(i) => (&l[..i], l[i + 1..].trim_start_matches(|c: char| c == '=' || c.is_whitespace())), None => (l, "") };
    let mut vals = vec![]; let mut cur = String::new(); let mut q: Option<char> = None;
    for c in rest.chars() { match (q, c) { (None, '#') => break, (None, '"' | '\'') => q = Some(c), (Some(x), c) if c == x => q = None, (None, c) if c.is_whitespace() => { if !cur.is_empty() { vals.push(std::mem::take(&mut cur)); } } _ => cur.push(c) } }
    if !cur.is_empty() { vals.push(cur); }
    Some((k.trim().to_lowercase(), vals))
}
fn parse_config(path: &std::path::Path, depth: u32, out: &mut Vec<(String, std::collections::HashMap<String, String>)>) {
    let Ok(text) = std::fs::read_to_string(path) else { return };
    let mut current: Vec<usize> = vec![]; let mut in_match = false;
    for raw in text.lines() {
        let Some((k, vals)) = tokens(raw) else { continue };
        if k == "include" && depth < 8 {
            for pat in &vals { let p = paths::expand(pat); let p = if p.is_absolute() { p } else { paths::home().join(".ssh").join(p) }; for f in glob(&p) { parse_config(&f, depth + 1, out); } }
            continue;
        }
        if k == "host" { in_match = false; current = vec![]; for v in vals.iter().filter(|v| !v.contains(['*', '?', '!'])) { out.push((v.clone(), Default::default())); current.push(out.len() - 1); } continue; }
        if k == "match" { in_match = true; current.clear(); continue; }
        if in_match || vals.is_empty() { continue; }
        for &i in &current { out[i].1.entry(k.clone()).or_insert_with(|| vals[0].clone()); }
    }
}
/// minimal glob for Include: "*" and "?" in the last path part
fn glob(p: &std::path::Path) -> Vec<std::path::PathBuf> {
    let name = p.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_default();
    if !name.contains(['*', '?']) { return if p.exists() { vec![p.to_path_buf()] } else { vec![] }; }
    let dir = p.parent().unwrap_or(std::path::Path::new("."));
    fn m(pat: &[char], s: &[char]) -> bool { match (pat.first(), s.first()) { (None, None) => true, (Some('*'), _) => m(&pat[1..], s) || (!s.is_empty() && m(pat, &s[1..])), (Some('?'), Some(_)) => m(&pat[1..], &s[1..]), (Some(a), Some(b)) if a == b => m(&pat[1..], &s[1..]), _ => false } }
    let pc: Vec<char> = name.chars().collect();
    let mut v: Vec<std::path::PathBuf> = std::fs::read_dir(dir).map(|rd| rd.flatten().map(|e| e.path()).filter(|f| m(&pc, &f.file_name().map(|n| n.to_string_lossy().chars().collect::<Vec<_>>()).unwrap_or_default())).collect()).unwrap_or_default();
    v.sort(); v
}
/// hosts from ~/.ssh/config not already saved (by name or host:port)
pub fn import_ssh_config(existing: &[Server]) -> Vec<Server> {
    let mut entries = vec![]; parse_config(&paths::home().join(".ssh/config"), 0, &mut entries);
    let mut names: std::collections::HashSet<String> = existing.iter().map(|s| s.name.to_lowercase()).collect();
    let mut eps: std::collections::HashSet<(String, u16)> = existing.iter().map(|s| (s.host.to_lowercase(), s.port)).collect();
    let mut out = vec![];
    for (alias, o) in entries {
        let jump = o.get("proxyjump").cloned().unwrap_or_default();
        let s = Server { name: alias.clone(), host: o.get("hostname").cloned().unwrap_or(alias.clone()), user: o.get("user").cloned().unwrap_or_default(), port: o.get("port").and_then(|p| p.parse().ok()).unwrap_or(22),
            key: o.get("identityfile").cloned().unwrap_or_default(), jump: if jump.eq_ignore_ascii_case("none") { String::new() } else { jump }, tag: "ssh_config".into(), ..Default::default() };
        if names.contains(&s.name.to_lowercase()) || eps.contains(&(s.host.to_lowercase(), s.port)) { continue; }
        names.insert(s.name.to_lowercase()); eps.insert((s.host.to_lowercase(), s.port)); out.push(s);
    }
    out
}
pub fn export_ssh_config(servers: &[Server]) -> String {
    let mut blocks = vec!["# Generated by sshm — paste into ~/.ssh/config".to_string()];
    for s in servers {
        let alias = s.name.split_whitespace().collect::<Vec<_>>().join("-"); let alias = if alias.is_empty() { s.host.clone() } else { alias };
        let mut l = vec![format!("Host {alias}"), format!("    HostName {}", s.host)];
        if !s.user.is_empty() { l.push(format!("    User {}", s.user)); } if s.port != 22 { l.push(format!("    Port {}", s.port)); }
        if !s.key.is_empty() { l.push(format!("    IdentityFile {}", s.key)); } if !s.jump.is_empty() { l.push(format!("    ProxyJump {}", s.jump)); }
        blocks.push(l.join("\n"));
    }
    blocks.join("\n\n") + "\n"
}
