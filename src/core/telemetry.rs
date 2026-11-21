//! Signed UDP telemetry from sshm agents: the same packet format, HMAC check and cache file
//! ($XDG_RUNTIME_DIR/sshm/telemetry.json) as the Python version, so the TUI/CLI can read what this process receives.
use super::paths;
use hmac::{Hmac, Mac};
use serde_json::{Map, Value};
use sha2::Sha256;
use std::collections::HashMap;
use std::net::UdpSocket;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

pub const PROTOCOL: i64 = 2;
pub const MAX_CLOCK_SKEW: f64 = 300.0;
pub const FRESH_AFTER: f64 = 12.0;
pub const HISTORY: usize = 60;

/// json.dumps(body, sort_keys=True, separators=(",", ":")) with Python's default ensure_ascii, minus "sig".
/// Numbers keep the exact text the agent sent (serde_json arbitrary_precision), so the bytes match what it signed.
pub fn canonical(payload: &Map<String, Value>) -> String {
    let mut out = String::new();
    let mut body = payload.clone(); body.remove("sig");
    write_value(&Value::Object(body), &mut out); out
}
fn write_value(v: &Value, out: &mut String) {
    match v {
        Value::Null => out.push_str("null"), Value::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
        Value::Number(n) => out.push_str(&n.to_string()),
        Value::String(s) => write_str(s, out),
        Value::Array(a) => { out.push('['); for (i, x) in a.iter().enumerate() { if i > 0 { out.push(','); } write_value(x, out); } out.push(']'); }
        Value::Object(m) => {   // serde_json's Map is a BTreeMap: keys come out sorted by code point, like Python
            out.push('{');
            for (i, (k, x)) in m.iter().enumerate() { if i > 0 { out.push(','); } write_str(k, out); out.push(':'); write_value(x, out); }
            out.push('}');
        }
    }
}
fn write_str(s: &str, out: &mut String) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""), '\\' => out.push_str("\\\\"), '\n' => out.push_str("\\n"), '\r' => out.push_str("\\r"), '\t' => out.push_str("\\t"),
            '\u{8}' => out.push_str("\\b"), '\u{c}' => out.push_str("\\f"),
            ' '..='~' => out.push(c),
            _ => { let mut buf = [0u16; 2]; for u in c.encode_utf16(&mut buf) { out.push_str(&format!("\\u{:04x}", u)); } }
        }
    }
    out.push('"');
}
pub fn sign(payload: &Map<String, Value>, secret: &str) -> String {
    let mut mac = Hmac::<Sha256>::new_from_slice(secret.as_bytes()).expect("hmac key");
    mac.update(canonical(payload).as_bytes());
    hex::encode(mac.finalize().into_bytes())
}
pub fn verify(payload: &Map<String, Value>, secret: &str) -> bool {
    let Some(sig) = payload.get("sig").and_then(|s| s.as_str()) else { return false };
    if secret.is_empty() { return false; }
    let Ok(want) = hex::decode(sig) else { return false };
    let mut mac = Hmac::<Sha256>::new_from_slice(secret.as_bytes()).expect("hmac key");
    mac.update(canonical(payload).as_bytes());
    mac.verify_slice(&want).is_ok()   // constant time
}

