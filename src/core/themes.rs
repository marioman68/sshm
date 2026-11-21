//! The same ten themes as the Python GUI and TUI.
#[derive(Clone, Copy, Debug)]
pub struct Theme { pub name: &'static str, pub accent: u32, pub bg: u32, pub surface: u32, pub surface2: u32, pub border: u32, pub text: u32, pub muted: u32, pub success: u32, pub warning: u32, pub danger: u32, pub info: u32, pub dark: bool }
const fn t(name: &'static str, accent: u32, bg: u32, surface: u32, surface2: u32, border: u32, text: u32, muted: u32) -> Theme {
    Theme { name, accent, bg, surface, surface2, border, text, muted, success: 0x4ade80, warning: 0xfbbf24, danger: 0xf87171, info: 0x60a5fa, dark: true }
}
pub const THEMES: [Theme; 10] = [
    t("Royal Purple", 0xb48ead, 0x14141f, 0x1c1c2b, 0x262638, 0x34344a, 0xe2e4f3, 0x8b8fa8),
    Theme { success: 0x34d399, info: 0xa78bfa, ..t("Cyber Neon", 0x22d3ee, 0x0b0f17, 0x111824, 0x182233, 0x22314a, 0xe6f1ff, 0x7d8ba3) },
    Theme { success: 0x86efac, ..t("Matrix Green", 0x4ade80, 0x0a110b, 0x101a11, 0x162418, 0x22382a, 0xd9f5df, 0x7a9a80) },
    t("Solar Amber", 0xf5a524, 0x15120d, 0x1d1912, 0x28221a, 0x3a3123, 0xf3ead9, 0xa3957d),
    t("Crimson Red", 0xf43f5e, 0x140d0f, 0x1d1316, 0x281a1e, 0x3d262c, 0xf5e1e4, 0xa3848a),
    t("Oceanic Blue", 0x60a5fa, 0x0b1220, 0x111a2c, 0x18243a, 0x26364f, 0xe2ebf8, 0x8193ad),
    t("Rose Pink", 0xf472b6, 0x150f15, 0x1e151e, 0x2a1d2a, 0x3d2a3d, 0xf6e4f0, 0xa68aa0),
    t("Stealth Slate", 0x94a3b8, 0x0f1115, 0x16191f, 0x1e222a, 0x2b313c, 0xe5e7eb, 0x8a919e),
    Theme { success: 0xa3be8c, warning: 0xebcb8b, danger: 0xbf616a, info: 0x81a1c1, ..t("Nordic Frost", 0x88c0d0, 0x1d222b, 0x242a35, 0x2e3542, 0x3b4352, 0xeceff4, 0x97a1b3) },
    Theme { success: 0x16a34a, warning: 0xd97706, danger: 0xdc2626, info: 0x2563eb, dark: false, ..t("Daylight", 0x4f46e5, 0xf4f5f8, 0xffffff, 0xeef0f5, 0xd8dbe4, 0x1f2330, 0x6b7183) },
];
pub fn get(name: &str) -> &'static Theme { THEMES.iter().find(|t| t.name.eq_ignore_ascii_case(name)).unwrap_or(&THEMES[0]) }
pub fn rgb(c: u32) -> (u8, u8, u8) { ((c >> 16) as u8, (c >> 8) as u8, c as u8) }
