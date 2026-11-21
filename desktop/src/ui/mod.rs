//! The main window: server list on the left, the selected server on the right, everything else in the menu bar.
mod detail;
mod dialogs;
mod sidebar;
mod windows;

use crate::core::containers::Container;
use crate::core::model::Server;
use crate::core::{agent, fleet, mounts, net, paths, procs, sshcmd, terminal, themes, tunnels};
use crate::hub::{Hub, Level};
use crate::{icon, ipc};
use eframe::egui::{self, Color32, Key, Modifiers, RichText};
use std::collections::HashMap;
use std::sync::mpsc::{channel, Receiver, Sender};
use std::sync::Arc;
use std::time::{Duration, Instant};

pub fn c32(c: u32) -> Color32 { let (r, g, b) = themes::rgb(c); Color32::from_rgb(r, g, b) }

#[derive(Clone, Copy, PartialEq)]
pub enum Sort { Name, Status, Latency, Recent }

pub enum UiMsg {
    Procs(u64, Result<Vec<procs::Process>, String>),
    ProcAction(u64, Result<String, String>),
    Fleet(u64, fleet::RunResult),
    ScanProgress(usize, usize),
    ScanDone(Vec<net::Found>),
    Mac(String),
    Ipc(String),
}

pub enum Act {
    Select(String), Connect(String, Option<bool>), Sftp(String), CopyCmd(String), OpenFiles(String), ToggleBookmark(String), ToggleSshfs(String),
    Procs(String), Htop(String), FindContainers(String), NewTunnel(String), StopTunnel(String), Wake(String), PushKey(String),
    Agent(String, bool), AgentStatus(String), ToggleFav(String), ToggleTray(String), Edit(String), Add, Duplicate(String), AskDelete(String), Delete(String),
    RunCmd(String, usize), AddCmd(String), EditCmd(String, usize), DelCmd(String, usize),
    Ctr(String, Container, &'static str), AskStopCtr(String, Container), CtrLogs(String, Container), CtrShell(String, Container), CtrStats(String, Option<Container>),
    Refresh, Scan, Import, Export, Backup, Restore, Settings, Fleet, Activity, TunnelsWin, Tui, Shortcuts, About, Quit, CloseWindow, OpenUrl(String),
}

pub struct App {
    pub hub: Hub,
    pub sel: Option<String>,
    pub search: String, pub tag_filter: String, pub sort: Sort, pub focus_search: bool,
    pub status: Option<(Level, String, Instant)>,
    pub tx: Sender<UiMsg>, rx: Receiver<UiMsg>,
    pub dlg: dialogs::Dialogs,
    pub win: windows::Windows,
    pub tunnels: Vec<tunnels::Tunnel>, tunnels_t: Instant,
    pub avail: HashMap<String, (Instant, Option<f64>, Option<f64>, Vec<f64>)>,
    pub fs_state: HashMap<String, (Instant, bool, bool)>,   // bookmarked, mounted
    applied_theme: String,
    pub tray_running: bool, tray_check: Instant,
    pub detail_tab: detail::Tab,
}

pub fn run(procs_for: Option<String>, activity: bool) {
    let icon = icon::app_icon(128);
    let opts = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default().with_title("sshm — SSH Connection Hub").with_app_id("io.github.marioman68.sshm")
            .with_inner_size([1240.0, 800.0]).with_min_inner_size([940.0, 580.0])
            .with_icon(egui::IconData { rgba: icon::to_rgba(&icon), width: 128, height: 128 }),
        ..Default::default()
    };
    let _ = eframe::run_native("sshm", opts, Box::new(move |cc| Ok(Box::new(App::new(cc, procs_for, activity)))));
}

