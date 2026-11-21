//! sshm desktop: `sshm-gui` opens the window, `sshm-gui --tray` runs the tray monitor.
//! The tray is the long-running process (telemetry, history, alerts); the window is its own process that comes and goes.
#![allow(clippy::too_many_arguments)]
mod core;
mod hub;
mod icon;
mod ipc;
mod tray;
mod ui;

use core::paths;

const HELP: &str = "sshm-gui — SSH Connection Hub desktop app

  sshm-gui                open the window (starts the tray monitor too)
  sshm-gui --tray         run only the tray monitor
  sshm-gui --no-tray      open the window without starting the tray
  sshm-gui --procs ID     open the process viewer for a server
  sshm-gui --activity     open the alerts & activity log
  sshm-gui --deploy-agent NAME   install / update the telemetry agent on a server (key login)
  sshm-gui --version";

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let has = |f: &str| args.iter().any(|a| a == f);
    let val = |f: &str| args.iter().position(|a| a == f).and_then(|i| args.get(i + 1)).cloned();
    if has("--help") || has("-h") { println!("{HELP}"); return; }
    if has("--version") { println!("sshm-gui {}", env!("CARGO_PKG_VERSION")); return; }
    if let Some(name) = val("--deploy-agent") {
        let store = core::store::Store::load(); let st = core::settings::Settings::load();
        let Some(s) = store.find(&name).cloned() else { eprintln!("No server matches '{name}'"); std::process::exit(1) };
        match core::agent::run_noninteractive(&s, &core::agent::build_installer(&s, &st)) {
            Ok(o) if o.code == Some(0) => println!("{}: {}", s.name, o.stdout.trim().lines().last().unwrap_or("done")),
            Ok(o) => { eprintln!("{}: failed: {}", s.name, o.stderr.trim().lines().last().unwrap_or("error")); std::process::exit(1) }
            Err(e) => { eprintln!("{}: {e}", s.name); std::process::exit(1) }
        }
        return;
    }
    if has("--tray") {
        if ipc::alive(&paths::tray_socket()) { return; }   // already running
        tray::run();
        return;
    }
    // window: if one is open, raise it (and pass along what to show)
    let request = if let Some(id) = val("--procs") { format!("procs {id}") } else if has("--activity") { "activity".into() } else { "raise".into() };
    if ipc::send(&paths::window_socket(), &request).is_ok() { return; }
    if !has("--no-tray") && !ipc::alive(&paths::tray_socket()) {
        let exe = std::env::current_exe().map(|p| p.to_string_lossy().to_string()).unwrap_or_else(|_| "sshm-gui".into());
        let _ = core::terminal::spawn_detached(&[exe, "--tray".into()]);
    }
    ui::run(val("--procs"), has("--activity"));
}
