//! Availability history and event log in SQLite (~/.local/state/sshm/history.db), same schema as the Python version.
use super::paths;
use rusqlite::{params, Connection};
use std::collections::HashMap;

pub const SAMPLE_EVERY: f64 = 60.0;
pub const KEEP_DAYS: f64 = 30.0;
const SCHEMA: &str = "
CREATE TABLE IF NOT EXISTS samples (server_id TEXT NOT NULL, ts INTEGER NOT NULL, online INTEGER NOT NULL, latency REAL, cpu REAL, mem REAL, disk REAL);
CREATE INDEX IF NOT EXISTS samples_by_server ON samples(server_id, ts);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, server_id TEXT NOT NULL, server_name TEXT NOT NULL,
    kind TEXT NOT NULL, severity TEXT NOT NULL, message TEXT NOT NULL, resolved INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS events_by_ts ON events(ts);
CREATE TABLE IF NOT EXISTS active (server_id TEXT NOT NULL, kind TEXT NOT NULL, since INTEGER NOT NULL, severity TEXT NOT NULL, message TEXT NOT NULL, PRIMARY KEY (server_id, kind));";

#[derive(Clone, Debug)]
pub struct Event { pub ts: f64, pub server_id: String, pub server_name: String, pub kind: String, pub severity: String, pub message: String, pub resolved: bool }
impl Event {
    pub fn time_label(&self) -> String {
        let fmt = if paths::now() - self.ts < 86400.0 { "%H:%M" } else { "%b %d %H:%M" };
        strftime(self.ts, fmt)
    }
}
pub fn strftime(ts: f64, fmt: &str) -> String {
    unsafe {
        let t = ts as libc::time_t; let mut tm: libc::tm = std::mem::zeroed(); libc::localtime_r(&t, &mut tm);
        let mut buf = [0u8; 64]; let f = std::ffi::CString::new(fmt).unwrap();
        let n = libc::strftime(buf.as_mut_ptr() as *mut libc::c_char, buf.len(), f.as_ptr(), &tm);
        String::from_utf8_lossy(&buf[..n]).into_owned()
    }
}
pub fn pct_label(p: Option<f64>) -> String { match p { None => "--".into(), Some(x) if x >= 99.995 => "100%".into(), Some(x) if x >= 99.0 => format!("{x:.2}%"), Some(x) => format!("{x:.1}%") } }