impl App {
    fn new(cc: &eframe::CreationContext<'_>, procs_for: Option<String>, activity: bool) -> App {
        let ctx = cc.egui_ctx.clone();
        let waker: crate::hub::Waker = { let c = ctx.clone(); Arc::new(move || c.request_repaint()) };
        // the tray owns telemetry; if it isn't running (--no-tray) this window takes the port itself
        let own = !ipc::alive(&paths::tray_socket());
        let hub = Hub::new(own, waker);
        let (tx, rx) = channel();
        { let t = tx.clone(); let c = ctx.clone(); ipc::serve(&paths::window_socket(), move |l| { let _ = t.send(UiMsg::Ipc(l.to_string())); c.request_repaint(); }); }
        add_fallback_fonts(&ctx);
        let mut app = App { sel: hub.servers().first().map(|s| s.id.clone()), hub, search: String::new(), tag_filter: String::new(), sort: Sort::Name, focus_search: false, status: None,
            tx, rx, dlg: Default::default(), win: Default::default(), tunnels: tunnels::list(), tunnels_t: Instant::now(), avail: HashMap::new(), fs_state: HashMap::new(),
            applied_theme: String::new(), tray_running: !own, tray_check: Instant::now(), detail_tab: detail::Tab::Details };
        app.apply_theme(&ctx);
        if let Some(id) = procs_for { app.open_procs(&id); }
        if activity { app.win.activity = true; }
        if let Ok(name) = std::env::var("SSHM_SELECT") { if let Some(s) = app.hub.store.by_name(&name) { app.sel = Some(s.id.clone()); } }
        // SSHM_OPEN=procs|edit|settings|fleet|scan|activity opens a view at start (used for screenshots while developing)
        if let (Ok(v), Some(id)) = (std::env::var("SSHM_OPEN"), app.sel.clone()) {
            match v.as_str() { "procs" => app.open_procs(&id), "edit" => app.dlg.editor = app.hub.store.get(&id).cloned().map(dialogs::Editor::edit), "settings" => app.dlg.settings = Some(dialogs::SettingsDlg::new(&app.hub.settings)),
                "fleet" => app.win.fleet = Some(Default::default()), "scan" => app.dlg.scan = Some(dialogs::ScanDlg::new()), "activity" => app.win.activity = true,
                "containers" => app.detail_tab = detail::Tab::Containers, "commands" => app.detail_tab = detail::Tab::Commands, _ => {} }
        }
        app
    }
    pub fn theme(&self) -> &'static themes::Theme { themes::get(&self.hub.settings.theme) }
    fn apply_theme(&mut self, ctx: &egui::Context) {
        let t = self.theme(); self.applied_theme = t.name.to_string();
        let mut v = if t.dark { egui::Visuals::dark() } else { egui::Visuals::light() };
        let (bg, surf, surf2, border, text, accent) = (c32(t.bg), c32(t.surface), c32(t.surface2), c32(t.border), c32(t.text), c32(t.accent));
        v.panel_fill = surf; v.window_fill = surf; v.extreme_bg_color = bg; v.faint_bg_color = surf2; v.code_bg_color = surf2;
        v.override_text_color = Some(text); v.hyperlink_color = accent;
        v.selection.bg_fill = accent.linear_multiply(if t.dark { 0.35 } else { 0.25 }); v.selection.stroke.color = text;
        v.window_stroke.color = border; v.widgets.noninteractive.bg_stroke.color = border;
        v.widgets.inactive.weak_bg_fill = surf2; v.widgets.inactive.bg_fill = surf2;
        v.widgets.hovered.weak_bg_fill = surf2.gamma_multiply(1.25); v.widgets.hovered.bg_stroke.color = accent.linear_multiply(0.6);
        v.widgets.active.weak_bg_fill = accent.linear_multiply(0.5);
        for w in [&mut v.widgets.inactive, &mut v.widgets.hovered, &mut v.widgets.active, &mut v.widgets.noninteractive, &mut v.widgets.open] { w.rounding = egui::Rounding::same(4.0); }
        v.window_rounding = egui::Rounding::same(6.0); v.menu_rounding = egui::Rounding::same(5.0);
        ctx.set_visuals(v);
        ctx.style_mut(|s| { s.spacing.item_spacing = egui::vec2(8.0, 6.0); s.spacing.button_padding = egui::vec2(10.0, 4.0); s.spacing.interact_size.y = 24.0; });
    }
    pub fn current(&self) -> Option<Server> { self.sel.as_ref().and_then(|id| self.hub.store.get(id)).cloned() }
    pub fn say(&mut self, l: Level, m: impl Into<String>) { self.status = Some((l, m.into(), Instant::now())); }

