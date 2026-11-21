//! `sshm-gui --tray`: the always-on monitor. Owns the telemetry port, records history, raises alerts and notifications,
//! and shows a native StatusNotifierItem (KDE's own tray protocol; GNOME shows it with the AppIndicator extension).
use crate::core::{mounts, net, paths, procs, sshcmd, terminal};
use crate::hub::{Hub, Level};
use crate::icon::{self, State, Style};
use crate::ipc;
use ksni::blocking::TrayMethods;
use ksni::menu::{StandardItem, SubMenu};
use ksni::MenuItem;
use std::sync::mpsc::{channel, Receiver, Sender};
use std::sync::Arc;
use std::time::{Duration, Instant};

#[derive(Debug)]
pub enum Cmd { Open, OpenProcs(String), Activity, Tui, Connect(String, bool), Sftp(String), Files(String), Run(String, usize), Wake(String), Htop(String), Refresh, Quit }

#[derive(Clone)]
struct Row { id: String, name: String, label: String, dot: (u8, u8, u8), hollow: bool, endpoint: String, lines: Vec<String>, commands: Vec<String>, mac: bool }

pub struct SshmTray {
    tx: Sender<Cmd>, icon: Vec<ksni::Icon>, tooltip: (String, String), rows: Vec<Row>, events: Vec<String>, active: usize, open_icon: Vec<u8>,
}
fn std_item(label: &str, icon: &str, f: impl Fn(&mut SshmTray) + Send + 'static) -> MenuItem<SshmTray> {
    StandardItem { label: label.into(), icon_name: icon.into(), activate: Box::new(f), ..Default::default() }.into()
}
fn info(label: String) -> MenuItem<SshmTray> { StandardItem { label, enabled: false, ..Default::default() }.into() }

impl ksni::Tray for SshmTray {
    fn id(&self) -> String { "sshm".into() }
    fn title(&self) -> String { "sshm".into() }
    fn category(&self) -> ksni::Category { ksni::Category::SystemServices }
    fn icon_pixmap(&self) -> Vec<ksni::Icon> { self.icon.clone() }
    fn tool_tip(&self) -> ksni::ToolTip { ksni::ToolTip { title: self.tooltip.0.clone(), description: self.tooltip.1.clone(), icon_name: String::new(), icon_pixmap: vec![] } }
    fn activate(&mut self, _x: i32, _y: i32) { let _ = self.tx.send(Cmd::Open); }
    fn menu(&self) -> Vec<MenuItem<Self>> {
        let mut m: Vec<MenuItem<Self>> = vec![];
        m.push(StandardItem { label: "Open sshm".into(), icon_data: self.open_icon.clone(), activate: Box::new(|t: &mut Self| { let _ = t.tx.send(Cmd::Open); }), ..Default::default() }.into());
        m.push(std_item("Open terminal UI", "utilities-terminal", |t| { let _ = t.tx.send(Cmd::Tui); }));
        m.push(MenuItem::Separator);
        if self.rows.is_empty() { m.push(info("No servers monitored in the tray".into())); }
        for r in &self.rows {
            let mut sub: Vec<MenuItem<Self>> = vec![info(r.endpoint.clone())];
            for l in &r.lines { sub.push(info(l.clone())); }
            sub.push(MenuItem::Separator);
            let id = r.id.clone(); sub.push(std_item("Connect", "utilities-terminal", move |t| { let _ = t.tx.send(Cmd::Connect(id.clone(), false)); }));
            let id = r.id.clone(); sub.push(std_item("Connect in tmux", "", move |t| { let _ = t.tx.send(Cmd::Connect(id.clone(), true)); }));
            let id = r.id.clone(); sub.push(std_item("Open files", "folder-remote", move |t| { let _ = t.tx.send(Cmd::Files(id.clone())); }));
            let id = r.id.clone(); sub.push(std_item("SFTP shell", "", move |t| { let _ = t.tx.send(Cmd::Sftp(id.clone())); }));
            let id = r.id.clone(); sub.push(std_item("Processes…", "utilities-system-monitor", move |t| { let _ = t.tx.send(Cmd::OpenProcs(id.clone())); }));
            let id = r.id.clone(); sub.push(std_item("htop", "", move |t| { let _ = t.tx.send(Cmd::Htop(id.clone())); }));
            if !r.commands.is_empty() {
                let cmds: Vec<MenuItem<Self>> = r.commands.iter().enumerate().map(|(i, c)| { let id = r.id.clone(); std_item(c, "system-run", move |t| { let _ = t.tx.send(Cmd::Run(id.clone(), i)); }) }).collect();
                sub.push(SubMenu { label: "Saved commands".into(), icon_name: "system-run".into(), submenu: cmds, ..Default::default() }.into());
            }
            if r.mac { let id = r.id.clone(); sub.push(std_item("Wake-on-LAN", "system-suspend", move |t| { let _ = t.tx.send(Cmd::Wake(id.clone())); })); }
            m.push(SubMenu { label: format!("{}    {}", r.name, r.label), icon_data: icon::dot_png(r.dot, r.hollow), submenu: sub, ..Default::default() }.into());
        }
        m.push(MenuItem::Separator);
        let mut alerts: Vec<MenuItem<Self>> = if self.events.is_empty() { vec![info("Nothing recorded yet".into())] } else { self.events.iter().map(|e| info(e.clone())).collect() };
        alerts.push(MenuItem::Separator);
        alerts.push(std_item("Open activity log…", "view-list-details", |t| { let _ = t.tx.send(Cmd::Activity); }));
        let label = if self.active > 0 { format!("Alerts ({} active)", self.active) } else { "Recent activity".into() };
        m.push(SubMenu { label, icon_name: if self.active > 0 { "dialog-warning".into() } else { String::new() }, submenu: alerts, ..Default::default() }.into());
        m.push(std_item("Refresh now", "view-refresh", |t| { let _ = t.tx.send(Cmd::Refresh); }));
        m.push(std_item("Quit sshm", "application-exit", |t| { let _ = t.tx.send(Cmd::Quit); }));
        m
    }
}

