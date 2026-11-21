//! The sshm icon, drawn in code so it can match the desktop it runs on.
//!
//! The glyph is a two-unit server stack on a 22-unit grid with 1-unit strokes on half-pixel lines, the same
//! construction as Breeze's 22 px tray icons, so it stays crisp at 22 / 44 px. The status dot (green = all up,
//! amber = some, red = none) sits bottom-right with a gap cut around it, like KDE's own badges.
use tiny_skia::{BlendMode, Color, FillRule, LineCap, Paint, PathBuilder, Pixmap, Stroke, Transform};

#[derive(Clone, Copy, PartialEq, Debug)]
pub enum State { None, Ok, Partial, Down }
#[derive(Clone, Copy, PartialEq, Debug)]
pub enum Style {
    /// one-colour line icon in the panel's text colour (KDE, GNOME, COSMIC…)
    Symbolic(u8, u8, u8),
    /// small full-colour tile (panels that show colourful tray icons: XFCE, MATE, Cinnamon…)
    Tile,
}
pub const GREEN: (u8, u8, u8) = (46, 204, 113);
pub const AMBER: (u8, u8, u8) = (246, 176, 38);
pub const RED: (u8, u8, u8) = (232, 72, 72);

fn rrect(pb: &mut PathBuilder, x: f32, y: f32, w: f32, h: f32, r: f32) {
    let k = 0.5523 * r;   // cubic approximation of a quarter circle
    pb.move_to(x + r, y);
    pb.line_to(x + w - r, y); pb.cubic_to(x + w - r + k, y, x + w, y + r - k, x + w, y + r);
    pb.line_to(x + w, y + h - r); pb.cubic_to(x + w, y + h - r + k, x + w - r + k, y + h, x + w - r, y + h);
    pb.line_to(x + r, y + h); pb.cubic_to(x + r - k, y + h, x, y + h - r + k, x, y + h - r);
    pb.line_to(x, y + r); pb.cubic_to(x, y + r - k, x + r - k, y, x + r, y);
    pb.close();
}
fn paint(c: (u8, u8, u8), a: u8) -> Paint<'static> { let mut p = Paint::default(); p.set_color_rgba8(c.0, c.1, c.2, a); p.anti_alias = true; p }

/// the server stack, in 22-unit coordinates, transformed by `t`
fn glyph(pm: &mut Pixmap, t: Transform, c: (u8, u8, u8), stroke: f32) {
    let p = paint(c, 255);
    let st = Stroke { width: stroke, line_cap: LineCap::Round, ..Default::default() };
    for y in [3.5f32, 12.5] {
        let mut pb = PathBuilder::new(); rrect(&mut pb, 2.5, y, 17.0, 6.0, 1.5);
        if let Some(path) = pb.finish() { pm.stroke_path(&path, &p, &st, t, None); }
        // status light and drive slot
        if let Some(dot) = PathBuilder::from_circle(6.0, y + 3.0, 1.25) { pm.fill_path(&dot, &p, FillRule::Winding, t, None); }
        let mut pb = PathBuilder::new(); pb.move_to(9.5, y + 3.0); pb.line_to(16.0, y + 3.0);
        if let Some(path) = pb.finish() { pm.stroke_path(&path, &p, &st, t, None); }
    }
}
fn badge(pm: &mut Pixmap, t: Transform, state: State, cx: f32, cy: f32, r: f32, gap: f32) {
    let col = match state { State::Ok => GREEN, State::Partial => AMBER, State::Down => RED, State::None => return };
    let mut clear = Paint::default(); clear.blend_mode = BlendMode::Clear; clear.anti_alias = true;
    if let Some(c) = PathBuilder::from_circle(cx, cy, r + gap) { pm.fill_path(&c, &clear, FillRule::Winding, t, None); }
    if let Some(c) = PathBuilder::from_circle(cx, cy, r) { pm.fill_path(&c, &paint(col, 255), FillRule::Winding, t, None); }
}
fn tile(pm: &mut Pixmap, t: Transform, x: f32, y: f32, w: f32, r: f32) {
    // flat slate tile with a slightly lighter top half (Breeze app icons are flat with soft shading)
    let mut pb = PathBuilder::new(); rrect(&mut pb, x, y, w, w, r);
    let path = pb.finish().unwrap();
    let mut p = Paint::default(); p.anti_alias = true;
    p.shader = tiny_skia::LinearGradient::new(tiny_skia::Point::from_xy(x, y), tiny_skia::Point::from_xy(x, y + w),
        vec![tiny_skia::GradientStop::new(0.0, Color::from_rgba8(66, 84, 112, 255)), tiny_skia::GradientStop::new(1.0, Color::from_rgba8(34, 44, 60, 255))],
        tiny_skia::SpreadMode::Pad, Transform::identity()).unwrap();
    pm.fill_path(&path, &p, FillRule::Winding, t, None);
}