    pub fn visible(&self) -> Vec<Server> {
        let mut v: Vec<Server> = self.hub.servers().iter().filter(|s| self.tag_filter.is_empty() || s.tag == self.tag_filter).cloned().collect();
        let q = self.search.trim();
        if !q.is_empty() {
            let mut scored: Vec<(i32, Server)> = v.into_iter().map(|s| (crate::core::model::fuzzy_score(q, &s.search_text()), s)).filter(|(sc, _)| *sc > 0).collect();
            scored.sort_by(|a, b| b.0.cmp(&a.0)); v = scored.into_iter().map(|x| x.1).collect();
            v.sort_by_key(|s| !s.favorite); return v;
        }
        match self.sort {
            Sort::Name => v.sort_by_key(|s| s.name.to_lowercase()),
            Sort::Status => v.sort_by_key(|s| (!self.hub.status(&s.id).map_or(false, |x| x.online), s.name.to_lowercase())),
            Sort::Latency => v.sort_by(|a, b| { let l = |s: &Server| self.hub.status(&s.id).filter(|x| x.online).and_then(|x| x.latency_ms).unwrap_or(1e9); l(a).partial_cmp(&l(b)).unwrap_or(std::cmp::Ordering::Equal).then(a.name.to_lowercase().cmp(&b.name.to_lowercase())) }),
            Sort::Recent => v.sort_by(|a, b| b.last_connected.partial_cmp(&a.last_connected).unwrap_or(std::cmp::Ordering::Equal)),
        }
        v.sort_by_key(|s| !s.favorite); v
    }
    /// uptime 24h / 7d and a latency series, cached (it reads the database)
    pub fn availability(&mut self, id: &str) -> (Option<f64>, Option<f64>, Vec<f64>) {
        if let Some((t, a, b, l)) = self.avail.get(id) { if t.elapsed() < Duration::from_secs(30) { return (*a, *b, l.clone()); } }
        let r = match &self.hub.history { Some(h) => (h.uptime(id, 86400.0), h.uptime(id, 7.0 * 86400.0), h.latency_series(id, 86400.0, 48)), None => (None, None, vec![]) };
        self.avail.insert(id.to_string(), (Instant::now(), r.0, r.1, r.2.clone())); r
    }
    pub fn fs(&mut self, s: &Server) -> (bool, bool) {
        if let Some((t, b, m)) = self.fs_state.get(&s.id) { if t.elapsed() < Duration::from_secs(5) { return (*b, *m); } }
        let r = (mounts::is_bookmarked(s, &self.hub.settings), mounts::is_mounted(s, &self.hub.settings));
        self.fs_state.insert(s.id.clone(), (Instant::now(), r.0, r.1)); r
    }
    pub fn launch(&mut self, argv: Vec<String>, title: &str, pause: bool) -> bool {
        match terminal::launch(&sshcmd::hold(&argv, title, pause), &self.hub.settings.terminal) { Ok(_) => true, Err(e) => { self.say(Level::Error, e); false } }
    }
    pub fn open_procs(&mut self, id: &str) {
        if let Some(s) = self.hub.store.get(id).cloned() { self.sel = Some(s.id.clone()); self.win.open_procs(s, &self.tx); }
    }

