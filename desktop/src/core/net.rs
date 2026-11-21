//! Wake-on-LAN, LAN scan, MAC lookup and Minecraft server ping.
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream, ToSocketAddrs, UdpSocket};
use std::time::{Duration, Instant};

pub fn wake(mac: &str) -> Result<(), String> {
    let raw = super::model::normalize_mac(mac)?.replace(':', ""); if raw.is_empty() { return Err("No MAC address configured".into()); }
    let m = hex::decode(raw).map_err(|e| e.to_string())?;
    let mut pkt = vec![0xffu8; 6]; for _ in 0..16 { pkt.extend_from_slice(&m); }
    let s = UdpSocket::bind("0.0.0.0:0").map_err(|e| e.to_string())?; s.set_broadcast(true).map_err(|e| e.to_string())?;
    for port in [9, 7] { s.send_to(&pkt, ("255.255.255.255", port)).map_err(|e| e.to_string())?; }
    Ok(())
}
pub fn read_arp() -> std::collections::HashMap<String, String> {
    std::fs::read_to_string("/proc/net/arp").unwrap_or_default().lines().skip(1).filter_map(|l| { let p: Vec<&str> = l.split_whitespace().collect(); if p.len() >= 4 && p[3] != "00:00:00:00:00:00" { Some((p[0].to_string(), p[3].to_lowercase())) } else { None } }).collect()
}
pub fn mac_for(host: &str) -> String {
    let Some(ip) = (host, 22).to_socket_addrs().ok().and_then(|mut a| a.find(|x| x.is_ipv4())) else { return String::new() };
    let _ = TcpStream::connect_timeout(&ip, Duration::from_millis(600));
    read_arp().get(&ip.ip().to_string()).cloned().unwrap_or_default()
}
#[derive(Clone, Debug)]
pub struct Found { pub ip: String, pub port: u16, pub banner: String, pub hostname: String, pub mac: String, pub latency_ms: f64 }
impl Found { pub fn suggested_name(&self) -> String { let base = if self.hostname.is_empty() { format!("host-{}", self.ip.rsplit('.').next().unwrap_or("")) } else { self.hostname.split('.').next().unwrap_or("").to_string() }; if self.port == 22 { base } else { format!("{base}-{}", self.port) } } }
pub fn parse_ports(spec: &str) -> Result<Vec<u16>, String> {
    let mut v = std::collections::BTreeSet::new();
    for part in spec.replace(' ', "").split(',').filter(|p| !p.is_empty()) {
        if let Some((a, b)) = part.split_once('-') { if let (Ok(a), Ok(b)) = (a.parse::<u32>(), b.parse::<u32>()) { let (lo, hi) = (a.min(b), a.max(b)); for p in lo..=hi.min(lo + 512) { if (1..=65535).contains(&p) { v.insert(p as u16); } } } }
        else if let Ok(p) = part.parse::<u32>() { if (1..=65535).contains(&p) { v.insert(p as u16); } }
    }
    if v.is_empty() { Err(format!("No valid ports in '{spec}'")) } else { Ok(v.into_iter().collect()) }
}
/// "192.168.1.0/24", "192.168.1" (= /24), "10.0.0.5-40" or one IP
pub fn parse_targets(spec: &str) -> Result<Vec<String>, String> {
    let mut s = spec.trim().to_string(); if s.is_empty() { return Err("Empty target".into()); }
    let ip4 = |t: &str| -> Option<u32> { let p: Vec<u32> = t.split('.').map(|x| x.parse().ok()).collect::<Option<Vec<_>>>()?; if p.len() == 4 && p.iter().all(|x| *x < 256) { Some(p[0] << 24 | p[1] << 16 | p[2] << 8 | p[3]) } else { None } };
    let fmt = |n: u32| format!("{}.{}.{}.{}", n >> 24, (n >> 16) & 255, (n >> 8) & 255, n & 255);
    if s.split('.').count() == 3 && s.split('.').all(|p| p.parse::<u8>().is_ok()) { s = format!("{s}.0/24"); }
    if let (Some((base, end)), false) = (s.rsplit_once('-'), s.contains('/')) {
        let b = ip4(base).ok_or(format!("Bad range '{s}'"))?; let last: u32 = end.parse().map_err(|_| format!("Bad range '{s}'"))?; let first = b & 255;
        if first > last || last > 255 { return Err(format!("Bad range '{s}'")); }
        return Ok((first..=last).map(|i| fmt((b & !255) | i)).collect());
    }
    let (addr, bits) = s.split_once('/').map(|(a, b)| (a.to_string(), b.parse::<u32>().unwrap_or(32))).unwrap_or((s.clone(), 32));
    let a = ip4(&addr).ok_or(format!("'{addr}' is not an IPv4 address"))?;
    if bits > 32 { return Err("Bad prefix length".into()); }
    let size = 1u64 << (32 - bits); if size > 4098 { return Err(format!("{s} has {size} addresses; the limit is 4096")); }
    let net = if bits == 0 { 0 } else { a & (u32::MAX << (32 - bits)) };
    if size <= 2 { return Ok((0..size as u32).map(|i| fmt(net + i)).collect()); }
    Ok((1..size as u32 - 1).map(|i| fmt(net + i)).collect())
}
pub fn local_network() -> String {
    let ip = UdpSocket::bind("0.0.0.0:0").ok().and_then(|s| { s.connect("1.1.1.1:9").ok()?; s.local_addr().ok() }).map(|a| a.ip().to_string());
    let Some(ip) = ip else { return "192.168.1.0/24".into() };
    let mut plen = 24u32;
    if let Ok(o) = std::process::Command::new("ip").args(["-j", "-4", "addr"]).output() {
        if let Ok(v) = serde_json::from_slice::<serde_json::Value>(&o.stdout) { for i in v.as_array().into_iter().flatten() { for a in i["addr_info"].as_array().into_iter().flatten() { if a["local"].as_str() == Some(&ip) { plen = a["prefixlen"].as_u64().unwrap_or(24) as u32; } } } }
    }
    let plen = plen.max(22); let p: Vec<u32> = ip.split('.').filter_map(|x| x.parse().ok()).collect(); if p.len() != 4 { return "192.168.1.0/24".into(); }
    let n = (p[0] << 24 | p[1] << 16 | p[2] << 8 | p[3]) & (u32::MAX << (32 - plen));
    format!("{}.{}.{}.{}/{plen}", n >> 24, (n >> 16) & 255, (n >> 8) & 255, n & 255)
}
fn probe(ip: &str, port: u16, timeout: f64) -> Option<Found> {
    let addr: SocketAddr = format!("{ip}:{port}").parse().ok()?; let t0 = Instant::now();
    let mut s = TcpStream::connect_timeout(&addr, Duration::from_secs_f64(timeout)).ok()?; let lat = t0.elapsed().as_secs_f64() * 1000.0;
    let _ = s.set_read_timeout(Some(Duration::from_secs_f64(timeout + 0.3)));
    let mut buf = [0u8; 128]; let n = s.read(&mut buf).ok()?; let b = String::from_utf8_lossy(&buf[..n]); let line = b.trim().lines().next()?.to_string();
    if !line.starts_with("SSH-") { return None; }
    Some(Found { ip: ip.into(), port, banner: line.splitn(3, '-').nth(2).unwrap_or("").chars().take(48).collect(), hostname: String::new(), mac: String::new(), latency_ms: lat })
}
fn rdns(ip: &str) -> String {
    // getnameinfo via libc
    let Ok(addr) = ip.parse::<std::net::Ipv4Addr>() else { return String::new() };
    unsafe {
        let mut sa: libc::sockaddr_in = std::mem::zeroed(); sa.sin_family = libc::AF_INET as u16; sa.sin_addr.s_addr = u32::from_ne_bytes(addr.octets());
        let mut host = [0 as libc::c_char; 256];
        let r = libc::getnameinfo(&sa as *const _ as *const libc::sockaddr, std::mem::size_of::<libc::sockaddr_in>() as u32, host.as_mut_ptr(), 256, std::ptr::null_mut(), 0, libc::NI_NAMEREQD);
        if r == 0 { std::ffi::CStr::from_ptr(host.as_ptr()).to_string_lossy().into_owned() } else { String::new() }
    }
}
/// parallel scan; progress(done, total) is called now and then; stops early when cancel is set
pub fn scan(targets: &[String], ports: &[u16], cancel: &std::sync::atomic::AtomicBool, progress: &(dyn Fn(usize, usize) + Sync)) -> Vec<Found> {
    let jobs: Vec<(String, u16)> = targets.iter().flat_map(|ip| ports.iter().map(move |p| (ip.clone(), *p))).collect();
    let total = jobs.len(); let done = std::sync::atomic::AtomicUsize::new(0);
    let found = std::sync::Mutex::new(vec![]);
    let next = std::sync::atomic::AtomicUsize::new(0);
    std::thread::scope(|s| { for _ in 0..128.min(total.max(1)) { s.spawn(|| loop {
        if cancel.load(std::sync::atomic::Ordering::Relaxed) { break; }
        let i = next.fetch_add(1, std::sync::atomic::Ordering::Relaxed); if i >= total { break; }
        if let Some(f) = probe(&jobs[i].0, jobs[i].1, 0.5) { found.lock().unwrap().push(f); }
        let d = done.fetch_add(1, std::sync::atomic::Ordering::Relaxed) + 1; if d % 32 == 0 || d == total { progress(d, total); }
    }); } });
    let mut v = found.into_inner().unwrap(); let arp = read_arp();
    let names: std::collections::HashMap<String, String> = std::thread::scope(|s| { let hs: Vec<_> = v.iter().map(|f| f.ip.clone()).collect::<std::collections::BTreeSet<_>>().into_iter().map(|ip| s.spawn(move || { let n = rdns(&ip); (ip, n) })).collect(); hs.into_iter().filter_map(|h| h.join().ok()).collect() });
    for f in v.iter_mut() { f.mac = arp.get(&f.ip).cloned().unwrap_or_default(); f.hostname = names.get(&f.ip).cloned().unwrap_or_default(); }
    v.sort_by_key(|f| (f.ip.split('.').map(|x| x.parse::<u32>().unwrap_or(0)).collect::<Vec<_>>(), f.port)); v
}

