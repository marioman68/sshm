//! Docker / Podman: discovery over SSH, agent rows, and spotting saved servers that are really published container ports.
use super::model::Server;
use super::{procs, sshcmd};
use serde_json::Value;
use std::collections::HashMap;

pub fn well_known(port: u16) -> &'static str {
    match port { 22 => "SSH", 25565 => "Minecraft", 19132 => "Minecraft Bedrock", 80 | 8080 => "HTTP", 443 | 8443 => "HTTPS", 3000 | 8000 => "Web", 8096 => "Jellyfin", 32400 => "Plex",
        9000 | 9443 => "Portainer", 3306 => "MySQL", 5432 => "PostgreSQL", 6379 => "Redis", 27017 => "MongoDB", 1883 => "MQTT", 8123 => "Home Assistant", 53 => "DNS",
        51820 => "WireGuard", 2049 => "NFS", 445 => "SMB", 25575 => "RCON", 27015 => "Steam", 7777 => "Game", 8384 => "Syncthing", 9090 => "Prometheus", 3001 => "Uptime Kuma", _ => "" }
}
const HTTP_PORTS: [u16; 16] = [80, 443, 8080, 8443, 3000, 8000, 8096, 32400, 9000, 9443, 8123, 8384, 9090, 3001, 5000, 8888];

#[derive(Clone, Debug, PartialEq)]
pub struct PortMap { pub host_port: u16, pub container_port: u16, pub proto: String }
impl PortMap {
    pub fn label(&self) -> String { format!("{}→{}/{}", self.host_port, self.container_port, self.proto) }
    pub fn service(&self) -> &'static str { let s = well_known(self.container_port); if s.is_empty() { well_known(self.host_port) } else { s } }
    pub fn is_web(&self) -> bool { self.proto == "tcp" && (HTTP_PORTS.contains(&self.container_port) || HTTP_PORTS.contains(&self.host_port)) }
}
#[derive(Clone, Debug)]
pub struct Container { pub id: String, pub name: String, pub image: String, pub state: String, pub status: String, pub ports: Vec<PortMap>, pub cpu: Option<f64>, pub mem: u64, pub mem_limit: u64, pub project: String, pub runtime: String, pub source: String }
impl Container {
    pub fn running(&self) -> bool { self.state == "running" }
    pub fn health(&self) -> &'static str { if self.status.contains("(unhealthy)") { "unhealthy" } else if self.status.contains("(healthy)") { "healthy" } else if self.status.contains("(health: starting)") { "health: starting" } else { "" } }
    pub fn mem_pct(&self) -> Option<f64> { if self.mem_limit > 0 && self.mem > 0 { Some(100.0 * self.mem as f64 / self.mem_limit as f64) } else { None } }
    pub fn mem_label(&self) -> String { if self.mem == 0 { return "--".into(); } let lim = if self.mem_limit > 0 { format!(" / {}", super::telemetry::human_bytes(self.mem_limit as f64)) } else { String::new() }; format!("{}{lim}", super::telemetry::human_bytes(self.mem as f64)) }
    pub fn ports_label(&self) -> String { if self.ports.is_empty() { "none published".into() } else { self.ports.iter().map(|p| p.label()).collect::<Vec<_>>().join(", ") } }
    /// runtime for interactive use (sudo may prompt in a terminal)
    pub fn cli(&self) -> String { self.runtime.replace("sudo -n ", "sudo ") }
    pub fn image_short(&self) -> String { let i = self.image.split('@').next().unwrap_or(&self.image); match i.strip_prefix("sha256:") { Some(h) => format!("sha256:{}", &h[..h.len().min(12)]), None => i.to_string() } }
}
#[derive(Clone, Debug, Default)]
pub struct HostContainers { pub host_id: String, pub containers: Vec<Container>, pub runtime: String, pub source: String, pub error: String, pub fetched: f64 }
impl HostContainers { pub fn by_port(&self, port: u16) -> Option<&Container> { self.containers.iter().find(|c| c.ports.iter().any(|p| p.host_port == port)) } }
#[derive(Clone, Debug)]
pub struct Link { pub host: Server, pub container: Container }

