//! The selected server: header with the main actions, live metrics, then tabs for details, commands, tunnels and containers.
use super::{c32, item, Act, App};
use crate::core::history::{pct_label, strftime};
use crate::core::model::Server;
use crate::core::{agent, mounts};
use eframe::egui::{self, Color32, RichText, Sense, Stroke, Vec2};

#[derive(Clone, Copy, PartialEq)]
pub enum Tab { Details, Commands, Tunnels, Containers }

/// everything you can do to a server (Server menu, More button, right-click)
pub fn server_menu(app: &mut App, ui: &mut egui::Ui, s: &Server, acts: &mut Vec<Act>) {
    let id = s.id.clone();
    if item(ui, "Connect", "Enter") { acts.push(Act::Connect(id.clone(), Some(false))); }
    if item(ui, "Connect in tmux", "Ctrl+T") { acts.push(Act::Connect(id.clone(), Some(true))); }
    if item(ui, "SFTP shell", "") { acts.push(Act::Sftp(id.clone())); }
    if item(ui, "Copy ssh command", "") { acts.push(Act::CopyCmd(id.clone())); }
    ui.separator();
    files_items(app, ui, s, acts);
    ui.separator();
    if item(ui, "Processes…", "Ctrl+P") { acts.push(Act::Procs(id.clone())); }
    if item(ui, "htop in terminal", "") { acts.push(Act::Htop(id.clone())); }
    if item(ui, "Find docker containers", "") { acts.push(Act::FindContainers(id.clone())); }
    ui.separator();
    if item(ui, "Port forward…", "") { acts.push(Act::NewTunnel(id.clone())); }
    if ui.add_enabled(!s.mac.is_empty(), egui::Button::new(if s.mac.is_empty() { "Wake-on-LAN (no MAC set)".to_string() } else { format!("Wake-on-LAN ({})", s.mac) })).clicked() { acts.push(Act::Wake(id.clone())); ui.close_menu(); }
    if item(ui, "Push SSH key…", "") { acts.push(Act::PushKey(id.clone())); }
    ui.menu_button("Telemetry agent", |ui| {
        if item(ui, "Deploy / update", "") { acts.push(Act::Agent(id.clone(), false)); }
        if item(ui, "Show status", "") { acts.push(Act::AgentStatus(id.clone())); }
        if item(ui, "Remove", "") { acts.push(Act::Agent(id.clone(), true)); }
    });
    ui.separator();
    let mut fav = s.favorite; if ui.checkbox(&mut fav, "Favourite").clicked() { acts.push(Act::ToggleFav(id.clone())); ui.close_menu(); }
    let mut tray = s.tray; if ui.checkbox(&mut tray, "Monitor in tray").clicked() { acts.push(Act::ToggleTray(id.clone())); ui.close_menu(); }
    ui.separator();
    if item(ui, "Edit…", "Ctrl+E") { acts.push(Act::Edit(id.clone())); }
    if item(ui, "Duplicate", "") { acts.push(Act::Duplicate(id.clone())); }
    if item(ui, "Delete…", "Del") { acts.push(Act::AskDelete(id)); }
}
fn files_items(app: &mut App, ui: &mut egui::Ui, s: &Server, acts: &mut Vec<Act>) {
    let (bm, mounted) = app.fs(s); let id = s.id.clone();
    if item(ui, "Open in file manager", "") { acts.push(Act::OpenFiles(id.clone())); }
    if item(ui, if bm { "Remove file-manager bookmark" } else { "Bookmark in file manager" }, "") { acts.push(Act::ToggleBookmark(id.clone())); }
    if mounts::sshfs_available() { if item(ui, if mounted { "Unmount SSHFS" } else { "Mount with SSHFS" }, "") { acts.push(Act::ToggleSshfs(id)); } }
    else { ui.add_enabled(false, egui::Button::new("Mount with SSHFS (install sshfs)")); }
}