/// tray / panel icon at `size` px
pub fn render(size: u32, style: Style, state: State) -> Pixmap {
    let mut pm = Pixmap::new(size, size).unwrap();
    let s = size as f32 / 22.0;
    match style {
        Style::Symbolic(r, g, b) => {
            glyph(&mut pm, Transform::from_scale(s, s), (r, g, b), 1.0);
            badge(&mut pm, Transform::from_scale(s, s), state, 17.0, 17.0, 4.0, 1.5);
        }
        Style::Tile => {
            tile(&mut pm, Transform::from_scale(s, s), 1.0, 1.0, 20.0, 4.5);
            // the glyph shrunk into the tile
            let k = s * 0.68; let off = s * 11.0 - k * 11.0;
            glyph(&mut pm, Transform::from_row(k, 0.0, 0.0, k, off, off - s * 0.5), (240, 244, 250), 1.25);
            badge(&mut pm, Transform::from_scale(s, s), state, 17.0, 17.0, 4.0, 1.25);
        }
    }
    pm
}
/// the application icon (window, launcher): the tile at full size with a green dot
pub fn app_icon(size: u32) -> Pixmap {
    let mut pm = Pixmap::new(size, size).unwrap();
    let s = size as f32 / 128.0;
    tile(&mut pm, Transform::from_scale(s, s), 8.0, 8.0, 112.0, 26.0);
    let k = s * 128.0 / 22.0 * 0.62; let off = (size as f32 - k * 22.0) / 2.0;
    glyph(&mut pm, Transform::from_row(k, 0.0, 0.0, k, off, off - 3.0 * s), (240, 244, 250), 1.3);
    badge(&mut pm, Transform::from_scale(s, s), State::Ok, 98.0, 98.0, 15.0, 6.0);
    pm
}
/// small coloured dot for menus (PNG bytes)
pub fn dot_png(c: (u8, u8, u8), hollow: bool) -> Vec<u8> {
    let mut pm = Pixmap::new(16, 16).unwrap();
    if let Some(circle) = PathBuilder::from_circle(8.0, 8.0, if hollow { 4.5 } else { 5.0 }) {
        if hollow { pm.stroke_path(&circle, &paint(c, 255), &Stroke { width: 1.6, ..Default::default() }, Transform::identity(), None); }
        else { pm.fill_path(&circle, &paint(c, 255), FillRule::Winding, Transform::identity(), None); }
    }
    pm.encode_png().unwrap_or_default()
}
/// premultiplied RGBA -> ARGB32 big-endian (StatusNotifierItem pixmaps)
pub fn to_argb(pm: &Pixmap) -> Vec<u8> {
    let mut out = Vec::with_capacity(pm.data().len());
    for p in pm.pixels() { let c = p.demultiply(); out.extend_from_slice(&[c.alpha(), c.red(), c.green(), c.blue()]); }
    out
}
pub fn to_rgba(pm: &Pixmap) -> Vec<u8> {
    let mut out = Vec::with_capacity(pm.data().len());
    for p in pm.pixels() { let c = p.demultiply(); out.extend_from_slice(&[c.red(), c.green(), c.blue(), c.alpha()]); }
    out
}

