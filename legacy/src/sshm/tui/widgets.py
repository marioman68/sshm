"""Drawing primitives, colour palette, input events and modal dialogs for the TUI."""

from __future__ import annotations

import curses
import threading
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sshm.core.themes import Theme, hex_to_xterm256

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
SPARKS = "▁▂▃▄▅▆▇█"
WHEEL_UP = getattr(curses, "BUTTON4_PRESSED", 0x80000)
WHEEL_DOWN = getattr(curses, "BUTTON5_PRESSED", 0x200000)
CLICK = curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED | curses.BUTTON1_DOUBLE_CLICKED
ESC = 27


# =============================================================== text helpers
def text_width(s: str) -> int:
    w = 0
    for ch in s:
        if unicodedata.combining(ch):
            continue
        w += 2 if unicodedata.east_asian_width(ch) in "WF" else 1
    return w


def clip(s: str, width: int) -> str:
    if width <= 0:
        return ""
    if text_width(s) <= width:
        return s
    out, w = [], 0
    for ch in s:
        cw = 2 if unicodedata.east_asian_width(ch) in "WF" else 1
        if w + cw > width - 1:
            break
        out.append(ch)
        w += cw
    return "".join(out) + "…"


def fit(s: str, width: int, align: str = "<") -> str:
    s = clip(s, width)
    gap = " " * max(0, width - text_width(s))
    return s + gap if align == "<" else gap + s


def bar(pct: float | None, width: int) -> tuple[str, str]:
    """Returns (filled, empty) segments for a horizontal meter."""
    if pct is None or width <= 0:
        return "", "─" * max(0, width)
    filled = round(max(0.0, min(100.0, pct)) / 100 * width)
    return "█" * filled, "░" * (width - filled)


def sparkline(values: list[float], width: int) -> str:
    vals = values[-width:]
    if not vals:
        return ""
    return "".join(SPARKS[min(7, int(v / 100 * 7.999))] for v in vals)


# =================================================================== palette
class Palette:
    """Lazily allocates curses colour pairs for (foreground, background) roles."""

    def __init__(self) -> None:
        self.roles: dict[str, int] = {}
        self._pairs: dict[tuple[str, str | None], int] = {}

    def apply(self, theme: Theme) -> None:
        rich = curses.COLORS >= 256

        def c(hexv: str, basic: int) -> int:
            return hex_to_xterm256(hexv) if rich else basic

        self.roles = {
            "text": -1,
            "muted": 245 if rich else curses.COLOR_WHITE,
            "border": 240 if rich else curses.COLOR_BLUE,
            "accent": c(theme.accent, curses.COLOR_CYAN),
            "success": c(theme.success, curses.COLOR_GREEN),
            "warning": c(theme.warning, curses.COLOR_YELLOW),
            "danger": c(theme.danger, curses.COLOR_RED),
            "info": c(theme.info, curses.COLOR_BLUE),
            "sel": (236 if theme.dark else 254) if rich else curses.COLOR_BLUE,
            "hover": (238 if theme.dark else 253) if rich else curses.COLOR_BLUE,
            "panel": (234 if theme.dark else 255) if rich else curses.COLOR_BLACK,
            "shadow": 232 if rich else curses.COLOR_BLACK,
            "black": 16 if rich else curses.COLOR_BLACK,
            "white": 231 if rich else curses.COLOR_WHITE,
        }
        if curses.COLORS < 8:
            self.roles = dict.fromkeys(self.roles, -1)
        for (fg, bg), n in self._pairs.items():
            self._init(n, fg, bg)

    def _init(self, n: int, fg: str, bg: str | None) -> None:
        try:
            curses.init_pair(n, self.roles.get(fg, -1), self.roles.get(bg, -1) if bg else -1)
        except curses.error:
            pass

    def __call__(self, fg: str = "text", bg: str | None = None, bold: bool = False, dim: bool = False) -> int:
        key = (fg, bg)
        n = self._pairs.get(key)
        if n is None:
            n = len(self._pairs) + 1
            if n >= curses.COLOR_PAIRS:
                return curses.A_BOLD if bold else 0
            self._pairs[key] = n
            self._init(n, fg, bg)
        attr = curses.color_pair(n)
        if bold:
            attr |= curses.A_BOLD
        if dim:
            attr |= curses.A_DIM
        return attr