    fn run_act(&mut self, ctx: &egui::Context, a: Act) {
        let find = |app: &App, id: &str| app.hub.store.get(id).cloned();
        let session = self.hub.settings.tmux_session.clone();
        match a {
            Act::Select(id) => { self.sel = Some(id); }
            Act::Connect(id, tmux) => if let Some(s) = find(self, &id) {
                if self.launch(sshcmd::ssh_command(&s, tmux, None, &session), &format!("{} · {}", s.name, s.endpoint()), false) { self.hub.store.mark_connected(&id); self.say(Level::Info, format!("Opening terminal for {}", s.name)); }
            },
            Act::Sftp(id) => if let Some(s) = find(self, &id) { self.launch(sshcmd::sftp_command(&s), &format!("SFTP · {}", s.name), false); },
            Act::CopyCmd(id) => if let Some(s) = find(self, &id) { let t = sshcmd::display(&sshcmd::ssh_command(&s, None, None, &session)); ctx.copy_text(t.clone()); self.say(Level::Success, format!("Copied: {t}")); },
            Act::OpenFiles(id) => if let Some(s) = find(self, &id) {
                let (_, mounted) = self.fs(&s);
                let target = if mounted { mounts::mountpoint(&s, &self.hub.settings).to_string_lossy().to_string() } else { s.sftp_url() };
                if terminal::xdg_open(&target) { self.say(Level::Info, format!("Opening {target}")); } else { self.say(Level::Error, "xdg-open is not available"); }
            },
            Act::ToggleBookmark(id) => if let Some(s) = find(self, &id) { match mounts::toggle_bookmark(&s, &self.hub.settings) { Ok(on) => self.say(Level::Success, format!("{} {}", if on { "Bookmarked" } else { "Removed bookmark for" }, s.name)), Err(e) => self.say(Level::Error, format!("Bookmark failed: {e}")) } self.fs_state.remove(&id); },
            Act::ToggleSshfs(id) => if let Some(s) = find(self, &id) {
                let (_, mounted) = self.fs(&s); let st = self.hub.settings.clone(); self.fs_state.remove(&id);
                self.say(Level::Info, format!("{} {}…", if mounted { "Unmounting" } else { "Mounting" }, s.name));
                self.hub.task(move || {
                    let r = if mounted { mounts::unmount(&s, &st) } else { mounts::mount(&s, &st) };
                    match r { Ok(m) => { if !mounted { terminal::xdg_open(&mounts::mountpoint(&s, &st).to_string_lossy()); } (Level::Success, m, false) } Err(e) => (Level::Error, format!("SSHFS: {e}"), false) }
                });
            },
            Act::Procs(id) => self.open_procs(&id),
            Act::Htop(id) => if let Some(s) = find(self, &id) { self.launch(procs::top_argv(&s, &session), &format!("htop · {}", s.name), false); },
            Act::FindContainers(id) => if let Some(s) = find(self, &id) { if self.hub.discover_containers(&s, true) { self.say(Level::Info, format!("Looking for docker / podman containers on {}…", s.name)); } },
            Act::NewTunnel(id) => if let Some(s) = find(self, &id) { self.dlg.tunnel = Some(dialogs::TunnelDlg::new(s)); },
            Act::StopTunnel(tid) => { if tunnels::stop(&tid) { self.say(Level::Success, "Tunnel stopped"); } self.tunnels = tunnels::list(); },
            Act::Wake(id) => if let Some(s) = find(self, &id) {
                if s.mac.is_empty() { self.say(Level::Warning, format!("{} has no MAC address — edit it and use Detect", s.name)); }
                else { match net::wake(&s.mac) { Ok(_) => self.say(Level::Success, format!("Magic packet sent to {} ({})", s.name, s.mac)), Err(e) => self.say(Level::Error, format!("Wake-on-LAN failed: {e}")) } }
            },
            Act::PushKey(id) => if let Some(s) = find(self, &id) { self.launch(sshcmd::copy_id_command(&s), &format!("Push SSH key · {}", s.name), true); },
            Act::Agent(id, remove) => if let Some(s) = find(self, &id) { self.deploy_agent(s, remove); },
            Act::AgentStatus(id) => if let Some(s) = find(self, &id) { self.launch(sshcmd::ssh_command(&s, Some(false), Some(agent::STATUS_COMMAND), &session), &format!("Agent status · {}", s.name), true); },
            Act::ToggleFav(id) => self.mutate(&id, |s| s.favorite = !s.favorite),
            Act::ToggleTray(id) => self.mutate(&id, |s| s.tray = !s.tray),
            Act::Edit(id) => if let Some(s) = find(self, &id) { self.dlg.editor = Some(dialogs::Editor::edit(s)); },
            Act::Add => { self.dlg.editor = Some(dialogs::Editor::add(self.tag_filter.clone())); }
            Act::Duplicate(id) => if let Some(s) = find(self, &id) { let mut d = s.clone(); d.id = crate::core::model::new_id(); d.name = self.hub.store.unique_name(&format!("{} copy", s.name)); d.last_connected = 0.0; self.dlg.editor = Some(dialogs::Editor::add_from(d)); },
            Act::AskDelete(id) => if let Some(s) = find(self, &id) { self.dlg.confirm = Some(dialogs::Confirm::delete_server(&s)); },
            Act::Delete(id) => {
                let name = find(self, &id).map(|s| s.name).unwrap_or_default();
                match self.hub.store.remove(&id) { Ok(_) => { if let Some(h) = &self.hub.history { h.forget(&id); } self.say(Level::Success, format!("Deleted {name}")); if self.sel.as_deref() == Some(&id) { self.sel = self.visible().first().map(|s| s.id.clone()); } } Err(e) => self.say(Level::Error, e) }
            }
            Act::RunCmd(id, i) => if let Some(s) = find(self, &id) { if let Some(c) = s.commands.get(i).cloned() { self.launch(sshcmd::ssh_command(&s, Some(false), Some(&c.command), &session), &format!("{} · {}", c.label, s.name), true); } },
            Act::AddCmd(id) => { self.dlg.command = Some(dialogs::CommandDlg::new(id, None, None)); }
            Act::EditCmd(id, i) => if let Some(s) = find(self, &id) { if let Some(c) = s.commands.get(i).cloned() { self.dlg.command = Some(dialogs::CommandDlg::new(id, Some(i), Some(c))); } },
            Act::DelCmd(id, i) => self.mutate(&id, |s| { if i < s.commands.len() { s.commands.remove(i); } }),
            Act::Ctr(hid, c, action) => if let Some(h) = find(self, &hid) {
                self.say(Level::Info, format!("{} {}…", capitalize(action), c.name));
                let h2 = h.clone();
                self.hub.task(move || { match crate::core::containers::run_action(&h2, &c, action) { Ok(m) => (Level::Success, m, false), Err(e) => (Level::Error, format!("{action} {} failed: {e}", c.name), false) } });
                self.hub.discover_containers(&h, true);
            },
            Act::AskStopCtr(hid, c) => { self.dlg.confirm = Some(dialogs::Confirm::stop_container(hid, c)); }
            Act::CtrLogs(hid, c) => if let Some(h) = find(self, &hid) { self.launch(crate::core::containers::logs_argv(&h, &c, &session), &format!("logs · {} on {}", c.name, h.name), false); },
            Act::CtrShell(hid, c) => if let Some(h) = find(self, &hid) { self.launch(crate::core::containers::shell_argv(&h, &c, &session), &format!("shell · {} on {}", c.name, h.name), false); },
            Act::CtrStats(hid, c) => if let Some(h) = find(self, &hid) { self.launch(crate::core::containers::stats_argv(&h, c.as_ref(), &session), &format!("stats · {}", h.name), false); },
            Act::Refresh => { if self.hub.refresh() { self.say(Level::Info, "Refreshing server status…"); } }
            Act::Scan => { self.dlg.scan = Some(dialogs::ScanDlg::new()); }
            Act::Import => { let c = fleet::import_ssh_config(self.hub.servers()); if c.is_empty() { self.say(Level::Info, "Nothing new in ~/.ssh/config"); } else { self.dlg.import = Some(dialogs::ImportDlg::new(c)); } }
            Act::Export => { let v = self.visible(); self.dlg.export = Some(fleet::export_ssh_config(&v)); }
            Act::Backup => if let Some(p) = rfd::FileDialog::new().set_title("Back up servers").set_file_name("sshm-servers.json").add_filter("JSON", &["json"]).save_file() {
                match fleet::export_backup(self.hub.servers(), &p) { Ok(n) => self.say(Level::Success, format!("Backed up {n} server(s) to {}", p.display())), Err(e) => self.say(Level::Error, e) }
            },
            Act::Restore => if let Some(p) = rfd::FileDialog::new().set_title("Restore servers").add_filter("JSON", &["json"]).pick_file() {
                match fleet::import_backup(&mut self.hub.store, &p, false) { Ok((a, u)) => self.say(Level::Success, format!("Restored: {a} added, {u} updated")), Err(e) => self.say(Level::Error, e) }
                self.hub.refresh();
            },
            Act::Settings => { self.dlg.settings = Some(dialogs::SettingsDlg::new(&self.hub.settings)); }
            Act::Fleet => { self.win.fleet.get_or_insert_with(Default::default).open = true; }
            Act::Activity => self.win.activity = true,
            Act::TunnelsWin => { self.tunnels = tunnels::list(); self.win.tunnels = true; }
            Act::Tui => { let exe = paths::which("sshm").map(|p| p.to_string_lossy().to_string()).unwrap_or_else(|| "sshm".into()); self.launch(vec![exe], "sshm", false); }
            Act::Shortcuts => self.dlg.shortcuts = true,
            Act::About => self.dlg.about = true,
            Act::Quit => { let _ = ipc::send(&paths::tray_socket(), "quit"); ctx.send_viewport_cmd(egui::ViewportCommand::Close); }
            Act::CloseWindow => ctx.send_viewport_cmd(egui::ViewportCommand::Close),
            Act::OpenUrl(u) => { terminal::xdg_open(&u); }
        }
    }
    pub fn mutate(&mut self, id: &str, f: impl FnOnce(&mut Server)) {
        if let Some(mut s) = self.hub.store.get(id).cloned() { f(&mut s); if let Err(e) = self.hub.store.update(s) { self.say(Level::Error, e); } }
    }
    fn deploy_agent(&mut self, s: Server, remove: bool) {
        let script = if remove { agent::build_remover() } else { agent::build_installer(&s, &self.hub.settings) };
        let verb = if remove { "Removing agent from" } else { "Deploying agent to" };
        self.say(Level::Info, format!("{verb} {}…", s.name));
        let term = self.hub.settings.terminal.clone(); let title = format!("{verb} {}", s.name);
        self.hub.task(move || match agent::run_noninteractive(&s, &script) {
            Ok(o) if o.code == Some(0) => (Level::Success, o.stdout.trim().lines().last().unwrap_or("Done").to_string(), false),
            Ok(o) if o.code != Some(255) => (Level::Error, format!("Agent {} failed: {}", if remove { "removal" } else { "install" }, o.stderr.trim().lines().last().unwrap_or("error")), false),
            _ => {   // no key login: continue in a terminal where ssh can ask for a password / sudo
                match agent::write_script(&script) {
                    Ok(p) => match terminal::launch(&sshcmd::hold(&sshcmd::with_stdin_file(&agent::remote_script_argv(&s, false), &p), &title, true), &term) {
                        Ok(_) => (Level::Info, "Key login unavailable — continuing in a terminal".into(), false),
                        Err(e) => { let _ = std::fs::remove_file(&p); (Level::Error, e, false) } },
                    Err(e) => (Level::Error, e, false),
                }
            }
        });
    }

