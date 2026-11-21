//! Server profiles, matching the Python dataclass field for field. Unknown keys are carried along unchanged.
use serde_json::{Map, Value};

#[derive(Clone, Debug, PartialEq)]
pub struct Command { pub label: String, pub command: String }

#[derive(Clone, Debug, PartialEq)]
pub struct Server {
    pub name: String, pub host: String, pub user: String, pub port: u16, pub tag: String, pub mac: String, pub key: String, pub jump: String,
    pub remote_path: String, pub tmux: bool, pub tray: bool, pub favorite: bool, pub notes: String, pub commands: Vec<Command>, pub id: String,
    pub last_connected: f64, pub extra: Map<String, Value>,
}
pub fn new_id() -> String { super::paths::random_hex(6) }

impl Default for Server {
    fn default() -> Self {
        Server { name: String::new(), host: String::new(), user: String::new(), port: 22, tag: String::new(), mac: String::new(), key: String::new(), jump: String::new(),
            remote_path: String::new(), tmux: false, tray: true, favorite: false, notes: String::new(), commands: vec![], id: new_id(), last_connected: 0.0, extra: Map::new() }
    }
}

/// "aa:bb:cc:dd:ee:ff" or "" (Err for garbage)
pub fn normalize_mac(v: &str) -> Result<String, String> {
    let raw: String = v.to_lowercase().chars().filter(|c| !matches!(c, ' ' | ':' | '.' | '-' | '\t')).collect();
    if raw.is_empty() { return Ok(String::new()); }
    if raw.len() != 12 || !raw.chars().all(|c| c.is_ascii_hexdigit()) { return Err(format!("'{v}' is not a valid MAC address")); }
    Ok((0..6).map(|i| &raw[i * 2..i * 2 + 2]).collect::<Vec<_>>().join(":"))
}

impl Server {
    pub fn target(&self) -> String { if self.user.is_empty() { self.host.clone() } else { format!("{}@{}", self.user, self.host) } }
    pub fn endpoint(&self) -> String { format!("{}:{}", self.target(), self.port) }
    /// expanded identity file, or "" if unset or missing
    pub fn key_path(&self) -> String { if self.key.is_empty() { return String::new(); } let p = super::paths::expand(&self.key); if p.is_file() { p.to_string_lossy().into_owned() } else { String::new() } }
    pub fn home_path(&self) -> String {
        if !self.remote_path.is_empty() { return if self.remote_path.starts_with('/') { self.remote_path.clone() } else { format!("/{}", self.remote_path) }; }
        if self.user == "root" { return "/root".into(); }
        if self.user.is_empty() { "/".into() } else { format!("/home/{}", self.user) }
    }
    pub fn sftp_url_prefix(&self) -> String { let who = if self.user.is_empty() { String::new() } else { format!("{}@", self.user) }; format!("sftp://{who}{}:{}/", self.host, self.port) }
    pub fn sftp_url(&self) -> String { format!("{}{}", self.sftp_url_prefix(), self.home_path().trim_start_matches('/')) }
    pub fn search_text(&self) -> String { [&self.name, &self.host, &self.user, &self.tag, &self.notes].iter().filter(|s| !s.is_empty()).map(|s| s.as_str()).collect::<Vec<_>>().join(" ") }
    pub fn validate(&self) -> Vec<String> {
        let mut e = vec![];
        if self.name.trim().is_empty() { e.push("Name is required".to_string()); }
        if self.host.trim().is_empty() { e.push("Host is required".into()); }
        if self.host.trim().chars().any(char::is_whitespace) { e.push("Host must not contain spaces".into()); }
        if self.port == 0 { e.push("Port must be between 1 and 65535".into()); }
        if let Err(m) = normalize_mac(&self.mac) { e.push(m); }
        if [&self.name, &self.host, &self.user, &self.tag, &self.key, &self.jump].iter().any(|v| v.contains('\n') || v.contains('\r')) { e.push("Fields must not contain line breaks".into()); }
        e
    }
    pub fn to_json(&self) -> Value {
        let mut m = self.extra.clone();
        let cmds: Vec<Value> = self.commands.iter().map(|c| serde_json::json!({"label": c.label, "command": c.command})).collect();
        for (k, v) in [("name", Value::from(self.name.clone())), ("host", self.host.clone().into()), ("user", self.user.clone().into()), ("port", self.port.into()),
            ("tag", self.tag.clone().into()), ("mac", self.mac.clone().into()), ("key", self.key.clone().into()), ("jump", self.jump.clone().into()),
            ("remote_path", self.remote_path.clone().into()), ("tmux", self.tmux.into()), ("tray", self.tray.into()), ("favorite", self.favorite.into()),
            ("notes", self.notes.clone().into()), ("commands", Value::Array(cmds)), ("id", self.id.clone().into()),
            ("last_connected", serde_json::Number::from_f64(self.last_connected).map(Value::Number).unwrap_or(Value::from(0.0)))] { m.insert(k.into(), v); }
        Value::Object(m)
    }
    pub fn from_json(v: &Value) -> Option<Server> {
        let m = v.as_object()?;
        let st = |k: &str| m.get(k).map(|x| match x { Value::String(s) => s.trim().to_string(), Value::Null => String::new(), o => o.to_string() }).unwrap_or_default();
        let bl = |k: &str, d: bool| m.get(k).map(|x| match x { Value::Bool(b) => *b, Value::Number(n) => n.as_f64().unwrap_or(0.0) != 0.0, Value::String(s) => !s.is_empty(), _ => false }).unwrap_or(d);
        const KNOWN: [&str; 16] = ["name", "host", "user", "port", "tag", "mac", "key", "jump", "remote_path", "tmux", "tray", "favorite", "notes", "commands", "id", "last_connected"];
        let port = m.get("port").and_then(|p| p.as_u64().or_else(|| p.as_str().and_then(|s| s.trim().parse().ok()))).filter(|p| (1..=65535).contains(p)).unwrap_or(22) as u16;
        let commands = m.get("commands").and_then(|c| c.as_array()).map(|a| a.iter().filter_map(|c| { let o = c.as_object()?; let label = o.get("label")?.as_str()?.trim().to_string();
            let command = o.get("command").or_else(|| o.get("cmd")).and_then(|x| x.as_str()).unwrap_or("").trim().to_string(); if label.is_empty() || command.is_empty() { None } else { Some(Command { label, command }) } }).collect()).unwrap_or_default();
        let id = st("id");
        Some(Server { name: st("name"), host: st("host"), user: st("user"), port, tag: st("tag"), mac: normalize_mac(&st("mac")).unwrap_or_default(), key: st("key"), jump: st("jump"),
            remote_path: st("remote_path"), tmux: bl("tmux", false), tray: bl("tray", true), favorite: bl("favorite", false), notes: st("notes"), commands,
            id: if id.is_empty() { new_id() } else { id }, last_connected: m.get("last_connected").and_then(|x| x.as_f64()).unwrap_or(0.0),
            extra: m.iter().filter(|(k, _)| !KNOWN.contains(&k.as_str())).map(|(k, v)| (k.clone(), v.clone())).collect() })
    }
}

