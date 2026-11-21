//! Find the user's terminal emulator (Settings, $TERMINAL, KDE/GNOME defaults, then common ones) and run argv in it.
use super::paths;

fn prefix(name: &str) -> Option<Vec<&'static str>> {
    Some(match name {
        "xdg-terminal-exec" | "foot" | "footclient" | "kitty" | "contour" => vec![], "yakuake" => return None, "wezterm" => vec!["start", "--"],
        "ptyxis" | "gnome-terminal" | "kgx" | "gnome-console" => vec!["--"], "terminator" | "xfce4-terminal" | "mate-terminal" => vec!["-x"], _ => vec!["-e"],
    })
}
const ORDER: [&str; 19] = ["xdg-terminal-exec", "konsole", "ptyxis", "kgx", "gnome-terminal", "ghostty", "kitty", "wezterm", "alacritty", "foot", "cosmic-term", "xfce4-terminal", "tilix", "terminator", "mate-terminal", "lxterminal", "qterminal", "x-terminal-emulator", "xterm"];
fn split(s: &str) -> Vec<String> { s.split_whitespace().map(|x| x.trim_matches(|c| c == '\'' || c == '"').to_string()).collect() }
fn normalize(parts: Vec<String>) -> Option<Vec<String>> {
    let first = parts.first()?; paths::which(first)?;
    if parts.len() > 1 { return Some(parts); }
    let name = std::path::Path::new(first).file_name()?.to_string_lossy().to_string();
    let mut v = vec![first.clone()]; v.extend(prefix(&name)?.into_iter().map(String::from)); Some(v)
}
fn kde() -> Option<Vec<String>> {
    let t = std::fs::read_to_string(paths::home().join(".config/kdeglobals")).ok()?;
    let mut in_general = false;
    for l in t.lines() { let l = l.trim(); if l.starts_with('[') { in_general = l == "[General]"; continue; } if in_general { if let Some(v) = l.strip_prefix("TerminalApplication=") { return normalize(split(v).into_iter().take(1).collect()); } } }
    None
}
fn gsettings() -> Option<Vec<String>> {
    for schema in ["org.gnome.desktop.default-applications.terminal", "org.cinnamon.desktop.default-applications.terminal", "org.mate.applications-terminal"] {
        let o = std::process::Command::new("gsettings").args(["get", schema, "exec"]).output().ok()?;
        let v = String::from_utf8_lossy(&o.stdout).trim().trim_matches('\'').to_string();
        if o.status.success() && !v.is_empty() { if let Some(f) = normalize(split(&v).into_iter().take(1).collect()) { return Some(f); } }
    }
    None
}
pub fn resolve(over: &str) -> Result<Vec<String>, String> {
    if !over.trim().is_empty() { if let Some(f) = normalize(split(over)) { return Ok(f); } }
    let de = std::env::var("XDG_CURRENT_DESKTOP").unwrap_or_default().to_uppercase();
    if let Ok(t) = std::env::var("TERMINAL") { if let Some(f) = normalize(split(&t)) { return Ok(f); } }
    if de.contains("KDE") { if let Some(f) = kde() { return Ok(f); } }
    if ["GNOME", "CINNAMON", "MATE", "BUDGIE", "UNITY", "PANTHEON"].iter().any(|d| de.contains(d)) { if let Some(f) = gsettings() { return Ok(f); } }
    if let Some(f) = kde() { return Ok(f); }
    for n in ORDER { if let Some(f) = normalize(vec![n.to_string()]) { return Ok(f); } }
    Err("No terminal emulator found. Set one in Settings → Terminal.".into())
}
pub fn launch(argv: &[String], over: &str) -> Result<(), String> {
    let mut full = resolve(over)?; full.extend_from_slice(argv);
    spawn_detached(&full)
}
/// start a program in its own session, detached from us (it outlives the tray and the window)
pub fn spawn_detached(argv: &[String]) -> Result<(), String> {
    use std::os::unix::process::CommandExt;
    let mut c = std::process::Command::new(&argv[0]);
    c.args(&argv[1..]).stdin(std::process::Stdio::null()).stdout(std::process::Stdio::null()).stderr(std::process::Stdio::null()).env_remove("SSHM_TUI");
    unsafe { c.pre_exec(|| { libc::setsid(); Ok(()) }); }
    match c.spawn() { Ok(mut ch) => { std::thread::spawn(move || { let _ = ch.wait(); }); Ok(()) } Err(e) => Err(format!("Could not start {}: {e}", argv[0])) }
}
pub fn xdg_open(target: &str) -> bool { paths::which("xdg-open").is_some() && spawn_detached(&["xdg-open".to_string(), target.to_string()]).is_ok() }