# ==================================================================== events
@dataclass
class Event:
    key: str | int | None = None       # str for characters, int for curses KEY_*
    mouse: tuple[int, int, int] | None = None  # (x, y, bstate)

    @property
    def is_click(self) -> bool:
        return bool(self.mouse and self.mouse[2] & CLICK)

    @property
    def is_motion(self) -> bool:
        return bool(self.mouse and self.mouse[2] & curses.REPORT_MOUSE_POSITION and not self.mouse[2] & CLICK)

    def is_key(self, *names: str | int) -> bool:
        return self.key in names


def read_event(scr: curses.window) -> Event | None:
    try:
        ch = scr.get_wch()
    except curses.error:
        return None
    if ch == curses.KEY_MOUSE:
        try:
            _id, x, y, _z, bstate = curses.getmouse()
        except curses.error:
            return None
        return Event(mouse=(x, y, bstate))
    if isinstance(ch, str):
        if ch in ("\n", "\r"):
            return Event(key=curses.KEY_ENTER)
        if ch == "\x1b":
            return Event(key=ESC)
        if ch in ("\x7f", "\x08"):
            return Event(key=curses.KEY_BACKSPACE)
        if ch == "\t":
            return Event(key="\t")
    return Event(key=ch)


# ==================================================================== canvas
class Canvas:
    """Thin, exception-safe wrapper around a curses window."""

    def __init__(self, scr: curses.window, palette: Palette) -> None:
        self.scr = scr
        self.p = palette

    @property
    def size(self) -> tuple[int, int]:
        return self.scr.getmaxyx()

    def put(self, y: int, x: int, text: str, attr: int = 0, width: int | None = None) -> int:
        h, w = self.size
        if y < 0 or y >= h or x >= w or x < 0:
            return x
        room = w - x - (1 if y == h - 1 else 0)
        if width is not None:
            room = min(room, width)
        text = clip(text, room)
        try:
            self.scr.addstr(y, x, text, attr)
        except curses.error:
            pass
        return x + text_width(text)

    def fill(self, y: int, x: int, width: int, attr: int = 0, ch: str = " ") -> None:
        self.put(y, x, ch * max(0, width), attr)

    def box(self, y: int, x: int, h: int, w: int, attr: int, title: str = "", title_attr: int = 0,
            right: str = "", right_attr: int = 0, fill_attr: int | None = None) -> None:
        if h < 2 or w < 4:
            return
        self.put(y, x, "╭" + "─" * (w - 2) + "╮", attr)
        for r in range(y + 1, y + h - 1):
            self.put(r, x, "│", attr)
            if fill_attr is not None:
                self.fill(r, x + 1, w - 2, fill_attr)
            self.put(r, x + w - 1, "│", attr)
        self.put(y + h - 1, x, "╰" + "─" * (w - 2) + "╯", attr)
        if title:
            self.put(y, x + 2, f" {clip(title, w - 8)} ", title_attr)
        if right and w > text_width(title) + text_width(right) + 10:
            self.put(y, x + w - text_width(right) - 4, f" {right} ", right_attr)

    def section(self, y: int, x: int, w: int, label: str, attr: int, line_attr: int) -> None:
        end = self.put(y, x, label, attr)
        self.put(y, end + 1, "─" * max(0, w - (end - x) - 1), line_attr)


