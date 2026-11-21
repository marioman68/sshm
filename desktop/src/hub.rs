//! The live state both front-ends (tray and window) work from. Network work runs on threads and reports back over a channel;
//! the owner calls `tick()` about once a second.
use crate::core::containers::{self, HostContainers, Link};
use crate::core::history::{Event, History};
use crate::core::net::{self, Minecraft};
use crate::core::settings::Settings;
use crate::core::status::{self, HostStatus};
use crate::core::store::Store;
use crate::core::telemetry::{self, Listener};
use crate::core::{alerts::Alerts, model::Server, paths};
use std::collections::{HashMap, HashSet};
use std::sync::mpsc::{channel, Receiver, Sender};
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime};

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Level { Info, Success, Warning, Error }

pub enum Msg {
    Statuses(Vec<(String, HostStatus)>),
    Containers(String, HostContainers, u64),
    Minecraft(String, Result<Minecraft, String>),
    Telemetry(bool),
    Done(Level, String, bool),   // message, tunnels changed
}

pub type Waker = Arc<dyn Fn() + Send + Sync>;

pub struct Hub {
    pub settings: Settings, settings_mtime: Option<SystemTime>,
    pub store: Store,
    pub statuses: HashMap<String, HostStatus>,
    pub listener: Option<Listener>,
    pub history: Option<History>,
    alerts: Alerts,
    ssh_containers: HashMap<String, HostContainers>,
    disc_next: HashMap<String, Instant>, disc_running: HashSet<String>,
    mc: HashMap<String, (Instant, Option<Result<Minecraft, String>>)>,
    pub tx: Sender<Msg>, rx: Receiver<Msg>, pub waker: Waker,
    probing: bool, last_probe: Option<Instant>, last_store_check: Instant, last_disc_check: Instant, last_tel: Instant,
    /// alert events raised since the front-end last took them (for notifications)
    pub new_events: Vec<Event>,
    /// status messages for the front-end (text, level)
    pub messages: Vec<(Level, String)>,
    pub tunnels_changed: bool,
    pub changed_state: Vec<(String, bool)>,
    known_online: HashMap<String, bool>,
}

impl Hub {
    pub fn new(own_telemetry: bool, waker: Waker) -> Hub {
        let settings = Settings::load();
        let (tx, rx) = channel();
        let mut h = Hub {
            settings_mtime: Settings::modified(), store: Store::load(), statuses: HashMap::new(), listener: None, history: History::open(), alerts: Alerts::default(),
            ssh_containers: HashMap::new(), disc_next: HashMap::new(), disc_running: HashSet::new(), mc: HashMap::new(), tx, rx, waker,
            probing: false, last_probe: None, last_store_check: Instant::now(), last_disc_check: Instant::now(), last_tel: Instant::now() - Duration::from_secs(5),
            new_events: vec![], messages: vec![], tunnels_changed: false, changed_state: vec![], known_online: HashMap::new(), settings,
        };
        if own_telemetry { h.start_listener(); }
        h.refresh();
        h
    }
    fn start_listener(&mut self) {
        let tx = self.tx.clone(); let w = self.waker.clone();
        self.listener = Listener::start(self.settings.telemetry_port, self.settings.telemetry_secret.clone(), self.settings.accept_legacy_agents, move |changed| {
            if changed { let _ = tx.send(Msg::Telemetry(true)); w(); }
        });
        if self.listener.is_some() {
            // a fresh owner re-derives active alerts from scratch
            if let Some(h) = &self.history { h.clear_active(); h.prune(); }
        }
    }
    /// this process writes history and raises alerts only if it owns the telemetry port
    pub fn recording(&self) -> bool { self.listener.is_some() }
    pub fn servers(&self) -> &[Server] { &self.store.servers }
    pub fn status(&self, id: &str) -> Option<&HostStatus> { self.statuses.get(id) }
    pub fn probing(&self) -> bool { self.probing }

    fn cache(&self) -> telemetry::Cache { match &self.listener { Some(l) => l.cache.lock().map(|c| c.clone()).unwrap_or_default(), None => telemetry::read_cache() } }
    pub fn reattach_telemetry(&mut self) {
        let cache = self.cache();
        // like the Python hub: telemetry can only mark a probed-online host as "sshd stopped" until the next probe
        for s in &self.store.servers { if let Some(st) = self.statuses.get_mut(&s.id) { status::attach(s, st, &cache); } }
    }