#[derive(Clone, Debug)]
pub struct TopProcess { pub name: String, pub pid: i64, pub cpu: f64, pub rss: u64 }
#[derive(Clone, Debug, Default)]
pub struct Telemetry {
    pub received: f64, pub cpu: Option<f64>, pub mem_used: u64, pub mem_total: u64, pub swap_used: u64, pub swap_total: u64, pub disk_used: u64, pub disk_total: u64,
    pub load: Option<[f64; 3]>, pub uptime: u64, pub uptime_text: String, pub ssh_alive: bool, pub os_name: String, pub kernel: String, pub signed: bool,
    pub history: Vec<f64>, pub procs: Vec<TopProcess>, pub containers: Option<Vec<Value>>, pub runtime: String, pub containers_error: String,
    pub agent_version: String, pub reboot_required: Option<bool>,
}
fn fnum(v: Option<&Value>) -> Option<f64> { v.and_then(|x| x.as_f64().or_else(|| x.as_str().and_then(|s| s.parse().ok()))) }
fn unum(v: Option<&Value>) -> u64 { fnum(v).map(|x| x.max(0.0) as u64).unwrap_or(0) }
fn sval(v: Option<&Value>) -> String { v.and_then(|x| x.as_str()).unwrap_or("").to_string() }
pub fn human_bytes(n: f64) -> String {
    let mut n = n;
    for u in ["B", "K", "M", "G", "T"] { if n.abs() < 1024.0 || u == "T" { return if u == "B" || u == "K" { format!("{n:.0}{u}") } else { format!("{n:.1}{u}") }; } n /= 1024.0; }
    format!("{n:.1}T")
}
pub fn format_duration(secs: u64) -> String { let (d, h, m) = (secs / 86400, secs % 86400 / 3600, secs % 3600 / 60); if d > 0 { format!("{d}d {h}h") } else if h > 0 { format!("{h}h {m}m") } else { format!("{m}m") } }
fn gib(n: u64) -> String { format!("{:.1} GiB", n as f64 / 1024f64.powi(3)) }

impl Telemetry {
    pub fn from_entry(e: &Map<String, Value>) -> Telemetry {
        let load = e.get("load").and_then(|l| l.as_array()).filter(|a| a.len() >= 3).map(|a| [a[0].as_f64().unwrap_or(0.0), a[1].as_f64().unwrap_or(0.0), a[2].as_f64().unwrap_or(0.0)]);
        Telemetry {
            received: fnum(e.get("ts")).unwrap_or(0.0), cpu: fnum(e.get("cpu")), mem_used: unum(e.get("mem_used")), mem_total: unum(e.get("mem_total")),
            swap_used: unum(e.get("swap_used")), swap_total: unum(e.get("swap_total")), disk_used: unum(e.get("disk_used")), disk_total: unum(e.get("disk_total")),
            load, uptime: unum(e.get("uptime")), uptime_text: sval(e.get("uptime_text")), ssh_alive: e.get("ssh").map(|v| v.as_f64().map(|x| x != 0.0).or(v.as_bool()).unwrap_or(true)).unwrap_or(true),
            os_name: sval(e.get("os")), kernel: sval(e.get("kernel")), signed: e.get("signed").and_then(|v| v.as_bool()).unwrap_or(false),
            history: e.get("hist").and_then(|h| h.as_array()).map(|a| a.iter().filter_map(|x| x.as_f64()).collect()).unwrap_or_default(),
            procs: e.get("procs").and_then(|p| p.as_array()).map(|a| a.iter().filter_map(|p| { let r = p.as_array()?; if r.len() != 4 { return None; }
                Some(TopProcess { name: r[0].as_str().unwrap_or("").to_string(), pid: r[1].as_i64().unwrap_or(0), cpu: r[2].as_f64().unwrap_or(0.0), rss: r[3].as_u64().unwrap_or(0) }) }).collect()).unwrap_or_default(),
            containers: e.get("containers").and_then(|c| c.as_array()).cloned(), runtime: sval(e.get("rt")), containers_error: sval(e.get("containers_error")),
            agent_version: sval(e.get("agent")), reboot_required: e.get("reboot").map(|v| v.as_f64().map(|x| x != 0.0).or(v.as_bool()).unwrap_or(false)),
        }
    }
    pub fn age(&self) -> f64 { paths::now() - self.received }
    pub fn fresh(&self) -> bool { self.age() <= FRESH_AFTER }
    pub fn mem_pct(&self) -> Option<f64> { if self.mem_total > 0 { Some(100.0 * self.mem_used as f64 / self.mem_total as f64) } else { None } }
    pub fn disk_pct(&self) -> Option<f64> { if self.disk_total > 0 { Some(100.0 * self.disk_used as f64 / self.disk_total as f64) } else { None } }
    pub fn mem_label(&self) -> String { if self.mem_total > 0 { format!("{} / {}", gib(self.mem_used), gib(self.mem_total)) } else { "--".into() } }
    pub fn disk_label(&self) -> String { if self.disk_total > 0 { format!("{} / {}", gib(self.disk_used), gib(self.disk_total)) } else { "--".into() } }
    pub fn load_label(&self) -> String { self.load.map(|l| format!("{:.2} {:.2} {:.2}", l[0], l[1], l[2])).unwrap_or_else(|| "--".into()) }
    pub fn uptime_label(&self) -> String { if !self.uptime_text.is_empty() { self.uptime_text.clone() } else if self.uptime > 0 { format_duration(self.uptime) } else { "--".into() } }
    pub fn top(&self, by_mem: bool, n: usize) -> Vec<TopProcess> {
        let mut v = self.procs.clone();
        if by_mem { v.sort_by(|a, b| b.rss.cmp(&a.rss)); } else { v.sort_by(|a, b| b.cpu.partial_cmp(&a.cpu).unwrap_or(std::cmp::Ordering::Equal).then(b.rss.cmp(&a.rss))); }
        v.truncate(n); v
    }
}