/// Which style fits the panel we are on. `setting` is "auto", "light", "dark" or "color".
pub fn detect_style(setting: &str) -> Style {
    match setting { "light" => return Style::Symbolic(252, 252, 252), "dark" => return Style::Symbolic(35, 38, 41), "color" => return Style::Tile, _ => {} }
    let de = std::env::var("XDG_CURRENT_DESKTOP").unwrap_or_default().to_uppercase();
    if de.contains("KDE") { return kde_style(); }
    // these draw tray icons on a dark bar in one colour
    if ["GNOME", "UBUNTU", "UNITY", "PANTHEON", "BUDGIE", "COSMIC", "SWAY", "HYPRLAND", "NIRI"].iter().any(|d| de.contains(d)) { return Style::Symbolic(255, 255, 255); }
    Style::Tile
}
/// Plasma: a "-dark" / "-light" Plasma style decides; otherwise the colour scheme's window text colour (what Breeze icons use)
fn kde_style() -> Style {
    let home = crate::core::paths::home();
    let plasma = std::fs::read_to_string(home.join(".config/plasmarc")).unwrap_or_default();
    if let Some(name) = ini_get(&plasma, "Theme", "name") { let n = name.to_lowercase(); if n.contains("dark") { return Style::Symbolic(252, 252, 252); } if n.contains("light") { return Style::Symbolic(35, 38, 41); } }
    let globals = std::fs::read_to_string(home.join(".config/kdeglobals")).unwrap_or_default();
    for section in ["Colors:Header", "Colors:Window"] {
        if let Some(v) = ini_get(&globals, section, "ForegroundNormal") { let c: Vec<u8> = v.split(',').filter_map(|x| x.trim().parse().ok()).collect(); if c.len() >= 3 { return Style::Symbolic(c[0], c[1], c[2]); } }
    }
    if let Some(lnf) = ini_get(&globals, "KDE", "LookAndFeelPackage") { if lnf.contains("dark") { return Style::Symbolic(252, 252, 252); } }
    Style::Symbolic(35, 38, 41)   // Breeze light default
}
fn ini_get(text: &str, section: &str, key: &str) -> Option<String> {
    let mut inside = false;
    for l in text.lines() { let l = l.trim(); if l.starts_with('[') { inside = l == format!("[{section}]"); continue; } if inside { if let Some(v) = l.strip_prefix(&format!("{key}=")) { return Some(v.trim().to_string()); } } }
    None
}
/// files whose change means the panel colours may have changed
pub fn theme_files_stamp() -> Vec<Option<std::time::SystemTime>> {
    let h = crate::core::paths::home();
    [".config/kdeglobals", ".config/plasmarc"].iter().map(|f| std::fs::metadata(h.join(f)).and_then(|m| m.modified()).ok()).collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn renders() {
        let dir = std::env::temp_dir().join("sshm-icon-test"); let dir = dir.as_path();
        let _ = std::fs::create_dir_all(dir);
        for (n, st) in [("ok", State::Ok), ("partial", State::Partial), ("down", State::Down), ("none", State::None)] {
            for sz in [22u32, 44, 96] {
                render(sz, Style::Symbolic(252, 252, 252), st).save_png(dir.join(format!("sym-{n}-{sz}.png"))).unwrap();
                render(sz, Style::Symbolic(35, 38, 41), st).save_png(dir.join(format!("dark-{n}-{sz}.png"))).unwrap();
                render(sz, Style::Tile, st).save_png(dir.join(format!("tile-{n}-{sz}.png"))).unwrap();
            }
        }
        app_icon(256).save_png(dir.join("app-256.png")).unwrap();
        assert_eq!(to_argb(&render(22, Style::Tile, State::Ok)).len(), 22 * 22 * 4);
    }
}
