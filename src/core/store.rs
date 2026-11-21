//! ~/.config/sshm/servers.json, shared with the Python TUI/CLI: locked, atomic writes; reloads when another process changes it.
use super::model::{fuzzy_score, Server};
use super::paths;
use serde_json::{Map, Value};
use std::time::SystemTime;

pub struct Store { pub servers: Vec<Server>, mtime: Option<SystemTime>, top: Map<String, Value>, pub error: Option<String> }

impl Store {
    pub fn load() -> Store { let mut s = Store { servers: vec![], mtime: None, top: Map::new(), error: None }; s.reload(); s }
    fn stat() -> Option<SystemTime> { std::fs::metadata(paths::servers_file()).and_then(|m| m.modified()).ok() }
    pub fn reload(&mut self) {
        let p = paths::servers_file();
        self.mtime = Self::stat();
        let Ok(text) = std::fs::read_to_string(&p) else { self.servers.clear(); return };
        match serde_json::from_str::<Value>(if text.trim().is_empty() { "{}" } else { &text }) {
            Ok(v) => {
                let items = match &v { Value::Object(m) => { self.top = m.clone(); m.get("servers").and_then(|s| s.as_array()).cloned().unwrap_or_default() } Value::Array(a) => a.clone(), _ => vec![] };
                self.servers = items.iter().filter_map(Server::from_json).filter(|s| !s.name.is_empty() && !s.host.is_empty()).collect();
                self.error = None;
            }
            Err(e) => self.error = Some(format!("Could not read {}: {e}", p.display())),   // never overwrite a file we can't read
        }
    }
    pub fn reload_if_changed(&mut self) -> bool { if Self::stat() != self.mtime { self.reload(); true } else { false } }
    pub fn save(&mut self) -> Result<(), String> {
        if let Some(e) = &self.error { return Err(e.clone()); }
        let p = paths::servers_file();
        let _l = paths::lock(&p);
        let mut top = self.top.clone();
        top.insert("version".into(), 1.into());
        top.insert("servers".into(), Value::Array(self.servers.iter().map(|s| s.to_json()).collect()));
        let text = serde_json::to_string_pretty(&Value::Object(top)).map_err(|e| e.to_string())? + "\n";
        paths::atomic_write(&p, text.as_bytes(), 0o600).map_err(|e| format!("Could not save servers: {e}"))?;
        self.mtime = Self::stat();
        Ok(())
    }
    pub fn get(&self, id: &str) -> Option<&Server> { self.servers.iter().find(|s| s.id == id) }
    pub fn by_name(&self, name: &str) -> Option<&Server> { let n = name.trim().to_lowercase(); self.servers.iter().find(|s| s.name.to_lowercase() == n) }
    pub fn tags(&self) -> Vec<String> { let mut t: Vec<String> = self.servers.iter().map(|s| s.tag.clone()).filter(|t| !t.is_empty()).collect(); t.sort_by_key(|x| x.to_lowercase()); t.dedup(); t }
    fn check(&self, s: &Server) -> Result<(), String> {
        let e = s.validate(); if !e.is_empty() { return Err(e.join("; ")); }
        if let Some(c) = self.by_name(&s.name) { if c.id != s.id { return Err(format!("A server named '{}' already exists", s.name)); } }
        Ok(())
    }
    pub fn add(&mut self, s: Server) -> Result<(), String> { self.check(&s)?; self.servers.push(s); self.save() }
    pub fn update(&mut self, s: Server) -> Result<(), String> {
        self.check(&s)?;
        match self.servers.iter_mut().find(|x| x.id == s.id) { Some(x) => { *x = s; self.save() } None => Err(format!("Unknown server id {}", s.id)) }
    }
    pub fn remove(&mut self, id: &str) -> Result<(), String> { let n = self.servers.len(); self.servers.retain(|s| s.id != id); if n != self.servers.len() { self.save() } else { Ok(()) } }
    pub fn mark_connected(&mut self, id: &str) { if let Some(s) = self.servers.iter_mut().find(|s| s.id == id) { s.last_connected = paths::now(); let _ = self.save(); } }
    pub fn unique_name(&self, base: &str) -> String { let mut n = 2; let mut name = base.to_string(); while self.by_name(&name).is_some() { name = format!("{base}-{n}"); n += 1; } name }
    #[allow(dead_code)]
    pub fn find(&self, q: &str) -> Option<&Server> {
        if let Some(s) = self.by_name(q) { return Some(s); }
        let ql = q.to_lowercase(); let pre: Vec<&Server> = self.servers.iter().filter(|s| s.name.to_lowercase().starts_with(&ql)).collect();
        if pre.len() == 1 { return Some(pre[0]); }
        let c: Vec<&Server> = if pre.is_empty() { self.servers.iter().filter(|s| fuzzy_score(&ql, &s.search_text()) > 0).collect() } else { pre };
        if c.len() == 1 { Some(c[0]) } else { None }
    }
}