fn clean_procs(raw: Option<&Value>) -> Value {
    let mut out = vec![];
    if let Some(a) = raw.and_then(|r| r.as_array()) {
        for item in a.iter().take(12) {
            let Some(r) = item.as_array() else { continue }; if r.len() != 4 { continue; }
            let name: String = match &r[0] { Value::String(s) => s.chars().take(32).collect(), o => o.to_string().chars().take(32).collect() };
            let (Some(pid), Some(cpu), Some(rss)) = (fnum(Some(&r[1])), fnum(Some(&r[2])), fnum(Some(&r[3]))) else { continue };
            out.push(serde_json::json!([name, pid as i64, (cpu * 10.0).round() / 10.0, rss as i64]));
        }
    }
    Value::Array(out)
}
fn short(s: &str, n: usize) -> String { s.chars().take(n).collect() }
fn f64v(x: f64) -> Value { serde_json::Number::from_f64(x).map(Value::Number).unwrap_or(Value::Null) }

/// Validate a datagram: (cache keys, cache entry), like the Python parse_packet
pub fn parse_packet(data: &[u8], addr_ip: &str, secret: &str, accept_legacy: bool) -> Option<(Vec<String>, Map<String, Value>)> {
    let msg: Map<String, Value> = serde_json::from_slice(data).ok()?;
    let now = paths::now();
    let port = match msg.get("port") { Some(Value::String(s)) => s.clone(), Some(v) => v.to_string(), None => "22".into() };
    let mut entry = Map::new();
    let label;
    if msg.get("v").and_then(|v| v.as_i64()) == Some(PROTOCOL) {
        if !verify(&msg, secret) { return None; }
        let ts = fnum(msg.get("ts")).unwrap_or(0.0);
        if (now - ts).abs() > MAX_CLOCK_SKEW { return None; }
        entry.insert("ts".into(), f64v(now)); entry.insert("signed".into(), true.into());
        entry.insert("cpu".into(), fnum(msg.get("cpu")).map(f64v).unwrap_or(Value::Null));
        let ssh = if msg.get("state").and_then(|s| s.as_str()) == Some("stopping") { 0 } else { msg.get("ssh").map(|v| v.as_f64().map(|x| (x != 0.0) as i64).or(v.as_bool().map(|b| b as i64)).unwrap_or(1)).unwrap_or(1) };
        entry.insert("ssh".into(), ssh.into());
        for k in ["mem_used", "mem_total", "swap_used", "swap_total", "disk_used", "disk_total", "uptime"] { if let Some(x) = msg.get(k).and_then(|v| v.as_f64()) { entry.insert(k.into(), (x as i64).into()); } }
        if let Some(l) = msg.get("load").and_then(|l| l.as_array()) { entry.insert("load".into(), Value::Array(l.iter().take(3).map(|x| f64v(x.as_f64().unwrap_or(0.0))).collect())); }
        for k in ["os", "kernel", "agent"] { if let Some(s) = msg.get(k).and_then(|v| v.as_str()) { entry.insert(k.into(), short(s, 80).into()); } }
        if let Some(r) = msg.get("reboot") { entry.insert("reboot".into(), (r.as_f64().map(|x| x != 0.0).or(r.as_bool()).unwrap_or(false) as i64).into()); }
        entry.insert("procs".into(), clean_procs(msg.get("procs")));
        if let Some(c) = msg.get("containers").and_then(|c| c.as_array()) {
            entry.insert("containers".into(), Value::Array(c.iter().take(40).filter(|r| r.as_array().map_or(false, |a| a.len() >= 10)).cloned().collect()));
            let rt = msg.get("rt").and_then(|r| r.as_str()).filter(|s| !s.is_empty()).unwrap_or("docker");
            entry.insert("rt".into(), short(rt, 16).into());
        }
        if let Some(e) = msg.get("containers_error").and_then(|v| v.as_str()) { entry.insert("containers_error".into(), short(e, 200).into()); }
        label = match msg.get("id") { Some(Value::String(s)) => s.clone(), Some(Value::Null) | None => String::new(), Some(v) => v.to_string() };
    } else if accept_legacy && msg.contains_key("cpu") && !msg.contains_key("v") {
        entry.insert("ts".into(), f64v(now)); entry.insert("signed".into(), false.into());
        entry.insert("cpu".into(), fnum(msg.get("cpu")).map(f64v).unwrap_or(Value::Null));
        entry.insert("ssh".into(), (msg.get("ssh").map(|v| v.as_f64().map(|x| x != 0.0).or(v.as_bool()).unwrap_or(true)).unwrap_or(true) as i64).into());
        let ram = sval(msg.get("ram"));   // "1.2/7.6G"
        if let Some((a, b)) = ram.split_once('/') { if let (Ok(u), Ok(t)) = (a.trim().parse::<f64>(), b.trim().trim_end_matches(['G', ' ']).trim().parse::<f64>()) { if b.contains('G') {
            entry.insert("mem_used".into(), ((u * 1024f64.powi(3)) as i64).into()); entry.insert("mem_total".into(), ((t * 1024f64.powi(3)) as i64).into()); } } }
        if let Some(up) = msg.get("up").filter(|u| !u.is_null() && u.as_str() != Some("")) { entry.insert("uptime_text".into(), short(&up.as_str().map(|s| s.to_string()).unwrap_or_else(|| up.to_string()), 20).into()); }
        label = sval(msg.get("host"));
    } else { return None; }
    let mut keys = vec![format!("{addr_ip}:{port}")];
    if !label.is_empty() && label != addr_ip { keys.push(format!("{label}:{port}")); }
    Some((keys, entry))
}

