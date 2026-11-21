//! Alert rules: fire only on observed good → bad transitions, resolve with an "info" event (same rules as Python).
use super::containers::HostContainers;
use super::history::Event;
use super::model::Server;
use super::settings::Settings;
use super::status::HostStatus;
use std::collections::HashMap;

#[derive(Default)]
struct Track { bad_since: Option<f64>, firing: bool, seen_good: bool }
#[derive(Default)]
pub struct Alerts { tracks: HashMap<(String, String), Track> }
impl Alerts {
    #[allow(clippy::too_many_arguments)]
    fn check(&mut self, s: &Server, key: &str, bad: Option<bool>, now: f64, hold: f64, sev: &str, fire: String, clear: String) -> Option<Event> {
        let bad = bad?;
        let tr = self.tracks.entry((s.id.clone(), key.to_string())).or_default();
        let ev = |sev: &str, msg: String, resolved: bool| Event { ts: now, server_id: s.id.clone(), server_name: s.name.clone(), kind: key.to_string(), severity: sev.to_string(), message: msg, resolved };
        if !bad { tr.bad_since = None; tr.seen_good = true; if tr.firing { tr.firing = false; return Some(ev("info", clear, true)); } return None; }
        if !tr.seen_good { return None; }
        let since = *tr.bad_since.get_or_insert(now);
        if !tr.firing && now - since >= hold { tr.firing = true; return Some(ev(sev, fire, false)); }
        None
    }
    pub fn evaluate(&mut self, st: &Settings, servers: &[Server], statuses: &HashMap<String, HostStatus>, hosts: &HashMap<String, HostContainers>) -> Vec<Event> {
        if !st.alerts_enabled { return vec![]; }
        let now = super::paths::now(); let sustain = st.alert_sustain_minutes as f64 * 60.0; let mut out = vec![];
        for s in servers.iter().filter(|s| s.tray) {
            let Some(h) = statuses.get(&s.id) else { continue };
            let why = if h.error.is_empty() { "unreachable".to_string() } else { h.error.clone() };
            out.extend(self.check(s, "offline", Some(!h.online), now, st.alert_offline_grace as f64, "critical", format!("{} is down ({why})", s.name), format!("{} is back online", s.name)));
            if let (true, Some(t)) = (h.online, &h.telemetry) {
                out.extend(self.check(s, "cpu", t.cpu.map(|c| c >= st.alert_cpu), now, sustain, "warning", format!("{}: CPU at {:.0}% for {} min", s.name, t.cpu.unwrap_or(0.0), st.alert_sustain_minutes), format!("{}: CPU back to normal", s.name)));
                out.extend(self.check(s, "mem", t.mem_pct().map(|m| m >= st.alert_mem), now, sustain, "warning", format!("{}: memory at {:.0}%", s.name, t.mem_pct().unwrap_or(0.0)), format!("{}: memory back to normal", s.name)));
                out.extend(self.check(s, "disk", t.disk_pct().map(|d| d >= st.alert_disk), now, 0.0, "warning", format!("{}: disk / is {:.0}% full", s.name, t.disk_pct().unwrap_or(0.0)), format!("{}: disk usage back under {:.0}%", s.name, st.alert_disk)));
                out.extend(self.check(s, "reboot", t.reboot_required, now, 0.0, "info", format!("{} needs a reboot (updated kernel)", s.name), format!("{} was rebooted", s.name)));
            }
            for c in hosts.get(&s.id).map(|h| h.containers.as_slice()).unwrap_or(&[]) {
                out.extend(self.check(s, &format!("container:{}", c.name), Some(!c.running()), now, 30.0, "warning", format!("Container {} on {} stopped ({})", c.name, s.name, if c.status.is_empty() { &c.state } else { &c.status }), format!("Container {} on {} is running again", c.name, s.name)));
                if c.running() { out.extend(self.check(s, &format!("unhealthy:{}", c.name), if c.health().is_empty() { None } else { Some(c.health() == "unhealthy") }, now, 0.0, "warning", format!("Container {} on {} is unhealthy", c.name, s.name), format!("Container {} on {} is healthy again", c.name, s.name))); }
            }
        }
        out
    }
}