    pub fn refresh(&mut self) -> bool {
        if self.probing { return false; }
        self.probing = true;
        let servers = self.store.servers.clone(); let timeout = self.settings.probe_timeout; let tx = self.tx.clone(); let w = self.waker.clone();
        std::thread::spawn(move || { let r = status::probe_many(&servers, timeout); let _ = tx.send(Msg::Statuses(r)); w(); });
        true
    }

    /// housekeeping; true if anything the UI shows may have changed
    pub fn tick(&mut self) -> bool {
        let mut changed = false;
        while let Ok(m) = self.rx.try_recv() {
            changed = true;
            match m {
                Msg::Statuses(v) => {
                    self.probing = false; self.last_probe = Some(Instant::now());
                    let known: HashSet<&String> = self.store.servers.iter().map(|s| &s.id).collect();
                    self.statuses.retain(|k, _| known.contains(k));
                    let cache = self.cache();
                    for (id, mut st) in v { if let Some(s) = self.store.servers.iter().find(|s| s.id == id) { status::attach(s, &mut st, &cache); } self.statuses.insert(id, st); }
                    self.observe();
                    for s in &self.store.servers { if let Some(st) = self.statuses.get(&s.id) {
                        if let Some(prev) = self.known_online.insert(s.id.clone(), st.online) { if prev != st.online { self.changed_state.push((s.id.clone(), st.online)); } }
                    } }
                }
                Msg::Containers(id, hc, backoff) => { self.disc_running.remove(&id); self.disc_next.insert(id.clone(), Instant::now() + Duration::from_secs(backoff)); self.ssh_containers.insert(id, hc); self.observe(); }
                Msg::Minecraft(key, r) => { self.mc.insert(key, (Instant::now(), Some(r))); }
                Msg::Telemetry(_) => { self.reattach_telemetry(); if !self.probing { self.refresh(); } }
                Msg::Done(level, text, tun) => { self.messages.push((level, text)); if tun { self.tunnels_changed = true; } }
            }
        }
        if self.last_store_check.elapsed() > Duration::from_millis(1500) {
            self.last_store_check = Instant::now();
            if self.store.reload_if_changed() { changed = true; self.refresh(); }
            let m = Settings::modified();
            if m != self.settings_mtime { self.settings_mtime = m; self.settings = Settings::load(); changed = true; }
        }
        let iv = self.settings.refresh_interval;
        if iv > 0 && !self.probing && self.last_probe.map_or(true, |t| t.elapsed() >= Duration::from_secs(iv)) { self.refresh(); }
        if self.last_disc_check.elapsed() > Duration::from_secs(5) && !self.statuses.is_empty() { self.last_disc_check = Instant::now(); self.auto_discover(); }
        if self.last_tel.elapsed() > Duration::from_secs(1) { self.last_tel = Instant::now(); self.reattach_telemetry(); changed = true; }
        changed
    }

    fn observe(&mut self) {
        if !self.recording() { return; }
        let servers = self.store.servers.clone();
        if let Some(h) = self.history.as_mut() {
            for s in &servers { if let Some(st) = self.statuses.get(&s.id) {
                let t = st.telemetry.as_ref();
                h.record(&s.id, st.online, st.latency_ms, t.and_then(|t| t.cpu), t.and_then(|t| t.mem_pct()), t.and_then(|t| t.disk_pct()));
            } }
        }
        let hosts = self.host_containers();
        let evs = self.alerts.evaluate(&self.settings, &servers, &self.statuses, &hosts);
        if let Some(h) = &self.history { for e in &evs { h.add_event(e); } }
        self.new_events.extend(evs);
    }