fn card(ui: &mut egui::Ui, app: &App, add: impl FnOnce(&mut egui::Ui)) {
    let t = app.theme();
    egui::Frame::none().fill(c32(t.surface)).stroke(Stroke::new(1.0_f32, c32(t.border))).rounding(6.0).inner_margin(egui::Margin::symmetric(14.0, 10.0)).show(ui, |ui| { ui.set_width(ui.available_width()); add(ui) });
}
fn caption(ui: &mut egui::Ui, app: &App, text: &str) { ui.label(RichText::new(text).small().strong().color(c32(app.theme().muted))); }
fn bar(ui: &mut egui::Ui, frac: f32, col: Color32, bg: Color32) {
    let (r, _) = ui.allocate_exact_size(Vec2::new(ui.available_width(), 5.0), Sense::hover());
    ui.painter().rect_filled(r, 2.5, bg);
    ui.painter().rect_filled(egui::Rect::from_min_size(r.min, Vec2::new(r.width() * frac.clamp(0.0, 1.0), 5.0)), 2.5, col);
}
fn spark(ui: &mut egui::Ui, vals: &[f64], col: Color32, h: f32, max: Option<f64>) {
    let (r, _) = ui.allocate_exact_size(Vec2::new(ui.available_width(), h), Sense::hover());
    if vals.len() < 2 { return; }
    let m = max.unwrap_or_else(|| vals.iter().cloned().fold(1.0, f64::max)).max(1.0);
    let pts: Vec<egui::Pos2> = vals.iter().enumerate().map(|(i, v)| egui::pos2(r.left() + r.width() * i as f32 / (vals.len() - 1) as f32, r.bottom() - r.height() * (*v / m) as f32)).collect();
    // fill under the line one slice at a time (each slice is convex; the whole area usually isn't)
    for w in pts.windows(2) {
        ui.painter().add(egui::Shape::convex_polygon(vec![w[0], w[1], egui::pos2(w[1].x, r.bottom()), egui::pos2(w[0].x, r.bottom())], col.linear_multiply(0.12), Stroke::NONE));
    }
    ui.painter().add(egui::Shape::line(pts, Stroke::new(1.5_f32, col)));
}
fn pill(ui: &mut egui::Ui, text: &str, col: Color32) {
    egui::Frame::none().fill(col.linear_multiply(0.16)).rounding(10.0).inner_margin(egui::Margin::symmetric(8.0, 2.0)).show(ui, |ui| { ui.label(RichText::new(text).color(col).small().strong()); });
}
fn level_col(app: &App, pct: f64) -> Color32 { let t = app.theme(); if pct >= 90.0 { c32(t.danger) } else if pct >= 75.0 { c32(t.warning) } else { c32(t.accent) } }

