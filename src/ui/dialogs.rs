//! Dialogs: server editor, settings, tunnel, saved command, network scan, ssh_config import/export, confirmations.
use super::{c32, Act, App, UiMsg};
use crate::core::containers::Container;
use crate::core::model::{normalize_mac, Command, Server};
use crate::core::settings::{Settings, REFRESH_CHOICES};
use crate::core::{net, paths, themes, tunnels};
use crate::hub::Level;
use eframe::egui::{self, Align2, Color32, RichText, Vec2};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

#[derive(Default)]
pub struct Dialogs {
    pub editor: Option<Editor>, pub settings: Option<SettingsDlg>, pub tunnel: Option<TunnelDlg>, pub command: Option<CommandDlg>,
    pub scan: Option<ScanDlg>, pub import: Option<ImportDlg>, pub export: Option<String>, pub confirm: Option<Confirm>, pub shortcuts: bool, pub about: bool,
}

pub struct Editor { pub s: Server, pub is_new: bool, port: String, pub error: String, pub detecting: bool }
impl Editor {
    pub fn add(tag: String) -> Editor { Editor::add_from(Server { user: std::env::var("USER").unwrap_or_default(), tag, ..Default::default() }) }
    pub fn add_from(s: Server) -> Editor { Editor { port: s.port.to_string(), s, is_new: true, error: String::new(), detecting: false } }
    pub fn edit(s: Server) -> Editor { Editor { port: s.port.to_string(), s, is_new: false, error: String::new(), detecting: false } }
}
pub struct SettingsDlg { pub s: Settings, autostart: bool, port_before: u16 }
impl SettingsDlg { pub fn new(s: &Settings) -> SettingsDlg { SettingsDlg { s: s.clone(), autostart: autostart_path().exists(), port_before: s.telemetry_port } } }
pub struct TunnelDlg { s: Server, kind: char, text: String, error: String, busy: bool }
impl TunnelDlg { pub fn new(s: Server) -> TunnelDlg { TunnelDlg { s, kind: 'L', text: "8080:localhost:80".into(), error: String::new(), busy: false } } }
pub struct CommandDlg { id: String, index: Option<usize>, label: String, command: String }
impl CommandDlg { pub fn new(id: String, index: Option<usize>, c: Option<Command>) -> CommandDlg { let c = c.unwrap_or(Command { label: String::new(), command: String::new() }); CommandDlg { id, index, label: c.label, command: c.command } } }
pub struct ScanDlg { target: String, ports: String, pub running: bool, pub progress: (usize, usize), pub found: Vec<(bool, net::Found)>, cancel: Arc<AtomicBool>, error: String, done: bool }
impl ScanDlg {
    pub fn finish(&mut self, v: Vec<net::Found>) { self.running = false; self.done = true; self.found = v.into_iter().map(|f| (true, f)).collect(); self.progress = (1, 1); }
    pub fn new() -> ScanDlg { ScanDlg { target: net::local_network(), ports: "22, 2222, 2200, 22222, 8022".into(), running: false, progress: (0, 0), found: vec![], cancel: Arc::new(AtomicBool::new(false)), error: String::new(), done: false } } }
pub struct ImportDlg { items: Vec<(bool, Server)> }
impl ImportDlg { pub fn new(c: Vec<Server>) -> ImportDlg { ImportDlg { items: c.into_iter().map(|s| (true, s)).collect() } } }
pub enum Confirm { DeleteServer(String, String), StopContainer(String, Container), Kill(u64, i64, String, bool) }
impl Confirm {
    pub fn delete_server(s: &Server) -> Confirm { Confirm::DeleteServer(s.id.clone(), s.name.clone()) }
    pub fn stop_container(hid: String, c: Container) -> Confirm { Confirm::StopContainer(hid, c) }
}
fn autostart_path() -> std::path::PathBuf { paths::home().join(".config/autostart/sshm-tray.desktop") }
fn set_autostart(on: bool) -> Result<(), String> {
    let p = autostart_path();
    if !on { let _ = std::fs::remove_file(&p); return Ok(()); }
    let exe = std::env::current_exe().map(|e| e.to_string_lossy().to_string()).unwrap_or_else(|_| "sshm-gui".into());
    let text = format!("[Desktop Entry]\nType=Application\nName=sshm tray monitor\nComment=Watch your SSH servers from the system tray\nExec={exe} --tray\nIcon=io.github.marioman68.sshm\nTerminal=false\nX-GNOME-Autostart-enabled=true\nX-GNOME-Autostart-Delay=5\nX-KDE-autostart-after=panel\n");
    if let Some(d) = p.parent() { paths::ensure_dir(d, 0o755); }
    paths::atomic_write(&p, text.as_bytes(), 0o644).map_err(|e| e.to_string())
}