/// "0.0.0.0:2222->22/tcp, :::2222->22/tcp" or the podman/API list form
pub fn parse_ports(v: &Value) -> Vec<PortMap> {
    let mut out: Vec<PortMap> = vec![];
    let mut push = |hp: u16, cp: u16, proto: &str| { let p = PortMap { host_port: hp, container_port: cp, proto: proto.to_string() }; if !out.contains(&p) { out.push(p); } };
    match v {
        Value::String(s) => for part in s.split(',') {
            let Some((left, right)) = part.trim().split_once("->") else { continue };
            let hp = left.rsplit(':').next().unwrap_or(left).split('-').next().unwrap_or("");
            let (cp, proto) = right.split_once('/').unwrap_or((right, "tcp"));
            if let (Ok(h), Ok(c)) = (hp.trim().parse(), cp.split('-').next().unwrap_or("").trim().parse()) { push(h, c, proto.trim()); }
        },
        Value::Array(a) => for p in a {
            let g = |ks: &[&str]| ks.iter().find_map(|k| p.get(*k).and_then(|x| x.as_u64())).map(|x| x as u16);
            if let (Some(h), Some(c)) = (g(&["PublicPort", "host_port", "hostPort"]), g(&["PrivatePort", "container_port", "containerPort"])) {
                let proto = ["Type", "protocol"].iter().find_map(|k| p.get(*k).and_then(|x| x.as_str())).unwrap_or("tcp"); if h > 0 && c > 0 { push(h, c, proto); }
            }
        },
        _ => {}
    }
    out
}
pub fn parse_size(t: &str) -> u64 {
    let t = t.trim(); let i = t.find(|c: char| !(c.is_ascii_digit() || c == '.')).unwrap_or(t.len());
    let Ok(n) = t[..i].parse::<f64>() else { return 0 };
    let mult = match t[i..].trim().to_lowercase().as_str() { "kb" => 1e3, "kib" => 1024.0, "mb" => 1e6, "mib" => 1048576.0, "gb" => 1e9, "gib" => 1073741824.0, "tb" => 1e12, "tib" => 1099511627776.0, _ => 1.0 };
    (n * mult) as u64
}
fn name_of(v: Option<&Value>) -> String {
    let s = match v { Some(Value::Array(a)) => a.first().and_then(|x| x.as_str()).unwrap_or("").to_string(), Some(Value::String(s)) => s.clone(), _ => String::new() };
    s.trim_start_matches('/').split(',').next().unwrap_or("").to_string()
}
fn labels(v: Option<&Value>) -> HashMap<String, String> {
    match v { Some(Value::Object(m)) => m.iter().map(|(k, v)| (k.clone(), v.as_str().unwrap_or("").to_string())).collect(),
        Some(Value::String(s)) => s.split(',').filter_map(|p| { let (k, v) = p.split_once('=').unwrap_or((p, "")); if k.is_empty() { None } else { Some((k.trim().to_string(), v.trim().to_string())) } }).collect(), _ => HashMap::new() }
}
fn sortc(v: &mut [Container]) { v.sort_by_key(|c| (!c.running(), c.name.to_lowercase())); }