# ==================================================================== modals
@dataclass
class Field:
    key: str
    label: str
    value: Any = ""
    hint: str = ""
    kind: str = "text"          # text | bool | choice | secret
    choices: list[str] = field(default_factory=list)
    cursor: int = -1

    def display(self) -> str:
        if self.kind == "bool":
            return "[✓]" if self.value else "[ ]"
        if self.kind == "choice":
            return f"‹ {self.value} ›"
        return str(self.value)


class Modal:
    """Base class. Subclasses implement draw() and handle(); run() returns a result."""

    min_w = 40

    def __init__(self, ui: Any, title: str, subtitle: str = "") -> None:
        self.ui = ui
        self.c: Canvas = ui.canvas
        self.p: Palette = ui.palette
        self.title = title
        self.subtitle = subtitle
        self.done = False
        self.result: Any = None
        self.zones: list[tuple[int, int, int, Any]] = []
        self.hover: Any = None

    # geometry ------------------------------------------------------------
    def frame(self, inner_h: int, want_w: int) -> tuple[int, int, int, int]:
        sh, sw = self.c.size
        w = max(min(want_w, sw - 4), min(self.min_w, sw - 2))
        h = min(inner_h + 4 + (1 if self.subtitle else 0), sh - 2)
        y = max(1, (sh - h) // 2)
        x = max(1, (sw - w) // 2)
        for r in range(y + 1, y + h + 1):
            if x + w < sw:
                self.c.put(r, x + w, "  ", self.p("shadow", "shadow"))
        self.c.fill(y + h, x + 2, w - 1, self.p("shadow", "shadow"))
        self.c.box(y, x, h, w, self.p("accent", "panel"), self.title, self.p("accent", "panel", bold=True),
                   fill_attr=self.p("text", "panel"))
        top = y + 1
        if self.subtitle:
            self.c.put(top, x + 3, clip(self.subtitle, w - 6), self.p("muted", "panel"))
            top += 1
        return top + 1, x + 2, h - (top - y) - 2, w - 4

    def zone(self, y: int, x1: int, x2: int, tag: Any) -> None:
        self.zones.append((y, x1, x2, tag))

    def hit(self, ev: Event) -> Any:
        if not ev.mouse:
            return None
        x, y, _ = ev.mouse
        for zy, x1, x2, tag in self.zones:
            if y == zy and x1 <= x <= x2:
                return tag
        return None

    def button(self, y: int, x: int, label: str, tag: Any, style: str = "normal", focused: bool = False) -> int:
        active = focused or self.hover == tag
        if style == "primary":
            attr = self.p("black", "accent", bold=True) if active else self.p("accent", "panel", bold=True)
        elif style == "danger":
            attr = self.p("white", "danger", bold=True) if active else self.p("danger", "panel", bold=True)
        else:
            attr = self.p("text", "hover", bold=True) if active else self.p("muted", "panel")
        text = f"  {label}  "
        end = self.c.put(y, x, text, attr)
        self.zone(y, x, end - 1, tag)
        return end + 2

    # loop ----------------------------------------------------------------
    def run(self) -> Any:
        self.ui.scr.timeout(120)
        while not self.done:
            self.ui.draw()
            self.zones = []
            self.draw()
            self.ui.scr.refresh()
            ev = read_event(self.ui.scr)
            if ev is None:
                self.tick()
                continue
            if ev.mouse:
                self.hover = self.hit(ev)
            self.handle(ev)
        self.ui.scr.timeout(200)
        return self.result

    def close(self, result: Any = None) -> None:
        self.result = result
        self.done = True

    def tick(self) -> None:  # periodic hook
        pass

    def draw(self) -> None:
        raise NotImplementedError

    def handle(self, ev: Event) -> None:
        raise NotImplementedError


class FormModal(Modal):
    min_w = 56

    def __init__(self, ui: Any, title: str, fields: list[Field], subtitle: str = "", submit: str = "Save",
                 validate: Callable[[dict], str | None] | None = None,
                 extra: list[tuple[str, Callable[[dict], tuple[dict, str]]]] | None = None) -> None:
        super().__init__(ui, title, subtitle)
        self.fields = fields
        for f in fields:
            if f.kind in ("text", "secret"):
                f.value = str(f.value or "")
                f.cursor = len(f.value)
        self.submit_label = submit
        self.validate = validate
        self.extra = extra or []
        self.focus = 0
        self.error = ""
        self.notice = ""
        self.n_buttons = 2 + len(self.extra)

    def values(self) -> dict:
        return {f.key: (f.value.strip() if isinstance(f.value, str) else f.value) for f in self.fields}

    def draw(self) -> None:
        top, x, _h, w = self.frame(len(self.fields) + 3, 76)
        label_w = max(len(f.label) for f in self.fields) + 2
        in_x = x + label_w + 2
        in_w = w - label_w - 3
        for i, f in enumerate(self.fields):
            y = top + i
            focused = self.focus == i
            hovered = self.hover == ("field", i)
            self.c.put(y, x, "▸" if focused else " ", self.p("accent", "panel", bold=True))
            self.c.put(y, x + 2, f.label, self.p("accent" if focused else "text", "panel", bold=focused))
            bg = "hover" if (focused or hovered) else "sel"
            self.c.fill(y, in_x, in_w, self.p("text", bg))
            shown = f.display() if f.kind != "secret" else "•" * len(str(f.value))
            if f.kind in ("text", "secret"):
                start = max(0, f.cursor - in_w + 2)
                vis = shown[start:start + in_w - 2]
                if vis:
                    self.c.put(y, in_x + 1, vis, self.p("text", bg, bold=True))
                elif f.hint and not focused:
                    self.c.put(y, in_x + 1, f.hint, self.p("muted", bg), in_w - 2)
                if focused:
                    cx = in_x + 1 + (f.cursor - start)
                    under = shown[f.cursor] if f.cursor < len(shown) else " "
                    self.c.put(y, cx, under, self.p("black", "accent"))
            else:
                self.c.put(y, in_x + 1, shown, self.p("accent" if f.kind == "bool" and f.value else "text", bg,
                                                      bold=True))
                if f.hint:
                    hx = in_x + 3 + text_width(shown)
                    self.c.put(y, hx, f.hint, self.p("muted", bg), in_w - text_width(shown) - 4)
            self.zone(y, x, x + w, ("field", i))
        msg_y = top + len(self.fields)
        if self.error:
            self.c.put(msg_y, x + 2, f"✖ {self.error}", self.p("danger", "panel", bold=True), w - 2)
        elif self.notice:
            self.c.put(msg_y, x + 2, f"ℹ {self.notice}", self.p("info", "panel"), w - 2)
        by = msg_y + 2
        nf = len(self.fields)
        bx = self.button(by, x, f"✔ {self.submit_label}", ("btn", 0), "primary", self.focus == nf)
        bx = self.button(by, bx, "✖ Cancel", ("btn", 1), "normal", self.focus == nf + 1)
        for j, (label, _fn) in enumerate(self.extra):
            bx = self.button(by, bx, label, ("btn", 2 + j), "normal", self.focus == nf + 2 + j)
        hint = "Tab/↑↓ move · Space toggle · ←→ choose · Enter save · Esc cancel"
        if bx + text_width(hint) < x + w:
            self.c.put(by, x + w - text_width(hint), hint, self.p("muted", "panel"))

    def _activate_button(self, idx: int) -> None:
        if idx == 0:
            vals = self.values()
            err = self.validate(vals) if self.validate else None
            if err:
                self.error = err
                return
            self.close(vals)
        elif idx == 1:
            self.close(None)
        else:
            _label, fn = self.extra[idx - 2]
            new_vals, msg = fn(self.values())
            for f in self.fields:
                if f.key in new_vals and new_vals[f.key] != f.value:
                    f.value = new_vals[f.key]
                    if f.kind in ("text", "secret"):
                        f.cursor = len(f.value)
            self.notice, self.error = msg, ""

    def handle(self, ev: Event) -> None:
        total = len(self.fields) + self.n_buttons
        if ev.mouse:
            tag = self.hit(ev)
            if ev.is_click and tag:
                kind, idx = tag
                if kind == "field":
                    self.focus = idx
                    f = self.fields[idx]
                    if f.kind == "bool":
                        f.value = not f.value
                    elif f.kind == "choice":
                        self._cycle(f, 1)
                else:
                    self._activate_button(idx)
            return
        k = ev.key
        if k == ESC:
            self.close(None)
            return
        if k in ("\t", curses.KEY_DOWN):
            self.focus = (self.focus + 1) % total
            return
        if k in (curses.KEY_BTAB, curses.KEY_UP):
            self.focus = (self.focus - 1) % total
            return
        if k == curses.KEY_ENTER:
            if self.focus >= len(self.fields):
                self._activate_button(self.focus - len(self.fields))
            else:
                self._activate_button(0)
            return
        if self.focus >= len(self.fields):
            if k in (curses.KEY_LEFT, curses.KEY_RIGHT):
                step = 1 if k == curses.KEY_RIGHT else -1
                off = (self.focus - len(self.fields) + step) % self.n_buttons
                self.focus = len(self.fields) + off
            return
        f = self.fields[self.focus]
        self.error = ""
        if f.kind == "bool":
            if k in (" ", "x", curses.KEY_LEFT, curses.KEY_RIGHT):
                f.value = not f.value
            return
        if f.kind == "choice":
            if k in (curses.KEY_RIGHT, " "):
                self._cycle(f, 1)
            elif k == curses.KEY_LEFT:
                self._cycle(f, -1)
            return
        val, cur = f.value, f.cursor
        if k == curses.KEY_BACKSPACE:
            if cur > 0:
                f.value, f.cursor = val[: cur - 1] + val[cur:], cur - 1
        elif k == curses.KEY_DC:
            f.value = val[:cur] + val[cur + 1 :]
        elif k == curses.KEY_LEFT:
            f.cursor = max(0, cur - 1)
        elif k == curses.KEY_RIGHT:
            f.cursor = min(len(val), cur + 1)
        elif k in (curses.KEY_HOME, "\x01"):
            f.cursor = 0
        elif k in (curses.KEY_END, "\x05"):
            f.cursor = len(val)
        elif k == "\x15":  # Ctrl+U
            f.value, f.cursor = "", 0
        elif k == "\x17":  # Ctrl+W
            head = val[:cur].rstrip()
            cut = head.rfind(" ") + 1
            f.value, f.cursor = val[:cut] + val[cur:], cut
        elif isinstance(k, str) and k.isprintable():
            f.value, f.cursor = val[:cur] + k + val[cur:], cur + len(k)

    @staticmethod
    def _cycle(f: Field, step: int) -> None:
        if f.choices:
            i = f.choices.index(f.value) if f.value in f.choices else 0
            f.value = f.choices[(i + step) % len(f.choices)]


@dataclass
class Option:
    code: Any
    label: str
    desc: str = ""
    key: str = ""
    style: str = "text"


class ChoiceModal(Modal):
    def __init__(self, ui: Any, title: str, options: list[Option], subtitle: str = "",
                 on_highlight: Callable[[Any], None] | None = None, initial: int = 0) -> None:
        super().__init__(ui, title, subtitle)
        self.options = options
        self.sel = max(0, min(initial, len(options) - 1))
        self.scroll = 0
        self.on_highlight = on_highlight

    def draw(self) -> None:
        sh, _ = self.c.size
        rows = min(len(self.options), max(3, sh - 12))
        top, x, _h, w = self.frame(rows + 2, 72)
        if self.sel < self.scroll:
            self.scroll = self.sel
        if self.sel >= self.scroll + rows:
            self.scroll = self.sel - rows + 1
        for i in range(rows):
            idx = self.scroll + i
            if idx >= len(self.options):
                break
            o = self.options[idx]
            y = top + i
            active = idx == self.sel or self.hover == ("opt", idx)
            bg = "hover" if active else "panel"
            self.c.fill(y, x - 1, w + 2, self.p("text", bg))
            self.c.put(y, x, "▸" if idx == self.sel else " ", self.p("accent", bg, bold=True))
            kx = x + 2
            if o.key:
                self.c.put(y, kx, f"{o.key:>3}", self.p("accent", bg, bold=True))
                kx += 5
            end = self.c.put(y, kx, o.label, self.p(o.style, bg, bold=True), w - (kx - x) - 1)
            if o.desc:
                self.c.put(y, end + 2, o.desc, self.p("muted", bg), w - (end - x) - 3)
            self.zone(y, x - 1, x + w, ("opt", idx))
        if len(self.options) > rows:
            self.c.put(top + rows, x, f"  {self.scroll + 1}-{self.scroll + rows} of {len(self.options)}",
                       self.p("muted", "panel"))
        bx = self.button(top + rows + 1, x, "✖ Cancel", ("cancel", 0))
        hint = "↑↓ select · Enter choose · Esc cancel"
        if bx + text_width(hint) < x + w:
            self.c.put(top + rows + 1, x + w - text_width(hint), hint, self.p("muted", "panel"))

    def _moved(self) -> None:
        if self.on_highlight and self.options:
            self.on_highlight(self.options[self.sel].code)

    def handle(self, ev: Event) -> None:
        if ev.mouse:
            b = ev.mouse[2]
            tag = self.hit(ev)
            if b & WHEEL_UP:
                self.sel = max(0, self.sel - 1)
                self._moved()
            elif b & WHEEL_DOWN:
                self.sel = min(len(self.options) - 1, self.sel + 1)
                self._moved()
            elif tag and tag[0] == "opt" and tag[1] != self.sel and not ev.is_click:
                self.sel = tag[1]
                self._moved()
            if ev.is_click and tag:
                if tag[0] == "cancel":
                    self.close(None)
                else:
                    self.close(self.options[tag[1]].code)
            return
        k = ev.key
        if k in (ESC, "q"):
            self.close(None)
        elif k in (curses.KEY_UP, "k"):
            self.sel = (self.sel - 1) % len(self.options)
            self._moved()
        elif k in (curses.KEY_DOWN, "j", "\t"):
            self.sel = (self.sel + 1) % len(self.options)
            self._moved()
        elif k == curses.KEY_ENTER:
            self.close(self.options[self.sel].code)
        elif isinstance(k, str):
            for o in self.options:
                if o.key and o.key.strip("[]").lower() == k.lower():
                    self.close(o.code)
                    return


class ConfirmModal(Modal):
    def __init__(self, ui: Any, title: str, message: str, yes: str = "Yes", danger: bool = False) -> None:
        super().__init__(ui, title)
        self.message = message
        self.yes = yes
        self.danger = danger
        self.focus = 1  # default to the safe choice

    def draw(self) -> None:
        lines = wrap(self.message, 60)
        top, x, _h, _w = self.frame(len(lines) + 2, 66)
        for i, line in enumerate(lines):
            self.c.put(top + i, x, line, self.p("text", "panel"))
        by = top + len(lines) + 1
        bx = self.button(by, x, self.yes, ("btn", 0), "danger" if self.danger else "primary", self.focus == 0)
        self.button(by, bx, "Cancel", ("btn", 1), "normal", self.focus == 1)

    def handle(self, ev: Event) -> None:
        if ev.mouse:
            tag = self.hit(ev)
            if ev.is_click and tag:
                self.close(tag[1] == 0)
            return
        k = ev.key
        if k in (ESC, "n", "q"):
            self.close(False)
        elif k in ("y", "Y"):
            self.close(True)
        elif k in (curses.KEY_LEFT, curses.KEY_RIGHT, "\t"):
            self.focus = 1 - self.focus
        elif k == curses.KEY_ENTER:
            self.close(self.focus == 0)


class TextModal(Modal):
    def __init__(self, ui: Any, title: str, lines: list[tuple[str, str]], subtitle: str = "", width: int = 78):
        super().__init__(ui, title, subtitle)
        self.lines = lines  # (text, role)
        self.scroll = 0
        self.width = width

    def draw(self) -> None:
        sh, _ = self.c.size
        rows = min(len(self.lines), sh - 10)
        top, x, _h, w = self.frame(rows + 2, self.width)
        self.scroll = max(0, min(self.scroll, len(self.lines) - rows))
        for i in range(rows):
            text, role = self.lines[self.scroll + i]
            bold = role.endswith("!")
            self.c.put(top + i, x, text, self.p(role.rstrip("!") or "text", "panel", bold=bold), w)
        foot = "↑↓/PgUp/PgDn scroll · Esc close" if len(self.lines) > rows else "Esc / Enter close"
        self.c.put(top + rows + 1, x, foot, self.p("muted", "panel"))

    def handle(self, ev: Event) -> None:
        if ev.mouse:
            b = ev.mouse[2]
            if b & WHEEL_UP:
                self.scroll -= 3
            elif b & WHEEL_DOWN:
                self.scroll += 3
            elif ev.is_click:
                self.close()
            return
        k = ev.key
        if k in (ESC, "q", curses.KEY_ENTER, "?"):
            self.close()
        elif k in (curses.KEY_UP, "k"):
            self.scroll -= 1
        elif k in (curses.KEY_DOWN, "j"):
            self.scroll += 1
        elif k == curses.KEY_PPAGE:
            self.scroll -= 10
        elif k in (curses.KEY_NPAGE, " "):
            self.scroll += 10


class ChecklistModal(Modal):
    def __init__(self, ui: Any, title: str, items: list[tuple[str, str, bool]], subtitle: str = "",
                 submit: str = "Add selected") -> None:
        super().__init__(ui, title, subtitle)
        self.items = [[label, desc, checked] for label, desc, checked in items]
        self.sel = 0
        self.scroll = 0
        self.submit = submit

    def draw(self) -> None:
        sh, _ = self.c.size
        rows = min(len(self.items), max(3, sh - 12))
        top, x, _h, w = self.frame(rows + 2, 92)
        if self.sel < self.scroll:
            self.scroll = self.sel
        if self.sel >= self.scroll + rows:
            self.scroll = self.sel - rows + 1
        for i in range(rows):
            idx = self.scroll + i
            if idx >= len(self.items):
                break
            label, desc, checked = self.items[idx]
            y = top + i
            active = idx == self.sel or self.hover == ("item", idx)
            bg = "hover" if active else "panel"
            self.c.fill(y, x - 1, w + 2, self.p("text", bg))
            self.c.put(y, x, "[✓]" if checked else "[ ]", self.p("success" if checked else "muted", bg, bold=True))
            end = self.c.put(y, x + 4, label, self.p("text", bg, bold=True), w // 2 - 6)
            dx = max(end + 2, x + w // 2)
            self.c.put(y, dx, desc, self.p("muted", bg), x + w - dx)
            self.zone(y, x - 1, x + w, ("item", idx))
        n = sum(1 for it in self.items if it[2])
        by = top + rows + 1
        bx = self.button(by, x, f"✔ {self.submit} ({n})", ("btn", 0), "primary")
        bx = self.button(by, bx, "Toggle all", ("btn", 2))
        bx = self.button(by, bx, "✖ Cancel", ("btn", 1))
        hint = "Space toggle · a all · Enter confirm"
        if bx + text_width(hint) < x + w:
            self.c.put(by, x + w - text_width(hint), hint, self.p("muted", "panel"))

    def _toggle_all(self) -> None:
        state = not all(it[2] for it in self.items)
        for it in self.items:
            it[2] = state

    def handle(self, ev: Event) -> None:
        if ev.mouse:
            tag = self.hit(ev)
            b = ev.mouse[2]
            if b & WHEEL_UP:
                self.sel = max(0, self.sel - 1)
            elif b & WHEEL_DOWN:
                self.sel = min(len(self.items) - 1, self.sel + 1)
            elif ev.is_click and tag:
                kind, idx = tag
                if kind == "item":
                    self.sel = idx
                    self.items[idx][2] = not self.items[idx][2]
                elif idx == 0:
                    self.close([i for i, it in enumerate(self.items) if it[2]])
                elif idx == 2:
                    self._toggle_all()
                else:
                    self.close(None)
            return
        k = ev.key
        if k in (ESC, "q"):
            self.close(None)
        elif k in (curses.KEY_UP, "k"):
            self.sel = (self.sel - 1) % len(self.items)
        elif k in (curses.KEY_DOWN, "j"):
            self.sel = (self.sel + 1) % len(self.items)
        elif k in (" ", "x"):
            self.items[self.sel][2] = not self.items[self.sel][2]
        elif k == "a":
            self._toggle_all()
        elif k == curses.KEY_ENTER:
            self.close([i for i, it in enumerate(self.items) if it[2]])


class ProgressModal(Modal):
    """Runs ``fn(progress, cancel)`` on a thread, showing a bar; Esc requests cancel."""

    def __init__(self, ui: Any, title: str, fn: Callable[[Callable[[int, int], None], threading.Event], Any],
                 message: str = "Working…") -> None:
        super().__init__(ui, title)
        self.fn = fn
        self.message = message
        self.cancel = threading.Event()
        self.done_n, self.total = 0, 0
        self.error: Exception | None = None
        self._value: Any = None
        self.started = time.monotonic()
        self.thread = threading.Thread(target=self._work, daemon=True)
        self.thread.start()

    def _work(self) -> None:
        try:
            self._value = self.fn(self._progress, self.cancel)
        except Exception as exc:  # surfaced to the caller as the result
            self.error = exc

    def _progress(self, done: int, total: int) -> None:
        self.done_n, self.total = done, total

    def tick(self) -> None:
        if not self.thread.is_alive():
            self.close(self.error or self._value)

    def draw(self) -> None:
        if not self.thread.is_alive():
            self.close(self.error or self._value)
        top, x, _h, w = self.frame(3, 60)
        spin = SPINNER[int(time.monotonic() * 10) % len(SPINNER)]
        msg = "Cancelling…" if self.cancel.is_set() else self.message
        self.c.put(top, x, f"{spin} {msg}", self.p("accent", "panel", bold=True), w)
        pct = 100.0 * self.done_n / self.total if self.total else None
        bw = w - 10
        filled, empty = bar(pct if pct is not None else (time.monotonic() * 40) % 100, bw)
        self.c.put(top + 1, x, filled, self.p("accent", "panel"))
        self.c.put(top + 1, x + text_width(filled), empty, self.p("border", "panel"))
        if pct is not None:
            self.c.put(top + 1, x + bw + 2, f"{pct:3.0f}%", self.p("text", "panel", bold=True))
        self.c.put(top + 2, x, f"{time.monotonic() - self.started:4.1f}s · Esc to cancel", self.p("muted", "panel"))

    def handle(self, ev: Event) -> None:
        if ev.key in (ESC, "q"):
            self.cancel.set()


def wrap(text: str, width: int) -> list[str]:
    out: list[str] = []
    for para in text.split("\n"):
        line = ""
        for word in para.split(" "):
            if line and text_width(line) + 1 + text_width(word) > width:
                out.append(line)
                line = word
            else:
                line = f"{line} {word}" if line else word
        out.append(line)
    return out