pub struct History { db: Connection, last: HashMap<String, (f64, bool)> }
impl History {
    pub fn open() -> Option<History> {
        let p = paths::history_file(); if let Some(d) = p.parent() { paths::ensure_dir(d, 0o700); }
        let db = Connection::open(&p).ok()?;
        let _ = db.busy_timeout(std::time::Duration::from_secs(5));
        let _ = db.pragma_update(None, "journal_mode", "WAL"); let _ = db.pragma_update(None, "synchronous", "NORMAL");
        db.execute_batch(SCHEMA).ok()?;
        Some(History { db, last: HashMap::new() })
    }
    pub fn record(&mut self, id: &str, online: bool, latency: Option<f64>, cpu: Option<f64>, mem: Option<f64>, disk: Option<f64>) -> bool {
        let now = paths::now();
        if let Some((t, o)) = self.last.get(id) { if now - t < SAMPLE_EVERY && *o == online { return false; } }
        self.last.insert(id.to_string(), (now, online));
        self.db.execute("INSERT INTO samples VALUES (?1,?2,?3,?4,?5,?6,?7)", params![id, now as i64, online as i64, latency, cpu, mem, disk]).is_ok()
    }
    pub fn add_event(&self, e: &Event) {
        let _ = self.db.execute("INSERT INTO events (ts, server_id, server_name, kind, severity, message, resolved) VALUES (?1,?2,?3,?4,?5,?6,?7)",
            params![e.ts as i64, e.server_id, e.server_name, e.kind, e.severity, e.message, e.resolved as i64]);
        if e.resolved { let _ = self.db.execute("DELETE FROM active WHERE server_id=?1 AND kind=?2", params![e.server_id, e.kind]); }
        else { let _ = self.db.execute("INSERT OR REPLACE INTO active VALUES (?1,?2,?3,?4,?5)", params![e.server_id, e.kind, e.ts as i64, e.severity, e.message]); }
    }
    pub fn clear_active(&self) { let _ = self.db.execute("DELETE FROM active", []); }
    pub fn clear_events(&self) { let _ = self.db.execute("DELETE FROM events", []); }
    pub fn prune(&self) { let cut = (paths::now() - KEEP_DAYS * 86400.0) as i64; let _ = self.db.execute("DELETE FROM samples WHERE ts < ?1", [cut]); let _ = self.db.execute("DELETE FROM events WHERE ts < ?1", [cut]); }
    pub fn forget(&self, id: &str) { for t in ["samples", "events", "active"] { let _ = self.db.execute(&format!("DELETE FROM {t} WHERE server_id=?1"), [id]); } }
    /// percent of time online in the window, each sample weighted by how long it held (long unwatched gaps count one minute)
    pub fn uptime(&self, id: &str, secs: f64) -> Option<f64> {
        let now = paths::now(); let start = now - secs;
        let mut st = self.db.prepare_cached("SELECT ts, online FROM samples WHERE server_id=?1 AND ts>=?2 ORDER BY ts").ok()?;
        let rows: Vec<(f64, bool)> = st.query_map(params![id, start as i64], |r| Ok((r.get::<_, i64>(0)? as f64, r.get::<_, i64>(1)? != 0))).ok()?.flatten().collect();
        let prev: Option<bool> = self.db.query_row("SELECT online FROM samples WHERE server_id=?1 AND ts<?2 ORDER BY ts DESC LIMIT 1", params![id, start as i64], |r| Ok(r.get::<_, i64>(0)? != 0)).ok();
        if rows.is_empty() && prev.is_none() { return None; }
        let mut pts: Vec<(f64, bool)> = prev.map(|p| vec![(start, p)]).unwrap_or_default(); pts.extend(rows);
        let (mut up, mut total) = (0.0, 0.0);
        for i in 0..pts.len() {
            let next = if i + 1 < pts.len() { pts[i + 1].0 } else { now };
            let mut span = (next.min(now) - pts[i].0).max(0.0); if span > 3.0 * SAMPLE_EVERY { span = SAMPLE_EVERY; }
            total += span; if pts[i].1 { up += span; }
        }
        if total > 0.0 { Some(100.0 * up / total) } else { None }
    }
    pub fn latency_series(&self, id: &str, secs: f64, buckets: usize) -> Vec<f64> {
        let now = paths::now(); let start = now - secs; let w = secs / buckets as f64;
        let (mut sums, mut counts) = (vec![0.0; buckets], vec![0u32; buckets]);
        if let Ok(mut st) = self.db.prepare_cached("SELECT ts, online, latency FROM samples WHERE server_id=?1 AND ts>=?2") {
            if let Ok(rows) = st.query_map(params![id, start as i64], |r| Ok((r.get::<_, i64>(0)? as f64, r.get::<_, i64>(1)? != 0, r.get::<_, Option<f64>>(2)?))) {
                for (ts, on, lat) in rows.flatten() { if let (true, Some(l)) = (on, lat) { let i = (((ts - start) / w) as usize).min(buckets - 1); sums[i] += l; counts[i] += 1; } }
            }
        }
        (0..buckets).map(|i| if counts[i] > 0 { sums[i] / counts[i] as f64 } else { 0.0 }).collect()
    }
    pub fn events(&self, limit: usize, server: Option<&str>) -> Vec<Event> {
        let q = format!("SELECT ts, server_id, server_name, kind, severity, message, resolved FROM events {} ORDER BY ts DESC, id DESC LIMIT ?1", if server.is_some() { "WHERE server_id=?2" } else { "" });
        let Ok(mut st) = self.db.prepare(&q) else { return vec![] };
        let map = |r: &rusqlite::Row| Ok(Event { ts: r.get::<_, i64>(0)? as f64, server_id: r.get(1)?, server_name: r.get(2)?, kind: r.get(3)?, severity: r.get(4)?, message: r.get(5)?, resolved: r.get::<_, i64>(6)? != 0 });
        match server { Some(s) => st.query_map(params![limit as i64, s], map).map(|r| r.flatten().collect()).unwrap_or_default(), None => st.query_map(params![limit as i64], map).map(|r| r.flatten().collect()).unwrap_or_default() }
    }
    pub fn active(&self) -> Vec<Event> {
        let Ok(mut st) = self.db.prepare("SELECT server_id, kind, since, severity, message FROM active ORDER BY since DESC") else { return vec![] };
        st.query_map([], |r| Ok(Event { server_id: r.get(0)?, kind: r.get(1)?, ts: r.get::<_, i64>(2)? as f64, severity: r.get(3)?, message: r.get(4)?, server_name: String::new(), resolved: false })).map(|r| r.flatten().collect()).unwrap_or_default()
    }
}
