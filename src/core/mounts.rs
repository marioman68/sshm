//! File-manager bookmarks (Dolphin user-places.xbel + remoteview, GTK bookmarks, a .desktop link) and SSHFS mounts.
use super::model::Server;
use super::settings::Settings;
use super::{paths, sshcmd};
use std::path::PathBuf;

pub fn safe_filename(name: &str) -> String {
    let s: String = name.chars().map(|c| if c.is_alphanumeric() || c == '.' || c == '-' || c == '_' { c } else { '_' }).collect();
    let mut out = String::new(); for c in s.chars() { if !(c == '_' && out.ends_with('_')) { out.push(c); } }
    let t = out.trim_matches('_').to_string(); if t.is_empty() { "server".into() } else { t }
}
fn gtk_file() -> PathBuf { paths::home().join(".config/gtk-3.0/bookmarks") }
fn xbel_file() -> PathBuf { paths::home().join(".local/share/user-places.xbel") }
fn links(s: &Server, st: &Settings) -> Vec<PathBuf> { let f = format!("{}.desktop", safe_filename(&s.name)); vec![st.mount_path().join(&f), paths::home().join(".local/share/remoteview").join(&f)] }
pub fn is_bookmarked(s: &Server, st: &Settings) -> bool {
    if links(s, st).iter().any(|p| p.exists()) { return true; }
    let pre = s.sftp_url_prefix();
    [gtk_file(), xbel_file()].iter().any(|f| std::fs::read_to_string(f).map_or(false, |t| t.contains(&pre)))
}
fn xml_escape(s: &str) -> String { s.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;").replace('"', "&quot;") }
fn xbel_edit(s: &Server, add: bool) {
    let p = xbel_file(); let Ok(text) = std::fs::read_to_string(&p) else { return };
    if !text.contains("</xbel>") { return; }   // never touch a file we don't understand
    let pre = s.sftp_url_prefix(); let has = text.contains(&format!("href=\"{}", xml_escape(&pre)));
    if add == has { return; }
    let backup = p.with_extension("xbel.sshm-backup"); if !backup.exists() { let _ = std::fs::copy(&p, &backup); }
    let new = if add {
        let bm = format!(" <bookmark href=\"{}\">\n  <title>{}</title>\n  <info>\n   <metadata owner=\"http://freedesktop.org\">\n    <bookmark:icon name=\"folder-remote\"/>\n   </metadata>\n   <metadata owner=\"http://www.kde.org\">\n    <ID>{}/sshm-{}</ID>\n    <isSystemItem>false</isSystemItem>\n   </metadata>\n  </info>\n </bookmark>\n",
            xml_escape(&s.sftp_url()), xml_escape(&s.name), paths::now() as i64, safe_filename(&s.name));
        let i = text.rfind("</xbel>").unwrap(); format!("{}{}{}", &text[..i], bm, &text[i..])
    } else {
        let mut t = text.clone(); let needle = format!("<bookmark href=\"{}", xml_escape(&pre));
        while let Some(st) = t.find(&needle) {
            let Some(end) = t[st..].find("</bookmark>").map(|e| st + e + "</bookmark>".len()) else { break };
            let line_start = t[..st].rfind('\n').map(|i| i + 1).unwrap_or(st); let line_end = if t[end..].starts_with('\n') { end + 1 } else { end };
            t.replace_range(line_start..line_end, "");
        }
        t
    };
    let _ = paths::atomic_write(&p, new.as_bytes(), 0o644);
}
pub fn toggle_bookmark(s: &Server, st: &Settings) -> Result<bool, String> {
    if is_bookmarked(s, st) {
        for l in links(s, st) { let _ = std::fs::remove_file(l); }
        if let Ok(t) = std::fs::read_to_string(gtk_file()) { let lines: Vec<&str> = t.lines().filter(|l| !l.starts_with(&s.sftp_url_prefix())).collect(); let _ = paths::atomic_write(&gtk_file(), (lines.join("\n") + if lines.is_empty() { "" } else { "\n" }).as_bytes(), 0o644); }
        xbel_edit(s, false); Ok(false)
    } else {
        let desktop = format!("[Desktop Entry]\nType=Link\nIcon=folder-remote\nName={} ({})\nURL[$e]={}\n", s.name, s.target(), s.sftp_url());
        for l in links(s, st) { if let Some(d) = l.parent() { paths::ensure_dir(d, 0o755); } paths::atomic_write(&l, desktop.as_bytes(), 0o755).map_err(|e| e.to_string())?; }
        let t = std::fs::read_to_string(gtk_file()).unwrap_or_default(); let mut lines: Vec<String> = t.lines().map(String::from).collect();
        if !lines.iter().any(|l| l.starts_with(&s.sftp_url_prefix())) { lines.push(format!("{} {}", s.sftp_url(), s.name)); let _ = paths::atomic_write(&gtk_file(), (lines.join("\n") + "\n").as_bytes(), 0o644); }
        xbel_edit(s, true); Ok(true)
    }
}
pub fn sshfs_available() -> bool { paths::which("sshfs").is_some() }
pub fn mountpoint(s: &Server, st: &Settings) -> PathBuf { st.mount_path().join(safe_filename(&s.name)) }
pub fn is_mounted(s: &Server, st: &Settings) -> bool {
    let mp = mountpoint(s, st).to_string_lossy().to_string();
    std::fs::read_to_string("/proc/self/mounts").map_or(false, |t| t.lines().any(|l| { let p: Vec<&str> = l.split_whitespace().collect(); p.len() > 2 && p[2].contains("sshfs") && p[1].replace("\\040", " ") == mp }))
}
pub fn mount(s: &Server, st: &Settings) -> Result<String, String> {
    if !sshfs_available() { return Err("sshfs is not installed".into()); }
    let mp = mountpoint(s, st); paths::ensure_dir(&mp, 0o755);
    let mut a = vec!["sshfs".to_string(), format!("{}:{}", s.target(), s.home_path()), mp.to_string_lossy().into(), "-p".into(), s.port.to_string(), "-o".into(), "reconnect,ServerAliveInterval=15,ServerAliveCountMax=3,BatchMode=yes,follow_symlinks".into()];
    let k = s.key_path(); if !k.is_empty() { a.push("-o".into()); a.push(format!("IdentityFile={k}")); }
    if !s.jump.is_empty() { a.push("-o".into()); a.push(format!("ssh_command=ssh -J {}", s.jump)); }
    let o = sshcmd::run_capture(&a, 25.0)?;
    if o.code != Some(0) { let m = if o.stderr.trim().is_empty() { &o.stdout } else { &o.stderr }; return Err(m.trim().lines().last().map(|s| s.to_string()).unwrap_or_else(|| "sshfs failed".into()) + " — SSHFS needs key-based login (use Push SSH key)"); }
    Ok(format!("Mounted at {}", mp.display()))
}
pub fn unmount(s: &Server, st: &Settings) -> Result<String, String> {
    let mp = mountpoint(s, st).to_string_lossy().to_string();
    for tool in [vec!["fusermount3", "-u"], vec!["fusermount", "-u"], vec!["umount"]] {
        if paths::which(tool[0]).is_none() { continue; }
        let o = std::process::Command::new(tool[0]).args(&tool[1..]).arg(&mp).output().map_err(|e| e.to_string())?;
        if o.status.success() { let _ = std::fs::remove_dir(&mp); return Ok("Unmounted".into()); }
        return Err(String::from_utf8_lossy(&o.stderr).trim().to_string());
    }
    Err("no unmount tool found".into())
}