    fn keys(&mut self, ctx: &egui::Context, acts: &mut Vec<Act>) {
        let typing = ctx.wants_keyboard_input();
        let sel = self.sel.clone();
        ctx.input_mut(|i| {
            let cmd = Modifiers::COMMAND;
            if i.consume_key(cmd, Key::K) || i.consume_key(cmd, Key::F) { self.focus_search = true; }
            if i.consume_key(cmd, Key::N) { acts.push(Act::Add); }
            if i.consume_key(Modifiers::NONE, Key::F5) { acts.push(Act::Refresh); }
            if i.consume_key(cmd, Key::Comma) { acts.push(Act::Settings); }
            if i.consume_key(cmd | Modifiers::SHIFT, Key::R) { acts.push(Act::Fleet); }
            if i.consume_key(cmd, Key::Q) { acts.push(Act::Quit); }
            if i.consume_key(cmd, Key::W) { acts.push(Act::CloseWindow); }
            if let Some(id) = sel {
                if i.consume_key(cmd, Key::T) { acts.push(Act::Connect(id.clone(), Some(true))); }
                if i.consume_key(cmd, Key::E) { acts.push(Act::Edit(id.clone())); }
                if i.consume_key(cmd, Key::P) { acts.push(Act::Procs(id.clone())); }
                if !typing {
                    if i.consume_key(Modifiers::NONE, Key::Enter) { acts.push(Act::Connect(id.clone(), None)); }
                    if i.consume_key(Modifiers::NONE, Key::Delete) { acts.push(Act::AskDelete(id.clone())); }
                }
            }
        });
        if !typing {
            let (up, down) = ctx.input_mut(|i| (i.consume_key(Modifiers::NONE, Key::ArrowUp), i.consume_key(Modifiers::NONE, Key::ArrowDown)));
            if up || down {
                let v = self.visible(); if v.is_empty() { return; }
                let at = v.iter().position(|s| Some(&s.id) == self.sel.as_ref());
                let n = match at { Some(k) => if up { k.saturating_sub(1) } else { (k + 1).min(v.len() - 1) }, None => 0 };
                acts.push(Act::Select(v[n].id.clone()));
            }
        }
    }

