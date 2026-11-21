"""One theme definition shared by the GUI (hex colours) and the TUI (xterm-256)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    name: str
    accent: str
    bg: str
    surface: str
    surface2: str
    border: str
    text: str
    muted: str
    success: str = "#4ade80"
    warning: str = "#fbbf24"
    danger: str = "#f87171"
    info: str = "#60a5fa"
    dark: bool = True


THEMES: list[Theme] = [
    Theme("Royal Purple", "#b48ead", "#14141f", "#1c1c2b", "#262638", "#34344a", "#e2e4f3", "#8b8fa8"),
    Theme("Cyber Neon", "#22d3ee", "#0b0f17", "#111824", "#182233", "#22314a", "#e6f1ff", "#7d8ba3",
          success="#34d399", info="#a78bfa"),
    Theme("Matrix Green", "#4ade80", "#0a110b", "#101a11", "#162418", "#22382a", "#d9f5df", "#7a9a80",
          success="#86efac"),
    Theme("Solar Amber", "#f5a524", "#15120d", "#1d1912", "#28221a", "#3a3123", "#f3ead9", "#a3957d"),
    Theme("Crimson Red", "#f43f5e", "#140d0f", "#1d1316", "#281a1e", "#3d262c", "#f5e1e4", "#a3848a"),
    Theme("Oceanic Blue", "#60a5fa", "#0b1220", "#111a2c", "#18243a", "#26364f", "#e2ebf8", "#8193ad"),
    Theme("Rose Pink", "#f472b6", "#150f15", "#1e151e", "#2a1d2a", "#3d2a3d", "#f6e4f0", "#a68aa0"),
    Theme("Stealth Slate", "#94a3b8", "#0f1115", "#16191f", "#1e222a", "#2b313c", "#e5e7eb", "#8a919e"),
    Theme("Nordic Frost", "#88c0d0", "#1d222b", "#242a35", "#2e3542", "#3b4352", "#eceff4", "#97a1b3",
          success="#a3be8c", warning="#ebcb8b", danger="#bf616a", info="#81a1c1"),
    Theme("Daylight", "#4f46e5", "#f4f5f8", "#ffffff", "#eef0f5", "#d8dbe4", "#1f2330", "#6b7183",
          success="#16a34a", warning="#d97706", danger="#dc2626", info="#2563eb", dark=False),
]

DEFAULT_THEME = THEMES[0].name


def get_theme(name: str) -> Theme:
    return next((t for t in THEMES if t.name.lower() == (name or "").lower()), THEMES[0])


def theme_names() -> list[str]:
    return [t.name for t in THEMES]


# --------------------------------------------------------------------- xterm-256
_CUBE = (0, 95, 135, 175, 215, 255)


def _hex_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def hex_to_xterm256(value: str) -> int:
    """Nearest xterm-256 palette index (6x6x6 cube or greyscale ramp)."""
    r, g, b = _hex_rgb(value)

    def nearest(c: int) -> int:
        return min(range(6), key=lambda i: abs(_CUBE[i] - c))

    ri, gi, bi = nearest(r), nearest(g), nearest(b)
    cube_rgb = (_CUBE[ri], _CUBE[gi], _CUBE[bi])
    cube_idx = 16 + 36 * ri + 6 * gi + bi

    grey_level = round(((r + g + b) / 3 - 8) / 10)
    grey_level = max(0, min(23, grey_level))
    grey_val = 8 + grey_level * 10
    grey_idx = 232 + grey_level

    def dist(rgb: tuple[int, int, int]) -> int:
        return (rgb[0] - r) ** 2 + (rgb[1] - g) ** 2 + (rgb[2] - b) ** 2

    return grey_idx if dist((grey_val,) * 3) < dist(cube_rgb) else cube_idx
