//! ~/.config/sshm/settings.json. Unknown keys (from newer or older Python versions) are kept untouched on save.
use super::paths;
use serde_json::{Map, Value};

#[derive(Clone, Debug)]
pub struct Settings {
    pub theme: String, pub refresh_interval: u64, pub probe_timeout: f64, pub telemetry_port: u16, pub telemetry_secret: String,
    pub accept_legacy_agents: bool, pub notifications: bool, pub terminal: String, pub mount_dir: String, pub close_to_tray: bool,
    pub tmux_session: String, pub alerts_enabled: bool, pub alert_cpu: f64, pub alert_mem: f64, pub alert_disk: f64,
    pub alert_sustain_minutes: u64, pub alert_offline_grace: u64,
    /// desktop-only: "auto" | "light" | "dark" | "color"
    pub tray_icon_style: String,
    raw: Map<String, Value>,
}
fn s(m: &Map<String, Value>, k: &str, d: &str) -> String { m.get(k).and_then(|v| v.as_str()).map(|x| x.to_string()).unwrap_or_else(|| d.to_string()) }
fn f(m: &Map<String, Value>, k: &str, d: f64) -> f64 { m.get(k).and_then(|v| v.as_f64()).unwrap_or(d) }
fn b(m: &Map<String, Value>, k: &str, d: bool) -> bool { m.get(k).and_then(|v| v.as_bool()).unwrap_or(d) }
pub const REFRESH_CHOICES: [u64; 5] = [5, 10, 30, 60, 0];

impl Settings {
    pub fn load() -> Settings {
        let path = paths::settings_file();
        let existed = path.exists();
        let raw: Map<String, Value> = std::fs::read_to_string(&path).ok().and_then(|t| serde_json::from_str(&t).ok()).unwrap_or_default();
        let m = &raw;
        let mut st = Settings {
            theme: super::themes::get(&s(m, "theme", "Royal Purple")).name.to_string(),
            refresh_interval: f(m, "refresh_interval", 10.0).max(0.0) as u64, probe_timeout: f(m, "probe_timeout", 1.5),
            telemetry_port: f(m, "telemetry_port", 55889.0) as u16, telemetry_secret: s(m, "telemetry_secret", ""),
            accept_legacy_agents: b(m, "accept_legacy_agents", true), notifications: b(m, "notifications", true), terminal: s(m, "terminal", ""),
            mount_dir: s(m, "mount_dir", "~/Network_Servers"), close_to_tray: b(m, "close_to_tray", true), tmux_session: s(m, "tmux_session", "sshm"),
            alerts_enabled: b(m, "alerts_enabled", true), alert_cpu: f(m, "alert_cpu", 90.0), alert_mem: f(m, "alert_mem", 90.0), alert_disk: f(m, "alert_disk", 90.0),
            alert_sustain_minutes: f(m, "alert_sustain_minutes", 5.0) as u64, alert_offline_grace: f(m, "alert_offline_grace", 60.0) as u64,
            tray_icon_style: s(m, "tray_icon_style", "auto"), raw,
        };
        if st.telemetry_secret.is_empty() || !existed { if st.telemetry_secret.is_empty() { st.telemetry_secret = paths::random_hex(24); } st.save(); }
        st
    }
    pub fn save(&self) {
        let mut m = self.raw.clone();
        let num = |x: f64| -> Value { if x.fract() == 0.0 { Value::from(x as i64) } else { serde_json::Number::from_f64(x).map(Value::Number).unwrap_or(Value::Null) } };
        m.insert("theme".into(), self.theme.clone().into()); m.insert("refresh_interval".into(), self.refresh_interval.into());
        m.insert("probe_timeout".into(), serde_json::Number::from_f64(self.probe_timeout).map(Value::Number).unwrap_or(1.5.into()));
        m.insert("telemetry_port".into(), self.telemetry_port.into()); m.insert("telemetry_secret".into(), self.telemetry_secret.clone().into());
        m.insert("accept_legacy_agents".into(), self.accept_legacy_agents.into()); m.insert("notifications".into(), self.notifications.into());
        m.insert("terminal".into(), self.terminal.clone().into()); m.insert("mount_dir".into(), self.mount_dir.clone().into());
        m.insert("close_to_tray".into(), self.close_to_tray.into()); m.insert("tmux_session".into(), self.tmux_session.clone().into());
        m.insert("alerts_enabled".into(), self.alerts_enabled.into()); m.insert("alert_cpu".into(), num(self.alert_cpu)); m.insert("alert_mem".into(), num(self.alert_mem));
        m.insert("alert_disk".into(), num(self.alert_disk)); m.insert("alert_sustain_minutes".into(), self.alert_sustain_minutes.into());
        m.insert("alert_offline_grace".into(), self.alert_offline_grace.into()); m.insert("tray_icon_style".into(), self.tray_icon_style.clone().into());
        if let Ok(t) = serde_json::to_string_pretty(&Value::Object(m)) { let _ = paths::atomic_write(&paths::settings_file(), (t + "\n").as_bytes(), 0o600); }
    }
    pub fn mount_path(&self) -> std::path::PathBuf { paths::expand(&self.mount_dir) }
    /// reread if another process (the Python TUI, or the tray/window) changed the file
    pub fn modified() -> Option<std::time::SystemTime> { std::fs::metadata(paths::settings_file()).and_then(|m| m.modified()).ok() }
}