pub type Cache = HashMap<String, Map<String, Value>>;
pub fn read_cache() -> Cache { std::fs::read_to_string(paths::telemetry_cache_file()).ok().and_then(|t| serde_json::from_str(&t).ok()).unwrap_or_default() }
pub fn lookup(cache: &Cache, host: &str, port: u16, ip: &str) -> Option<Telemetry> {
    let mut keys = vec![format!("{host}:{port}")];
    if !ip.is_empty() { keys.push(format!("{ip}:{port}")); }
    if port == 22 { keys.push(host.to_string()); }
    for k in keys { if let Some(e) = cache.get(&k) { let t = Telemetry::from_entry(e); if t.fresh() { return Some(t); } } }
    None
}

/// Owns the UDP port. Only one sshm process can; the others read the cache file.
pub struct Listener { pub cache: Arc<Mutex<Cache>> }
impl Listener {
    /// None if the port is taken (another sshm process is already listening)
    pub fn start(port: u16, secret: String, accept_legacy: bool, on_update: impl Fn(bool) + Send + 'static) -> Option<Listener> {
        let sock = UdpSocket::bind(("0.0.0.0", port)).ok()?;
        sock.set_read_timeout(Some(Duration::from_secs(1))).ok()?;
        let cache = Arc::new(Mutex::new(read_cache()));
        let c2 = cache.clone();
        std::thread::Builder::new().name("sshm-telemetry".into()).spawn(move || {
            let mut buf = vec![0u8; 65535]; let mut last_flush = Instant::now(); let mut dirty = false;
            loop {
                match sock.recv_from(&mut buf) {
                    Ok((n, addr)) => {
                        let Some((keys, entry)) = parse_packet(&buf[..n], &addr.ip().to_string(), &secret, accept_legacy) else { continue };
                        let mut changed = false;
                        { let mut c = c2.lock().unwrap();
                          for k in &keys {
                              let prev = c.get(k).cloned().unwrap_or_default();
                              let mut hist: Vec<Value> = prev.get("hist").and_then(|h| h.as_array()).cloned().unwrap_or_default();
                              if let Some(cpu) = entry.get("cpu").and_then(|x| x.as_f64()) { hist.push(f64v((cpu * 10.0).round() / 10.0)); if hist.len() > HISTORY { hist.drain(..hist.len() - HISTORY); } }
                              let stale = paths::now() - fnum(prev.get("ts")).unwrap_or(0.0) > FRESH_AFTER;
                              if prev.get("ssh") != entry.get("ssh") || stale { changed = true; }
                              let mut e = entry.clone(); e.insert("hist".into(), Value::Array(hist)); c.insert(k.clone(), e);
                          } }
                        dirty = true;
                        if last_flush.elapsed() > Duration::from_millis(500) { flush(&c2); last_flush = Instant::now(); dirty = false; }
                        on_update(changed);
                    }
                    Err(_) => { if dirty { flush(&c2); last_flush = Instant::now(); dirty = false; } }
                }
            }
        }).ok()?;
        Some(Listener { cache })
    }
}
fn flush(cache: &Arc<Mutex<Cache>>) {
    let cutoff = paths::now() - 3600.0;
    let text = { let mut c = cache.lock().unwrap(); c.retain(|_, v| fnum(v.get("ts")).unwrap_or(0.0) > cutoff); serde_json::to_string(&*c).unwrap_or_default() };
    let _ = paths::atomic_write(&paths::telemetry_cache_file(), text.as_bytes(), 0o600);
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn canonical_matches_python() {
        // python3 -c 'import json; print(json.dumps({"v":2,"id":"nas","cpu":12.5,"x":1e-05,"os":"Fedora Linux 44 (KDE Plasma Desktop Edition)","n":"café \U0001F600","sig":"x"}, sort_keys=True, separators=(",",":")))' (minus sig)
        let m: Map<String, Value> = serde_json::from_str(r#"{"v": 2, "id": "nas", "cpu": 12.5, "x": 1e-05, "os": "Fedora", "n": "caf\u00e9 \ud83d\ude00", "sig": "x"}"#).unwrap();
        assert_eq!(canonical(&m), r#"{"cpu":12.5,"id":"nas","n":"caf\u00e9 \ud83d\ude00","os":"Fedora","v":2,"x":1e-05}"#);
    }
}

#[cfg(test)]
mod python_packet {
    use super::*;
    /// a packet signed by Python's hmac/json, as the agent does
    #[test] fn verifies_real_python_signature() {
        let raw = include_bytes!("../../packaging/testdata/python-signed-packet.json");
        let m: Map<String, Value> = serde_json::from_slice(raw).unwrap();
        assert!(verify(&m, "testsecret"), "signature from Python must verify");
        assert!(!verify(&m, "wrong"));
        let mut t = m.clone(); t.insert("cpu".into(), serde_json::json!(99.9)); assert!(!verify(&t, "testsecret"), "tampered packet must fail");
    }
}