    fn menu_bar(&mut self, ctx: &egui::Context, acts: &mut Vec<Act>) {
        let cur = self.current();
        egui::TopBottomPanel::top("menu").show(ctx, |ui| {
            egui::menu::bar(ui, |ui| {
                ui.menu_button("File", |ui| {
                    if item(ui, "Add server…", "Ctrl+N") { acts.push(Act::Add); }
                    if item(ui, "Scan network…", "") { acts.push(Act::Scan); }
                    if item(ui, "Import from ~/.ssh/config…", "") { acts.push(Act::Import); }
                    if item(ui, "Export as ssh_config…", "") { acts.push(Act::Export); }
                    ui.separator();
                    if item(ui, "Back up servers to file…", "") { acts.push(Act::Backup); }
                    if item(ui, "Restore servers from file…", "") { acts.push(Act::Restore); }
                    ui.separator();
                    if item(ui, "Settings…", "Ctrl+,") { acts.push(Act::Settings); }
                    ui.separator();
                    if item(ui, "Close window", "Ctrl+W") { acts.push(Act::CloseWindow); }
                    if item(ui, "Quit sshm", "Ctrl+Q") { acts.push(Act::Quit); }
                });
                ui.add_enabled_ui(cur.is_some(), |ui| ui.menu_button("Server", |ui| { if let Some(s) = &cur { detail::server_menu(self, ui, s, acts); } }));
                ui.menu_button("Tools", |ui| {
                    if item(ui, "Run on many servers…", "Ctrl+Shift+R") { acts.push(Act::Fleet); }
                    if item(ui, "Alerts & activity…", "") { acts.push(Act::Activity); }
                    if item(ui, "Active tunnels…", "") { acts.push(Act::TunnelsWin); }
                    ui.separator();
                    if item(ui, "Open terminal UI", "") { acts.push(Act::Tui); }
                    if item(ui, "Refresh status", "F5") { acts.push(Act::Refresh); }
                });
                ui.menu_button("View", |ui| {
                    ui.menu_button("Theme", |ui| { for t in themes::THEMES.iter() { if ui.radio(self.hub.settings.theme == t.name, t.name).clicked() { self.hub.settings.theme = t.name.to_string(); self.hub.settings.save(); ui.close_menu(); } } });
                    ui.menu_button("Sort list by", |ui| { for (s, l) in [(Sort::Name, "Name"), (Sort::Status, "Status"), (Sort::Latency, "Latency"), (Sort::Recent, "Recently used")] { if ui.radio(self.sort == s, l).clicked() { self.sort = s; ui.close_menu(); } } });
                });
                ui.menu_button("Help", |ui| {
                    if item(ui, "Keyboard shortcuts", "") { acts.push(Act::Shortcuts); }
                    if item(ui, "About sshm", "") { acts.push(Act::About); }
                });
            });
        });
    }