pub fn parse_discovery(output: &str) -> HostContainers {
    let lines: Vec<&str> = output.lines().collect();
    if lines.is_empty() || lines[0].starts_with("SSHM_NODOCKER") {
        let reason = lines.first().and_then(|l| l.split_once(' ')).map(|x| x.1).unwrap_or("");
        return HostContainers { error: if reason.is_empty() { "no docker or podman found".into() } else { reason.to_string() }, ..Default::default() };
    }
    let runtime = lines[0].strip_prefix("SSHM_RT ").map(|s| s.trim().to_string()).unwrap_or_else(|| "docker".into());
    let mut cs: Vec<Container> = vec![]; let mut stats = false;
    for line in &lines[1..] {
        let l = line.trim(); if l == "SSHM_STATS" { stats = true; continue; }
        if !(l.starts_with('{') || l.starts_with('[')) { continue; }
        let Ok(v) = serde_json::from_str::<Value>(l) else { continue };
        let items = match v { Value::Array(a) => a, o => vec![o] };
        for o in items {
            if !stats {
                let id = o.get("ID").or_else(|| o.get("Id")).and_then(|x| x.as_str()).unwrap_or("").to_string();
                let name = name_of(o.get("Names").or_else(|| o.get("Name")));
                if id.is_empty() || name.is_empty() { continue; }
                let status = o.get("Status").and_then(|x| x.as_str()).unwrap_or("").to_string();
                let mut state = o.get("State").and_then(|x| x.as_str()).unwrap_or("").to_lowercase();
                if state.is_empty() { state = if status.starts_with("Up") { "running".into() } else { "exited".into() }; }
                cs.push(Container { id, name, image: o.get("Image").and_then(|x| x.as_str()).unwrap_or("").to_string(), state, status, ports: o.get("Ports").map(parse_ports).unwrap_or_default(),
                    cpu: None, mem: 0, mem_limit: 0, project: labels(o.get("Labels")).get("com.docker.compose.project").cloned().unwrap_or_default(), runtime: runtime.clone(), source: "ssh".into() });
                continue;
            }
            let sid = ["ID", "ContainerID", "id"].iter().find_map(|k| o.get(*k).and_then(|x| x.as_str())).unwrap_or("").to_string();
            let nm = name_of(o.get("Name"));
            let Some(t) = cs.iter_mut().find(|c| (!sid.is_empty() && (c.id.starts_with(&sid) || sid.starts_with(&c.id))) || c.name == nm) else { continue };
            let cpu = ["CPUPerc", "cpu_percent", "CPU"].iter().find_map(|k| o.get(*k)).map(|x| x.as_str().map(|s| s.to_string()).unwrap_or_else(|| x.to_string())).unwrap_or_default();
            if let Ok(c) = cpu.trim_end_matches('%').trim().parse() { t.cpu = Some(c); }
            let usage = ["MemUsage", "mem_usage"].iter().find_map(|k| o.get(*k).and_then(|x| x.as_str())).unwrap_or("");
            let (u, l) = usage.split_once('/').unwrap_or((usage, "")); t.mem = parse_size(u); t.mem_limit = parse_size(l);
        }
    }
    sortc(&mut cs);
    HostContainers { containers: cs, runtime, source: "ssh".into(), fetched: super::paths::now(), ..Default::default() }
}
/// agent rows: [id, name, image, state, status, ports, cpu, mem, mem_limit, project]
pub fn from_agent(rows: &[Value], runtime: &str) -> Vec<Container> {
    let mut out: Vec<Container> = rows.iter().filter_map(|r| { let a = r.as_array()?; if a.len() < 10 { return None; }
        let s = |i: usize| a[i].as_str().map(|x| x.to_string()).unwrap_or_else(|| if a[i].is_null() { String::new() } else { a[i].to_string() });
        Some(Container { id: s(0), name: s(1), image: s(2), state: s(3), status: s(4), ports: parse_ports(&Value::String(s(5))), cpu: a[6].as_f64(), mem: a[7].as_u64().unwrap_or(0),
            mem_limit: a[8].as_u64().unwrap_or(0), project: s(9), runtime: runtime.to_string(), source: "agent".into() }) }).collect();
    sortc(&mut out); out
}
const FMT: &str = "'{{json .}}'";
pub fn discovery_script() -> String {
    format!("rt=''; for c in docker podman; do command -v $c >/dev/null 2>&1 || continue; if out=$($c ps -a --no-trunc --format {FMT} 2>/dev/null); then rt=$c; break; elif out=$(sudo -n $c ps -a --no-trunc --format {FMT} 2>/dev/null); then rt=\"sudo -n $c\"; break; else err=\"$c found but permission denied (add your user to the $c group)\"; fi; done; if [ -z \"$rt\" ]; then echo \"SSHM_NODOCKER ${{err:-no docker or podman}}\"; exit 0; fi; echo \"SSHM_RT $rt\"; printf '%s\\n' \"$out\"; echo SSHM_STATS; $rt stats --no-stream --no-trunc --format {FMT} 2>/dev/null || true")
}
pub fn discover(host: &Server) -> Result<HostContainers, String> {
    let remote = format!("sh -c {}", sshcmd::quote(&discovery_script()));
    let out = sshcmd::run_capture(&procs::remote_argv(host, &remote), 25.0)?;
    if !out.stdout.starts_with("SSHM_") { return Err(procs::explain(&out)); }
    let mut hc = parse_discovery(&out.stdout); hc.host_id = host.id.clone(); Ok(hc)
}
pub fn run_action(host: &Server, c: &Container, action: &str) -> Result<String, String> {
    let done = match action { "start" => "Started", "stop" => "Stopped", "restart" => "Restarted", "pause" => "Paused", "unpause" => "Resumed", _ => return Err(format!("unknown action {action}")) };
    let out = sshcmd::run_capture(&procs::remote_argv(host, &format!("{} {action} {}", c.runtime, sshcmd::quote(&c.name))), 60.0)?;
    if out.code != Some(0) { return Err(procs::explain(&out)); }
    Ok(format!("{done} {}", c.name))
}
pub fn logs_argv(host: &Server, c: &Container, tmux_session: &str) -> Vec<String> { sshcmd::ssh_command(host, Some(false), Some(&format!("{} logs -f --tail 200 {}", c.cli(), sshcmd::quote(&c.name))), tmux_session) }
pub fn shell_argv(host: &Server, c: &Container, tmux_session: &str) -> Vec<String> {
    let inner = sshcmd::quote("command -v bash >/dev/null 2>&1 && exec bash || exec sh");
    sshcmd::ssh_command(host, Some(false), Some(&format!("{} exec -it {} sh -c {inner}", c.cli(), sshcmd::quote(&c.name))), tmux_session)
}
pub fn stats_argv(host: &Server, c: Option<&Container>, tmux_session: &str) -> Vec<String> {
    let (rt, target) = match c { Some(c) => (c.cli(), sshcmd::quote(&c.name)), None => ("docker".into(), String::new()) };
    sshcmd::ssh_command(host, Some(false), Some(format!("{rt} stats {target}").trim()), tmux_session)
}
/// server id -> (docker host, container) for servers that are a container's published port on the same machine
pub fn link_servers(servers: &[Server], hosts: &HashMap<String, HostContainers>, addrs: &HashMap<String, String>) -> HashMap<String, Link> {
    let same = |a: &Server, b: &Server| a.host.eq_ignore_ascii_case(&b.host) || matches!((addrs.get(&a.id), addrs.get(&b.id)), (Some(x), Some(y)) if x == y);
    let mut links = HashMap::new();
    for (hid, hc) in hosts {
        let Some(host) = servers.iter().find(|s| &s.id == hid) else { continue };
        for s in servers {
            if &s.id == hid || links.contains_key(&s.id) || !same(s, host) || s.port == host.port { continue; }
            if let Some(c) = hc.by_port(s.port) { links.insert(s.id.clone(), Link { host: host.clone(), container: c.clone() }); }
        }
    }
    links
}
/// servers worth asking: another profile points at the same machine on a different port (port 22 first)
pub fn candidate_hosts(servers: &[Server], addrs: &HashMap<String, String>) -> Vec<Server> {
    let key = |s: &Server| addrs.get(&s.id).cloned().unwrap_or_else(|| s.host.to_lowercase());
    let mut out: Vec<Server> = servers.iter().filter(|s| servers.iter().any(|o| o.id != s.id && key(o) == key(s) && o.port != s.port)).cloned().collect();
    out.sort_by_key(|s| (s.port != 22, s.port)); out
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn ports() { let p = parse_ports(&Value::String("0.0.0.0:2222->22/tcp, :::2222->22/tcp, 25565->25565/tcp".into())); assert_eq!(p.len(), 2); assert_eq!(p[0].host_port, 2222); assert_eq!(p[1].service(), "Minecraft"); }
    #[test] fn sizes() { assert_eq!(parse_size("1.5GiB"), 1610612736); assert_eq!(parse_size("512MiB "), 536870912); }
    #[test] fn discovery() {
        let out = "SSHM_RT docker\n{\"ID\":\"abc123\",\"Names\":\"mc\",\"Image\":\"itzg/minecraft\",\"State\":\"running\",\"Status\":\"Up 3 days (healthy)\",\"Ports\":\"0.0.0.0:2222->22/tcp\",\"Labels\":\"com.docker.compose.project=games\"}\nSSHM_STATS\n{\"ID\":\"abc\",\"Name\":\"mc\",\"CPUPerc\":\"12.5%\",\"MemUsage\":\"1GiB / 4GiB\"}";
        let hc = parse_discovery(out); let c = &hc.containers[0];
        assert_eq!((c.name.as_str(), c.project.as_str(), c.health(), c.cpu), ("mc", "games", "healthy", Some(12.5))); assert_eq!(c.mem_limit, 4294967296);
        let host = Server { id: "h".into(), name: "Homelab".into(), host: "192.168.4.100".into(), port: 22, ..Default::default() };
        let mc = Server { id: "m".into(), name: "Minecraft".into(), host: "192.168.4.100".into(), port: 2222, ..Default::default() };
        let links = link_servers(&[host.clone(), mc.clone()], &[("h".to_string(), hc)].into_iter().collect(), &HashMap::new());
        assert_eq!(links["m"].container.name, "mc");
        assert_eq!(candidate_hosts(&[host, mc], &HashMap::new())[0].id, "h");
    }
}
