"""Container widgets: the card shown for a server that is a container, and a host's Containers tab."""

from __future__ import annotations

import html

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sshm.core.containers import Container, ContainerLink, HostContainers
from sshm.core.models import Server
from sshm.gui.style import mix


def _cap(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setObjectName("Caption")
    return lbl


def _val(selectable: bool = True) -> QLabel:
    lbl = QLabel("—")
    lbl.setObjectName("Value")
    lbl.setWordWrap(True)
    if selectable:
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lbl


class ContainerCard(QFrame):
    """Details + controls for a saved server that turned out to be a container."""

    def __init__(self, window) -> None:
        super().__init__()
        self.window = window
        self.link: ContainerLink | None = None
        self.setObjectName("Card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 14, 20, 16)
        lay.setSpacing(10)

        head = QHBoxLayout()
        head.addWidget(_cap("Container"))
        head.addStretch()
        self.host_btn = QPushButton("")
        self.host_btn.setObjectName("Flat")
        self.host_btn.setToolTip("Show the docker host")
        self.host_btn.clicked.connect(lambda: self.link and self.window.select_server(self.link.host.id))
        head.addWidget(self.host_btn)
        lay.addLayout(head)

        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(6)
        self.values: dict[str, QLabel] = {}
        for i, (label, key) in enumerate([("Name", "name"), ("Image", "image"), ("Status", "status"),
                                          ("Ports", "ports"), ("Compose project", "project"), ("Runtime", "runtime")]):
            r, c = divmod(i, 2)
            grid.addWidget(_cap(label), r * 2, c)
            self.values[key] = _val()
            grid.addWidget(self.values[key], r * 2 + 1, c)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)

        self.services = QLabel("")
        self.services.setWordWrap(True)
        self.services.setOpenExternalLinks(True)
        self.services.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.services)

        row = QHBoxLayout()
        self.restart_btn = QPushButton("Restart")
        self.restart_btn.clicked.connect(lambda: self._act("restart"))
        self.startstop_btn = QPushButton("Stop")
        self.startstop_btn.clicked.connect(self._start_stop)
        logs = QPushButton("Logs")
        logs.clicked.connect(lambda: self.link and self.window.ctrl.container_logs(self.link.host, self.link.container))
        shell = QPushButton("Shell")
        shell.setToolTip("docker exec into the container from its host (works even if its SSH server is down)")
        shell.clicked.connect(lambda: self.link and self.window.ctrl.container_shell(self.link.host,
                                                                                     self.link.container))
        for b in (self.restart_btn, self.startstop_btn, logs, shell):
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        self.hide()

    def _act(self, action: str) -> None:
        if self.link:
            self.window.ctrl.container_action(self.link.host, self.link.container, action)

    def _start_stop(self) -> None:
        if not self.link:
            return
        if self.link.container.running:
            self.window._confirm_stop(self.link.host, self.link.container)
        else:
            self._act("start")

    def show_link(self, link: ContainerLink | None, hub, theme) -> None:
        self.link = link
        self.setVisible(link is not None)
        if link is None:
            return
        c, host = link.container, link.host
        v = self.values
        v["name"].setText(f"{c.name}  ·  {c.short_id}")
        v["image"].setText(c.image_short)
        color = theme.success if c.running and c.health != "unhealthy" else theme.warning if c.running else theme.danger
        v["status"].setText(c.status or c.state)
        v["status"].setStyleSheet(f"color: {color};")
        v["ports"].setText(c.ports_label)
        v["project"].setText(c.project or "—")
        v["runtime"].setText(f"{c.runtime} · data via {'agent (live)' if c.source == 'agent' else 'SSH'}")
        self.host_btn.setText(f"on {host.name}  →")
        self.restart_btn.setEnabled(c.running)
        self.startstop_btn.setText("Stop" if c.running else "Start")
        self.startstop_btn.setObjectName("Danger" if c.running else "Primary")
        self.startstop_btn.style().unpolish(self.startstop_btn)
        self.startstop_btn.style().polish(self.startstop_btn)

        parts = []
        for pub_host, pub_port, mapping in hub.service_ports(link):
            if mapping.service == "Minecraft":
                mc = hub.minecraft_status(pub_host, pub_port)
                if mc is None:
                    parts.append("<b>Minecraft</b> — checking…")
                elif isinstance(mc, str):
                    parts.append(f"<b>Minecraft</b> — <span style='color:{theme.warning}'>not answering</span>")
                else:
                    players = f"<br><span style='color:{theme.muted}'>{html.escape(', '.join(mc.players))}</span>" \
                        if mc.players else ""
                    motd = f" — <i>{html.escape(mc.motd)}</i>" if mc.motd else ""
                    parts.append(f"<b>Minecraft</b> <span style='color:{theme.success}'>{mc.online}/{mc.max_players} "
                                 f"players</span> · {html.escape(mc.version)}{motd}{players}")
            elif mapping.is_web:
                scheme = "https" if mapping.container_port in (443, 8443, 9443) else "http"
                url = f"{scheme}://{pub_host}:{pub_port}"
                link_html = f"<a style='color:{theme.accent}' href='{url}'>{url}</a>"
                parts.append(f"<b>{mapping.service or 'Web'}</b> {link_html}")
        self.services.setVisible(bool(parts))
        self.services.setText("<br>".join(parts))