#[derive(Clone, Debug)]
pub struct Minecraft { pub online: i64, pub max: i64, pub version: String, pub motd: String, pub players: Vec<String> }
impl Minecraft { pub fn summary(&self) -> String { format!("{}/{} players · {}", self.online, self.max, self.version) } }
fn varint(mut n: u32) -> Vec<u8> { let mut o = vec![]; loop { let b = (n & 0x7f) as u8; n >>= 7; o.push(b | if n != 0 { 0x80 } else { 0 }); if n == 0 { return o; } } }
fn read_varint(s: &mut TcpStream) -> std::io::Result<u32> { let mut num = 0u32; for i in 0..5 { let mut b = [0u8]; s.read_exact(&mut b)?; num |= ((b[0] & 0x7f) as u32) << (7 * i); if b[0] & 0x80 == 0 { return Ok(num); } } Err(std::io::Error::other("varint too long")) }
fn flatten_motd(v: &serde_json::Value) -> String {
    let t = match v { serde_json::Value::String(s) => s.clone(), serde_json::Value::Object(m) => m.get("text").and_then(|x| x.as_str()).unwrap_or("").to_string() + &m.get("extra").and_then(|e| e.as_array()).map(|a| a.iter().map(flatten_motd).collect::<String>()).unwrap_or_default(), serde_json::Value::Array(a) => a.iter().map(flatten_motd).collect(), _ => String::new() };
    let mut out = String::new(); let mut skip = false; for c in t.chars() { if skip { skip = false; continue; } if c == '§' { skip = true; continue; } out.push(c); } out
}
/// Java Edition "Server List Ping"
pub fn minecraft_ping(host: &str, port: u16) -> Result<Minecraft, String> {
    let addr = (host, port).to_socket_addrs().map_err(|e| e.to_string())?.next().ok_or("no address")?;
    let mut s = TcpStream::connect_timeout(&addr, Duration::from_secs(2)).map_err(|e| e.to_string())?;
    let _ = s.set_read_timeout(Some(Duration::from_secs(2)));
    let mut hs = vec![0u8]; hs.extend(varint(767)); hs.extend(varint(host.len() as u32)); hs.extend(host.as_bytes()); hs.extend(port.to_be_bytes()); hs.extend(varint(1));
    let mut pkt = varint(hs.len() as u32); pkt.extend(hs); pkt.extend([1u8, 0u8]);
    s.write_all(&pkt).map_err(|e| e.to_string())?;
    let io = |e: std::io::Error| e.to_string();
    let _len = read_varint(&mut s).map_err(io)?; if read_varint(&mut s).map_err(io)? != 0 { return Err("unexpected packet".into()); }
    let size = read_varint(&mut s).map_err(io)? as usize; if size > 1 << 20 { return Err("status too large".into()); }
    let mut buf = vec![0u8; size]; s.read_exact(&mut buf).map_err(io)?;
    let d: serde_json::Value = serde_json::from_slice(&buf).map_err(|e| e.to_string())?;
    let pl = &d["players"];
    Ok(Minecraft { online: pl["online"].as_i64().unwrap_or(0), max: pl["max"].as_i64().unwrap_or(0), version: d["version"]["name"].as_str().unwrap_or("?").to_string(),
        motd: flatten_motd(&d["description"]).trim().chars().take(120).collect(), players: pl["sample"].as_array().map(|a| a.iter().filter_map(|p| p["name"].as_str().map(String::from)).filter(|n| !n.is_empty()).take(12).collect()).unwrap_or_default() })
}
#[cfg(test)]
mod tests { use super::*;
    #[test] fn targets() { assert_eq!(parse_targets("192.168.1").unwrap().len(), 254); assert_eq!(parse_targets("10.0.0.5-7").unwrap(), ["10.0.0.5", "10.0.0.6", "10.0.0.7"]); assert_eq!(parse_targets("10.0.0.9").unwrap(), ["10.0.0.9"]); assert!(parse_targets("10.0.0.0/8").is_err()); }
    #[test] fn ports() { assert_eq!(parse_ports("22, 2222, 2200-2202").unwrap(), [22, 2200, 2201, 2202, 2222]); }
}
