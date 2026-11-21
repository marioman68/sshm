"""System tray icon with per-server submenus and up/down notifications."""

from __future__ import annotations

import time

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from sshm import APP_TITLE
from sshm.core.models import Server
from sshm.core.themes import get_theme
from sshm.gui.controller import Controller
from sshm.gui.style import app_icon, dot_icon, themed_icon


class Tray(QSystemTrayIcon):
    def __init__(self, ctrl: Controller, show_window, quit_app, open_processes=None, open_activity=None) -> None:
        super().__init__()
        self.open_processes = open_processes
        self.open_activity = open_activity
        self.ctrl = ctrl
        self.show_window = show_window
        self.quit_app = quit_app
        self._menu_open_until = 0.0
        self._last_state = ""
        self.menu = QMenu()
        self.menu.aboutToShow.connect(self._rebuild)
        self.menu.aboutToHide.connect(lambda: setattr(self, "_menu_open_until", 0.0))
        self.setContextMenu(self.menu)
        self.activated.connect(self._activated)
        ctrl.statuses_changed.connect(self._update_icon)
        ctrl.events_raised.connect(self._notify_events)
        ctrl.settings_changed.connect(lambda: self._update_icon(force=True))
        self._update_icon(force=True)

    def tracked(self) -> list[Server]:
        return [s for s in self.ctrl.servers if s.tray]

    # --------------------------------------------------------------- icon
    def _update_icon(self, force: bool = False) -> None:
        servers = self.tracked()
        statuses = [self.ctrl.status(s) for s in servers]
        known = [st for st in statuses if st is not None]
        online = sum(1 for st in known if st.online)
        if not servers or not known:
            state = "none"
        elif online == len(servers):
            state = "ok"
        elif online == 0:
            state = "down"
        else:
            state = "partial"
        accent = get_theme(self.ctrl.settings.theme).accent
        key = f"{state}:{accent}"
        if force or key != self._last_state:
            self._last_state = key
            self.setIcon(app_icon(state, accent))
        lines = [f"{APP_TITLE} — {online}/{len(servers)} online"]
        for s, st in zip(servers, statuses, strict=True):
            mark = "●" if st and st.online else "○"
            extra = ""
            if st and st.telemetry and st.telemetry.cpu is not None:
                extra = f"  cpu {st.telemetry.cpu:.0f}%"
            lines.append(f"{mark} {s.name}{extra}")
        self.setToolTip("\n".join(lines[:16]))

    def _notify_events(self, events: list) -> None:
        if not self.ctrl.settings.notifications or not events:
            return
        icons = {"critical": QSystemTrayIcon.MessageIcon.Critical, "warning": QSystemTrayIcon.MessageIcon.Warning}
        if len(events) > 3:  # e.g. the network dropped: one summary instead of a notification storm
            worst = "critical" if any(e.severity == "critical" for e in events) else "warning"
            self.showMessage(f"{len(events)} sshm alerts", "\n".join(e.message for e in events[:5]),
                             icons.get(worst, QSystemTrayIcon.MessageIcon.Information), 10000)
            return
        for ev in events:
            icon = QSystemTrayIcon.MessageIcon.Information if ev.resolved else icons.get(
                ev.severity, QSystemTrayIcon.MessageIcon.Information)
            title = "Resolved" if ev.resolved else {"critical": "Alert", "warning": "Warning"}.get(ev.severity, "sshm")
            self.showMessage(title, ev.message, icon, 6000 if ev.resolved else 10000)

    def _activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_window()

    # --------------------------------------------------------------- menu
    def _rebuild(self) -> None:
        self._menu_open_until = time.monotonic() + 60
        m = self.menu
        m.clear()
        t = get_theme(self.ctrl.settings.theme)
        head = m.addAction(app_icon("ok", t.accent), "Open sshm")
        head.triggered.connect(self.show_window)
        f = head.font()
        f.setBold(True)
        head.setFont(f)
        m.addAction(themed_icon("utilities-terminal-symbolic", "utilities-terminal"), "Open terminal UI",
                    self.ctrl.launch_tui)
        m.addSeparator()

        servers = self.tracked()
        if not servers:
            act = m.addAction("No servers pinned to the tray")
            act.setEnabled(False)
        for srv in servers:
            st = self.ctrl.status(srv)
            if st is None:
                icon, label = dot_icon(t.muted, hollow=True), "…"
            elif st.online:
                icon = dot_icon(t.success)
                tel = st.telemetry
                label = f"{tel.cpu:.0f}% cpu" if tel and tel.cpu is not None else st.latency_label
            else:
                icon, label = dot_icon(t.danger, hollow=True), "offline"
            sub = m.addMenu(icon, f"{srv.name}    {label}")
            self._server_menu(sub, srv)

        m.addSeparator()
        try:
            recent = self.ctrl.hub.history.events(5)
            active = self.ctrl.hub.history.active()
        except Exception:
            recent, active = [], []
        alerts = m.addMenu(f"Alerts ({len(active)} active)" if active else "Recent activity")
        if not recent:
            none = alerts.addAction("Nothing recorded yet")
            none.setEnabled(False)
        for ev in recent:
            icon = "✔" if ev.resolved else {"critical": "✖", "warning": "⚠"}.get(ev.severity, "ℹ")
            act = alerts.addAction(f"{ev.time_label}  {icon} {ev.message}")
            act.setEnabled(False)
        if self.open_activity:
            alerts.addSeparator()
            alerts.addAction("Open activity log…", self.open_activity)
        refresh = QAction(themed_icon("view-refresh-symbolic", "view-refresh"), "Refresh now", m)
        refresh.triggered.connect(lambda: self.ctrl.refresh())
        m.addAction(refresh)
        m.addAction(themed_icon("application-exit-symbolic", "application-exit"), "Quit sshm", self.quit_app)

    def _server_menu(self, sub: QMenu, srv: Server) -> None:
        st = self.ctrl.status(srv)
        info = sub.addAction(srv.endpoint)
        info.setEnabled(False)
        if st and st.telemetry:
            tel = st.telemetry
            line = sub.addAction(f"CPU {tel.cpu or 0:.0f}%  ·  RAM {tel.mem_label}  ·  up {tel.uptime_label}")
            line.setEnabled(False)
            for tp in tel.top("cpu", 3):
                row = sub.addAction(f"    {tp.cpu:5.1f}%  {tp.name}  ({tp.rss_label})")
                row.setEnabled(False)
        sub.addSeparator()
        sub.addAction("Connect", lambda: self.ctrl.connect(srv))
        sub.addAction("Connect in tmux", lambda: self.ctrl.connect(srv, tmux=True))
        sub.addAction("Open files", lambda: self.ctrl.open_files(srv))
        sub.addAction("SFTP shell", lambda: self.ctrl.sftp(srv))
        if self.open_processes:
            sub.addAction("Processes…", lambda: self.open_processes(srv))
        link = self.ctrl.hub.links().get(srv.id)
        if link is not None:
            ctr, host = link.container, link.host
            sub.addSeparator()
            head = sub.addAction(f"⬢ {ctr.name} on {host.name} — {ctr.status or ctr.state}")
            head.setEnabled(False)
            for pub_host, pub_port, mapping in self.ctrl.hub.service_ports(link):
                if mapping.service == "Minecraft":
                    mc = self.ctrl.hub.minecraft_status(pub_host, pub_port)
                    if mc is not None and not isinstance(mc, str):
                        line = sub.addAction(f"    Minecraft: {mc.summary}")
                        line.setEnabled(False)
            if ctr.running:
                sub.addAction("Restart container", lambda: self.ctrl.container_action(host, ctr, "restart"))
            else:
                sub.addAction("Start container", lambda: self.ctrl.container_action(host, ctr, "start"))
            sub.addAction("Container logs", lambda: self.ctrl.container_logs(host, ctr))
        if srv.commands:
            sub.addSeparator()
            for c in srv.commands:
                sub.addAction(f"▶ {c.label}", lambda _=False, c=c: self.ctrl.run_command(srv, c.label, c.command))
        if srv.mac:
            sub.addSeparator()
            sub.addAction(f"Wake-on-LAN ({srv.mac})", lambda: self.ctrl.wake(srv))
