//! argv lists for ssh / sftp / ssh-copy-id (never shell strings), and running a command with captured output.
use super::model::Server;
use std::process::{Command, Stdio};

const HOLD_SCRIPT: &str = r#"
title=$1; pause=$2; shift 2
if [ -n "$title" ]; then printf '\033[1;36m━━ %s ━━\033[0m\n\n' "$title"; fi
"$@"; rc=$?
printf '\033[?1000l\033[?1002l\033[?1003l\033[?1006l\033[?1015l'
if [ "$rc" -ne 0 ] || [ "$pause" = 1 ]; then
  if [ "$rc" -ne 0 ]; then printf '\n\033[1;31m✖ exited with status %s\033[0m' "$rc"; fi
  printf '\n\033[2mPress Enter to close…\033[0m'; read -r _
fi
exit "$rc"
"#;

/// POSIX shell quoting, like Python's shlex.quote
pub fn quote(s: &str) -> String {
    if !s.is_empty() && s.chars().all(|c| c.is_ascii_alphanumeric() || "@%+=:,./-_".contains(c)) { return s.to_string(); }
    format!("'{}'", s.replace('\'', "'\"'\"'"))
}
pub fn display(argv: &[String]) -> String { argv.iter().map(|a| quote(a)).collect::<Vec<_>>().join(" ") }
pub fn base_options(s: &Server, batch: bool) -> Vec<String> {
    let mut o = vec!["-p".to_string(), s.port.to_string()];
    let k = s.key_path(); if !k.is_empty() { o.push("-i".into()); o.push(k); }
    if !s.jump.is_empty() { o.push("-J".into()); o.push(s.jump.clone()); }
    if batch { o.extend(["-o", "BatchMode=yes", "-o", "ConnectTimeout=8"].map(String::from)); }
    o
}
pub fn tmux_remote_command(session: &str) -> String {
    let s = quote(session);
    format!("if command -v tmux >/dev/null 2>&1; then exec tmux new-session -A -s {s}; else echo \"tmux not installed on remote host - starting a normal shell\"; exec \"${{SHELL:-sh}}\" -l; fi")
}
pub fn ssh_command(s: &Server, tmux: Option<bool>, remote: Option<&str>, session: &str) -> Vec<String> {
    let mut a = vec!["ssh".to_string()]; a.extend(base_options(s, false));
    if let Some(r) = remote { a.extend(["-t".to_string(), s.target(), "--".into(), r.to_string()]); }
    else if tmux.unwrap_or(s.tmux) { a.extend(["-t".to_string(), s.target(), "--".into(), tmux_remote_command(session)]); }
    else { a.push(s.target()); }
    a
}
pub fn sftp_command(s: &Server) -> Vec<String> {
    let mut a = vec!["sftp".to_string(), "-P".into(), s.port.to_string()];
    let k = s.key_path(); if !k.is_empty() { a.push("-i".into()); a.push(k); }
    if !s.jump.is_empty() { a.push("-J".into()); a.push(s.jump.clone()); }
    a.push(s.target()); a
}
pub fn public_key_for(s: &Server) -> String {
    let k = s.key_path(); if !k.is_empty() && std::path::Path::new(&format!("{k}.pub")).is_file() { return format!("{k}.pub"); }
    if s.key.ends_with(".pub") { let p = super::paths::expand(&s.key); if p.is_file() { return p.to_string_lossy().into_owned(); } }
    String::new()
}
pub fn copy_id_command(s: &Server) -> Vec<String> {
    let mut a = vec!["ssh-copy-id".to_string(), "-p".into(), s.port.to_string()];
    let pubk = public_key_for(s); if !pubk.is_empty() { a.push("-i".into()); a.push(pubk); }
    if !s.jump.is_empty() { a.push("-o".into()); a.push(format!("ProxyJump={}", s.jump)); }
    a.push(s.target()); a
}
/// keep the terminal open if the command fails (or always, with pause)
pub fn hold(argv: &[String], title: &str, pause: bool) -> Vec<String> {
    let mut a = vec!["sh".to_string(), "-c".into(), HOLD_SCRIPT.into(), "sshm".into(), title.into(), if pause { "1" } else { "0" }.into()]; a.extend_from_slice(argv); a
}
/// run argv with stdin from a file, deleting the file afterwards
pub fn with_stdin_file(argv: &[String], path: &str) -> Vec<String> {
    let mut a = vec!["sh".to_string(), "-c".into(), r#"f=$1; shift; "$@" < "$f"; rc=$?; rm -f "$f"; exit $rc"#.into(), "sshm".into(), path.into()]; a.extend_from_slice(argv); a
}
pub struct Output { pub code: Option<i32>, pub stdout: String, pub stderr: String }
/// run and capture via temp files, so background children (ControlPersist masters, sshfs) holding stdout can't block us
pub fn run_capture(argv: &[String], timeout: f64) -> Result<Output, String> { run_capture_input(argv, timeout, None) }
pub fn run_capture_input(argv: &[String], timeout: f64, input: Option<&str>) -> Result<Output, String> {
    let dir = super::paths::runtime_dir();
    let tag = format!("{}-{}", std::process::id(), super::paths::random_hex(4));
    let (op, ep) = (dir.join(format!(".out-{tag}")), dir.join(format!(".err-{tag}")));
    let (of, ef) = (std::fs::File::create(&op).map_err(|e| e.to_string())?, std::fs::File::create(&ep).map_err(|e| e.to_string())?);
    let mut cmd = Command::new(&argv[0]);
    cmd.args(&argv[1..]).stdout(of).stderr(ef).stdin(if input.is_some() { Stdio::piped() } else { Stdio::null() });
    let mut child = cmd.spawn().map_err(|e| if e.kind() == std::io::ErrorKind::NotFound { format!("{} is not installed", argv[0]) } else { e.to_string() })?;
    if let (Some(i), Some(mut sin)) = (input, child.stdin.take()) { let data = i.to_string(); std::thread::spawn(move || { let _ = std::io::Write::write_all(&mut sin, data.as_bytes()); }); }
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs_f64(timeout);
    let code = loop {
        match child.try_wait() { Ok(Some(s)) => break s.code(), Ok(None) => {}, Err(e) => return Err(e.to_string()) }
        if std::time::Instant::now() > deadline { let _ = child.kill(); let _ = child.wait(); let _ = std::fs::remove_file(&op); let _ = std::fs::remove_file(&ep); return Err(format!("timed out after {timeout:.0}s")); }
        std::thread::sleep(std::time::Duration::from_millis(30));
    };
    let read = |p: &std::path::Path| { let t = String::from_utf8_lossy(&std::fs::read(p).unwrap_or_default()).into_owned(); let _ = std::fs::remove_file(p); t };
    Ok(Output { code, stdout: read(&op), stderr: read(&ep) })
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn quoting() { assert_eq!(quote("abc"), "abc"); assert_eq!(quote("it's"), "'it'\"'\"'s'"); assert_eq!(quote(""), "''"); }
    #[test] fn ssh_argv() { let s = Server { user: "me".into(), host: "h".into(), port: 2222, jump: "b".into(), ..Default::default() };
        assert_eq!(ssh_command(&s, Some(false), None, "sshm"), ["ssh", "-p", "2222", "-J", "b", "me@h"]); }
}
