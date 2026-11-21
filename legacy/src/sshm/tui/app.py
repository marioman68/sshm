"""sshm terminal UI.

Layout (wide terminals)::

    ▌◆ sshm  SSH Connection Hub          ● 4/6 online  ⚑ All  ⇅ Name  ⟳ 10s ▐
    ╭ Servers (6) ───────────╮╭ nas ─────────────────────────── ● Online ╮
    │▌● ★ nas      Homelab 3 ms││ Endpoint  lucas@192.168.4.10:22          │
    │ ● · pihole   Lab     1 ms││ SYSTEM ─────────────────────────────────  │
    │ ○ · backup          --   ││ CPU  ████████░░░░░░  48%  ▁▂▃▅▆▇▅▃      │
    ╰──────────────────────────╯╰──────────────────────────────────────────╯
     ⏎ connect  / search  a add  n scan  ? help  q quit           updated 2s ago

Everything slow (probing, scans, SSHFS, tunnels) runs off the UI thread.
"""

from __future__ import annotations

import contextlib
import curses
import locale
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

from sshm import __version__
from sshm.core import agent, clipboard, mounts, netscan, sshcmd, sshconfig, wol
from sshm.core.hub import Hub
from sshm.core.models import CustomCommand, Server, fuzzy_score, normalize_mac
from sshm.core.settings import REFRESH_CHOICES
from sshm.core.status import HostStatus
from sshm.core.store import StoreError
from sshm.core.themes import THEMES, get_theme
from sshm.core.tunnels import TunnelError, TunnelSpec
from sshm.tui.widgets import (
    ESC,
    SPINNER,
    WHEEL_DOWN,
    WHEEL_UP,
    Canvas,
    ChecklistModal,
    ChoiceModal,
    ConfirmModal,
    Event,
    Field,
    FormModal,
    Option,
    Palette,
    ProgressModal,
    TextModal,
    bar,
    fit,
    read_event,
    sparkline,
    text_width,
)

os.environ.setdefault("ESCDELAY", "25")

SORTS = ["name", "status", "latency", "recent"]
MOUSE_ON = "\033[?1003h\033[?1006h"
MOUSE_OFF = "\033[?1000l\033[?1002l\033[?1003l\033[?1006l\033[?1015l"


@dataclass
class Action:
    code: str
    key: str
    label: str
    help: str
    style: str = "text"


SERVER_ACTIONS = [
    Action("connect", "⏎", "Connect", "Open an SSH session (uses the server's tmux preference)", "accent"),
    Action("tmux", "m", "tmux session", "Connect and attach/create a persistent tmux session"),
    Action("sftp", "s", "SFTP shell", "Interactive command-line file transfer"),
    Action("files", "o", "Open files", "Open the remote home folder in your desktop file manager"),
    Action("bookmark", "b", "Bookmark", "Add/remove this server in your file manager's sidebar"),
    Action("sshfs", "M", "SSHFS mount", "Mount the remote home folder locally with SSHFS"),
    Action("docker", "D", "Containers", "Docker/Podman: container status, restart/stop/start, logs and shell"),
    Action("procs", "P", "Processes", "Live process list for this server — sort, filter, kill, or open htop"),
    Action("tunnel", "t", "Port forward", "Start a background -L / -R / -D (SOCKS) tunnel"),
    Action("wake", "w", "Wake-on-LAN", "Send a magic packet to the saved MAC address"),
    Action("key", "k", "Push SSH key", "Install your public key for password-less login (ssh-copy-id)"),
    Action("agent", "g", "Telemetry agent", "Deploy, inspect or remove the live CPU/RAM/disk agent"),
    Action("run", "x", "Run command", "Run one of this server's saved commands, or add a new one"),
    Action("copy", "y", "Copy ssh cmd", "Copy the equivalent ssh command line to the clipboard"),
    Action("fav", "*", "Favorite", "Pin this server to the top of the list"),
    Action("edit", "e", "Edit", "Edit this server profile"),
    Action("delete", "d", "Delete", "Remove this server profile", "danger"),
]

KEYMAP = {
    "c": "connect", "m": "tmux", "s": "sftp", "o": "files", "b": "bookmark", "M": "sshfs",
    "P": "procs", "D": "docker", "t": "tunnel", "w": "wake", "k": "key", "g": "agent",
    "x": "run", "y": "copy", "*": "fav",
    "e": "edit", "d": "delete", curses.KEY_DC: "delete", curses.KEY_ENTER: "connect",
    "a": "add", "n": "scan", "i": "import", "T": "tunnels", "p": "theme", ",": "settings",
    "r": "refresh", "f": "filter", "F": "filter_pick", "S": "sort", "/": "search", "?": "help",
    "q": "quit", "E": "export", "!": "events", "X": "fleet",
}

HELP = [
    ("NAVIGATION", "accent!"),
    ("  ↑ ↓ / j k        move selection          PgUp PgDn Home End", "text"),
    ("  1-9              jump to row             mouse wheel scrolls the list", "text"),
    ("  /                search (fuzzy)          Esc clears the search", "text"),
    ("  f / F            next tag / pick tag     S  cycle sort order", "text"),
    ("", "text"),
    ("SERVER", "accent!"),
    ("  Enter / c        connect                 m  connect in tmux", "text"),
    ("  s                SFTP shell              o  open in file manager", "text"),
    ("  b                toggle bookmark         M  SSHFS mount / unmount", "text"),
    ("  t                port forward            T  list & stop tunnels", "text"),
    ("  w                Wake-on-LAN             k  push SSH key", "text"),
    ("  g                telemetry agent         x  saved commands", "text"),
    ("  P                process viewer (sort c/m/p/n · k kill · h htop)", "text"),
    ("  D                containers: restart / stop / logs / shell (detects docker & podman)", "text"),
    ("  y                copy ssh command        *  favorite", "text"),
    ("  e                edit                    d / Del  delete", "text"),
    ("", "text"),
    ("HUB", "accent!"),
    ("  a                add server              n  scan network", "text"),
    ("  i                import ~/.ssh/config    E  export as ssh_config", "text"),
    ("  r                refresh now             p  theme", "text"),
    ("  X                run a command on many   !  alerts & activity log", "text"),
    ("  ,                settings                q  quit", "text"),
    ("", "text"),
    ("MOUSE", "accent!"),
    ("  click selects · double-click connects · click ★ to favorite · click actions", "text"),
]


