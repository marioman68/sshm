//! Tool windows: process viewer, run on many servers, alerts & activity, active tunnels.
use super::dialogs::{Confirm, Dialogs};
use super::{c32, Act, App, UiMsg};
use crate::core::model::Server;
use crate::core::{fleet, procs};
use eframe::egui::{self, Color32, RichText, Vec2};
use std::collections::HashSet;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::Sender;
use std::sync::Arc;
use std::time::{Duration, Instant};

#[derive(Clone, Copy, PartialEq)]
enum Col { Cpu, Mem, Pid, Name, User, Time }
pub struct ProcWin { id: u64, s: Server, list: Vec<procs::Process>, error: String, loading: bool, last: Instant, auto: bool, sort: Col, filter: String, sel: Option<i64>, open: bool, msg: String }
#[derive(Clone, PartialEq)]
enum Target { All, Tag(String), Pick }
pub struct FleetWin { pub open: bool, target: Target, picked: HashSet<String>, command: String, running: bool, results: Vec<fleet::RunResult>, expected: usize, run: u64, expanded: HashSet<String>, cancel: Arc<AtomicBool> }
impl Default for FleetWin { fn default() -> Self { FleetWin { open: true, target: Target::All, picked: HashSet::new(), command: "uptime".into(), running: false, results: vec![], expected: 0, run: 0, expanded: HashSet::new(), cancel: Arc::new(AtomicBool::new(false)) } } }
#[derive(Default)]
pub struct Windows { pub procs: Vec<ProcWin>, pub fleet: Option<FleetWin>, pub activity: bool, pub tunnels: bool, next: u64 }

fn fetch(id: u64, s: Server, tx: &Sender<UiMsg>) { let tx = tx.clone(); std::thread::spawn(move || { let _ = tx.send(UiMsg::Procs(id, procs::fetch(&s))); }); }
impl Windows {
    pub fn open_procs(&mut self, s: Server, tx: &Sender<UiMsg>) {
        if let Some(w) = self.procs.iter_mut().find(|w| w.s.id == s.id) { w.open = true; return; }
        self.next += 1; let id = self.next;
        fetch(id, s.clone(), tx);
        self.procs.push(ProcWin { id, s, list: vec![], error: String::new(), loading: true, last: Instant::now(), auto: true, sort: Col::Cpu, filter: String::new(), sel: None, open: true, msg: String::new() });
    }
    pub fn kill(&mut self, win: u64, pid: i64, force: bool, tx: &Sender<UiMsg>) {
        if let Some(w) = self.procs.iter().find(|w| w.id == win) { let (s, tx) = (w.s.clone(), tx.clone()); std::thread::spawn(move || { let _ = tx.send(UiMsg::ProcAction(win, procs::kill(&s, pid, force))); }); }
    }
    pub fn handle(&mut self, m: UiMsg, dlg: &mut Dialogs) {
        match m {
            UiMsg::Procs(id, r) => if let Some(w) = self.procs.iter_mut().find(|w| w.id == id) { w.loading = false; w.last = Instant::now(); match r { Ok(v) => { w.list = v; w.error.clear(); } Err(e) => w.error = e } },
            UiMsg::ProcAction(id, r) => if let Some(w) = self.procs.iter_mut().find(|w| w.id == id) { w.msg = match r { Ok(m) => m, Err(e) => format!("✖ {e}") }; w.last = Instant::now() - Duration::from_secs(60); },
            UiMsg::Fleet(run, r) => if let Some(f) = self.fleet.as_mut() { if f.run == run { f.results.push(r); if f.results.len() >= f.expected { f.running = false; } } },
            UiMsg::ScanProgress(a, b) => if let Some(s) = dlg.scan.as_mut() { s.progress = (a, b); },
            UiMsg::ScanDone(v) => if let Some(s) = dlg.scan.as_mut() { s.finish(v); },
            UiMsg::Mac(m) => if let Some(e) = dlg.editor.as_mut() { e.detecting = false; if m.is_empty() { e.error = "No MAC found (the host must be on your LAN and answering)".into(); } else { e.s.mac = m; e.error.clear(); } },
            UiMsg::Ipc(_) => {}
        }
    }
}