    pub fn addresses(&self) -> HashMap<String, String> { self.statuses.iter().filter(|(_, s)| !s.address.is_empty()).map(|(k, s)| (k.clone(), s.address.clone())).collect() }
    /// per-host containers: live agent data wins over (older) SSH discovery
    pub fn host_containers(&self) -> HashMap<String, HostContainers> {
        let mut out = HashMap::new();
        for s in &self.store.servers {
            let tel = self.statuses.get(&s.id).and_then(|st| st.telemetry.as_ref());
            if let Some(rows) = tel.and_then(|t| t.containers.as_ref()) {
                let rt = tel.map(|t| if t.runtime.is_empty() { "docker".to_string() } else { t.runtime.clone() }).unwrap_or_else(|| "docker".into());
                let mut cs = containers::from_agent(rows, &rt);
                if let Some(ssh) = self.ssh_containers.get(&s.id) { if !ssh.runtime.is_empty() { for c in cs.iter_mut() { c.runtime = ssh.runtime.clone(); } } }
                out.insert(s.id.clone(), HostContainers { host_id: s.id.clone(), containers: cs, runtime: rt, source: "agent".into(), error: String::new(), fetched: tel.map(|t| t.received).unwrap_or(0.0) });
            } else if let Some(hc) = self.ssh_containers.get(&s.id) { out.insert(s.id.clone(), hc.clone()); }
        }
        out
    }
    pub fn links(&self) -> HashMap<String, Link> {
        let hosts: HashMap<String, HostContainers> = self.host_containers().into_iter().filter(|(_, h)| !h.containers.is_empty()).collect();
        containers::link_servers(&self.store.servers, &hosts, &self.addresses())
    }
    pub fn discover_containers(&mut self, host: &Server, force: bool) -> bool {
        if self.disc_running.contains(&host.id) { return false; }
        if !force && self.disc_next.get(&host.id).map_or(false, |t| Instant::now() < *t) { return false; }
        self.disc_running.insert(host.id.clone());
        let (h, tx, w) = (host.clone(), self.tx.clone(), self.waker.clone());
        std::thread::spawn(move || {
            let (hc, backoff) = match containers::discover(&h) {
                Ok(hc) => { let b = if !hc.error.is_empty() && hc.containers.is_empty() { 600 } else { 60 }; (hc, b) }
                Err(e) => (HostContainers { host_id: h.id.clone(), error: e, fetched: paths::now(), ..Default::default() }, 600),   // probably no key auth: back off
            };
            let _ = tx.send(Msg::Containers(h.id.clone(), hc, backoff)); w();
        });
        true
    }
    pub fn ssh_containers_error(&self, id: &str) -> Option<String> { self.ssh_containers.get(id).map(|h| h.error.clone()).filter(|e| !e.is_empty()) }
    fn auto_discover(&mut self) {
        if !self.disc_running.is_empty() { return; }
        let agent_hosts: HashSet<String> = self.host_containers().into_iter().filter(|(_, h)| h.source == "agent").map(|(k, _)| k).collect();
        let linked: HashSet<String> = self.links().into_keys().collect();
        for host in containers::candidate_hosts(&self.store.servers, &self.addresses()) {
            let online = self.statuses.get(&host.id).map_or(false, |s| s.online);
            if agent_hosts.contains(&host.id) || linked.contains(&host.id) || !online { continue; }
            if self.discover_containers(&host, false) { return; }
        }
    }
    /// cached Minecraft status (refreshed in the background every 20 s while asked for)
    pub fn minecraft(&mut self, host: &str, port: u16) -> Option<Result<Minecraft, String>> {
        let key = format!("{host}:{port}");
        let (checked, value) = self.mc.get(&key).cloned().unwrap_or((Instant::now() - Duration::from_secs(60), None));
        if checked.elapsed() > Duration::from_secs(20) {
            self.mc.insert(key.clone(), (Instant::now(), value.clone()));
            let (h, tx, w) = (host.to_string(), self.tx.clone(), self.waker.clone());
            std::thread::spawn(move || { let r = net::minecraft_ping(&h, port); let _ = tx.send(Msg::Minecraft(key, r)); w(); });
        }
        value
    }
    pub fn summary(&self) -> (usize, usize) { (self.store.servers.iter().filter(|s| self.statuses.get(&s.id).map_or(false, |x| x.online)).count(), self.store.servers.len()) }

    /// run blocking work on a thread; its message shows up in `messages`
    pub fn task(&self, f: impl FnOnce() -> (Level, String, bool) + Send + 'static) {
        let (tx, w) = (self.tx.clone(), self.waker.clone());
        std::thread::spawn(move || { let (l, m, t) = f(); let _ = tx.send(Msg::Done(l, m, t)); w(); });
    }
    pub fn say(&mut self, level: Level, text: impl Into<String>) { self.messages.push((level, text.into())); }
}
