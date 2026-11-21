//! The server list: search, tag filter, and one compact row per server.
use super::{c32, Act, App};
use eframe::egui::{self, Align2, FontId, RichText, Sense, Vec2};

pub fn show(app: &mut App, ctx: &egui::Context, acts: &mut Vec<Act>) {
    let t = app.theme();
    egui::SidePanel::left("servers").resizable(true).default_width(300.0).width_range(240.0..=460.0)
        .frame(egui::Frame::side_top_panel(&ctx.style()).fill(c32(t.bg)).inner_margin(egui::Margin::symmetric(10.0, 8.0)))
        .show(ctx, |ui| {
            let te = ui.add(egui::TextEdit::singleline(&mut app.search).hint_text("Search  (Ctrl+K)").desired_width(f32::INFINITY));
            if std::mem::take(&mut app.focus_search) { te.request_focus(); }
            ui.horizontal(|ui| {
                let tags = app.hub.store.tags();
                let label = if app.tag_filter.is_empty() { "All tags".to_string() } else { app.tag_filter.clone() };
                egui::ComboBox::from_id_salt("tag").selected_text(label).width(130.0).show_ui(ui, |ui| {
                    ui.selectable_value(&mut app.tag_filter, String::new(), "All tags");
                    for tg in tags { let l = tg.clone(); ui.selectable_value(&mut app.tag_filter, tg, l); }
                });
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    if ui.button("Scan").on_hover_text("Find SSH servers on your network").clicked() { acts.push(Act::Scan); }
                    if ui.button("Add").on_hover_text("Add a server (Ctrl+N)").clicked() { acts.push(Act::Add); }
                });
            });
            ui.add_space(2.0);
            let list = app.visible();
            let links = app.hub.links();
            egui::ScrollArea::vertical().auto_shrink([false; 2]).show(ui, |ui| {
                if list.is_empty() {
                    ui.add_space(16.0);
                    ui.label(RichText::new(if app.hub.servers().is_empty() { "No servers yet. Use Add or Scan." } else { "Nothing matches." }).color(c32(t.muted)));
                }
                for s in &list {
                    let st = app.hub.status(&s.id);
                    let (rect, resp) = ui.allocate_exact_size(Vec2::new(ui.available_width(), 44.0), Sense::click());
                    let selected = app.sel.as_deref() == Some(&s.id);
                    let p = ui.painter();
                    if selected { p.rect_filled(rect, 5.0, c32(t.surface2)); p.rect_filled(egui::Rect::from_min_size(rect.min, Vec2::new(3.0, rect.height())), 1.5, c32(t.accent)); }
                    else if resp.hovered() { p.rect_filled(rect, 5.0, c32(t.surface)); }
                    let (dot, hollow) = match st.map(|x| x.state()) { Some("online") => (c32(t.success), false), Some("degraded") => (c32(t.warning), false), Some(_) => (c32(t.danger), true), None => (c32(t.muted), true) };
                    let c = rect.left_center() + Vec2::new(16.0, 0.0);
                    if hollow { p.circle_stroke(c, 4.0, egui::Stroke::new(1.5_f32, dot)); } else { p.circle_filled(c, 4.5, dot); }
                    let clip = ui.painter_at(rect.shrink2(Vec2::new(6.0, 0.0)));
                    let name = if s.favorite { format!("★ {}", s.name) } else { s.name.clone() };
                    clip.text(rect.left_top() + Vec2::new(30.0, 6.0), Align2::LEFT_TOP, name, FontId::proportional(14.0), c32(t.text));
                    let sub = match links.get(&s.id) { Some(l) => format!("⬢ {} on {}", l.container.name, l.host.name), None => if s.tag.is_empty() { s.target() } else { format!("{} · {}", s.tag, s.target()) } };
                    clip.text(rect.left_top() + Vec2::new(30.0, 25.0), Align2::LEFT_TOP, sub, FontId::proportional(11.5), c32(t.muted));
                    // right side: latency and a small CPU bar
                    let right = rect.right_top() + Vec2::new(-10.0, 7.0);
                    let lat = st.map(|x| x.latency_label()).unwrap_or_else(|| "…".into());
                    clip.text(right, Align2::RIGHT_TOP, lat, FontId::proportional(11.5), c32(t.muted));
                    if let Some(cpu) = st.and_then(|x| x.telemetry.as_ref()).and_then(|t| t.cpu) {
                        let bar = egui::Rect::from_min_size(rect.right_top() + Vec2::new(-56.0, 28.0), Vec2::new(46.0, 4.0));
                        clip.rect_filled(bar, 2.0, c32(t.surface2));
                        let col = if cpu >= 90.0 { c32(t.danger) } else if cpu >= 70.0 { c32(t.warning) } else { c32(t.accent) };
                        clip.rect_filled(egui::Rect::from_min_size(bar.min, Vec2::new(46.0 * (cpu as f32 / 100.0).clamp(0.02, 1.0), 4.0)), 2.0, col);
                    }
                    let resp = resp.on_hover_text(format!("{}\n{}{}", s.name, s.endpoint(), if s.notes.is_empty() { String::new() } else { format!("\n{}", s.notes) }));
                    if resp.clicked() { acts.push(Act::Select(s.id.clone())); }
                    if resp.double_clicked() { acts.push(Act::Connect(s.id.clone(), None)); }
                    let sid = s.id.clone();
                    resp.context_menu(|ui| {
                        if ui.button("Connect").clicked() { acts.push(Act::Connect(sid.clone(), Some(false))); ui.close_menu(); }
                        if ui.button("Connect in tmux").clicked() { acts.push(Act::Connect(sid.clone(), Some(true))); ui.close_menu(); }
                        if ui.button("Open files").clicked() { acts.push(Act::OpenFiles(sid.clone())); ui.close_menu(); }
                        if ui.button("Processes…").clicked() { acts.push(Act::Procs(sid.clone())); ui.close_menu(); }
                        ui.separator();
                        if ui.button("Edit…").clicked() { acts.push(Act::Edit(sid.clone())); ui.close_menu(); }
                        if ui.button("Duplicate").clicked() { acts.push(Act::Duplicate(sid.clone())); ui.close_menu(); }
                        if ui.button("Delete…").clicked() { acts.push(Act::AskDelete(sid.clone())); ui.close_menu(); }
                    });
                }
            });
        });
}
