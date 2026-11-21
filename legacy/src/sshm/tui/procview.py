"""Live process viewer modal for the TUI (refreshes over a multiplexed SSH session)."""

from __future__ import annotations

import curses
import threading
import time
from typing import Any

from sshm.core import procs
from sshm.core.models import Server
from sshm.tui.widgets import (
    ESC,
    SPINNER,
    WHEEL_DOWN,
    WHEEL_UP,
    ConfirmModal,
    Modal,
    ProgressModal,
    TextModal,
    fit,
    text_width,
)

REFRESH = 3.0
COLUMNS = [  # (sort key, header, width, align)
    ("pid", "PID", 7, ">"),
    ("user", "USER", 10, "<"),
    ("cpu", "CPU%", 6, ">"),
    ("mem", "MEM%", 6, ">"),
    ("mem", "RSS", 8, ">"),
    ("time", "TIME", 7, ">"),
    ("name", "COMMAND", 0, "<"),
]
SORT_KEYS = {"c": "cpu", "m": "mem", "p": "pid", "n": "name", "u": "user", "t": "time"}


class ProcessModal(Modal):
    min_w = 70

    def __init__(self, ui: Any, server: Server) -> None:
        super().__init__(ui, f"Processes — {server.name}")
        self.server = server
        self.all: list[procs.Process] = []
        self.error = ""
        self.loading = True
        self.updated = 0.0
        self.sort = "cpu"
        self.query = ""
        self.filtering = False
        self.sel_pid: int | None = None
        self.scroll = 0
        self.notice = ""
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="sshm-ps")
        self._thread.start()

    # ------------------------------------------------------------ fetching
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                result = procs.fetch(self.server)
                with self._lock:
                    self.all, self.error = result, ""
            except procs.ProcError as exc:
                with self._lock:
                    self.error = str(exc)
            self.loading = False
            self.updated = time.monotonic()
            self._wake.wait(REFRESH)
            self._wake.clear()

    def close(self, result: Any = None) -> None:
        self._stop.set()
        self._wake.set()
        super().close(result)

    def rows(self) -> list[procs.Process]:
        with self._lock:
            items = list(self.all)
        return procs.sort(procs.filter_procs(items, self.query), self.sort)

    def selected(self, rows: list[procs.Process]) -> procs.Process | None:
        if not rows:
            return None
        cur = next((p for p in rows if p.pid == self.sel_pid), None)
        if cur is None:
            cur = rows[0]
            self.sel_pid = cur.pid
        return cur

    def move(self, delta: int) -> None:
        rows = self.rows()
        if not rows:
            return
        cur = self.selected(rows)
        idx = rows.index(cur) if cur in rows else 0
        self.sel_pid = rows[max(0, min(len(rows) - 1, idx + delta))].pid

    # -------------------------------------------------------------- drawing
    def draw(self) -> None:
        sh, sw = self.c.size
        top, x, h, w = self.frame(max(8, sh - 8), max(80, sw - 6))
        p = self.p
        rows = self.rows()
        sel = self.selected(rows)

        # line 1: status + sort + filter
        now = time.monotonic()
        if self.loading:
            status = f"{SPINNER[int(now * 10) % len(SPINNER)]} connecting…"
        else:
            status = f"{len(rows)}{'' if not self.query else f'/{len(self.all)}'} processes · " \
                     f"updated {int(now - self.updated)}s ago"
        end = self.c.put(top, x, status, p("muted", "panel"))
        filt = f"/{self.query}{'▏' if self.filtering else ''}" if (self.query or self.filtering) else "/ filter"
        self.c.put(top, max(end + 3, x + w - text_width(filt)), filt,
                   p("warning" if self.query or self.filtering else "muted", "panel", bold=bool(self.query)))

        # header
        hy = top + 2
        cmd_w = w - sum(c[2] + 1 for c in COLUMNS[:-1])
        cx = x
        self.c.fill(hy, x - 1, w + 2, p("muted", "sel"))
        for key, label, width, align in COLUMNS:
            width = width or cmd_w
            active = key == self.sort and (label != "RSS")
            text = fit(label + (" ▾" if active else ""), width, align)
            self.c.put(hy, cx, text, p("accent" if active else "muted", "sel", bold=True))
            self.zone(hy, cx, cx + width, ("sort", key))
            cx += width + 1

        # body
        body_top = hy + 1
        body_h = h - 5
        if self.error and not rows:
            for i, line in enumerate(_wrap(self.error, w - 4)[: body_h - 2]):
                self.c.put(body_top + 1 + i, x + 2, line, p("danger", "panel", bold=i == 0))
            self.c.put(body_top + 2 + len(_wrap(self.error, w - 4)), x + 2,
                       "Press h to open htop in a terminal instead.", p("muted", "panel"))
        idx = rows.index(sel) if sel in rows else 0
        if idx < self.scroll:
            self.scroll = idx
        if idx >= self.scroll + body_h:
            self.scroll = idx - body_h + 1
        self.scroll = max(0, min(self.scroll, max(0, len(rows) - body_h)))
        for r in range(body_h):
            i = self.scroll + r
            if i >= len(rows):
                break
            proc = rows[i]
            y = body_top + r
            is_sel = proc.pid == self.sel_pid
            bg = "hover" if is_sel else "panel"
            self.c.fill(y, x - 1, w + 2, p("text", bg))
            if is_sel:
                self.c.put(y, x - 1, "▌", p("accent", bg, bold=True))
            cells = [str(proc.pid), proc.user, _pct(proc.cpu), _pct(proc.mem), proc.rss_label,
                     proc.elapsed_label, proc.command]
            cx = x
            for (_key, label, width, align), cell in zip(COLUMNS, cells, strict=True):
                width = width or cmd_w
                role = "muted" if label in ("USER", "RSS", "TIME") else "text"
                if label == "CPU%" and proc.cpu is not None:
                    role = "danger" if proc.cpu >= 80 else "warning" if proc.cpu >= 25 else "text"
                self.c.put(y, cx, fit(cell, width, align), p(role, bg, bold=is_sel and label == "COMMAND"))
                cx += width + 1
            self.zone(y, x - 1, x + w, ("row", proc.pid))

        # footer
        fy = body_top + body_h
        if self.notice:
            self.c.put(fy, x, self.notice, p("info", "panel"), w)
        elif self.error and rows:
            self.c.put(fy, x, f"⚠ {self.error}", p("warning", "panel"), w)
        hints = [("↑↓", "move"), ("c/m/p/n/u/t", "sort"), ("/", "filter"), ("⏎", "details"),
                 ("k", "kill"), ("K", "force kill"), ("h", "htop"), ("r", "refresh"), ("Esc", "close")]
        hx = x
        for key, label in hints:
            if hx + text_width(key) + text_width(label) + 3 > x + w:
                break
            hx = self.c.put(fy + 1, hx, key, p("accent", "panel", bold=True))
            hx = self.c.put(fy + 1, hx + 1, label, p("muted", "panel")) + 2

    # ------------------------------------------------------------- actions
    def kill_selected(self, force: bool) -> None:
        proc = self.selected(self.rows())
        if not proc:
            return
        sig = "SIGKILL" if force else "SIGTERM"
        if not ConfirmModal(self.ui, f"Send {sig}", f"{procs.describe(proc)}\n\non {self.server.name}?",
                            "Force kill" if force else "Kill", danger=True).run():
            return
        res = ProgressModal(self.ui, "Sending signal", lambda _p, _c: procs.kill(self.server, proc.pid, force),
                            f"{sig} → {proc.pid}").run()
        if isinstance(res, procs.ProcError) and "another user" in str(res):
            if ConfirmModal(self.ui, "Permission denied",
                            f"{proc.name} (pid {proc.pid}) belongs to {proc.user}.\n"
                            "Retry with sudo in this terminal?", "Use sudo").run():
                self.ui.suspend_run(procs.sudo_kill_argv(self.server, proc.pid, force),
                                    f"sudo kill {proc.pid} · {self.server.name}", pause=True)
                self.notice = f"Ran sudo kill on {proc.pid}"
        elif isinstance(res, Exception):
            self.notice = f"✖ {res}"
        elif res:
            self.notice = f"✔ {res}"
        self._wake.set()

    def details(self) -> None:
        proc = self.selected(self.rows())
        if not proc:
            return
        lines = [
            (f"PID       {proc.pid}", "text"), (f"User      {proc.user}", "text"),
            (f"CPU       {_pct(proc.cpu)} %", "text"), (f"Memory    {_pct(proc.mem)} %  ({proc.rss_label})", "text"),
            (f"Running   {proc.elapsed_label}", "text"), ("", "text"), ("Command line", "accent!"),
        ]
        lines += [(f"  {chunk}", "text") for chunk in _wrap(proc.command, 72)]
        TextModal(self.ui, proc.name, lines, width=80).run()

    def handle(self, ev) -> None:
        if ev.mouse:
            _x, _y, b = ev.mouse
            if b & WHEEL_UP:
                self.move(-3)
            elif b & WHEEL_DOWN:
                self.move(3)
            elif ev.is_click:
                tag = self.hit(ev)
                if tag and tag[0] == "sort":
                    self.sort = tag[1]
                elif tag and tag[0] == "row":
                    if self.sel_pid == tag[1] and time.monotonic() - getattr(self, "_last_click", 0) < 0.45:
                        self.details()
                    self.sel_pid = tag[1]
                    self._last_click = time.monotonic()
            return
        k = ev.key
        self.notice = ""
        if self.filtering:
            if k == ESC:
                self.filtering, self.query = False, ""
            elif k == curses.KEY_ENTER:
                self.filtering = False
            elif k == curses.KEY_BACKSPACE:
                self.query = self.query[:-1]
            elif k in (curses.KEY_UP, curses.KEY_DOWN):
                self.move(-1 if k == curses.KEY_UP else 1)
            elif isinstance(k, str) and k.isprintable():
                self.query += k
            return
        if k == ESC:
            if self.query:
                self.query = ""
            else:
                self.close()
        elif k == "q":
            self.close()
        elif k == curses.KEY_UP:
            self.move(-1)
        elif k == curses.KEY_DOWN:
            self.move(1)
        elif k == curses.KEY_PPAGE:
            self.move(-15)
        elif k == curses.KEY_NPAGE:
            self.move(15)
        elif k == curses.KEY_HOME:
            self.move(-10**6)
        elif k == curses.KEY_END:
            self.move(10**6)
        elif k == "/":
            self.filtering = True
        elif isinstance(k, str) and k in SORT_KEYS:
            self.sort = SORT_KEYS[k]
        elif k == "k":
            self.kill_selected(force=False)
        elif k == "K":
            self.kill_selected(force=True)
        elif k == "h":
            self.ui.suspend_run(procs.top_argv(self.server), f"htop · {self.server.name}")
        elif k == "r":
            self.loading = True
            self._wake.set()
        elif k == curses.KEY_ENTER:
            self.details()


def _pct(v: float | None) -> str:
    return f"{v:.1f}" if v is not None else "--"


def _wrap(text: str, width: int) -> list[str]:
    return [text[i : i + width] for i in range(0, len(text), width)] or [""]