    fn status_bar(&mut self, ctx: &egui::Context, acts: &mut Vec<Act>) {
        let t = self.theme();
        egui::TopBottomPanel::bottom("status").exact_height(26.0).show(ctx, |ui| {
            ui.horizontal_centered(|ui| {
                let active = self.hub.history.as_ref().map(|h| h.active().len()).unwrap_or(0);
                if active > 0 && ui.add(egui::Label::new(RichText::new(format!("⚠ {active} active alert{}", if active == 1 { "" } else { "s" })).color(c32(t.warning))).sense(egui::Sense::click())).on_hover_text("Open alerts & activity").clicked() { acts.push(Act::Activity); }
                if let Some((l, m, at)) = &self.status {
                    if at.elapsed() < Duration::from_secs(9) {
                        let (icon, col) = match l { Level::Success => ("✔", c32(t.success)), Level::Error => ("✖", c32(t.danger)), Level::Warning => ("⚠", c32(t.warning)), Level::Info => ("ℹ", c32(t.muted)) };
                        ui.label(RichText::new(format!("{icon}  {m}")).color(col));
                    }
                }
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    let (on, total) = self.hub.summary();
                    ui.label(RichText::new(format!("{on}/{total} online")).color(c32(t.muted)));
                    if self.hub.probing() { ui.add(egui::Spinner::new().size(12.0)); }
                    let tel = if self.hub.recording() { "receiving telemetry" } else if self.tray_running { "telemetry via tray" } else { "telemetry: another sshm process" };
                    ui.label(RichText::new(tel).color(c32(t.muted)).small());
                });
            });
        });
    }
}