pub fn show(app: &mut App, ctx: &egui::Context, acts: &mut Vec<Act>) {
    let t = app.theme();
    egui::CentralPanel::default().frame(egui::Frame::central_panel(&ctx.style()).inner_margin(egui::Margin::symmetric(22.0, 16.0))).show(ctx, |ui| {
        let Some(s) = app.current() else {
            ui.add_space(80.0);
            ui.vertical_centered(|ui| {
                ui.label(RichText::new(if app.hub.servers().is_empty() { "No servers yet" } else { "Select a server" }).size(20.0));
                ui.add_space(6.0);
                ui.label(RichText::new("Add one by hand, find the ones on your network, or bring them in from ~/.ssh/config.").color(c32(t.muted)));
                ui.add_space(14.0);
                ui.horizontal(|ui| {
                    ui.add_space((ui.available_width() - 360.0).max(0.0) / 2.0);
                    if ui.button("Add server…").clicked() { acts.push(Act::Add); }
                    if ui.button("Scan network…").clicked() { acts.push(Act::Scan); }
                    if ui.button("Import ~/.ssh/config…").clicked() { acts.push(Act::Import); }
                });
            });
            return;
        };
        let st = app.hub.status(&s.id).cloned();
        let tel = st.as_ref().and_then(|x| x.telemetry.clone());
        let link = app.hub.links().get(&s.id).cloned();

        // ---------------------------------------------------------------- header
        ui.horizontal(|ui| {
            ui.vertical(|ui| {
                ui.horizontal(|ui| {
                    ui.label(RichText::new(if s.favorite { format!("★ {}", s.name) } else { s.name.clone() }).size(22.0).strong());
                    let (txt, col) = match st.as_ref().map(|x| x.state()) { Some("online") => ("Online", c32(t.success)), Some("degraded") => ("SSH down", c32(t.warning)), Some(_) => ("Offline", c32(t.danger)), None => ("Checking…", c32(t.muted)) };
                    pill(ui, txt, col);
                    if let Some(l) = &link { pill(ui, &format!("⬢ {} on {}", l.container.name, l.host.name), c32(t.info)); }
                    if !s.tag.is_empty() { pill(ui, &s.tag, c32(t.muted)); }
                    if tel.as_ref().and_then(|x| x.reboot_required) == Some(true) { pill(ui, "⟳ Reboot required", c32(t.warning)); }
                });
                let ep = format!("{}{}", s.endpoint(), if s.jump.is_empty() { String::new() } else { format!("   via {}", s.jump) });
                ui.add(egui::Label::new(RichText::new(ep).color(c32(t.muted)).monospace()).selectable(true));
            });
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Min), |ui| {
                let sid = s.id.clone();
                ui.menu_button("More ▾", |ui| { server_menu(app, ui, &s, acts); });
                if ui.button("Processes").on_hover_text("Live process list (Ctrl+P)").clicked() { acts.push(Act::Procs(sid.clone())); }
                ui.menu_button("Files ▾", |ui| { files_items(app, ui, &s, acts); ui.separator(); if item(ui, "SFTP shell", "") { acts.push(Act::Sftp(sid.clone())); } });
                ui.spacing_mut().item_spacing.x = 1.0;
                ui.menu_button("▾", |ui| {
                    if item(ui, "Connect", "Enter") { acts.push(Act::Connect(sid.clone(), Some(false))); }
                    if item(ui, "Connect in tmux", "Ctrl+T") { acts.push(Act::Connect(sid.clone(), Some(true))); }
                    if item(ui, "SFTP shell", "") { acts.push(Act::Sftp(sid.clone())); }
                    ui.separator();
                    if item(ui, "Copy ssh command", "") { acts.push(Act::CopyCmd(sid.clone())); }
                });
                let b = egui::Button::new(RichText::new("Connect").strong().color(Color32::WHITE)).fill(c32(t.accent).linear_multiply(if t.dark { 0.85 } else { 1.0 }));
                if ui.add(b).on_hover_text(if s.tmux { "Open a terminal with tmux (Enter)" } else { "Open a terminal (Enter)" }).clicked() { acts.push(Act::Connect(sid, None)); }
            });
        });
        ui.add_space(10.0);

        egui::ScrollArea::vertical().auto_shrink([false; 2]).show(ui, |ui| {
            // ------------------------------------------------------------ metrics
            match &tel {
                Some(tl) => {
                    ui.columns(4, |c| {
                        card(&mut c[0], app, |ui| { caption(ui, app, "CPU"); ui.label(RichText::new(tl.cpu.map(|x| format!("{x:.0}%")).unwrap_or_else(|| "--".into())).size(20.0)); spark(ui, &tl.history, c32(t.accent), 26.0, Some(100.0)); ui.label(RichText::new(format!("load {}", tl.load_label())).small().color(c32(t.muted))); });
                        card(&mut c[1], app, |ui| { caption(ui, app, "MEMORY"); let p = tl.mem_pct(); ui.label(RichText::new(p.map(|x| format!("{x:.0}%")).unwrap_or_else(|| "--".into())).size(20.0)); ui.add_space(8.0); bar(ui, p.unwrap_or(0.0) as f32 / 100.0, level_col(app, p.unwrap_or(0.0)), c32(t.surface2)); ui.add_space(6.0); ui.label(RichText::new(tl.mem_label()).small().color(c32(t.muted))); });
                        card(&mut c[2], app, |ui| { caption(ui, app, "DISK /"); let p = tl.disk_pct(); ui.label(RichText::new(p.map(|x| format!("{x:.0}%")).unwrap_or_else(|| "--".into())).size(20.0)); ui.add_space(8.0); bar(ui, p.unwrap_or(0.0) as f32 / 100.0, level_col(app, p.unwrap_or(0.0)), c32(t.surface2)); ui.add_space(6.0); ui.label(RichText::new(tl.disk_label()).small().color(c32(t.muted))); });
                        card(&mut c[3], app, |ui| { caption(ui, app, "UPTIME"); ui.label(RichText::new(tl.uptime_label()).size(20.0)); ui.add_space(8.0); ui.label(RichText::new(if tl.os_name.is_empty() { "—".to_string() } else { tl.os_name.clone() }).small().color(c32(t.muted))); ui.label(RichText::new(if tl.agent_version.is_empty() { "agent: pre-3.3".to_string() } else { format!("agent {}", tl.agent_version) }).small().color(c32(t.muted))); });
                    });
                    if agent::is_outdated(&tl.agent_version) {
                        ui.add_space(8.0);
                        banner(ui, app, &format!("Agent update available ({} → {})", if tl.agent_version.is_empty() { "pre-3.3" } else { &tl.agent_version }, agent::bundled_version()), "The new agent adds container stats, top processes and reboot detection.", "Update agent", || acts.push(Act::Agent(s.id.clone(), false)));
                    }
                    if !tl.procs.is_empty() {
                        ui.add_space(10.0);
                        card(ui, app, |ui| {
                            ui.horizontal(|ui| { caption(ui, app, "TOP PROCESSES"); ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| { if ui.small_button("See all").clicked() { acts.push(Act::Procs(s.id.clone())); } }); });
                            egui::Grid::new("top").num_columns(4).spacing(Vec2::new(18.0, 3.0)).show(ui, |ui| {
                                for p in tl.top(false, 5) { ui.label(RichText::new(format!("{:.1}%", p.cpu)).strong()); ui.label(RichText::new(crate::core::telemetry::human_bytes(p.rss as f64)).color(c32(t.muted))); ui.label(&p.name); ui.label(RichText::new(format!("pid {}", p.pid)).color(c32(t.muted))); ui.end_row(); }
                            });
                        });
                    }
                }
                None => {
                    let online = st.as_ref().map_or(false, |x| x.online);
                    if online && link.is_none() { banner(ui, app, "Live metrics are off for this server", "Deploy the tiny telemetry agent (Python, no dependencies) to see CPU, memory, disk and uptime here and in the tray.", "Deploy agent", || acts.push(Act::Agent(s.id.clone(), false))); }
                }
            }
            // ------------------------------------------------------------ container card
            if let Some(l) = &link {
                ui.add_space(10.0);
                let c = l.container.clone(); let hid = l.host.id.clone();
                let mc_port = c.ports.iter().find(|p| p.container_port == 25565).map(|p| p.host_port);
                let mc = mc_port.and_then(|p| app.hub.minecraft(&l.host.host, p));
                card(ui, app, |ui| {
                    ui.horizontal(|ui| {
                        caption(ui, app, "CONTAINER");
                        let (txt, col) = if c.running() { if c.health() == "unhealthy" { ("unhealthy", c32(t.danger)) } else { ("running", c32(t.success)) } } else { (c.state.as_str(), c32(t.danger)) };
                        pill(ui, txt, col);
                        ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                            ui.menu_button("More ▾", |ui| { if item(ui, "Follow logs", "") { acts.push(Act::CtrLogs(hid.clone(), c.clone())); } if item(ui, "Shell inside container", "") { acts.push(Act::CtrShell(hid.clone(), c.clone())); } if item(ui, "Live stats", "") { acts.push(Act::CtrStats(hid.clone(), Some(c.clone()))); } ui.separator(); if item(ui, &format!("Go to host: {}", l.host.name), "") { acts.push(Act::Select(hid.clone())); } });
                            if c.running() { if ui.button("Stop").clicked() { acts.push(Act::AskStopCtr(hid.clone(), c.clone())); } if ui.button("Restart").clicked() { acts.push(Act::Ctr(hid.clone(), c.clone(), "restart")); } }
                            else if ui.button("Start").clicked() { acts.push(Act::Ctr(hid.clone(), c.clone(), "start")); }
                        });
                    });
                    egui::Grid::new("ctr").num_columns(2).spacing(Vec2::new(18.0, 4.0)).show(ui, |ui| {
                        let row = |ui: &mut egui::Ui, k: &str, v: String| { ui.label(RichText::new(k).color(c32(t.muted))); ui.add(egui::Label::new(v).selectable(true)); ui.end_row(); };
                        row(ui, "Name", format!("{} on {}", c.name, l.host.name)); row(ui, "Image", c.image_short()); row(ui, "Status", c.status.clone());
                        row(ui, "CPU · memory", format!("{} · {}", c.cpu.map(|x| format!("{x:.1}%")).unwrap_or_else(|| "--".into()), c.mem_label()));
                        row(ui, "Ports", c.ports_label()); if !c.project.is_empty() { row(ui, "Compose project", c.project.clone()); }
                        match &mc { Some(Ok(m)) => { row(ui, "Minecraft", m.summary()); if !m.motd.is_empty() { row(ui, "MOTD", m.motd.clone()); } if !m.players.is_empty() { row(ui, "Players", m.players.join(", ")); } } Some(Err(e)) => row(ui, "Minecraft", format!("not answering ({e})")), None if mc_port.is_some() => row(ui, "Minecraft", "checking…".into()), None => {} }
                    });
                    let web: Vec<_> = c.ports.iter().filter(|p| p.is_web()).collect();
                    if !web.is_empty() { ui.horizontal_wrapped(|ui| { for p in web { let url = format!("{}://{}:{}", if p.container_port == 443 || p.container_port == 8443 || p.container_port == 9443 { "https" } else { "http" }, l.host.host, p.host_port); let lbl = if p.service().is_empty() { url.clone() } else { format!("{} ↗", p.service()) }; if ui.link(lbl).on_hover_text(&url).clicked() { acts.push(Act::OpenUrl(url)); } } }); }
                });
            }
            ui.add_space(12.0);
            // ------------------------------------------------------------ tabs
            let hc = app.hub.host_containers().get(&s.id).cloned();
            let tuns: Vec<_> = app.tunnels.iter().filter(|x| x.server_id == s.id).cloned().collect();
            ui.horizontal(|ui| {
                ui.selectable_value(&mut app.detail_tab, Tab::Details, "Details");
                ui.selectable_value(&mut app.detail_tab, Tab::Commands, format!("Commands ({})", s.commands.len()));
                ui.selectable_value(&mut app.detail_tab, Tab::Tunnels, if tuns.is_empty() { "Tunnels".to_string() } else { format!("Tunnels ({})", tuns.len()) });
                ui.selectable_value(&mut app.detail_tab, Tab::Containers, match &hc { Some(h) if !h.containers.is_empty() => format!("Containers ({})", h.containers.len()), _ => "Containers".into() });
            });
            ui.separator();
            match app.detail_tab {
                Tab::Details => details(app, ui, &s, st.as_ref()),
                Tab::Commands => {
                    ui.horizontal(|ui| { if ui.button("Add command…").clicked() { acts.push(Act::AddCmd(s.id.clone())); } ui.label(RichText::new("One-click commands, run in a terminal on this server.").color(c32(t.muted))); });
                    ui.add_space(4.0);
                    if s.commands.is_empty() { ui.label(RichText::new("No saved commands yet (e.g. sudo dnf upgrade, docker ps, df -h).").color(c32(t.muted))); }
                    egui::Grid::new("cmds").striped(true).num_columns(3).spacing(Vec2::new(14.0, 6.0)).show(ui, |ui| {
                        for (i, c) in s.commands.iter().enumerate() {
                            ui.label(RichText::new(&c.label).strong()); ui.label(RichText::new(&c.command).monospace().color(c32(t.muted)));
                            ui.horizontal(|ui| { if ui.button("Run").clicked() { acts.push(Act::RunCmd(s.id.clone(), i)); } ui.menu_button("⋯", |ui| { if item(ui, "Edit…", "") { acts.push(Act::EditCmd(s.id.clone(), i)); } if item(ui, "Delete", "") { acts.push(Act::DelCmd(s.id.clone(), i)); } }); });
                            ui.end_row();
                        }
                    });
                }
                Tab::Tunnels => {
                    ui.horizontal(|ui| { if ui.button("New tunnel…").clicked() { acts.push(Act::NewTunnel(s.id.clone())); } ui.label(RichText::new("Background port forwards (-L local, -R remote, -D SOCKS).").color(c32(t.muted))); });
                    ui.add_space(4.0);
                    if tuns.is_empty() { ui.label(RichText::new("No tunnels running for this server.").color(c32(t.muted))); }
                    for tn in &tuns { ui.horizontal(|ui| { ui.label(RichText::new(format!("-{}", tn.kind)).monospace().strong()); ui.label(tn.description()); ui.label(RichText::new(format!("pid {}", tn.pid)).color(c32(t.muted))); if ui.small_button("Stop").clicked() { acts.push(Act::StopTunnel(tn.id.clone())); } }); }
                }
                Tab::Containers => containers_tab(app, ui, &s, hc, acts),
            }
        });
    });
}
fn banner(ui: &mut egui::Ui, app: &App, title: &str, text: &str, btn: &str, on: impl FnOnce()) {
    let t = app.theme();
    egui::Frame::none().fill(c32(t.accent).linear_multiply(0.10)).stroke(Stroke::new(1.0_f32, c32(t.accent).linear_multiply(0.4))).rounding(6.0).inner_margin(egui::Margin::symmetric(14.0, 10.0)).show(ui, |ui| {
        ui.set_width(ui.available_width());
        ui.horizontal(|ui| {
            ui.vertical(|ui| { ui.label(RichText::new(title).strong()); ui.label(RichText::new(text).color(c32(t.muted))); });
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| { if ui.button(btn).clicked() { on(); } });
        });
    });
}
fn details(app: &mut App, ui: &mut egui::Ui, s: &Server, st: Option<&crate::core::status::HostStatus>) {
    let t = app.theme();
    let (bm, mounted) = app.fs(s);
    let (u24, u7, lat) = app.availability(&s.id);
    let tel = st.and_then(|x| x.telemetry.as_ref());
    let key = if s.key.is_empty() { "ssh-agent / defaults".to_string() } else if s.key_path().is_empty() { format!("{} (missing!)", s.key) } else { s.key.clone() };
    let mut files = vec![]; if bm { files.push("bookmarked"); } if mounted { files.push("SSHFS mounted"); }
    let rows: Vec<(&str, String)> = vec![
        ("Status", st.map(|x| x.summary()).unwrap_or_else(|| "Checking…".into())), ("SSH server", st.map(|x| x.banner.clone()).filter(|b| !b.is_empty()).unwrap_or_else(|| "—".into())),
        ("User", if s.user.is_empty() { "(ssh default)".into() } else { s.user.clone() }), ("Port", s.port.to_string()), ("Identity", key), ("Jump host", if s.jump.is_empty() { "—".into() } else { s.jump.clone() }),
        ("MAC address", if s.mac.is_empty() { "not set".into() } else { s.mac.clone() }), ("Remote folder", s.home_path()), ("Files", if files.is_empty() { "—".into() } else { files.join(" · ") }),
        ("Last connected", if s.last_connected > 0.0 { strftime(s.last_connected, "%b %d, %H:%M") } else { "never".into() }),
        ("System", tel.filter(|x| !x.os_name.is_empty()).map(|x| format!("{} · {}", x.os_name, x.kernel)).unwrap_or_else(|| "—".into())),
        ("Uptime 24h · 7d", if u24.is_some() || u7.is_some() { format!("{} · {}", pct_label(u24), pct_label(u7)) } else if app.hub.recording() || app.tray_running { "collecting…".into() } else { "—".into() }),
    ];
    ui.add_space(4.0);
    egui::Grid::new("details").num_columns(4).spacing(Vec2::new(18.0, 8.0)).show(ui, |ui| {
        for pair in rows.chunks(2) {
            for (k, v) in pair { ui.label(RichText::new(*k).color(c32(t.muted))); ui.add(egui::Label::new(v.as_str()).selectable(true)); }
            ui.end_row();
        }
    });
    if lat.iter().any(|v| *v > 0.0) { ui.add_space(6.0); ui.label(RichText::new("Latency, last 24 h").small().color(c32(t.muted))); spark(ui, &lat, c32(t.info), 34.0, None); }
    if !s.notes.is_empty() { ui.add_space(8.0); ui.label(RichText::new(&s.notes).color(c32(t.muted))); }
}
fn containers_tab(app: &mut App, ui: &mut egui::Ui, s: &Server, hc: Option<crate::core::containers::HostContainers>, acts: &mut Vec<Act>) {
    let t = app.theme();
    ui.horizontal(|ui| {
        if ui.button("Find containers").on_hover_text("Ask this server for its docker / podman containers over SSH").clicked() { acts.push(Act::FindContainers(s.id.clone())); }
        if hc.as_ref().map_or(false, |h| !h.containers.is_empty()) && ui.button("Live stats").clicked() { acts.push(Act::CtrStats(s.id.clone(), None)); }
        if let Some(h) = &hc { ui.label(RichText::new(format!("via {} · {}", if h.source == "agent" { "agent" } else { "ssh" }, h.runtime)).color(c32(t.muted))); }
    });
    let Some(h) = hc else { if let Some(e) = app.hub.ssh_containers_error(&s.id) { ui.label(RichText::new(e).color(c32(t.muted))); } else { ui.label(RichText::new("No containers found yet.").color(c32(t.muted))); } return };
    if h.containers.is_empty() { ui.label(RichText::new(if h.error.is_empty() { "No containers on this host.".to_string() } else { h.error.clone() }).color(c32(t.muted))); return; }
    let saved: std::collections::HashMap<u16, String> = app.hub.links().into_iter().filter(|(_, l)| l.host.id == s.id).filter_map(|(sid, l)| l.container.ports.first().map(|_| (app.hub.store.get(&sid).map(|x| x.port).unwrap_or(0), sid))).collect();
    egui::Grid::new("ctrs").striped(true).num_columns(6).spacing(Vec2::new(14.0, 6.0)).show(ui, |ui| {
        for k in ["", "Name", "Image", "CPU", "Memory", "Ports"] { ui.label(RichText::new(k).small().strong().color(c32(t.muted))); } ui.end_row();
        for c in &h.containers {
            let col = if !c.running() { c32(t.danger) } else if c.health() == "unhealthy" { c32(t.warning) } else { c32(t.success) };
            let (r, _) = ui.allocate_exact_size(Vec2::splat(12.0), Sense::hover()); ui.painter().circle_filled(r.center(), 4.0, col);
            let jump = c.ports.iter().find_map(|p| saved.get(&p.host_port)).cloned();
            let nm = ui.add(egui::Label::new(RichText::new(&c.name).strong()).sense(Sense::click()));
            let nm = if jump.is_some() { nm.on_hover_text("Saved in sshm — double-click to open") } else { nm.on_hover_text(&c.status) };
            if nm.double_clicked() { if let Some(j) = &jump { acts.push(Act::Select(j.clone())); } }
            let (hid, cc) = (s.id.clone(), c.clone());
            nm.context_menu(|ui| {
                if cc.running() { if item(ui, "Restart", "") { acts.push(Act::Ctr(hid.clone(), cc.clone(), "restart")); } if item(ui, "Stop…", "") { acts.push(Act::AskStopCtr(hid.clone(), cc.clone())); } } else if item(ui, "Start", "") { acts.push(Act::Ctr(hid.clone(), cc.clone(), "start")); }
                if item(ui, "Follow logs", "") { acts.push(Act::CtrLogs(hid.clone(), cc.clone())); } if item(ui, "Shell inside container", "") { acts.push(Act::CtrShell(hid.clone(), cc.clone())); }
            });
            ui.label(RichText::new(c.image_short()).color(c32(t.muted))); ui.label(c.cpu.map(|x| format!("{x:.1}%")).unwrap_or_else(|| "--".into())); ui.label(c.mem_label()); ui.label(RichText::new(c.ports_label()).small());
            ui.end_row();
        }
    });
    ui.label(RichText::new("Right-click a container for restart, stop, logs and shell.").small().color(c32(t.muted)));
}
