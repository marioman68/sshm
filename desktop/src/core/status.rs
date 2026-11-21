//! Reachability: TCP connect latency + SSH banner, then telemetry merged in (same rules as the Python status module).
use super::model::Server;
use super::telemetry::{self, Cache, Telemetry};
use std::io::Read;
use std::net::{TcpStream, ToSocketAddrs};
use std::time::{Duration, Instant};

#[derive(Clone, Debug, Default)]
pub struct HostStatus { pub online: bool, pub latency_ms: Option<f64>, pub banner: String, pub address: String, pub error: String, pub checked_at: f64, pub telemetry: Option<Telemetry> }
impl HostStatus {
    pub fn latency_label(&self) -> String { match (self.online, self.latency_ms) { (true, Some(l)) if l >= 1.0 => format!("{l:.0} ms"), (true, Some(_)) => "<1 ms".into(), _ => "--".into() } }
    /// "online", "degraded" (host up, sshd down) or "offline"
    pub fn state(&self) -> &'static str { if self.online { "online" } else if self.telemetry.as_ref().map_or(false, |t| t.fresh()) { "degraded" } else { "offline" } }
    pub fn summary(&self) -> String {
        if self.online { return format!("Online · {}", self.latency_label()); }
        if self.state() == "degraded" { return "Host up · SSH not reachable".into(); }
        if self.error.is_empty() { "Offline".into() } else { format!("Offline · {}", self.error) }
    }
}
pub fn probe(host: &str, port: u16, timeout: f64) -> HostStatus {
    let started = Instant::now(); let now = super::paths::now();
    let to = Duration::from_secs_f64(timeout.max(0.2));
    let addrs: Vec<_> = match (host, port).to_socket_addrs() { Ok(a) => a.collect(), Err(_) => return HostStatus { error: "DNS lookup failed".into(), checked_at: now, ..Default::default() } };
    let mut last = "unreachable".to_string();
    for a in addrs.iter().take(4) {
        let t0 = Instant::now();
        match TcpStream::connect_timeout(a, to) {
            Ok(mut s) => {
                let lat = t0.elapsed().as_secs_f64() * 1000.0;
                let _ = s.set_read_timeout(Some(Duration::from_secs_f64(timeout.min(0.8))));
                let mut buf = [0u8; 256]; let mut banner = String::new();
                if let Ok(n) = s.read(&mut buf) { let t = String::from_utf8_lossy(&buf[..n]); if let Some(l) = t.trim().lines().next() { if l.starts_with("SSH-") { banner = l.splitn(3, '-').nth(2).unwrap_or("").chars().take(60).collect(); } } }
                return HostStatus { online: true, latency_ms: Some(lat), banner, address: a.ip().to_string(), checked_at: super::paths::now(), ..Default::default() };
            }
            Err(e) => { last = match e.kind() { std::io::ErrorKind::TimedOut | std::io::ErrorKind::WouldBlock => "timed out".into(), std::io::ErrorKind::ConnectionRefused => "connection refused".into(),
                _ => { let m = e.to_string(); m.split(" (os error").next().unwrap_or(&m).to_lowercase() } }; }
        }
        if started.elapsed() > to * 2 { break; }
    }
    HostStatus { error: last, checked_at: super::paths::now(), ..Default::default() }
}
/// probe every server in parallel (32 at a time)
pub fn probe_many(servers: &[Server], timeout: f64) -> Vec<(String, HostStatus)> {
    let mut out = vec![];
    for chunk in servers.chunks(32) {
        let got: Vec<(String, HostStatus)> = std::thread::scope(|s| {
            let hs: Vec<_> = chunk.iter().map(|srv| s.spawn(move || (srv.id.clone(), probe(&srv.host, srv.port, timeout)))).collect();
            hs.into_iter().filter_map(|h| h.join().ok()).collect()
        });
        out.extend(got);
    }
    out
}
pub fn attach(srv: &Server, st: &mut HostStatus, cache: &Cache) {
    let tel = telemetry::lookup(cache, &srv.host, srv.port, &st.address);
    if let Some(t) = &tel { if !t.ssh_alive && st.online { st.online = false; st.error = "agent reports sshd stopped".into(); } }
    st.telemetry = tel;
}