pub fn item(ui: &mut egui::Ui, label: &str, shortcut: &str) -> bool {
    let b = egui::Button::new(label).shortcut_text(shortcut);
    let c = ui.add(b).clicked(); if c { ui.close_menu(); } c
}
pub fn capitalize(s: &str) -> String { let mut c = s.chars(); c.next().map(|f| f.to_uppercase().collect::<String>() + c.as_str()).unwrap_or_default() }
fn add_fallback_fonts(ctx: &egui::Context) {
    let mut fonts = egui::FontDefinitions::default(); let mut n = 0;
    for p in ["/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/google-noto/NotoSansSymbols2-Regular.ttf", "/usr/share/fonts/google-noto/NotoSansMath-Regular.ttf"] {
        if let Ok(b) = std::fs::read(p) { let k = format!("fb{n}"); n += 1; fonts.font_data.insert(k.clone(), egui::FontData::from_owned(b)); for f in [egui::FontFamily::Proportional, egui::FontFamily::Monospace] { fonts.families.entry(f).or_default().push(k.clone()); } }
    }
    if n > 0 { ctx.set_fonts(fonts); }
}

impl eframe::App for App {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        let changed = self.hub.tick();
        if changed { self.avail.retain(|_, v| v.0.elapsed() < Duration::from_secs(30)); }
        for (l, m) in std::mem::take(&mut self.hub.messages) { self.say(l, m); }
        if std::mem::take(&mut self.hub.tunnels_changed) || self.tunnels_t.elapsed() > Duration::from_secs(3) { self.tunnels = tunnels::list(); self.tunnels_t = Instant::now(); }
        self.hub.new_events.clear();   // the tray shows notifications
        if self.tray_check.elapsed() > Duration::from_secs(5) { self.tray_check = Instant::now(); self.tray_running = ipc::alive(&paths::tray_socket()); }
        if self.applied_theme != self.hub.settings.theme { self.apply_theme(ctx); }
        if self.sel.as_ref().map_or(true, |id| self.hub.store.get(id).is_none()) { self.sel = self.visible().first().map(|s| s.id.clone()); }
        while let Ok(m) = self.rx.try_recv() {
            match m {
                UiMsg::Ipc(l) => {
                    if l == "quit" { ctx.send_viewport_cmd(egui::ViewportCommand::Close); }
                    else if let Some(id) = l.strip_prefix("procs ") { self.open_procs(id.trim()); }
                    else if l == "activity" { self.win.activity = true; }
                    ctx.send_viewport_cmd(egui::ViewportCommand::Visible(true)); ctx.send_viewport_cmd(egui::ViewportCommand::Minimized(false)); ctx.send_viewport_cmd(egui::ViewportCommand::Focus);
                }
                other => { self.win.handle(other, &mut self.dlg); }
            }
        }
        let mut acts = vec![];
        self.keys(ctx, &mut acts);
        self.menu_bar(ctx, &mut acts);
        self.status_bar(ctx, &mut acts);
        sidebar::show(self, ctx, &mut acts);
        detail::show(self, ctx, &mut acts);
        dialogs::show(self, ctx, &mut acts);
        windows::show(self, ctx, &mut acts);
        for a in acts { self.run_act(ctx, a); }
        ctx.request_repaint_after(Duration::from_millis(1000));
    }
}