pub fn show(app: &mut App, ctx: &egui::Context, acts: &mut Vec<Act>) {
    let t = app.theme(); let muted = c32(t.muted);
    // ------------------------------------------------------------------ processes
    let session = app.hub.settings.tmux_session.clone();
    let mut kill_req: Option<Confirm> = None; let mut launch: Vec<(Vec<String>, String)> = vec![];
    for w in app.win.procs.iter_mut() {
        if w.auto && !w.loading && w.last.elapsed() > Duration::from_secs(3) && w.open { w.loading = true; fetch(w.id, w.s.clone(), &app.tx); }
        let mut open = w.open;
        egui::Window::new(format!("Processes · {}", w.s.name)).id(egui::Id::new(("procs", w.id))).open(&mut open).default_size([820.0, 520.0]).resizable(true).show(ctx, |ui| {
            ui.horizontal(|ui| {
                ui.add(egui::TextEdit::singleline(&mut w.filter).hint_text("Filter by name, user or PID").desired_width(240.0));
                ui.checkbox(&mut w.auto, "Auto-refresh");
                if ui.button("Refresh").clicked() && !w.loading { w.loading = true; fetch(w.id, w.s.clone(), &app.tx); }
                if w.loading { ui.add(egui::Spinner::new().size(14.0)); }
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    if ui.button("Open htop").clicked() { launch.push((procs::top_argv(&w.s, &session), format!("htop · {}", w.s.name))); }
                    let selp = w.sel.and_then(|pid| w.list.iter().find(|p| p.pid == pid)).cloned();
                    ui.add_enabled_ui(selp.is_some(), |ui| {
                        ui.menu_button("More ▾", |ui| { if let Some(p) = &selp { if ui.button("End with sudo (in a terminal)").clicked() { launch.push((procs::sudo_kill_argv(&w.s, p.pid, false, &session), format!("sudo kill · {}", w.s.name))); ui.close_menu(); } if ui.button("Copy command line").clicked() { ui.ctx().copy_text(p.command.clone()); ui.close_menu(); } } });
                        if ui.button("Force kill").clicked() { if let Some(p) = &selp { kill_req = Some(Confirm::Kill(w.id, p.pid, p.name.clone(), true)); } }
                        if ui.button("End process").clicked() { if let Some(p) = &selp { kill_req = Some(Confirm::Kill(w.id, p.pid, p.name.clone(), false)); } }
                    });
                });
            });
            if !w.error.is_empty() { ui.colored_label(c32(t.danger), &w.error); }
            if !w.msg.is_empty() { ui.label(RichText::new(&w.msg).color(muted)); }
            let q = w.filter.trim().to_lowercase();
            let mut rows: Vec<&procs::Process> = w.list.iter().filter(|p| q.is_empty() || p.command.to_lowercase().contains(&q) || p.name.to_lowercase().contains(&q) || p.pid.to_string() == q || p.user == q).collect();
            match w.sort {
                Col::Cpu => rows.sort_by(|a, b| b.cpu.unwrap_or(0.0).partial_cmp(&a.cpu.unwrap_or(0.0)).unwrap_or(std::cmp::Ordering::Equal).then(b.rss.cmp(&a.rss))),
                Col::Mem => rows.sort_by(|a, b| b.rss.cmp(&a.rss)), Col::Pid => rows.sort_by_key(|p| p.pid), Col::Name => rows.sort_by_key(|p| p.name.to_lowercase()),
                Col::User => rows.sort_by(|a, b| a.user.cmp(&b.user).then(a.pid.cmp(&b.pid))), Col::Time => rows.sort_by(|a, b| b.elapsed.unwrap_or(0).cmp(&a.elapsed.unwrap_or(0))),
            }
            ui.label(RichText::new(format!("{} of {} processes · click a column to sort", rows.len(), w.list.len())).small().color(muted));
            egui::ScrollArea::both().auto_shrink([false; 2]).show(ui, |ui| {
                egui::Grid::new(("pg", w.id)).striped(true).num_columns(7).spacing(Vec2::new(14.0, 3.0)).show(ui, |ui| {
                    for (c, l) in [(Col::Cpu, "CPU %"), (Col::Mem, "Memory"), (Col::Pid, "PID"), (Col::User, "User"), (Col::Time, "Running"), (Col::Name, "Name")] {
                        let txt = RichText::new(if w.sort == c { format!("{l} ▾") } else { l.to_string() }).small().strong().color(if w.sort == c { c32(t.accent) } else { muted });
                        if ui.add(egui::Label::new(txt).sense(egui::Sense::click())).clicked() { w.sort = c; }
                    }
                    ui.label(RichText::new("Command").small().strong().color(muted)); ui.end_row();
                    for p in rows.iter().take(600) {
                        let sel = w.sel == Some(p.pid);
                        let hot = p.cpu.unwrap_or(0.0) >= 50.0;
                        if ui.selectable_label(sel, RichText::new(p.cpu.map(|x| format!("{x:.1}")).unwrap_or_else(|| "--".into())).color(if hot { c32(t.warning) } else { c32(t.text) })).clicked() { w.sel = Some(p.pid); }
                        ui.label(p.rss_label()); ui.label(RichText::new(p.pid.to_string()).monospace()); ui.label(&p.user); ui.label(p.elapsed_label());
                        if ui.selectable_label(sel, &p.name).clicked() { w.sel = Some(p.pid); }
                        ui.label(RichText::new(p.command.chars().take(160).collect::<String>()).monospace().small().color(muted)); ui.end_row();
                    }
                });
            });
        });
        w.open = open;
    }
    app.win.procs.retain(|w| w.open);
    if let Some(k) = kill_req { app.dlg.confirm = Some(k); }
    for (argv, title) in launch { app.launch(argv, &title, false); }

    // ------------------------------------------------------------------ run on many servers
    let servers: Vec<Server> = app.hub.servers().to_vec(); let tags = app.hub.store.tags();
    if let Some(f) = app.win.fleet.as_mut() {
        let mut open = f.open;
        egui::Window::new("Run on many servers").open(&mut open).default_size([760.0, 540.0]).resizable(true).show(ctx, |ui| {
            ui.label(RichText::new("Runs over SSH with key login, no terminal; output shows side by side.").color(muted));
            ui.horizontal(|ui| {
                ui.label("On"); ui.radio_value(&mut f.target, Target::All, format!("All ({})", servers.len()));
                for tg in &tags { ui.radio_value(&mut f.target, Target::Tag(tg.clone()), tg.as_str()); }
                ui.radio_value(&mut f.target, Target::Pick, "Pick…");
            });
            if f.target == Target::Pick { ui.horizontal_wrapped(|ui| { for s in &servers { let mut on = f.picked.contains(&s.id); if ui.checkbox(&mut on, &s.name).changed() { if on { f.picked.insert(s.id.clone()); } else { f.picked.remove(&s.id); } } } }); }
            let targets: Vec<Server> = servers.iter().filter(|s| match &f.target { Target::All => true, Target::Tag(tg) => &s.tag == tg, Target::Pick => f.picked.contains(&s.id) }).cloned().collect();
            ui.horizontal(|ui| {
                let te = ui.add(egui::TextEdit::singleline(&mut f.command).font(egui::TextStyle::Monospace).hint_text("e.g. df -h /   ·   docker ps   ·   sudo -n dnf -y upgrade").desired_width(ui.available_width() - 150.0));
                let enter = te.lost_focus() && ui.input(|i| i.key_pressed(egui::Key::Enter));
                if f.running { if ui.button("Stop").clicked() { f.cancel.store(true, Ordering::Relaxed); f.running = false; } }
                else if (ui.add_enabled(!targets.is_empty() && !f.command.trim().is_empty(), egui::Button::new(RichText::new(format!("Run on {}", targets.len())).strong().color(Color32::WHITE)).fill(c32(t.accent))).clicked() || enter) && !targets.is_empty() && !f.command.trim().is_empty() {
                    f.run += 1; f.results.clear(); f.expected = targets.len(); f.running = true; f.cancel = Arc::new(AtomicBool::new(false));
                    let (cmd, run, tx, c, cancel) = (f.command.trim().to_string(), f.run, app.tx.clone(), ctx.clone(), f.cancel.clone());
                    std::thread::spawn(move || {
                        let next = std::sync::atomic::AtomicUsize::new(0);
                        std::thread::scope(|sc| { for _ in 0..8.min(targets.len()) { sc.spawn(|| loop {
                            if cancel.load(Ordering::Relaxed) { break; }
                            let i = next.fetch_add(1, Ordering::Relaxed); if i >= targets.len() { break; }
                            let r = fleet::run_one(&targets[i], &cmd, 120.0); let _ = tx.send(UiMsg::Fleet(run, r)); c.request_repaint();
                        }); } });
                    });
                }
            });
            if f.running { ui.add(egui::ProgressBar::new(f.results.len() as f32 / f.expected.max(1) as f32).text(format!("{} / {}", f.results.len(), f.expected))); }
            let ok = f.results.iter().filter(|r| r.ok()).count();
            if !f.results.is_empty() { ui.label(RichText::new(format!("{ok} ok · {} failed", f.results.len() - ok)).color(muted)); }
            egui::ScrollArea::vertical().auto_shrink([false; 2]).show(ui, |ui| {
                for r in &f.results {
                    let exp = f.expanded.contains(&r.server.id);
                    ui.horizontal(|ui| {
                        ui.label(RichText::new(if r.ok() { "✔" } else { "✖" }).color(if r.ok() { c32(t.success) } else { c32(t.danger) }));
                        if ui.selectable_label(exp, RichText::new(&r.server.name).strong()).on_hover_text("Show full output").clicked() { if exp { f.expanded.remove(&r.server.id); } else { f.expanded.insert(r.server.id.clone()); } }
                        ui.label(RichText::new(format!("{:.1}s", r.seconds)).color(muted));
                        ui.label(RichText::new(r.summary()).monospace().small());
                    });
                    if exp { let mut text = format!("{}{}", r.stdout, if r.stderr.trim().is_empty() { String::new() } else { format!("\n--- stderr ---\n{}", r.stderr) }); ui.add(egui::TextEdit::multiline(&mut text).font(egui::TextStyle::Monospace).desired_width(f32::INFINITY).desired_rows(4)); }
                }
            });
        });
        f.open = open;
    }

    // ------------------------------------------------------------------ alerts & activity
    if app.win.activity {
        let mut open = true; let mut clear = false;
        let (active, events) = app.hub.history.as_ref().map(|h| (h.active(), h.events(300, None))).unwrap_or_default();
        let names: std::collections::HashMap<String, String> = app.hub.servers().iter().map(|s| (s.id.clone(), s.name.clone())).collect();
        egui::Window::new("Alerts & activity").open(&mut open).default_size([640.0, 480.0]).resizable(true).show(ctx, |ui| {
            if !app.hub.recording() && !app.tray_running { ui.label(RichText::new("Alerts are recorded by the tray monitor, which isn't running.").color(c32(t.warning))); }
            ui.label(RichText::new(format!("ACTIVE ({})", active.len())).small().strong().color(muted));
            if active.is_empty() { ui.label(RichText::new("Nothing wrong right now.").color(muted)); }
            for e in &active { ui.horizontal(|ui| { ui.label(RichText::new(sev_icon(&e.severity, false)).color(sev_col(app, &e.severity))); ui.label(&e.message); ui.label(RichText::new(format!("since {}", e.time_label())).color(muted)); }); }
            ui.add_space(6.0);
            ui.horizontal(|ui| { ui.label(RichText::new("LOG").small().strong().color(muted)); ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| { if ui.small_button("Clear log").clicked() { clear = true; } }); });
            egui::ScrollArea::vertical().auto_shrink([false; 2]).show(ui, |ui| {
                if events.is_empty() { ui.label(RichText::new("Nothing recorded yet.").color(muted)); }
                egui::Grid::new("ev").striped(true).num_columns(3).spacing(Vec2::new(12.0, 4.0)).show(ui, |ui| {
                    for e in &events { ui.label(RichText::new(e.time_label()).monospace().color(muted)); ui.label(RichText::new(sev_icon(&e.severity, e.resolved)).color(if e.resolved { c32(t.success) } else { sev_col(app, &e.severity) }));
                        ui.label(format!("{}{}", e.message, if names.contains_key(&e.server_id) { "" } else { "  (deleted server)" })); ui.end_row(); }
                });
            });
        });
        if clear { if let Some(h) = &app.hub.history { h.clear_events(); } }
        app.win.activity = open;
    }

    // ------------------------------------------------------------------ tunnels
    if app.win.tunnels {
        let mut open = true;
        egui::Window::new("Active tunnels").open(&mut open).default_width(560.0).show(ctx, |ui| {
            if app.tunnels.is_empty() { ui.label(RichText::new("No tunnels running. Start one from a server's Tunnels tab or More → Port forward.").color(muted)); }
            for tn in &app.tunnels { ui.horizontal(|ui| { ui.label(RichText::new(format!("-{}", tn.kind)).monospace().strong()); ui.label(tn.description()); ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| { if ui.small_button("Stop").clicked() { acts.push(Act::StopTunnel(tn.id.clone())); } }); }); }
            if app.tunnels.len() > 1 { ui.separator(); if ui.button("Stop all").clicked() { for tn in &app.tunnels { acts.push(Act::StopTunnel(tn.id.clone())); } } }
        });
        app.win.tunnels = open;
    }
}
fn sev_icon(sev: &str, resolved: bool) -> &'static str { if resolved { "✔" } else { match sev { "critical" => "✖", "warning" => "⚠", _ => "ℹ" } } }
fn sev_col(app: &App, sev: &str) -> Color32 { let t = app.theme(); match sev { "critical" => c32(t.danger), "warning" => c32(t.warning), _ => c32(t.info) } }
