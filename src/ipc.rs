//! Tiny line protocol over unix sockets in $XDG_RUNTIME_DIR/sshm, so the tray and the window can find each other.
use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::{UnixListener, UnixStream};
use std::path::Path;
use std::time::Duration;

pub fn send(path: &Path, line: &str) -> std::io::Result<()> {
    let mut s = UnixStream::connect(path)?;
    s.set_write_timeout(Some(Duration::from_millis(500)))?;
    s.write_all(format!("{line}\n").as_bytes())
}
pub fn alive(path: &Path) -> bool { UnixStream::connect(path).is_ok() }
/// listen on `path` (replacing a stale socket) and call `on` for each line received
pub fn serve(path: &Path, on: impl Fn(&str) + Send + 'static) -> bool {
    let _ = std::fs::remove_file(path);
    let Ok(l) = UnixListener::bind(path) else { return false };
    std::thread::spawn(move || {
        for conn in l.incoming().flatten() {
            let _ = conn.set_read_timeout(Some(Duration::from_secs(2)));
            for line in BufReader::new(conn).lines().map_while(Result::ok) { let t = line.trim(); if !t.is_empty() { on(t); } }
        }
    });
    true
}
