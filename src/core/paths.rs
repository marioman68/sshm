//! XDG locations, shared with the Python sshm (same env overrides: SSHM_CONFIG_DIR, SSHM_RUNTIME_DIR, SSHM_STATE_DIR).
use std::fs;
use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};

pub fn home() -> PathBuf { std::env::var_os("HOME").map(PathBuf::from).unwrap_or_else(|| PathBuf::from("/")) }
fn env_dir(over: &str, xdg: &str, fallback: &str) -> PathBuf {
    if let Some(o) = std::env::var_os(over).filter(|v| !v.is_empty()) { return PathBuf::from(o); }
    std::env::var_os(xdg).filter(|v| !v.is_empty()).map(PathBuf::from).unwrap_or_else(|| home().join(fallback)).join("sshm")
}
pub fn config_dir() -> PathBuf { env_dir("SSHM_CONFIG_DIR", "XDG_CONFIG_HOME", ".config") }
pub fn state_dir() -> PathBuf { env_dir("SSHM_STATE_DIR", "XDG_STATE_HOME", ".local/state") }
pub fn uid() -> u32 { unsafe { libc::getuid() } }
pub fn runtime_dir() -> PathBuf {
    let p = if let Some(o) = std::env::var_os("SSHM_RUNTIME_DIR").filter(|v| !v.is_empty()) { PathBuf::from(o) } else {
        match std::env::var_os("XDG_RUNTIME_DIR").map(PathBuf::from) { Some(b) if b.is_dir() => b.join("sshm"), _ => PathBuf::from(format!("/tmp/sshm-{}", uid())) }
    };
    ensure_dir(&p, 0o700); p
}
pub fn servers_file() -> PathBuf { config_dir().join("servers.json") }
pub fn settings_file() -> PathBuf { config_dir().join("settings.json") }
pub fn history_file() -> PathBuf { state_dir().join("history.db") }
pub fn telemetry_cache_file() -> PathBuf { runtime_dir().join("telemetry.json") }
pub fn tunnels_file() -> PathBuf { runtime_dir().join("tunnels.json") }
pub fn tray_socket() -> PathBuf { runtime_dir().join("desktop-tray.sock") }
pub fn window_socket() -> PathBuf { runtime_dir().join("desktop-window.sock") }

pub fn ensure_dir(p: &Path, mode: u32) { if !p.exists() { let _ = fs::create_dir_all(p); let _ = fs::set_permissions(p, fs::Permissions::from_mode(mode)); } }
pub fn expand(s: &str) -> PathBuf {
    let s = s.trim();
    if s == "~" { return home(); }
    if let Some(r) = s.strip_prefix("~/") { return home().join(r); }
    let mut out = String::new(); let mut rest = s;
    while let Some(i) = rest.find('$') {   // $VAR and ${VAR}, like os.path.expandvars
        out.push_str(&rest[..i]); let r = &rest[i + 1..];
        let (name, used) = if let Some(b) = r.strip_prefix('{') { match b.find('}') { Some(e) => (&b[..e], e + 2), None => ("", 0) } } else { let e = r.find(|c: char| !(c.is_alphanumeric() || c == '_')).unwrap_or(r.len()); (&r[..e], e) };
        if name.is_empty() { out.push('$'); rest = r; continue; }
        match std::env::var(name) { Ok(v) => out.push_str(&v), Err(_) => { out.push('$'); out.push_str(&r[..used]); } }
        rest = &r[used..];
    }
    out.push_str(rest); PathBuf::from(out)
}
/// write via temp file + fsync + rename, like the Python atomic_write_text
pub fn atomic_write(path: &Path, data: &[u8], mode: u32) -> std::io::Result<()> {
    if let Some(d) = path.parent() { ensure_dir(d, 0o700); }
    let tmp = path.with_file_name(format!(".{}.{}.tmp", path.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_default(), std::process::id()));
    { let mut f = fs::File::create(&tmp)?; f.write_all(data)?; f.sync_all()?; }
    fs::set_permissions(&tmp, fs::Permissions::from_mode(mode))?;
    fs::rename(&tmp, path).map_err(|e| { let _ = fs::remove_file(&tmp); e })
}
/// exclusive advisory lock on ".<name>.lock" next to the file (same lock file the Python code uses)
pub struct Lock(fs::File);
impl Drop for Lock { fn drop(&mut self) { unsafe { libc::flock(std::os::fd::AsRawFd::as_raw_fd(&self.0), libc::LOCK_UN); } } }
pub fn lock(path: &Path) -> Option<Lock> {
    let lp = path.with_file_name(format!(".{}.lock", path.file_name()?.to_string_lossy()));
    if let Some(d) = lp.parent() { ensure_dir(d, 0o700); }
    let f = fs::OpenOptions::new().create(true).append(true).read(true).open(lp).ok()?;
    unsafe { libc::flock(std::os::fd::AsRawFd::as_raw_fd(&f), libc::LOCK_EX); }
    Some(Lock(f))
}
pub fn random_hex(bytes: usize) -> String {
    let mut b = vec![0u8; bytes];
    if let Ok(mut f) = fs::File::open("/dev/urandom") { let _ = std::io::Read::read_exact(&mut f, &mut b); }
    hex::encode(b)
}
pub fn now() -> f64 { std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0) }
pub fn which(cmd: &str) -> Option<PathBuf> {
    if cmd.contains('/') { let p = PathBuf::from(cmd); return if p.is_file() { Some(p) } else { None }; }
    std::env::var_os("PATH").and_then(|path| std::env::split_paths(&path).map(|d| d.join(cmd)).find(|p| p.is_file() && fs::metadata(p).map(|m| m.permissions().mode() & 0o111 != 0).unwrap_or(false)))
}