fn modal<R>(ctx: &egui::Context, title: &str, width: f32, open: &mut bool, add: impl FnOnce(&mut egui::Ui) -> R) -> Option<R> {
    egui::Window::new(title).collapsible(false).resizable(false).anchor(Align2::CENTER_CENTER, [0.0, 0.0]).default_width(width).open(open).show(ctx, |ui| { ui.set_width(width); add(ui) }).and_then(|r| r.inner)
}
/// Cancel + primary button on the right; returns (primary clicked, cancel clicked)
fn buttons(ui: &mut egui::Ui, primary: &str, enabled: bool, accent: Color32) -> (bool, bool) {
    let mut r = (false, false);
    ui.add_space(6.0);
    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
        r.0 = ui.add_enabled(enabled, egui::Button::new(RichText::new(primary).strong().color(Color32::WHITE)).fill(accent)).clicked();
        r.1 = ui.button("Cancel").clicked();
    });
    r
}
fn row(ui: &mut egui::Ui, label: &str, muted: Color32, add: impl FnOnce(&mut egui::Ui)) { ui.label(RichText::new(label).color(muted)); add(ui); ui.end_row(); }

pub fn show(app: &mut App, ctx: &egui::Context, acts: &mut Vec<Act>) {
    let t = app.theme(); let (muted, accent) = (c32(t.muted), c32(t.accent));
    let escape = ctx.input(|i| i.key_pressed(egui::Key::Escape));

    // ---------------------------------------------------------------- server editor
    if let Some(ed) = app.dlg.editor.as_mut() {
        let mut open = !escape; let title = if ed.is_new { "Add server" } else { "Edit server" };
        let tags = app.hub.store.tags();
        let res = modal(ctx, title, 520.0, &mut open, |ui| {
            ui.label(RichText::new("Only a name and host are required.").color(muted));
            ui.add_space(4.0);
            egui::Grid::new("ed").num_columns(2).spacing(Vec2::new(12.0, 8.0)).show(ui, |ui| {
                row(ui, "Name", muted, |ui| { ui.add(egui::TextEdit::singleline(&mut ed.s.name).hint_text("e.g. Homelab NAS").desired_width(f32::INFINITY)); });
                row(ui, "Host", muted, |ui| { ui.add(egui::TextEdit::singleline(&mut ed.s.host).hint_text("192.168.1.10 or nas.lan").desired_width(f32::INFINITY)); });
                row(ui, "User", muted, |ui| { ui.horizontal(|ui| { ui.add(egui::TextEdit::singleline(&mut ed.s.user).desired_width(250.0)); ui.label(RichText::new("Port").color(muted)); ui.add(egui::TextEdit::singleline(&mut ed.port).desired_width(70.0)); }); });
                row(ui, "Tag", muted, |ui| { ui.horizontal(|ui| { ui.add(egui::TextEdit::singleline(&mut ed.s.tag).hint_text("group, e.g. Homelab").desired_width(250.0)); if !tags.is_empty() { ui.menu_button("▾", |ui| { for tg in &tags { if ui.button(tg).clicked() { ed.s.tag = tg.clone(); ui.close_menu(); } } }); } }); });
                row(ui, "Identity file", muted, |ui| { ui.horizontal(|ui| { ui.add(egui::TextEdit::singleline(&mut ed.s.key).hint_text("default: ssh-agent / ~/.ssh/id_*").desired_width(330.0));
                    if ui.button("Browse…").clicked() { if let Some(p) = rfd::FileDialog::new().set_directory(paths::home().join(".ssh")).pick_file() { let h = paths::home().to_string_lossy().to_string(); ed.s.key = p.to_string_lossy().replacen(&h, "~", 1); } } }); });
                row(ui, "Jump host", muted, |ui| { ui.add(egui::TextEdit::singleline(&mut ed.s.jump).hint_text("ProxyJump, e.g. me@bastion.example.com").desired_width(f32::INFINITY)); });
                row(ui, "MAC address", muted, |ui| { ui.horizontal(|ui| { ui.add(egui::TextEdit::singleline(&mut ed.s.mac).hint_text("for Wake-on-LAN").desired_width(330.0));
                    if ui.add_enabled(!ed.detecting && !ed.s.host.trim().is_empty(), egui::Button::new(if ed.detecting { "Looking…" } else { "Detect" })).on_hover_text("Look it up in the ARP cache (host must be on your LAN)").clicked() {
                        ed.detecting = true; let (h, tx, c) = (ed.s.host.trim().to_string(), app.tx.clone(), ctx.clone()); std::thread::spawn(move || { let _ = tx.send(UiMsg::Mac(net::mac_for(&h))); c.request_repaint(); }); } }); });
                row(ui, "Remote folder", muted, |ui| { let hint = { let mut x = ed.s.clone(); x.remote_path.clear(); format!("default {}", x.home_path()) }; ui.add(egui::TextEdit::singleline(&mut ed.s.remote_path).hint_text(hint).desired_width(f32::INFINITY)); });
                row(ui, "", muted, |ui| { ui.checkbox(&mut ed.s.tmux, "Open a tmux session by default"); });
                row(ui, "", muted, |ui| { ui.checkbox(&mut ed.s.tray, "Monitor in the system tray (status, alerts)"); });
                row(ui, "Notes", muted, |ui| { ui.add(egui::TextEdit::multiline(&mut ed.s.notes).desired_rows(2).hint_text("Anything worth remembering about this machine").desired_width(f32::INFINITY)); });
            });
            if !ed.error.is_empty() { ui.colored_label(c32(t.danger), &ed.error); }
            buttons(ui, if ed.is_new { "Add server" } else { "Save" }, !ed.s.name.trim().is_empty() && !ed.s.host.trim().is_empty(), accent)
        });
        let mut close = !open;
        if let Some((save, cancel)) = res {
            if cancel { close = true; }
            if save {
                let mut s = ed.s.clone();
                for f in [&mut s.name, &mut s.host, &mut s.user, &mut s.tag, &mut s.key, &mut s.jump, &mut s.remote_path] { *f = f.trim().to_string(); }
                s.notes = s.notes.trim().to_string();
                match (ed.port.trim().parse::<u16>().ok().filter(|p| *p > 0), normalize_mac(&s.mac)) {
                    (None, _) => ed.error = "Port must be between 1 and 65535".into(),
                    (_, Err(e)) => ed.error = e,
                    (Some(p), Ok(m)) => { s.port = p; s.mac = m; let id = s.id.clone(); let name = s.name.clone();
                        let r = if ed.is_new { app.hub.store.add(s) } else { app.hub.store.update(s) };
                        match r { Ok(_) => { close = true; acts.push(Act::Select(id)); app.hub.refresh(); app.status = Some((Level::Success, format!("Saved {name}"), std::time::Instant::now())); } Err(e) => ed.error = e } }
                }
            }
        }
        if close { app.dlg.editor = None; }
    }

    // ---------------------------------------------------------------- settings
    if let Some(d) = app.dlg.settings.as_mut() {
        let mut open = !escape;
        let res = modal(ctx, "Settings", 560.0, &mut open, |ui| {
            egui::Grid::new("set").num_columns(2).spacing(Vec2::new(12.0, 8.0)).show(ui, |ui| {
                row(ui, "Theme", muted, |ui| { egui::ComboBox::from_id_salt("theme").selected_text(d.s.theme.clone()).width(200.0).show_ui(ui, |ui| { for th in themes::THEMES.iter() { ui.selectable_value(&mut d.s.theme, th.name.to_string(), th.name); } }); });
                row(ui, "Tray icon", muted, |ui| { egui::ComboBox::from_id_salt("trayicon").selected_text(match d.s.tray_icon_style.as_str() { "light" => "Light (for dark panels)", "dark" => "Dark (for light panels)", "color" => "Colour tile", _ => "Automatic (match the desktop)" }).width(260.0).show_ui(ui, |ui| {
                    for (k, l) in [("auto", "Automatic (match the desktop)"), ("light", "Light (for dark panels)"), ("dark", "Dark (for light panels)"), ("color", "Colour tile")] { ui.selectable_value(&mut d.s.tray_icon_style, k.to_string(), l); } }); });
                row(ui, "Auto-refresh", muted, |ui| { egui::ComboBox::from_id_salt("refresh").selected_text(if d.s.refresh_interval == 0 { "Manual only".to_string() } else { format!("Every {} s", d.s.refresh_interval) }).width(200.0).show_ui(ui, |ui| { for v in REFRESH_CHOICES { ui.selectable_value(&mut d.s.refresh_interval, v, if v == 0 { "Manual only".to_string() } else { format!("Every {v} s") }); } }); });
                row(ui, "Probe timeout", muted, |ui| { ui.add(egui::DragValue::new(&mut d.s.probe_timeout).range(0.3..=10.0).speed(0.1).suffix(" s")); });
                row(ui, "Terminal", muted, |ui| { ui.add(egui::TextEdit::singleline(&mut d.s.terminal).hint_text("automatic (e.g. konsole, kitty, \"wezterm start --\")").desired_width(f32::INFINITY)); });
                row(ui, "tmux session", muted, |ui| { ui.add(egui::TextEdit::singleline(&mut d.s.tmux_session).desired_width(200.0)); });
                row(ui, "Mount folder", muted, |ui| { ui.add(egui::TextEdit::singleline(&mut d.s.mount_dir).desired_width(f32::INFINITY)); });
                row(ui, "Telemetry port", muted, |ui| { ui.add(egui::DragValue::new(&mut d.s.telemetry_port).range(1024..=65535)); });
                row(ui, "", muted, |ui| { ui.checkbox(&mut d.s.accept_legacy_agents, "Accept unsigned telemetry from sshm 2.x agents"); });
                row(ui, "Alerts", muted, |ui| { ui.checkbox(&mut d.s.alerts_enabled, "Alert when a server goes down, runs hot, fills its disk or a container stops"); });
                row(ui, "Thresholds", muted, |ui| { ui.add_enabled_ui(d.s.alerts_enabled, |ui| ui.horizontal(|ui| {
                    ui.label("CPU"); ui.add(egui::DragValue::new(&mut d.s.alert_cpu).range(10.0..=100.0).suffix("%")); ui.label("RAM"); ui.add(egui::DragValue::new(&mut d.s.alert_mem).range(10.0..=100.0).suffix("%"));
                    ui.label("Disk"); ui.add(egui::DragValue::new(&mut d.s.alert_disk).range(10.0..=100.0).suffix("%")); ui.label("for"); ui.add(egui::DragValue::new(&mut d.s.alert_sustain_minutes).range(1..=120).suffix(" min")); })); });
                row(ui, "", muted, |ui| { ui.checkbox(&mut d.s.notifications, "Desktop notifications for alerts"); });
                row(ui, "", muted, |ui| { ui.checkbox(&mut d.autostart, "Start the tray monitor when I log in"); });
            });
            buttons(ui, "Save", true, accent)
        });
        let mut close = !open;
        if let Some((save, cancel)) = res {
            if cancel { close = true; }
            if save {
                d.s.save(); let restart = d.s.telemetry_port != d.port_before; app.hub.settings = d.s.clone();
                if let Err(e) = set_autostart(d.autostart) { app.say(Level::Error, format!("Autostart: {e}")); }
                app.say(Level::Success, if restart { "Settings saved. Quit and reopen sshm for the new telemetry port." } else { "Settings saved" });
                close = true;
            }
        }
        if close { app.dlg.settings = None; }
    }

    // ---------------------------------------------------------------- tunnel
    if let Some(d) = app.dlg.tunnel.as_mut() {
        let mut open = !escape;
        let res = modal(ctx, &format!("Port forward · {}", d.s.name), 460.0, &mut open, |ui| {
            egui::Grid::new("tun").num_columns(2).spacing(Vec2::new(12.0, 8.0)).show(ui, |ui| {
                row(ui, "Type", muted, |ui| { egui::ComboBox::from_id_salt("kind").selected_text(match d.kind { 'L' => "Local (-L)", 'R' => "Remote (-R)", _ => "SOCKS proxy (-D)" }).width(200.0).show_ui(ui, |ui| {
                    for (k, l, ex) in [('L', "Local (-L)", "8080:localhost:80"), ('R', "Remote (-R)", "9000:localhost:3000"), ('D', "SOCKS proxy (-D)", "1080")] { if ui.selectable_value(&mut d.kind, k, l).clicked() { d.text = ex.into(); } } }); });
                row(ui, "Forward", muted, |ui| { ui.add(egui::TextEdit::singleline(&mut d.text).font(egui::TextStyle::Monospace).desired_width(f32::INFINITY)); });
            });
            let help = match tunnels::Spec::parse(d.kind, &d.text) { Ok(sp) => sp.describe(&d.s.name), Err(e) => e };
            ui.label(RichText::new(help).color(muted));
            if !d.error.is_empty() { ui.colored_label(c32(t.danger), &d.error); }
            buttons(ui, if d.busy { "Starting…" } else { "Start tunnel" }, !d.busy && tunnels::Spec::parse(d.kind, &d.text).is_ok(), accent)
        });
        let mut close = !open;
        if let Some((go, cancel)) = res {
            if cancel { close = true; }
            if go { if let Ok(sp) = tunnels::Spec::parse(d.kind, &d.text) {
                let s = d.s.clone(); let desc = sp.describe(&s.name);
                app.hub.task(move || match tunnels::start(&s, &sp) { Ok(_) => (Level::Success, format!("Tunnel up: {desc}"), true), Err(e) => (Level::Error, format!("Tunnel failed: {e}"), true) });
                app.say(Level::Info, "Starting tunnel…"); close = true;
            } }
        }
        if close { app.dlg.tunnel = None; }
    }

    // ---------------------------------------------------------------- saved command
    if let Some(d) = app.dlg.command.as_mut() {
        let mut open = !escape;
        let res = modal(ctx, if d.index.is_some() { "Edit command" } else { "Add command" }, 480.0, &mut open, |ui| {
            egui::Grid::new("cmd").num_columns(2).spacing(Vec2::new(12.0, 8.0)).show(ui, |ui| {
                row(ui, "Label", muted, |ui| { ui.add(egui::TextEdit::singleline(&mut d.label).hint_text("e.g. Update").desired_width(f32::INFINITY)); });
                row(ui, "Command", muted, |ui| { ui.add(egui::TextEdit::multiline(&mut d.command).font(egui::TextStyle::Monospace).desired_rows(2).hint_text("e.g. sudo dnf upgrade -y").desired_width(f32::INFINITY)); });
            });
            buttons(ui, "Save", !d.label.trim().is_empty() && !d.command.trim().is_empty(), accent)
        });
        let mut close = !open;
        if let Some((save, cancel)) = res {
            if cancel { close = true; }
            if save { let (id, idx, c) = (d.id.clone(), d.index, Command { label: d.label.trim().into(), command: d.command.trim().into() });
                app.mutate(&id, move |s| match idx { Some(i) if i < s.commands.len() => s.commands[i] = c, _ => s.commands.push(c) }); close = true; }
        }
        if close { app.dlg.command = None; }
    }

    // ---------------------------------------------------------------- network scan
    if let Some(d) = app.dlg.scan.as_mut() {
        let mut open = !escape || d.running;
        let have: std::collections::HashSet<(String, u16)> = app.hub.servers().iter().map(|s| (s.host.clone(), s.port)).collect();
        let res = modal(ctx, "Scan network", 600.0, &mut open, |ui| {
            ui.label(RichText::new("Finds machines that answer with an SSH banner. Nothing is added until you choose.").color(muted));
            egui::Grid::new("scan").num_columns(2).spacing(Vec2::new(12.0, 8.0)).show(ui, |ui| {
                row(ui, "Network", muted, |ui| { ui.add_enabled(!d.running, egui::TextEdit::singleline(&mut d.target).hint_text("192.168.1.0/24, 192.168.1 or 10.0.0.5-40").desired_width(f32::INFINITY)); });
                row(ui, "Ports", muted, |ui| { ui.add_enabled(!d.running, egui::TextEdit::singleline(&mut d.ports).desired_width(f32::INFINITY)); });
            });
            let mut start = false; let mut stop = false;
            ui.horizontal(|ui| {
                if d.running { if ui.button("Stop").clicked() { stop = true; } ui.add(egui::ProgressBar::new(if d.progress.1 > 0 { d.progress.0 as f32 / d.progress.1 as f32 } else { 0.0 }).desired_width(300.0).show_percentage()); }
                else if ui.button(if d.done { "Scan again" } else { "Start scan" }).clicked() { start = true; }
                if d.done && !d.running { ui.label(RichText::new(format!("{} found", d.found.len())).color(muted)); }
            });
            if !d.error.is_empty() { ui.colored_label(c32(t.danger), &d.error); }
            if !d.found.is_empty() {
                egui::ScrollArea::vertical().max_height(260.0).show(ui, |ui| {
                    egui::Grid::new("found").striped(true).num_columns(5).spacing(Vec2::new(12.0, 4.0)).show(ui, |ui| {
                        for (on, f) in d.found.iter_mut() {
                            let known = have.contains(&(f.ip.clone(), f.port));
                            ui.add_enabled(!known, egui::Checkbox::without_text(on));
                            ui.label(RichText::new(format!("{}:{}", f.ip, f.port)).monospace()); ui.label(if f.hostname.is_empty() { "—" } else { &f.hostname });
                            ui.label(RichText::new(&f.banner).color(muted)); ui.label(if known { RichText::new("saved").color(muted) } else { RichText::new(format!("{:.0} ms", f.latency_ms)).color(muted) }); ui.end_row();
                        }
                    });
                });
            }
            if start {
                match (net::parse_targets(&d.target), net::parse_ports(&d.ports)) {
                    (Err(e), _) | (_, Err(e)) => d.error = e,
                    (Ok(tg), Ok(ps)) => { d.error.clear(); d.running = true; d.done = false; d.found.clear(); d.cancel = Arc::new(AtomicBool::new(false));
                        let (tx, c, cancel) = (app.tx.clone(), ctx.clone(), d.cancel.clone());
                        std::thread::spawn(move || { let tx2 = std::sync::Mutex::new(tx.clone()); let c2 = c.clone();
                            let found = net::scan(&tg, &ps, &cancel, &move |a, b| { let _ = tx2.lock().map(|t| t.send(UiMsg::ScanProgress(a, b))); c2.request_repaint(); });
                            let _ = tx.send(UiMsg::ScanDone(found)); c.request_repaint(); }); }
                }
            }
            if stop { d.cancel.store(true, Ordering::Relaxed); }
            let n = d.found.iter().filter(|(on, f)| *on && !have.contains(&(f.ip.clone(), f.port))).count();
            buttons(ui, &format!("Add {n} server{}", if n == 1 { "" } else { "s" }), n > 0 && !d.running, accent)
        });
        let mut close = !open;
        if let Some((add, cancel)) = res {
            if cancel { d.cancel.store(true, Ordering::Relaxed); close = true; }
            if add {
                let user = std::env::var("USER").unwrap_or_default(); let mut added = 0;
                let picks: Vec<net::Found> = d.found.iter().filter(|(on, f)| *on && !have.contains(&(f.ip.clone(), f.port))).map(|x| x.1.clone()).collect();
                for f in picks { let name = app.hub.store.unique_name(&f.suggested_name()); let s = Server { name, host: f.ip.clone(), port: f.port, user: user.clone(), mac: f.mac.clone(), ..Default::default() }; if app.hub.store.add(s).is_ok() { added += 1; } }
                app.hub.refresh(); app.say(Level::Success, format!("Added {added} server(s)")); close = true;
            }
        }
        if close { app.dlg.scan = None; }
    }

    // ---------------------------------------------------------------- ssh_config import / export
    if let Some(d) = app.dlg.import.as_mut() {
        let mut open = !escape;
        let res = modal(ctx, "Import from ~/.ssh/config", 520.0, &mut open, |ui| {
            ui.label(RichText::new("Hosts not saved in sshm yet. They get the tag \"ssh_config\".").color(muted));
            egui::ScrollArea::vertical().max_height(320.0).show(ui, |ui| { for (on, s) in d.items.iter_mut() { ui.checkbox(on, format!("{}   {}", s.name, s.endpoint())); } });
            let n = d.items.iter().filter(|x| x.0).count();
            buttons(ui, &format!("Import {n}"), n > 0, accent)
        });
        let mut close = !open;
        if let Some((go, cancel)) = res {
            if cancel { close = true; }
            if go { let picks: Vec<Server> = d.items.iter().filter(|x| x.0).map(|x| x.1.clone()).collect(); let mut n = 0; for s in picks { if app.hub.store.add(s).is_ok() { n += 1; } } app.hub.refresh(); app.say(Level::Success, format!("Imported {n} server(s)")); close = true; }
        }
        if close { app.dlg.import = None; }
    }
    if let Some(text) = app.dlg.export.as_mut() {
        let mut open = !escape; let mut copy = false;
        modal(ctx, "Export as ssh_config", 560.0, &mut open, |ui| {
            ui.label(RichText::new("Paste this into ~/.ssh/config (the servers currently shown in the list).").color(muted));
            egui::ScrollArea::vertical().max_height(340.0).show(ui, |ui| { ui.add(egui::TextEdit::multiline(text).font(egui::TextStyle::Monospace).desired_width(f32::INFINITY)); });
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| { if ui.button("Copy to clipboard").clicked() { copy = true; } });
        });
        if copy { ctx.copy_text(text.clone()); app.say(Level::Success, "Copied ssh_config to the clipboard"); }
        if !open { app.dlg.export = None; }
    }

    // ---------------------------------------------------------------- confirmations
    if let Some(c) = app.dlg.confirm.take() {
        let (title, text, btn) = match &c {
            Confirm::DeleteServer(_, n) => ("Delete server".to_string(), format!("Delete {n}? Its history goes too. Your ssh keys and the remote machine are not touched."), "Delete"),
            Confirm::StopContainer(_, ct) => ("Stop container".to_string(), format!("Stop the container {}? Anything it serves goes offline until it is started again.", ct.name), "Stop"),
            Confirm::Kill(_, pid, name, force) => (if *force { "Force kill" } else { "End process" }.to_string(), format!("{} {name} (pid {pid})?", if *force { "Force-kill (SIGKILL)" } else { "End (SIGTERM)" }), if *force { "Force kill" } else { "End process" }),
        };
        let mut open = !escape;
        let res = modal(ctx, &title, 400.0, &mut open, |ui| { ui.label(text); buttons(ui, btn, true, c32(t.danger)) });
        let mut keep = open;
        if let Some((go, cancel)) = res {
            if cancel { keep = false; }
            if go { keep = false; match c { Confirm::DeleteServer(ref id, _) => acts.push(Act::Delete(id.clone())), Confirm::StopContainer(ref h, ref ct) => acts.push(Act::Ctr(h.clone(), ct.clone(), "stop")), Confirm::Kill(w, pid, _, force) => app.win.kill(w, pid, force, &app.tx) } }
        }
        if keep { app.dlg.confirm = Some(c); }
    }

    if app.dlg.shortcuts {
        let mut open = !escape;
        modal(ctx, "Keyboard shortcuts", 420.0, &mut open, |ui| {
            egui::Grid::new("keys").num_columns(2).spacing(Vec2::new(24.0, 5.0)).show(ui, |ui| {
                for (k, v) in [("Enter", "Connect"), ("Ctrl+T", "Connect in tmux"), ("Ctrl+P", "Processes"), ("Ctrl+K", "Search"), ("↑ / ↓", "Previous / next server"), ("Ctrl+N", "Add server"), ("Ctrl+E", "Edit server"), ("Del", "Delete server"),
                    ("F5", "Refresh status"), ("Ctrl+Shift+R", "Run on many servers"), ("Ctrl+,", "Settings"), ("Ctrl+W", "Close window (tray keeps running)"), ("Ctrl+Q", "Quit sshm")] { ui.label(RichText::new(k).monospace()); ui.label(v); ui.end_row(); }
            });
        });
        if !open { app.dlg.shortcuts = false; }
    }
    if app.dlg.about {
        let mut open = !escape;
        modal(ctx, "About sshm", 420.0, &mut open, |ui| {
            ui.label(RichText::new(format!("sshm desktop {}", env!("CARGO_PKG_VERSION"))).strong().size(16.0));
            ui.label("SSH Connection Hub: every server you SSH into, its status, live metrics, files, tunnels and containers.");
            ui.label(RichText::new("The desktop app and tray are written in Rust; the terminal UI (sshm) and CLI share the same config in ~/.config/sshm.").color(muted));
        });
        if !open { app.dlg.about = false; }
    }
}