fn icon_set(style: Style, state: State) -> Vec<ksni::Icon> {
    [16u32, 22, 24, 32, 44, 48, 64].iter().map(|&s| { let pm = icon::render(s, style, state); ksni::Icon { width: s as i32, height: s as i32, data: icon::to_argb(&pm) } }).collect()
}

pub fn run() {
    let (wake_tx, wake_rx) = channel::<()>();
    let waker: crate::hub::Waker = { let w = std::sync::Mutex::new(wake_tx.clone()); Arc::new(move || { let _ = w.lock().map(|t| t.send(())); }) };
    let mut hub = Hub::new(true, waker);
    let (cmd_tx, cmd_rx): (Sender<Cmd>, Receiver<Cmd>) = channel();
    // other sshm processes talk to the tray over a unix socket: "show", "quit"
    { let tx = cmd_tx.clone(); let w = wake_tx.clone(); ipc::serve(&paths::tray_socket(), move |line| { match line { "show" => { let _ = tx.send(Cmd::Open); } "quit" => { let _ = tx.send(Cmd::Quit); } _ => {} } let _ = w.send(()); }); }

    let mut style = icon::detect_style(&hub.settings.tray_icon_style);
    let mut stamp = (icon::theme_files_stamp(), hub.settings.tray_icon_style.clone());
    let mut state = State::None;
    let tray = SshmTray { tx: cmd_tx.clone(), icon: icon_set(style, state), tooltip: ("sshm".into(), String::new()), rows: vec![], events: vec![], active: 0, open_icon: icon::app_icon(32).encode_png().unwrap_or_default() };
    let handle = match tray.spawn() { Ok(h) => Some(h), Err(e) => { eprintln!("sshm: no system tray available ({e}); monitoring without an icon"); None } };
    let mut last_ui = Instant::now() - Duration::from_secs(10);
    loop {
        let _ = wake_rx.recv_timeout(Duration::from_millis(1000));
        while wake_rx.try_recv().is_ok() {}
        let changed = hub.tick();
        // commands from the menu, the socket or the window
        while let Ok(c) = cmd_rx.try_recv() { if !handle_cmd(&mut hub, c) { if let Some(h) = &handle { h.shutdown().wait(); } let _ = std::fs::remove_file(paths::tray_socket()); return; } }
        // notifications for new alerts
        let evs = std::mem::take(&mut hub.new_events);
        if hub.settings.notifications && !evs.is_empty() { notify(&evs); }
        for (lvl, msg) in std::mem::take(&mut hub.messages) { if lvl == Level::Error { notify_text("sshm", &msg); } }
        // panel theme switched (e.g. Breeze Dark -> Breeze): redraw in the new colour
        let st = (icon::theme_files_stamp(), hub.settings.tray_icon_style.clone());
        let restyle = st != stamp; if restyle { stamp = st; style = icon::detect_style(&hub.settings.tray_icon_style); }
        if !(changed || restyle) && last_ui.elapsed() < Duration::from_secs(5) { continue; }
        last_ui = Instant::now();
        let tracked: Vec<_> = hub.servers().iter().filter(|s| s.tray).cloned().collect();
        let known: Vec<_> = tracked.iter().filter_map(|s| hub.status(&s.id)).collect();
        let online = known.iter().filter(|s| s.online).count();
        let new_state = if tracked.is_empty() || known.is_empty() { State::None } else if online == tracked.len() { State::Ok } else if online == 0 { State::Down } else { State::Partial };
        let rows: Vec<Row> = tracked.iter().map(|s| {
            let st = hub.status(&s.id);
            let (label, dot, hollow) = match st { None => ("…".to_string(), (140, 140, 140), true), Some(x) if x.online => (x.telemetry.as_ref().and_then(|t| t.cpu).map(|c| format!("{c:.0}% cpu")).unwrap_or_else(|| x.latency_label()), icon::GREEN, false), Some(_) => ("offline".into(), icon::RED, true) };
            let mut lines = vec![];
            if let Some(t) = st.and_then(|x| x.telemetry.as_ref()) {
                lines.push(format!("CPU {:.0}%  ·  RAM {}  ·  up {}", t.cpu.unwrap_or(0.0), t.mem_label(), t.uptime_label()));
                for p in t.top(false, 3) { lines.push(format!("    {:5.1}%  {}  ({})", p.cpu, p.name, crate::core::telemetry::human_bytes(p.rss as f64))); }
            }
            Row { id: s.id.clone(), name: s.name.clone(), label, dot, hollow, endpoint: s.endpoint(), lines, commands: s.commands.iter().map(|c| c.label.clone()).collect(), mac: !s.mac.is_empty() }
        }).collect();
        let mut tip = vec![];
        for (s, r) in tracked.iter().zip(&rows) { tip.push(format!("{} {}  {}", if r.dot == icon::GREEN { "●" } else { "○" }, s.name, r.label)); }
        let (events, active) = hub.history.as_ref().map(|h| (h.events(5, None).iter().map(|e| format!("{}  {} {}", e.time_label(), if e.resolved { "✔" } else { match e.severity.as_str() { "critical" => "✖", "warning" => "⚠", _ => "ℹ" } }, e.message)).collect(), h.active().len())).unwrap_or_default();
        let redraw = new_state != state || restyle; state = new_state;
        if let Some(h) = &handle {
            let icons = if redraw { Some(icon_set(style, state)) } else { None };
            h.update(|t| { if let Some(i) = icons { t.icon = i; } t.rows = rows; t.tooltip = (format!("sshm — {online}/{} online", tracked.len()), tip.join("\n")); t.events = events; t.active = active; });
        }
    }
}