class TUI:
    def __init__(self, scr: curses.window) -> None:
        self.scr = scr
        self.hub = Hub()
        self.settings = self.hub.settings
        self.store = self.hub.store
        self.palette = Palette()
        self.canvas = Canvas(scr, self.palette)
        self.theme = get_theme(self.settings.theme)
        self.palette.apply(self.theme)

        self.sel_id: str | None = None
        self.scroll = 0
        self.query = ""
        self.searching = False
        self.tag = "ALL"
        self.sort = "name"
        self.zones: list[tuple[int, int, int, str, object]] = []
        self.mouse = (-1, -1)
        self.toast: tuple[str, str, float] | None = None
        self.last_click = (0.0, None)
        self.running = True
        self.sshfs = mounts.sshfs_available()
        self.hosts: dict = {}
        self.links: dict = {}
        self._avail: dict = {}
        self._alerts: list = []
        self._alerts_t = 0.0
        self._last_fleet_cmd = "uptime"
        self._cache: dict[str, tuple[bool, bool]] = {}
        self._cache_t = 0.0
        self.own_listener = self.hub.start_listener()
        self.hub.refresh()
        if self.store.migrated_from_legacy:
            self.notify(f"Imported {len(self.store)} server(s) from ~/.ssh_servers", "success")

    # ============================================================ helpers
    def notify(self, msg: str, level: str = "info") -> None:
        self.toast = (msg, level, time.monotonic())

    def visible(self) -> list[Server]:
        servers = self.store.servers
        if self.tag != "ALL":
            servers = [s for s in servers if s.tag.lower() == self.tag.lower()]
        if self.query:
            scored = [(fuzzy_score(self.query, s.search_text), s) for s in servers]
            servers = [s for score, s in sorted(scored, key=lambda t: -t[0]) if score > 0]
            return sorted(servers, key=lambda s: not s.favorite)

        def status_key(s: Server) -> tuple:
            st = self.hub.status_of(s)
            return (0 if st and st.online else 1, s.name.lower())

        def latency_key(s: Server) -> tuple:
            st = self.hub.status_of(s)
            return (st.latency_ms if st and st.online and st.latency_ms is not None else 1e9, s.name.lower())

        key: Callable = {
            "name": lambda s: s.name.lower(),
            "status": status_key,
            "latency": latency_key,
            "recent": lambda s: -s.last_connected,
        }[self.sort]
        return sorted(sorted(servers, key=key), key=lambda s: not s.favorite)

    def selected(self, servers: list[Server] | None = None) -> Server | None:
        servers = self.visible() if servers is None else servers
        if not servers:
            return None
        srv = next((s for s in servers if s.id == self.sel_id), None)
        if srv is None:
            srv = servers[0]
            self.sel_id = srv.id
        return srv

    def move(self, delta: int) -> None:
        servers = self.visible()
        if not servers:
            return
        cur = self.selected(servers)
        idx = servers.index(cur) if cur in servers else 0
        self.sel_id = servers[max(0, min(len(servers) - 1, idx + delta))].id

    def file_state(self, srv: Server) -> tuple[bool, bool]:
        """(bookmarked, sshfs mounted) — cached because it touches several files."""
        now = time.monotonic()
        if now - self._cache_t > 2.0:
            self._cache.clear()
            self._cache_t = now
        if srv.id not in self._cache:
            self._cache[srv.id] = (
                mounts.is_bookmarked(srv, self.settings),
                self.sshfs and mounts.is_sshfs_mounted(srv, self.settings),
            )
        return self._cache[srv.id]

    def zone(self, y: int, x1: int, x2: int, action: str, arg: object = None) -> None:
        self.zones.append((y, x1, x2, action, arg))

    def hit(self, x: int, y: int) -> tuple[str, object] | None:
        for zy, x1, x2, act, arg in self.zones:
            if y == zy and x1 <= x <= x2:
                return act, arg
        return None

    # =========================================================== drawing
    def draw(self) -> None:
        p, c = self.palette, self.canvas
        self.scr.erase()
        self.zones = []
        h, w = c.size
        if h < 16 or w < 60:
            c.put(0, 0, "sshm: terminal too small — resize to at least 60×16 (q quits)", p("danger", bold=True))
            return
        servers = self.visible()
        srv = self.selected(servers)
        self.hosts = self.hub.host_containers()
        self.links = self.hub.links()
        self.draw_header(w, servers)
        body_h = h - 2
        if w >= 104:
            lw = max(40, min(56, int(w * 0.38)))
            self.draw_list(1, 0, body_h, lw, servers)
            self.draw_detail(1, lw, body_h, w - lw, srv)
        else:
            list_h = max(6, min(len(servers) + 2, body_h // 2))
            self.draw_list(1, 0, list_h, w, servers)
            self.draw_detail(1 + list_h, 0, body_h - list_h, w, srv)
        self.draw_footer(h - 1, w)

    def draw_header(self, w: int, servers: list[Server]) -> None:
        p, c = self.palette, self.canvas
        bar_attr = p("black", "accent")
        c.fill(0, 0, w, bar_attr)
        c.put(0, 1, " ◆ sshm ", p("black", "accent", bold=True))
        end = c.put(0, 10, "SSH Connection Hub", bar_attr)
        c.put(0, end + 2, f"v{__version__}", p("black", "accent", dim=True))
        online, total = self.hub.summary(servers)
        interval = self.settings.refresh_interval
        chips = [
            ("refresh_pick", f"⟳ {interval}s" if interval else "⟳ manual"),
            ("sort", f"⇅ {self.sort.title()}"),
            ("filter_pick", f"⚑ {'All' if self.tag == 'ALL' else self.tag}"),
            ("", f"● {online}/{total} online"),
            *([("events", f"⚠ {n} alert{'s' if n != 1 else ''}")] if (n := len(self.active_alerts())) else []),
        ]
        x = w - 1
        for action, label in chips:
            text = f" {label} "
            x -= text_width(text) + 1
            hovered = self.hover_action() == (action, None)
            c.put(0, x, text, p("white", "sel", bold=True) if hovered else p("black", "accent", bold=True))
            if action:
                self.zone(0, x, x + text_width(text) - 1, action)

    def draw_list(self, y: int, x: int, h: int, w: int, servers: list[Server]) -> None:
        p, c = self.palette, self.canvas
        title = f"Servers ({len(servers)}{'' if len(servers) == len(self.store) else f'/{len(self.store)}'})"
        right = ""
        if self.searching or self.query:
            right = f"/{self.query}{'▏' if self.searching else ''}"
        c.box(y, x, h, w, p("border"), title, p("accent", bold=True), right, p("warning", bold=True))
        inner_h, inner_w = h - 2, w - 2
        if not servers:
            msg = "No servers match your search" if self.query or self.tag != "ALL" else "No servers yet"
            c.put(y + 2, x + 3, msg, p("text", bold=True))
            if not self.query:
                for i, (k, lbl) in enumerate((("a", "add a server"), ("n", "scan your network"),
                                              ("i", "import ~/.ssh/config"))):
                    c.put(y + 4 + i, x + 3, f"{k:>2}", p("accent", bold=True))
                    c.put(y + 4 + i, x + 6, lbl, p("muted"))
                    self.zone(y + 4 + i, x + 3, x + 6 + len(lbl), {"a": "add", "n": "scan", "i": "import"}[k])
            return
        srv = self.selected(servers)
        idx = servers.index(srv) if srv in servers else 0
        if idx < self.scroll:
            self.scroll = idx
        if idx >= self.scroll + inner_h:
            self.scroll = idx - inner_h + 1
        self.scroll = max(0, min(self.scroll, max(0, len(servers) - inner_h)))
        hover = self.hover_action()
        lat_text: dict[str, str] = {}
        for s in servers[self.scroll:self.scroll + inner_h]:
            st = self.hub.status_of(s)
            lat = st.latency_label if st else ""
            if st and st.telemetry and st.telemetry.cpu is not None and inner_w > 46:
                lat = f"{st.telemetry.cpu:3.0f}% {lat}"
            lat_text[s.id] = lat
        lat_w = max([7, *(text_width(v) for v in lat_text.values())])
        has_tags = any(s.tag for s in servers)
        tag_w = min(12, max(0, inner_w - 30 - lat_w)) if has_tags else 0
        name_w = inner_w - 7 - lat_w - (tag_w + 1 if tag_w else 0) - 1
        for row in range(inner_h):
            i = self.scroll + row
            if i >= len(servers):
                break
            s = servers[i]
            ry = y + 1 + row
            is_sel = s.id == self.sel_id
            is_hov = hover is not None and hover[1] == s.id
            bg = "sel" if is_sel else ("hover" if is_hov else None)
            c.fill(ry, x + 1, inner_w, p("text", bg))
            c.put(ry, x + 1, "▌" if is_sel else " ", p("accent", bg, bold=True))
            st = self.hub.status_of(s)
            dot, role = status_dot(st, self.hub.probing)
            c.put(ry, x + 3, dot, p(role, bg, bold=True))
            if s.favorite:
                c.put(ry, x + 5, "★", p("warning", bg, bold=True))
            elif s.id in self.links:
                c.put(ry, x + 5, "⬢", p("info", bg, bold=True))
            else:
                c.put(ry, x + 5, "·", p("border", bg))
            self.zone(ry, x + 5, x + 5, "fav_row", s.id)
            lat = lat_text.get(s.id, "")
            c.put(ry, x + 7, fit(s.name, name_w), p("text", bg, bold=is_sel))
            if tag_w and s.tag:
                c.put(ry, x + 7 + name_w + 1, fit(s.tag, tag_w), p("info", bg))
            c.put(ry, x + w - 2 - lat_w, fit(lat, lat_w, ">"),
                  p("muted" if not st or not st.online else "text", bg))
            self.zone(ry, x + 1, x + w - 2, "row", s.id)
        if len(servers) > inner_h:  # scrollbar
            track = inner_h
            thumb = max(1, track * inner_h // len(servers))
            pos = (track - thumb) * self.scroll // max(1, len(servers) - inner_h)
            for r in range(track):
                c.put(y + 1 + r, x + w - 1, "┃" if pos <= r < pos + thumb else "│",
                      p("accent" if pos <= r < pos + thumb else "border"))

    def draw_detail(self, y: int, x: int, h: int, w: int, srv: Server | None) -> None:
        p, c = self.palette, self.canvas
        if h < 4:
            return
        if srv is None:
            c.box(y, x, h, w, p("border"), "Welcome", p("accent", bold=True))
            lines = [
                ("Manage SSH servers, tunnels, mounts and live telemetry.", "text"),
                ("", "text"),
                ("Get started:", "accent"),
                ("  a   add a server by hand", "text"),
                ("  n   discover SSH servers on your LAN", "text"),
                ("  i   import hosts from ~/.ssh/config", "text"),
                ("  ?   all keyboard shortcuts", "text"),
            ]
            for i, (t, role) in enumerate(lines[: h - 3]):
                c.put(y + 2 + i, x + 3, t, p(role, bold=role == "accent"))
            return
        st = self.hub.status_of(srv)
        state_txt, state_role = state_label(st, self.hub.probing)
        c.box(y, x, h, w, p("border"), srv.name, p("accent", bold=True), state_txt, p(state_role, bold=True))
        ix, iw = x + 3, w - 6
        bottom = y + h - 1
        row = y + 1
        bookmarked, sshfs_on = self.file_state(srv)
        tunnels = self.hub.tunnels.list(srv.id)

        def kv(label: str, value: str, role: str = "text", bold: bool = False) -> None:
            nonlocal row
            if row >= bottom:
                return
            c.put(row, ix, f"{label:<9}", p("muted"))
            c.put(row, ix + 10, value, p(role, bold=bold), iw - 10)
            row += 1

        kv("Endpoint", srv.endpoint, "text", True)
        avail = self.availability(srv)
        if avail is not None and avail.uptime_24h is not None:
            from sshm.core.history import Availability

            pct = avail.uptime_24h
            kv("Uptime", f"{Availability.label(pct)} 24h · {Availability.label(avail.uptime_7d)} 7d",
               "success" if pct >= 99.5 else "warning" if pct >= 95 else "danger")
        if st and st.online:
            detail = f"{st.latency_label}" + (f" · {st.banner}" if st.banner else "")
            kv("Status", f"● Online · {detail}", "success")
        elif st:
            kv("Status", f"{'◐' if st.state == 'degraded' else '○'} {st.summary}",
               "warning" if st.state == "degraded" else "danger")
        else:
            kv("Status", "checking…", "muted")
        if srv.jump:
            kv("Via", srv.jump, "info")
        kv("Identity", srv.key or "default (ssh-agent / ~/.ssh)", "text" if srv.key else "muted")
        if srv.key and not srv.key_path:
            kv("", "⚠ key file not found", "warning")
        kv("MAC", srv.mac or "not set (needed for Wake-on-LAN)", "text" if srv.mac else "muted")
        files = []
        if bookmarked:
            files.append("◆ bookmarked")
        if sshfs_on:
            files.append(f"▣ mounted at {mounts.sshfs_mountpoint(srv, self.settings)}")
        kv("Files", " · ".join(files) or "◇ not bookmarked", "info" if files else "muted")
        if tunnels:
            kv("Tunnels", " · ".join(f"-{t.kind} {t.spec}" for t in tunnels), "warning")
        if srv.notes:
            kv("Notes", srv.notes, "text")

        link = self.links.get(srv.id)
        if link is not None:
            row = self.draw_container_section(row, ix, iw, bottom, link)
        row += 1
        tel = st.telemetry if st else None
        if link is None and row < bottom - 1:
            c.section(row, ix, iw, "SYSTEM", p("accent", bold=True), p("border"))
            row += 1
        if link is not None:
            pass
        elif tel and row < bottom:
            meter_w = max(10, min(30, iw - 34))
            for label, pct, text in (
                ("CPU", tel.cpu, f"{tel.cpu:.1f}%" if tel.cpu is not None else "--"),
                ("Memory", tel.mem_pct, tel.mem_label),
                ("Disk /", tel.disk_pct, tel.disk_label),
            ):
                if row >= bottom:
                    break
                c.put(row, ix, f"{label:<9}", p("muted"))
                filled, empty = bar(pct, meter_w)
                role = "success" if (pct or 0) < 70 else "warning" if (pct or 0) < 90 else "danger"
                end = c.put(row, ix + 10, filled, p(role))
                c.put(row, end, empty, p("border"))
                end = c.put(row, ix + 11 + meter_w, text, p("text", bold=True))
                if label == "CPU" and tel.history:
                    room = ix + iw - end - 2
                    if room > 4:
                        c.put(row, end + 2, sparkline(tel.history, room), p("accent"))
                row += 1
            kv("Load", f"{tel.load_label}    Uptime {tel.uptime_label}")
            if tel.os_name:
                kv("System", f"{tel.os_name}{' · ' + tel.kernel if tel.kernel else ''}", "muted")
            if tel.reboot_required:
                kv("", "⟳ reboot required — a newer kernel is installed", "warning")
            if agent.is_outdated(tel.agent_version):
                kv("", f"⬆ agent update available ({tel.agent_version or 'pre-3.3'} → {agent.bundled_version()}) "
                       "— press g", "info")
            if not tel.signed:
                kv("", "⚠ legacy unsigned agent — redeploy with g", "warning")
            top = tel.top("cpu", 3) if tel.procs else []
            if top and row < bottom - 2:
                row += 1
                c.section(row, ix, iw, "TOP PROCESSES", p("accent", bold=True), p("border"))
                c.put(row, ix + iw - 18, " P  all processes ", p("muted"))
                self.zone(row, ix + iw - 18, ix + iw - 1, "procs")
                row += 1
                for tp in top:
                    if row >= bottom:
                        break
                    role = "danger" if tp.cpu >= 80 else "warning" if tp.cpu >= 25 else "text"
                    c.put(row, ix, f"{tp.cpu:5.1f}%", p(role, bold=True))
                    c.put(row, ix + 8, f"{tp.rss_label:>7}", p("muted"))
                    c.put(row, ix + 17, tp.name, p("text"), iw - 30)
                    c.put(row, ix + iw - 9, f"{tp.pid:>8}", p("muted"))
                    row += 1
        elif row < bottom:
            c.put(row, ix, "No telemetry agent reporting.", p("muted"))
            c.put(row, ix + 30, " g ", p("black", "accent", bold=True))
            c.put(row, ix + 34, "deploy one for live CPU / memory / disk", p("muted"), iw - 34)
            self.zone(row, ix + 30, ix + 33, "agent")
            row += 1

        hc = self.hosts.get(srv.id)
        if hc is not None and hc.containers and link is None and row < bottom - 4:
            row = self.draw_host_containers(row + 1, ix, iw, bottom, srv, hc)
        row += 1
        if row < bottom - 1:
            c.section(row, ix, iw, "ACTIONS", p("accent", bold=True), p("border"))
            row += 1
        actions = [a for a in SERVER_ACTIONS if a.code != "sshfs" or self.sshfs]
        col_w = 22
        cols = max(1, min(4, iw // col_w))
        hover = self.hover_action()
        for i, a in enumerate(actions):
            r = row + i // cols
            if r >= bottom:
                break
            ax = ix + (i % cols) * col_w
            label = a.label
            if a.code == "bookmark" and bookmarked:
                label = "Remove bookmark"
            elif a.code == "sshfs" and sshfs_on:
                label = "Unmount SSHFS"
            elif a.code == "fav" and srv.favorite:
                label = "Unfavorite"
            elif a.code == "run" and srv.commands:
                label = f"Commands ({len(srv.commands)})"
            elif a.code == "docker":
                label = "Container…" if link else (f"Containers ({len(hc.containers)})" if hc and hc.containers
                                                  else "Find containers")
            is_hov = hover == (a.code, None)
            bg = "hover" if is_hov else None
            if is_hov:
                c.fill(r, ax - 1, col_w - 1, p("text", bg))
            c.put(r, ax, f"{a.key:>1}", p("black", "accent", bold=True) if a.code == "connect" else
                  p("accent", bg, bold=True))
            c.put(r, ax + 2, label, p(a.style if a.style != "accent" else "text", bg, bold=a.code == "connect"),
                  col_w - 4)
            self.zone(r, ax - 1, ax + col_w - 3, a.code)

    def draw_footer(self, y: int, w: int) -> None:
        p, c = self.palette, self.canvas
        now = time.monotonic()
        right = ""
        if self.hub.probing:
            right = f"{SPINNER[int(now * 10) % len(SPINNER)]} probing"
        elif self.hub.last_probe:
            right = f"updated {int(now - self.hub.last_probe)}s ago"
        if not self.own_listener and not self.hub.listener:
            right = f"telemetry via tray · {right}"
        c.put(y, w - text_width(right) - 2, right, p("muted"))
        room = w - text_width(right) - 4
        if self.toast and now - self.toast[2] < 5:
            msg, level, _ = self.toast
            icon = {"success": "✔", "error": "✖", "warning": "⚠"}.get(level, "ℹ")
            role = {"success": "success", "error": "danger", "warning": "warning"}.get(level, "info")
            c.put(y, 1, f" {icon} ", p("black", role, bold=True))
            c.put(y, 5, msg, p(role, bold=True), room - 5)
            return
        hov = self.hover_action()
        if hov:
            act = next((a for a in SERVER_ACTIONS if a.code == hov[0]), None)
            if act:
                c.put(y, 1, f"{act.key} {act.help}", p("accent"), room)
                return
            if hov[0] == "row":
                c.put(y, 1, "click to select · double-click to connect", p("accent"), room)
                return
        if self.searching:
            hints = [("type", "to filter"), ("Enter", "keep"), ("Esc", "clear"), ("↑↓", "move")]
        else:
            hints = [("⏎", "connect"), ("/", "search"), ("a", "add"), ("n", "scan"), ("e", "edit"),
                     ("t", "tunnel"), ("?", "help"), ("q", "quit")]
        x = 1
        for k, lbl in hints:
            if x + text_width(k) + text_width(lbl) + 3 > room:
                break
            x = c.put(y, x, k, p("accent", bold=True))
            x = c.put(y, x + 1, lbl, p("muted")) + 2

    def hover_action(self) -> tuple[str, object] | None:
        mx, my = self.mouse
        if mx < 0:
            return None
        hit = self.hit(mx, my)
        if hit and hit[0] in ("row", "fav_row"):
            return ("row", hit[1])
        return hit

    # ========================================================= main loop
    def run(self) -> None:
        self.scr.timeout(200)
        while self.running:
            self.hub.tick()
            self.draw()
            self.scr.refresh()
            ev = read_event(self.scr)
            if ev is None:
                continue
            try:
                self.handle(ev)
            except StoreError as exc:
                self.notify(str(exc), "error")
        self.hub.close()

    def handle(self, ev: Event) -> None:
        if ev.mouse:
            self.handle_mouse(ev)
            return
        k = ev.key
        if k == curses.KEY_RESIZE:
            return
        if self.searching:
            if k == ESC:
                self.searching, self.query = False, ""
            elif k == curses.KEY_ENTER:
                self.searching = False
            elif k == curses.KEY_BACKSPACE:
                self.query = self.query[:-1]
            elif k in (curses.KEY_UP, curses.KEY_DOWN):
                self.move(-1 if k == curses.KEY_UP else 1)
            elif isinstance(k, str) and k.isprintable():
                self.query += k
            return
        if k == ESC:
            self.query = ""
            return
        nav = {curses.KEY_UP: -1, "k": -1, curses.KEY_DOWN: 1, "j": 1, curses.KEY_PPAGE: -10,
               curses.KEY_NPAGE: 10, curses.KEY_HOME: -10**6, curses.KEY_END: 10**6, "G": 10**6}
        if k in nav:
            self.move(nav[k])
            return
        if isinstance(k, str) and k.isdigit() and k != "0":
            servers = self.visible()
            idx = self.scroll + int(k) - 1
            if idx < len(servers):
                self.sel_id = servers[idx].id
            return
        action = KEYMAP.get(k)
        if action:
            self.dispatch(action)

    def handle_mouse(self, ev: Event) -> None:
        assert ev.mouse is not None
        x, y, b = ev.mouse
        self.mouse = (x, y)
        if b & WHEEL_UP:
            self.move(-1)
            return
        if b & WHEEL_DOWN:
            self.move(1)
            return
        if not ev.is_click:
            return
        hit = self.hit(x, y)
        if not hit:
            return
        act, arg = hit
        if act == "row":
            now = time.monotonic()
            double = self.last_click[1] == arg and now - self.last_click[0] < 0.45
            self.last_click = (now, arg)
            self.sel_id = str(arg)
            if double:
                self.last_click = (0.0, None)
                self.dispatch("connect")
        elif act == "goto_host":
            self.sel_id, self.query, self.tag = str(arg), "", "ALL"
        elif act == "fav_row":
            self.sel_id = str(arg)
            self.dispatch("fav")
        else:
            self.dispatch(act)

    # ========================================================= actions
    def dispatch(self, action: str) -> None:
        global_actions: dict[str, Callable[[], None]] = {
            "quit": self.quit, "add": self.add_server, "scan": self.scan, "import": self.import_ssh_config,
            "export": self.export_ssh_config, "tunnels": self.list_tunnels, "theme": self.pick_theme,
            "settings": self.edit_settings, "refresh": self.refresh, "filter": self.cycle_tag,
            "filter_pick": self.pick_tag, "sort": self.cycle_sort, "search": self.start_search,
            "help": self.show_help, "refresh_pick": self.pick_interval,
            "events": self.show_events, "fleet": self.fleet_run,
        }
        if action in global_actions:
            global_actions[action]()
            return
        srv = self.selected()
        if srv is None:
            self.notify("No server selected — press a to add one", "warning")
            return
        handler = getattr(self, f"act_{action}", None)
        if handler:
            handler(srv)

    # ---- global
    def quit(self) -> None:
        self.running = False

    def refresh(self) -> None:
        if self.hub.refresh():
            self.notify("Refreshing all servers…")

    def start_search(self) -> None:
        self.searching = True

    def cycle_sort(self) -> None:
        self.sort = SORTS[(SORTS.index(self.sort) + 1) % len(SORTS)]
        self.notify(f"Sorted by {self.sort}")

    def cycle_tag(self) -> None:
        tags = ["ALL", *self.store.tags()]
        self.tag = tags[(tags.index(self.tag) + 1) % len(tags)] if self.tag in tags else "ALL"
        self.notify(f"Showing {'all servers' if self.tag == 'ALL' else 'tag ' + self.tag}")

    def pick_tag(self) -> None:
        tags = self.store.tags()
        counts = {t: sum(1 for s in self.store.servers if s.tag == t) for t in tags}
        opts = [Option("ALL", "All servers", f"{len(self.store)}")]
        opts += [Option(t, t, f"{counts[t]}") for t in tags]
        choice = ChoiceModal(self, "Filter by tag", opts, initial=(["ALL", *tags].index(self.tag)
                                                                      if self.tag in ["ALL", *tags] else 0)).run()
        if choice:
            self.tag = choice

    def pick_interval(self) -> None:
        opts = [Option(v, f"Every {v} seconds" if v else "Manual refresh only") for v in REFRESH_CHOICES]
        cur = REFRESH_CHOICES.index(self.settings.refresh_interval) if self.settings.refresh_interval in \
            REFRESH_CHOICES else 1
        choice = ChoiceModal(self, "Auto-refresh", opts, initial=cur).run()
        if choice is not None:
            self.settings.refresh_interval = int(choice)
            self.settings.save()

    def pick_theme(self) -> None:
        original = self.theme

        def preview(name: object) -> None:
            self.palette.apply(get_theme(str(name)))

        names = [t.name for t in THEMES]
        opts = [Option(t.name, t.name, "light" if not t.dark else "") for t in THEMES]
        choice = ChoiceModal(self, "Theme", opts, "Shared with the desktop app", on_highlight=preview,
                             initial=names.index(self.theme.name)).run()
        if choice:
            self.theme = get_theme(str(choice))
            self.settings.theme = self.theme.name
            self.settings.save()
            self.notify(f"Theme: {self.theme.name}", "success")
        else:
            self.theme = original
        self.palette.apply(self.theme)

    def show_help(self) -> None:
        TextModal(self, f"sshm {__version__} — keyboard reference", HELP, width=80).run()

    def edit_settings(self) -> None:
        s = self.settings
        fields = [
            Field("refresh", "Auto-refresh", f"{s.refresh_interval}s" if s.refresh_interval else "off",
                  kind="choice", choices=[f"{v}s" if v else "off" for v in REFRESH_CHOICES]),
            Field("timeout", "Probe timeout (s)", str(s.probe_timeout)),
            Field("tmux", "tmux session", s.tmux_session, "name used by 'tmux session'"),
            Field("mount", "Mount folder", s.mount_dir, "bookmarks & SSHFS mounts"),
            Field("terminal", "Terminal (GUI)", s.terminal, "auto-detect"),
            Field("legacy", "Accept 2.x agents", s.accept_legacy_agents, "unsigned telemetry", kind="bool"),
            Field("alerts", "Alerts", s.alerts_enabled, "notify on down / high load / stopped containers",
                  kind="bool"),
            Field("a_cpu", "Alert: CPU %", str(s.alert_cpu), f"sustained {s.alert_sustain_minutes} min"),
            Field("a_mem", "Alert: memory %", str(s.alert_mem)),
            Field("a_disk", "Alert: disk %", str(s.alert_disk)),
        ]

        def validate(v: dict) -> str | None:
            try:
                t = float(v["timeout"])
            except ValueError:
                return "Probe timeout must be a number"
            return None if 0.2 <= t <= 10 else "Probe timeout must be between 0.2 and 10 seconds"

        res = FormModal(self, "Settings", fields, f"Stored in {s._path}", validate=validate).run()
        if res:
            s.refresh_interval = 0 if res["refresh"] == "off" else int(res["refresh"].rstrip("s"))
            s.probe_timeout = float(res["timeout"])
            s.tmux_session = res["tmux"] or "sshm"
            s.mount_dir = res["mount"] or "~/Network_Servers"
            s.terminal = res["terminal"]
            s.accept_legacy_agents = bool(res["legacy"])
            s.alerts_enabled = bool(res["alerts"])
            for key, attr in (("a_cpu", "alert_cpu"), ("a_mem", "alert_mem"), ("a_disk", "alert_disk")):
                if str(res[key]).isdigit():
                    setattr(s, attr, max(1, min(100, int(res[key]))))
            s.save()
            self.notify("Settings saved (telemetry changes apply on restart)", "success")

    # ---- monitoring
    def availability(self, srv: Server):
        now = time.monotonic()
        hit = self._avail.get(srv.id)
        if hit is None or now - hit[0] > 15:
            try:
                hit = (now, self.hub.history.availability(srv.id))
            except Exception:  # unreadable history must never break drawing
                hit = (now, None)
            self._avail[srv.id] = hit
        return hit[1]

    def active_alerts(self) -> list:
        now = time.monotonic()
        if now - self._alerts_t > 3:
            self._alerts_t = now
            try:
                self._alerts = self.hub.history.active()
            except Exception:
                self._alerts = []
        return self._alerts

    def show_events(self) -> None:
        hist = self.hub.history
        lines: list[tuple[str, str]] = []
        active = hist.active()
        if active:
            lines.append((f"ACTIVE ALERTS ({len(active)})", "danger!"))
            for ev in active:
                lines.append((f"  ● {ev.message}", "danger" if ev.severity == "critical" else "warning"))
            lines.append(("", "text"))
        events = hist.events(300)
        lines.append(("ACTIVITY", "accent!"))
        if not events:
            lines.append(("  Nothing yet. Events are recorded while the tray or this window owns telemetry.", "muted"))
        for ev in events:
            icon = "✔" if ev.resolved else {"critical": "✖", "warning": "⚠"}.get(ev.severity, "ℹ")
            role = "success" if ev.resolved else {"critical": "danger", "warning": "warning"}.get(ev.severity, "info")
            lines.append((f"  {ev.time_label:>12}  {icon} {ev.message}", role))
        owner = "this window" if self.hub.recording else "the sshm tray / another window"
        TextModal(self, "Alerts & activity", lines, f"Recorded by {owner} · thresholds in settings (,)").run()

    def fleet_run(self) -> None:
        from sshm.core import fleet

        sel = self.selected()
        tags = self.store.tags()
        targets = ["All servers", *[f"Tag: {t}" for t in tags]] + ([f"Only {sel.name}"] if sel else [])
        default = f"Tag: {self.tag}" if self.tag != "ALL" and f"Tag: {self.tag}" in targets else "All servers"
        res = FormModal(self, "Run on many servers", [
            Field("target", "Servers", default, kind="choice", choices=targets),
            Field("command", "Command", self._last_fleet_cmd, "e.g. uptime, df -h /, sudo -n dnf -y upgrade"),
        ], "Runs in parallel over key-based SSH (no TTY — sudo needs NOPASSWD)", submit="Run",
            validate=lambda v: None if v["command"] else "Enter a command").run()
        if not res:
            return
        self._last_fleet_cmd = res["command"]
        tgt = res["target"]
        if tgt == "All servers":
            servers = self.store.servers
        elif tgt.startswith("Tag: "):
            servers = [s for s in self.store.servers if s.tag == tgt[5:]]
        else:
            servers = [sel] if sel else []
        if not servers:
            self.notify("No servers selected", "warning")
            return
        done: list = []

        def work(progress, cancel):
            def on_result(r):
                done.append(r)
                progress(len(done), len(servers))
            return fleet.run_many(servers, res["command"], on_result=on_result, cancel=cancel)

        results = ProgressModal(self, "Running", work, f"{res['command']} on {len(servers)} server(s)…").run()
        if isinstance(results, Exception) or not results:
            self.notify(f"Run failed: {results}" if results else "Cancelled", "error")
            return
        ok = sum(r.ok for r in results)
        lines: list[tuple[str, str]] = [(f"$ {res['command']}", "muted"), ("", "text")]
        for r in results:
            status = "✔" if r.ok else "✖"
            rc = "" if r.ok else (f"  exit {r.returncode}" if r.returncode is not None else "  did not run")
            lines.append((f"{status} {r.server.name}{rc}   {r.seconds:.1f}s", "success!" if r.ok else "danger!"))
            body = (r.stdout + ("" if r.ok else r.stderr)).rstrip().splitlines() or ["(no output)"]
            lines += [(f"  │ {ln}", "text") for ln in body[-200:]]
            lines.append(("", "text"))
        TextModal(self, f"Results — {ok}/{len(results)} succeeded", lines, width=100).run()

    # ---- server form (add / edit)
    def server_form(self, srv: Server | None) -> Server | None:
        base = srv or Server(name="", host="", user=os.environ.get("USER", ""),
                             tag="" if self.tag == "ALL" else self.tag)
        fields = [
            Field("name", "Name", base.name, "e.g. Homelab NAS"),
            Field("host", "Host / IP", base.host, "e.g. 192.168.1.10 or nas.lan"),
            Field("user", "User", base.user, "remote username"),
            Field("port", "Port", str(base.port)),
            Field("tag", "Tag", base.tag, "group, e.g. Homelab"),
            Field("key", "Identity file", base.key, "~/.ssh/id_ed25519 (optional)"),
            Field("jump", "Jump host", base.jump, "ProxyJump, e.g. user@bastion (optional)"),
            Field("mac", "MAC address", base.mac, "for Wake-on-LAN — use Detect"),
            Field("remote_path", "Remote folder", base.remote_path, f"default {base.home_path}"),
            Field("tmux", "Default to tmux", base.tmux, "Enter opens a tmux session", kind="bool"),
            Field("tray", "Show in tray", base.tray, "monitor in the desktop tray", kind="bool"),
            Field("notes", "Notes", base.notes, "optional"),
        ]

        def build(v: dict) -> Server:
            data = {**base.to_dict(), **v, "port": int(v["port"])}
            return Server.from_dict(data)

        def validate(v: dict) -> str | None:
            if not str(v["port"]).isdigit():
                return "Port must be a number"
            try:
                normalize_mac(v["mac"])
            except ValueError as exc:
                return str(exc)
            errors = build(v).validate()
            if errors:
                return errors[0]
            clash = self.store.by_name(v["name"])
            if clash and clash.id != base.id:
                return f"'{v['name']}' already exists"
            return None

        def detect_mac(v: dict) -> tuple[dict, str]:
            if not v["host"]:
                return v, "Enter a host first"
            mac = netscan.mac_for(v["host"])
            if mac:
                return {**v, "mac": mac}, f"Found {mac}"
            return v, "No MAC found (host must be on your local network and awake)"

        title = f"Edit — {srv.name}" if srv else "Add server"
        res = FormModal(self, title, fields, "Tab between fields · only name and host are required",
                        submit="Save" if srv else "Add server", validate=validate,
                        extra=[("⌕ Detect MAC", detect_mac)]).run()
        if res is None:
            return None
        new = build(res)
        new.id, new.commands, new.favorite, new.last_connected = base.id, base.commands, base.favorite, \
            base.last_connected
        return new

    def add_server(self) -> None:
        new = self.server_form(None)
        if new:
            self.store.add(new)
            self.sel_id = new.id
            self.hub.refresh([new])
            self.notify(f"Added {new.name}", "success")

    def act_edit(self, srv: Server) -> None:
        new = self.server_form(srv)
        if new:
            self.store.update(new)
            self.hub.refresh([new])
            self.notify(f"Saved {new.name}", "success")

    def act_delete(self, srv: Server) -> None:
        if ConfirmModal(self, "Delete server", f"Remove '{srv.name}' ({srv.endpoint}) from sshm?\n"
                        "This does not touch the remote machine.", "Delete", danger=True).run():
            self.store.remove(srv.id)
            self.notify(f"Deleted {srv.name}", "success")

    def act_fav(self, srv: Server) -> None:
        srv.favorite = not srv.favorite
        self.store.update(srv)

    # ---- running external programs
    def suspend_run(self, argv: list[str], title: str, pause: bool = False, stdin_path: str | None = None) -> int:
        curses.def_prog_mode()
        curses.endwin()
        sys.stdout.write(MOUSE_OFF + "\033[2J\033[H")
        sys.stdout.write(f"\033[1;36m━━ {title} ━━\033[0m\n\033[2m$ {sshcmd.display(argv)}\033[0m\n\n")
        sys.stdout.flush()
        rc = 0
        try:
            if stdin_path:
                with open(stdin_path) as fh:
                    rc = subprocess.call(argv, stdin=fh)
            else:
                rc = subprocess.call(argv)
        except FileNotFoundError:
            print(f"\033[1;31m✖ {argv[0]} is not installed\033[0m")
            rc, pause = 127, True
        except KeyboardInterrupt:
            rc = 130
        sys.stdout.write(MOUSE_OFF)
        if pause or rc not in (0, 130):
            with contextlib.suppress(EOFError, KeyboardInterrupt):
                input(f"\n\033[2m[exit {rc}] Press Enter to return to sshm…\033[0m")
        curses.reset_prog_mode()
        enable_mouse()
        curses.curs_set(0)
        curses.flushinp()
        self.scr.clear()
        return rc

    def act_connect(self, srv: Server, tmux: bool | None = None) -> None:
        argv = sshcmd.ssh_command(srv, tmux=tmux, tmux_session=self.settings.tmux_session)
        self.store.mark_connected(srv.id)
        self.suspend_run(argv, f"{srv.name} · {srv.endpoint}")
        self.hub.refresh([srv])

    def draw_container_section(self, row: int, ix: int, iw: int, bottom: int, link) -> int:
        from sshm.tui.docker import state_dot

        p, c = self.palette, self.canvas
        ctr, host = link.container, link.host
        row += 1
        if row >= bottom - 1:
            return row
        c.section(row, ix, iw, "CONTAINER", p("accent", bold=True), p("border"))
        c.put(row, ix + iw - 13, " D  actions… ", p("muted"))
        self.zone(row, ix + iw - 13, ix + iw - 1, "docker")
        row += 1

        def line(label: str, value: str, role: str = "text", bold: bool = False) -> None:
            nonlocal row
            if row < bottom:
                c.put(row, ix, f"{label:<9}", p("muted"))
                c.put(row, ix + 10, value, p(role, bold=bold), iw - 10)
                row += 1

        dot, role = state_dot(ctr)
        line("Name", f"{ctr.name}   ({ctr.short_id})", "text", True)
        line("State", f"{dot} {ctr.status or ctr.state}", role)
        line("Image", ctr.image_short)
        line("Host", f"{host.name} · {ctr.runtime}", "info")
        self.zone(row - 1, ix + 10, ix + 10 + len(host.name), "goto_host", host.id)
        line("Ports", ctr.ports_label, "muted")
        if ctr.project:
            line("Compose", ctr.project, "muted")
        if ctr.running and row < bottom:
            meter_w = max(10, min(30, iw - 34))
            for label, pct, text in (("CPU", ctr.cpu, f"{ctr.cpu:.1f}%" if ctr.cpu is not None else "--"),
                                     ("Memory", ctr.mem_pct, ctr.mem_label)):
                if row >= bottom:
                    break
                c.put(row, ix, f"{label:<9}", p("muted"))
                filled, empty = bar(min(100.0, pct) if pct is not None else None, meter_w)
                level = pct or 0
                end = c.put(row, ix + 10, filled, p("success" if level < 70 else "warning" if level < 90 else "danger"))
                c.put(row, end, empty, p("border"))
                c.put(row, ix + 11 + meter_w, text, p("text", bold=True))
                row += 1
        for pub_host, pub_port, mapping in self.hub.service_ports(link):
            if mapping.service == "Minecraft" and row < bottom:
                mc = self.hub.minecraft_status(pub_host, pub_port)
                if mc is None:
                    line("Minecraft", "checking…", "muted")
                elif isinstance(mc, str):
                    line("Minecraft", f"not answering ({mc})", "warning")
                else:
                    line("Minecraft", f"{mc.summary} · {mc.latency_ms:.0f} ms", "success", True)
                    if mc.motd:
                        line("", mc.motd, "muted")
                    if mc.players:
                        line("Players", ", ".join(mc.players), "text")
            elif mapping.is_web and row < bottom:
                scheme = "https" if mapping.container_port in (443, 8443, 9443) else "http"
                line(mapping.service or "Web", f"{scheme}://{pub_host}:{pub_port}", "info")
        return row

    def draw_host_containers(self, row: int, ix: int, iw: int, bottom: int, srv: Server, hc) -> int:
        from sshm.tui.docker import state_dot

        p, c = self.palette, self.canvas
        running = sum(1 for x in hc.containers if x.running)
        c.section(row, ix, iw, f"CONTAINERS {running}/{len(hc.containers)}", p("accent", bold=True), p("border"))
        c.put(row, ix + iw - 19, " D  all containers ", p("muted"))
        self.zone(row, ix + iw - 19, ix + iw - 1, "docker")
        row += 1
        shown = hc.containers[: max(1, min(6, bottom - row - 4))]
        for ctr in shown:
            if row >= bottom:
                break
            dot, role = state_dot(ctr)
            c.put(row, ix, dot, p(role, bold=True))
            c.put(row, ix + 2, ctr.name, p("text", bold=True), 22)
            cpu = f"{ctr.cpu:5.1f}%" if ctr.running and ctr.cpu is not None else ("" if ctr.running else ctr.state)
            c.put(row, ix + 25, cpu, p("muted" if not ctr.running else "text"))
            c.put(row, ix + 33, ctr.mem_label.split(" / ")[0] if ctr.running else "", p("muted"))
            c.put(row, ix + 42, ctr.image_short, p("muted"), iw - 42)
            row += 1
        if len(hc.containers) > len(shown) and row < bottom:
            c.put(row, ix + 2, f"… {len(hc.containers) - len(shown)} more (press D)", p("muted"))
            row += 1
        return row

    def act_docker(self, srv: Server) -> None:
        from sshm.tui.docker import container_menu, host_menu

        link = self.links.get(srv.id) or self.hub.links().get(srv.id)
        if link is not None:
            container_menu(self, link.host, link.container, linked_server=srv)
        else:
            host_menu(self, srv)

    def act_procs(self, srv: Server) -> None:
        from sshm.tui.procview import ProcessModal

        ProcessModal(self, srv).run()

    def act_tmux(self, srv: Server) -> None:
        self.act_connect(srv, tmux=True)

    def act_sftp(self, srv: Server) -> None:
        self.suspend_run(sshcmd.sftp_command(srv), f"SFTP · {srv.name}")

    def act_key(self, srv: Server) -> None:
        self.suspend_run(sshcmd.copy_id_command(srv), f"Push SSH key · {srv.name}", pause=True)

    def act_copy(self, srv: Server) -> None:
        cmd = sshcmd.display(sshcmd.ssh_command(srv, tmux_session=self.settings.tmux_session))
        how = clipboard.copy(cmd)
        self.notify(f"Copied via {how}: {cmd}" if how else cmd, "success" if how else "info")

    def act_files(self, srv: Server) -> None:
        if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            self.notify("No graphical session — try s (SFTP) or M (SSHFS) instead", "warning")
            return
        if mounts.open_in_file_manager(srv):
            self.notify(f"Opening {srv.sftp_url}", "success")
        else:
            self.notify("xdg-open not found", "error")

    def act_bookmark(self, srv: Server) -> None:
        state = mounts.toggle_bookmark(srv, self.settings)
        self._cache.pop(srv.id, None)
        self.notify(f"{'Bookmarked' if state else 'Removed bookmark for'} {srv.name}", "success")

    def act_sshfs(self, srv: Server) -> None:
        mounted = mounts.is_sshfs_mounted(srv, self.settings)
        fn = mounts.sshfs_unmount if mounted else mounts.sshfs_mount
        res = ProgressModal(self, "SSHFS", lambda _p, _c: fn(srv, self.settings),
                            "Unmounting…" if mounted else f"Mounting {srv.target}:{srv.home_path}…").run()
        self._cache.pop(srv.id, None)
        if isinstance(res, Exception):
            self.notify(f"SSHFS failed: {res}", "error")
        elif res:
            ok, msg = res
            self.notify(msg + ("" if ok or mounted else " (SSHFS needs key-based login — try k)"),
                        "success" if ok else "error")

    def act_wake(self, srv: Server) -> None:
        if not srv.mac:
            self.notify("No MAC address saved — edit the server (e) and use Detect MAC", "warning")
            return
        try:
            wol.wake(srv.mac)
        except (OSError, ValueError) as exc:
            self.notify(f"Wake-on-LAN failed: {exc}", "error")
            return
        self.notify(f"Magic packet sent to {srv.mac}", "success")

    def act_tunnel(self, srv: Server) -> None:
        kinds = {"Local  (-L)": "L", "Remote (-R)": "R", "SOCKS  (-D)": "D"}
        fields = [
            Field("kind", "Type", "Local  (-L)", kind="choice", choices=list(kinds)),
            Field("spec", "Forward", "8080:localhost:80", "L/R: port:host:port · D: port"),
        ]

        def validate(v: dict) -> str | None:
            try:
                TunnelSpec.parse(kinds[v["kind"]], v["spec"])
            except TunnelError as exc:
                return str(exc)
            return None

        res = FormModal(self, f"Port forward — {srv.name}", fields,
                        "Runs in the background with key auth · T lists active tunnels",
                        submit="Start tunnel", validate=validate).run()
        if not res:
            return
        spec = TunnelSpec.parse(kinds[res["kind"]], res["spec"])

        def start(_p: object, _c: object) -> object:
            try:
                return self.hub.tunnels.start(srv, spec)
            except TunnelError as exc:
                return exc

        out = ProgressModal(self, "Starting tunnel", start, spec.describe(srv.name)).run()
        if isinstance(out, Exception):
            self.notify(f"Tunnel failed: {out}", "error")
        elif out is not None:
            self.notify(f"Tunnel up: {spec.describe(srv.name)}", "success")

    def list_tunnels(self) -> None:
        tunnels = self.hub.tunnels.list()
        if not tunnels:
            self.notify("No active tunnels — press t on a server to start one")
            return
        opts = [Option(t.id, f"-{t.kind} {t.spec}", f"{t.server_name} · pid {t.pid}") for t in tunnels]
        opts.append(Option("__all__", "Stop all tunnels", "", style="danger"))
        choice = ChoiceModal(self, "Active tunnels", opts, "Choose a tunnel to stop it").run()
        if choice == "__all__":
            self.notify(f"Stopped {self.hub.tunnels.stop_all()} tunnel(s)", "success")
        elif choice:
            self.hub.tunnels.stop(str(choice))
            self.notify("Tunnel stopped", "success")

    def act_agent(self, srv: Server) -> None:
        st = self.hub.status_of(srv)
        active = bool(st and st.telemetry)
        opts = [
            Option("deploy", "Update agent" if active else "Deploy agent", "install as a systemd user service",
                   "1", "success"),
            Option("status", "Show agent status", "systemctl --user status", "2"),
            Option("remove", "Remove agent", "stop and uninstall", "3", "danger"),
        ]
        hub_ip = agent.hub_address_for(srv.host)
        choice = ChoiceModal(self, f"Telemetry agent — {srv.name}", opts,
                             f"Reports to {hub_ip}:{self.settings.telemetry_port}/udp · signed with your hub key").run()
        if choice == "deploy":
            path = agent.write_script(agent.build_installer(srv, self.settings, hub=hub_ip))
            try:
                rc = self.suspend_run(agent.remote_script_argv(srv), f"Deploying agent to {srv.name}", pause=True,
                                      stdin_path=path)
            finally:
                os.unlink(path)
            if rc == 0:
                self.notify("Agent deployed — stats appear within a few seconds "
                            f"(UDP {self.settings.telemetry_port} must be open on this PC)", "success")
        elif choice == "status":
            self.suspend_run(sshcmd.ssh_command(srv, remote_command=agent.STATUS_COMMAND),
                             f"Agent status · {srv.name}", pause=True)
        elif choice == "remove":
            path = agent.write_script(agent.build_remover())
            try:
                self.suspend_run(agent.remote_script_argv(srv), f"Removing agent from {srv.name}", pause=True,
                                 stdin_path=path)
            finally:
                os.unlink(path)

    def act_run(self, srv: Server) -> None:
        opts = [Option(i, c.label, c.command, str(i + 1) if i < 9 else "") for i, c in enumerate(srv.commands)]
        opts.append(Option("add", "＋ Add a command…", "saved per server", "+", "success"))
        if srv.commands:
            opts.append(Option("del", "✖ Delete a command…", "", "-", "danger"))
        choice = ChoiceModal(self, f"Commands — {srv.name}", opts, "Runs over SSH with a TTY").run()
        if choice is None:
            return
        if choice == "add":
            res = FormModal(self, "New command", [
                Field("label", "Label", "", "e.g. System update"),
                Field("command", "Command", "", "e.g. sudo dnf upgrade -y"),
            ], validate=lambda v: None if v["label"] and v["command"] else "Both fields are required").run()
            if res:
                srv.commands.append(CustomCommand(res["label"], res["command"]))
                self.store.update(srv)
                self.notify(f"Saved command '{res['label']}'", "success")
        elif choice == "del":
            d = ChoiceModal(self, "Delete which command?",
                            [Option(i, c.label, c.command) for i, c in enumerate(srv.commands)]).run()
            if d is not None:
                removed = srv.commands.pop(int(d))
                self.store.update(srv)
                self.notify(f"Deleted '{removed.label}'", "success")
        else:
            cmd = srv.commands[int(choice)]
            self.suspend_run(sshcmd.ssh_command(srv, remote_command=cmd.command), f"{cmd.label} · {srv.name}",
                             pause=True)

    # ---- discovery
    def scan(self) -> None:
        fields = [
            Field("net", "Network", netscan.local_network(), "CIDR, a.b.c or a.b.c.d-e"),
            Field("ports", "Ports", netscan.DEFAULT_PORTS),
            Field("user", "Default user", os.environ.get("USER", "")),
            Field("tag", "Tag new servers", "LAN"),
        ]

        def validate(v: dict) -> str | None:
            try:
                netscan.parse_targets(v["net"])
                netscan.parse_ports(v["ports"])
            except ValueError as exc:
                return str(exc)
            return None

        res = FormModal(self, "Scan network for SSH servers", fields, "Only hosts answering with an SSH banner "
                        "are listed", submit="Scan", validate=validate).run()
        if not res:
            return
        targets, ports = netscan.parse_targets(res["net"]), netscan.parse_ports(res["ports"])
        found = ProgressModal(
            self, "Scanning", lambda prog, cancel: netscan.scan(targets, ports, progress=prog, cancel=cancel),
            f"Probing {len(targets)} hosts × {len(ports)} port(s)…").run()
        if isinstance(found, Exception):
            self.notify(f"Scan failed: {found}", "error")
            return
        if not found:
            self.notify("No SSH servers found", "warning")
            return
        existing = {(s.host, s.port): s for s in self.store.servers}
        items = []
        for d in found:
            saved = existing.get((d.ip, d.port))
            label = f"{d.ip}:{d.port}  {d.hostname or ''}".strip()
            desc = " · ".join(filter(None, [d.banner, d.mac, f"saved as {saved.name}" if saved else "new"]))
            items.append((label, desc, saved is None))
        picked = ChecklistModal(self, f"Found {len(found)} SSH server(s)", items,
                                "Selected hosts are added; existing ones get a missing MAC filled in").run()
        if not picked:
            return
        added = updated = 0
        for i in picked:
            d = found[i]
            saved = existing.get((d.ip, d.port))
            if saved:
                if d.mac and not saved.mac:
                    saved.mac = d.mac
                    self.store.update(saved)
                    updated += 1
                continue
            srv = Server(name=self.store.unique_name(d.suggested_name), host=d.ip, port=d.port,
                         user=res["user"], tag=res["tag"], mac=d.mac)
            self.store.add(srv)
            added += 1
        self.hub.refresh()
        self.notify(f"Added {added} server(s), updated {updated} MAC address(es)", "success")

    def import_ssh_config(self) -> None:
        candidates = sshconfig.import_servers(self.store.servers)
        if not candidates:
            self.notify("Nothing new to import from ~/.ssh/config", "info")
            return
        items = [(s.name, s.endpoint + (f" via {s.jump}" if s.jump else ""), True) for s in candidates]
        picked = ChecklistModal(self, "Import from ~/.ssh/config", items, f"{len(items)} host(s) not yet in sshm",
                                submit="Import").run()
        if picked:
            for i in picked:
                srv = candidates[i]
                srv.name = self.store.unique_name(srv.name)
                self.store.add(srv)
            self.hub.refresh()
            self.notify(f"Imported {len(picked)} host(s)", "success")

    def export_ssh_config(self) -> None:
        text = sshconfig.export(self.visible())
        how = clipboard.copy(text)
        lines = [(ln, "text") for ln in text.splitlines()]
        TextModal(self, "ssh_config export", lines,
                  f"Copied to clipboard via {how}" if how else "Select and copy from your terminal").run()


def status_dot(st: HostStatus | None, probing: bool) -> tuple[str, str]:
    if st is None:
        return (SPINNER[int(time.monotonic() * 10) % len(SPINNER)] if probing else "·"), "muted"
    if st.online:
        return "●", "success"
    if st.state == "degraded":
        return "◐", "warning"
    return "○", "danger"


def state_label(st: HostStatus | None, probing: bool) -> tuple[str, str]:
    if st is None:
        return ("checking…" if probing else "unknown"), "muted"
    if st.online:
        return "● Online", "success"
    if st.state == "degraded":
        return "◐ SSH down", "warning"
    return "○ Offline", "danger"


def enable_mouse() -> None:
    curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
    curses.mouseinterval(0)
    sys.stdout.write(MOUSE_ON)
    sys.stdout.flush()


def _main(scr: curses.window) -> None:
    curses.curs_set(0)
    with contextlib.suppress(curses.error):
        curses.start_color()
        curses.use_default_colors()
    scr.keypad(True)
    enable_mouse()
    TUI(scr).run()


def run() -> int:
    locale.setlocale(locale.LC_ALL, "")
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("sshm: the terminal UI needs an interactive terminal (try 'sshm ls')", file=sys.stderr)
        return 2
    os.environ["SSHM_TUI"] = "1"
    try:
        curses.wrapper(_main)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write(MOUSE_OFF)
        sys.stdout.flush()
    return 0