class ContainersTab(QWidget):
    """All containers on a docker host, with actions on the selected one."""

    COLS = ("", "Name", "Image", "Status", "CPU", "Memory", "Ports")
    WIDTHS = (26, 170, 220, 170, 64, 90)

    def __init__(self, window) -> None:
        super().__init__()
        self.window = window
        self.host: Server | None = None
        self.hc: HostContainers | None = None
        self._ids: list[str] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        self.info = QLabel("")
        self.info.setObjectName("Muted")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)

        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(list(self.COLS))
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for i, w in enumerate(self.WIDTHS):
            hdr.resizeSection(i, w)
        hdr.setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._sync_buttons)
        self.table.itemDoubleClicked.connect(lambda _i: self._go_to_saved())
        lay.addWidget(self.table, 1)

        row = QHBoxLayout()
        self.btns: dict[str, QPushButton] = {}
        for key, label in (("restart", "Restart"), ("stop", "Stop"), ("start", "Start"), ("logs", "Logs"),
                           ("shell", "Shell"), ("stats", "Live stats")):
            b = QPushButton(label)
            if key == "stop":
                b.setObjectName("Danger")
            b.clicked.connect(lambda _c=False, k=key: self._action(k))
            self.btns[key] = b
            row.addWidget(b)
        row.addStretch()
        self.rescan = QPushButton("Rescan")
        self.rescan.clicked.connect(lambda: self.host and self.window.ctrl.detect_containers(self.host))
        row.addWidget(self.rescan)
        lay.addLayout(row)
        self._sync_buttons()

    def selected(self) -> Container | None:
        row = self.table.currentRow()
        if self.hc is None or not 0 <= row < len(self.hc.containers):
            return None
        return self.hc.containers[row]

    def _sync_buttons(self) -> None:
        c = self.selected()
        for key, b in self.btns.items():
            if key in ("restart", "stop"):
                b.setEnabled(bool(c and c.running))
            elif key == "start":
                b.setEnabled(bool(c and not c.running))
            elif key == "stats":
                b.setEnabled(self.host is not None)
            else:
                b.setEnabled(c is not None and (c.running or key == "logs"))

    def _action(self, key: str) -> None:
        c, host, ctrl = self.selected(), self.host, self.window.ctrl
        if host is None:
            return
        if key == "stats":
            ctrl.container_stats(host, c)
        elif c is None:
            return
        elif key == "logs":
            ctrl.container_logs(host, c)
        elif key == "shell":
            ctrl.container_shell(host, c)
        elif key == "stop":
            self.window._confirm_stop(host, c)
        else:
            ctrl.container_action(host, c, key)

    def _go_to_saved(self) -> None:
        c = self.selected()
        if c is None or self.host is None:
            return
        for sid, link in self.window.ctrl.hub.links().items():
            if link.host.id == self.host.id and link.container.id == c.id:
                self.window.select_server(sid)
                return

    def show_host(self, host: Server, hc: HostContainers | None, links: dict, hub) -> None:
        self.host, self.hc = host, hc
        if hc is None:
            self.table.setRowCount(0)
            self._ids = []
            return
        theme = self.window.theme
        saved = {(lk.host.id, lk.container.id): hub.store.get(sid) for sid, lk in links.items()}
        if hc.error and not hc.containers:
            self.info.setText(f"⚠ {hc.error}")
        else:
            age = "live from the agent" if hc.source == "agent" else "via SSH (refreshes every minute)"
            self.info.setText(f"{sum(c.running for c in hc.containers)} of {len(hc.containers)} running · "
                              f"{hc.runtime} · {age} · double-click a container saved in sshm to open it")
        ids = [c.id for c in hc.containers]
        if ids != self._ids:  # structure changed: rebuild rows once
            keep = self.selected().id if self.selected() else None
            self._ids = ids
            self.table.setRowCount(len(ids))
            for r in range(len(ids)):
                for col in range(len(self.COLS)):
                    self.table.setItem(r, col, QTableWidgetItem(""))
            if keep in ids:
                self.table.selectRow(ids.index(keep))
        for r, c in enumerate(hc.containers):  # cheap in-place text updates
            dot_color = theme.success if c.running else theme.warning if c.state == "paused" else theme.danger
            mark = saved.get((host.id, c.id))
            cells = ["●" if c.running else "○", c.name + (f"  (⬢ {mark.name})" if mark else ""), c.image_short,
                     c.status or c.state, f"{c.cpu:.1f}%" if c.running and c.cpu is not None else "",
                     c.mem_label.split(" / ")[0] if c.running and c.mem else "", c.ports_label if c.ports else ""]
            for col, text in enumerate(cells):
                item = self.table.item(r, col)
                if item is not None and item.text() != text:
                    item.setText(text)
            dot = self.table.item(r, 0)
            if dot is not None:
                dot.setForeground(QColor(dot_color))
                dot.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            name = self.table.item(r, 1)
            if name is not None and mark is not None:
                name.setForeground(QColor(mix(theme.text, theme.info, 0.6)))
        self._sync_buttons()