/// false = quit
fn handle_cmd(hub: &mut Hub, c: Cmd) -> bool {
    let find = |hub: &Hub, id: &str| hub.store.get(id).cloned();
    let session = hub.settings.tmux_session.clone(); let term = hub.settings.terminal.clone();
    let launch = |argv: Vec<String>, title: &str, pause: bool| { if let Err(e) = terminal::launch(&sshcmd::hold(&argv, title, pause), &term) { notify_text("sshm", &e); } };
    match c {
        Cmd::Quit => { let _ = ipc::send(&paths::window_socket(), "quit"); return false; }
        Cmd::Open => open_window(&[]),
        Cmd::OpenProcs(id) => { if ipc::send(&paths::window_socket(), &format!("procs {id}")).is_err() { open_window(&["--procs".into(), id]); } }
        Cmd::Activity => { if ipc::send(&paths::window_socket(), "activity").is_err() { open_window(&["--activity".into()]); } }
        Cmd::Tui => { let exe = paths::which("sshm").map(|p| p.to_string_lossy().to_string()).unwrap_or_else(|| "sshm".into()); launch(vec![exe], "sshm", false); }
        Cmd::Refresh => { hub.refresh(); }
        Cmd::Connect(id, tmux) => if let Some(s) = find(hub, &id) { launch(sshcmd::ssh_command(&s, Some(tmux || s.tmux), None, &session), &format!("{} · {}", s.name, s.endpoint()), false); hub.store.mark_connected(&id); },
        Cmd::Sftp(id) => if let Some(s) = find(hub, &id) { launch(sshcmd::sftp_command(&s), &format!("SFTP · {}", s.name), false); },
        Cmd::Files(id) => if let Some(s) = find(hub, &id) { if mounts::is_mounted(&s, &hub.settings) { terminal::xdg_open(&mounts::mountpoint(&s, &hub.settings).to_string_lossy()); } else { terminal::xdg_open(&s.sftp_url()); } },
        Cmd::Htop(id) => if let Some(s) = find(hub, &id) { launch(procs::top_argv(&s, &session), &format!("htop · {}", s.name), false); },
        Cmd::Run(id, i) => if let Some(s) = find(hub, &id) { if let Some(c) = s.commands.get(i) { launch(sshcmd::ssh_command(&s, Some(false), Some(&c.command), &session), &format!("{} · {}", c.label, s.name), true); } },
        Cmd::Wake(id) => if let Some(s) = find(hub, &id) { match net::wake(&s.mac) { Ok(_) => notify_text("sshm", &format!("Magic packet sent to {} ({})", s.name, s.mac)), Err(e) => notify_text("Wake-on-LAN failed", &e) } },
    }
    true
}
pub fn open_window(extra: &[String]) {
    if extra.is_empty() && ipc::send(&paths::window_socket(), "raise").is_ok() { return; }
    let exe = std::env::current_exe().map(|p| p.to_string_lossy().to_string()).unwrap_or_else(|_| "sshm-gui".into());
    let mut argv = vec![exe]; argv.extend_from_slice(extra);
    let _ = terminal::spawn_detached(&argv);
}
fn notify(evs: &[crate::core::history::Event]) {
    if evs.len() > 3 {   // e.g. the network dropped: one summary instead of a storm
        let body = evs.iter().take(5).map(|e| e.message.clone()).collect::<Vec<_>>().join("\n");
        notify_text(&format!("{} sshm alerts", evs.len()), &body); return;
    }
    for e in evs { notify_text(if e.resolved { "Resolved" } else { match e.severity.as_str() { "critical" => "Alert", "warning" => "Warning", _ => "sshm" } }, &e.message); }
}
pub fn notify_text(summary: &str, body: &str) {
    let (s, b) = (summary.to_string(), body.to_string());
    std::thread::spawn(move || { let _ = notify_rust::Notification::new().appname("sshm").summary(&s).body(&b).icon("sshm").timeout(notify_rust::Timeout::Milliseconds(8000)).show(); });
}