/// 0 = no match. Substring hits rank highest (earlier is better); otherwise each query char must start a word, in order.
pub fn fuzzy_score(query: &str, text: &str) -> i32 {
    let q = query.trim().to_lowercase(); if q.is_empty() { return 1; }
    let t = text.to_lowercase();
    if let Some(pos) = t.find(&q) { return 1000 - t[..pos].chars().count() as i32; }
    let tc: Vec<char> = t.chars().collect();
    let starts: Vec<usize> = (0..tc.len()).filter(|&i| tc[i].is_alphanumeric() && (i == 0 || !tc[i - 1].is_alphanumeric())).collect();
    let mut ti = 0;
    for ch in q.chars() { while ti < starts.len() && tc[starts[ti]] != ch { ti += 1; } if ti == starts.len() { return 0; } ti += 1; }
    100
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn mac() { assert_eq!(normalize_mac("AA-BB-CC-DD-EE-FF").unwrap(), "aa:bb:cc:dd:ee:ff"); assert!(normalize_mac("zz").is_err()); assert_eq!(normalize_mac("").unwrap(), ""); }
    #[test] fn fuzzy() { assert_eq!(fuzzy_score("nas", "home nas"), 995); assert_eq!(fuzzy_score("hl", "home-lab box"), 100); assert_eq!(fuzzy_score("xq", "home lab"), 0); }
    #[test] fn roundtrip_keeps_unknown() {
        let v: Value = serde_json::from_str(r#"{"name":"n","host":"h","port":"2222","future_field":[1,2],"commands":[{"label":"a","cmd":"ls"},{"label":"","command":"x"}]}"#).unwrap();
        let s = Server::from_json(&v).unwrap(); assert_eq!(s.port, 2222); assert_eq!(s.commands.len(), 1); assert_eq!(s.commands[0].command, "ls");
        assert_eq!(s.to_json()["future_field"], serde_json::json!([1, 2])); assert!(s.tray);
    }
    #[test] fn paths() { let s = Server { user: "root".into(), host: "h".into(), port: 2222, ..Default::default() }; assert_eq!(s.sftp_url(), "sftp://root@h:2222/root"); }
}
