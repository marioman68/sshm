"""Main desktop window: searchable server sidebar + rich detail view."""

from __future__ import annotations

import html
import time

from PyQt6.QtCore import QSettings, QSize, Qt, QTimer
from PyQt6.QtGui import QAction, QCloseEvent, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from sshm import APP_TITLE, __version__
from sshm.core import agent, mounts, procs, sshconfig
from sshm.core.models import Server, fuzzy_score
from sshm.core.themes import get_theme
from sshm.gui import autostart
from sshm.gui.containers import ContainerCard, ContainersTab
from sshm.gui.controller import Controller
from sshm.gui.dialogs import (
    CommandDialog,
    ImportDialog,
    ScanDialog,
    ServerDialog,
    SettingsDialog,
    TunnelDialog,
    show_export,
)
from sshm.gui.style import app_icon, apply_palette, stylesheet, themed_icon
from sshm.gui.widgets import (
    ROLE_ID,
    ROLE_LINK,
    ROLE_SERVER,
    ROLE_STATUS,
    MetricCard,
    Pill,
    ServerDelegate,
    state_color,
)

SORTS = [("Name", "name"), ("Status", "status"), ("Latency", "latency"), ("Recently used", "recent")]


def _label(text: str = "", name: str = "", selectable: bool = False) -> QLabel:
    lbl = QLabel(text)
    if name:
        lbl.setObjectName(name)
    if selectable:
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lbl


class MainWindow(QMainWindow):
    def __init__(self, ctrl: Controller) -> None:
        super().__init__()
        self.ctrl = ctrl
        self.theme = get_theme(ctrl.settings.theme)
        self.selected_id: str | None = None
        self.quitting = False
        self.tray_available = False
        self._cmd_sig: tuple = ()
        self._proc_windows: dict = {}
        self._hosts: dict = {}
        self._links: dict = {}
        self._ctr_hist: dict[str, list[float]] = {}
        self._avail_cache: dict = {}
        self._alerts: list = []
        self._alerts_t = 0.0
        self._ctr_seen: dict[str, float] = {}
        self._tun_sig: tuple = ()
        self.setWindowTitle(f"sshm {__version__} — {APP_TITLE}")
        self.setWindowIcon(app_icon("ok", self.theme.accent))
        self.setMinimumSize(1000, 620)
        self._restore_geometry()

        root = QWidget()
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_sidebar())
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_empty())
        self.stack.addWidget(self._build_detail())
        outer.addWidget(self.stack, 1)

        self.status_msg = _label()
        self.status_right = _label()
        self.alert_btn = QPushButton("")
        self.alert_btn.setObjectName("Flat")
        self.alert_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.alert_btn.clicked.connect(self.open_activity)
        self.alert_btn.hide()
        self.statusBar().addWidget(self.alert_btn)
        self.statusBar().addWidget(self.status_msg, 1)
        self.statusBar().addPermanentWidget(self.status_right)
        self._msg_timer = QTimer(self)
        self._msg_timer.setSingleShot(True)
        self._msg_timer.timeout.connect(lambda: self.status_msg.setText(""))

        self._shortcuts()
        ctrl.statuses_changed.connect(self.refresh_view)
        ctrl.servers_changed.connect(self.rebuild_list)
        ctrl.tunnels_changed.connect(self.refresh_view)
        ctrl.message.connect(self.show_message)
        self.apply_theme()
        self.rebuild_list()
        if ctrl.store.migrated_from_legacy:
            self.show_message(f"Imported {len(ctrl.store)} server(s) from your previous ~/.ssh_servers", "success")

    # ============================================================ building
    def _build_sidebar(self) -> QWidget:
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(360)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(16, 18, 16, 14)
        lay.setSpacing(10)

        brand = QHBoxLayout()
        mark = _label("◆", "BrandMark")
        brand.addWidget(mark)
        brand.addWidget(_label("sshm", "Brand"))
        ver = _label(f"v{__version__}", "Muted")
        ver.setToolTip("sshm version")
        brand.addWidget(ver, 0, Qt.AlignmentFlag.AlignBottom)
        brand.addStretch()
        self.summary = _label("", "Pill")
        brand.addWidget(self.summary)
        lay.addLayout(brand)

        self.search = QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText("Search servers…   Ctrl+K")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.rebuild_list)
        self.search.returnPressed.connect(self.connect_selected)
        lay.addWidget(self.search)

        filters = QHBoxLayout()
        self.tag_combo = QComboBox()
        self.tag_combo.currentIndexChanged.connect(self.rebuild_list)
        self.sort_combo = QComboBox()
        for label, key in SORTS:
            self.sort_combo.addItem(f"Sort: {label}", key)
        self.sort_combo.currentIndexChanged.connect(self.rebuild_list)
        filters.addWidget(self.tag_combo, 1)
        filters.addWidget(self.sort_combo, 1)
        lay.addLayout(filters)

        self.list = QListWidget()
        self.list.setObjectName("ServerList")
        self.list.setMouseTracking(True)
        self.list.setUniformItemSizes(True)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.delegate = ServerDelegate(self.theme, self.list)
        self.list.setItemDelegate(self.delegate)
        self.list.currentItemChanged.connect(self._on_current_changed)
        self.list.itemDoubleClicked.connect(lambda _i: self.connect_selected())
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._list_menu)
        lay.addWidget(self.list, 1)

        row = QHBoxLayout()
        add = QPushButton("＋  Add")
        add.setObjectName("Primary")
        add.setToolTip("Add a server (Ctrl+N)")
        add.clicked.connect(self.add_server)
        scan = QPushButton("Scan")
        scan.setToolTip("Discover SSH servers on your network")
        scan.clicked.connect(self.scan)
        more = QToolButton()
        more.setText("•••")
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(more)
        menu.addAction("Import from ~/.ssh/config…", self.import_ssh_config)
        menu.addAction("Export as ssh_config…", lambda: show_export(self, self.visible_servers()))
        menu.addSeparator()
        menu.addAction("Run on many servers…  Ctrl+Shift+R", self.open_fleet)
        menu.addAction("Alerts && activity…", self.open_activity)
        menu.addAction("Active tunnels…", self.show_all_tunnels)
        menu.addSeparator()
        menu.addAction("Back up servers to file…", self.export_backup)
        menu.addAction("Restore servers from file…", self.import_backup)
        menu.addAction("Open terminal UI", self.ctrl.launch_tui)
        menu.addSeparator()
        menu.addAction("Settings…", self.open_settings)
        menu.addAction(f"About sshm {__version__}", self.about)
        menu.addSeparator()
        menu.addAction("Quit", self.quit_app)
        more.setMenu(menu)
        row.addWidget(add, 2)
        row.addWidget(scan, 1)
        row.addWidget(more)
        lay.addLayout(row)
        return side

    def _build_empty(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addStretch()
        icon = QLabel()
        icon.setPixmap(app_icon("none", self.theme.accent).pixmap(96, 96))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(icon)
        title = _label("Your servers will live here", "EmptyTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)
        sub = _label("Add one by hand, discover them on your network, or import from ~/.ssh/config.", "Empty")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(sub)
        btns = QHBoxLayout()
        btns.addStretch()
        for text, slot, primary in (("Add server", self.add_server, True), ("Scan network", self.scan, False),
                                    ("Import ssh_config", self.import_ssh_config, False)):
            b = QPushButton(text)
            if primary:
                b.setObjectName("Primary")
            b.clicked.connect(slot)
            btns.addWidget(b)
        btns.addStretch()
        lay.addSpacing(12)
        lay.addLayout(btns)
        lay.addStretch()
        return page

    def _build_detail(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        page = QWidget()
        scroll.setWidget(page)
        lay = QVBoxLayout(page)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.setSpacing(16)

        # header ------------------------------------------------------------
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(4)
        name_row = QHBoxLayout()
        self.title = _label("", "Title")
        self.pill = Pill()
        self.tag_chip = _label("", "Chip")
        self.reboot_chip = _label("⟳ Reboot required", "Chip")
        self.reboot_chip.setToolTip("A newer kernel is installed than the one running")
        name_row.addWidget(self.title)
        name_row.addSpacing(6)
        name_row.addWidget(self.pill)
        name_row.addWidget(self.tag_chip)
        name_row.addWidget(self.reboot_chip)
        name_row.addStretch()
        titles.addLayout(name_row)
        self.endpoint = _label("", "Endpoint", selectable=True)
        titles.addWidget(self.endpoint)
        head.addLayout(titles, 1)

        self.connect_btn = QToolButton()
        self.connect_btn.setObjectName("Primary")
        self.connect_btn.setText("  Connect  ")
        self.connect_btn.setIcon(themed_icon("utilities-terminal-symbolic", "utilities-terminal"))
        self.connect_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.connect_btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.connect_btn.clicked.connect(self.connect_selected)
        cmenu = QMenu(self.connect_btn)
        cmenu.addAction("Connect", lambda: self._with(lambda s: self.ctrl.connect(s, tmux=False)))
        cmenu.addAction("Connect in tmux", lambda: self._with(lambda s: self.ctrl.connect(s, tmux=True)))
        cmenu.addAction("SFTP shell", lambda: self._with(self.ctrl.sftp))
        cmenu.addSeparator()
        cmenu.addAction("Copy ssh command", lambda: self._with(self.ctrl.copy_command))
        self.connect_btn.setMenu(cmenu)

        self.files_btn = QToolButton()
        self.files_btn.setText("Files")
        self.files_btn.setIcon(themed_icon("folder-remote-symbolic", "folder-remote"))
        self.files_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.files_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.files_menu = QMenu(self.files_btn)
        self.files_menu.aboutToShow.connect(self._fill_files_menu)
        self.files_btn.setMenu(self.files_menu)

        self.procs_btn = QToolButton()
        self.procs_btn.setText("Processes")
        self.procs_btn.setIcon(themed_icon("utilities-system-monitor-symbolic", "utilities-system-monitor"))
        self.procs_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.procs_btn.setToolTip("Live process list (Ctrl+P)")
        self.procs_btn.clicked.connect(lambda: self._with(self.open_processes))

        self.more_btn = QToolButton()
        self.more_btn.setText("More")
        self.more_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.more_menu = QMenu(self.more_btn)
        self.more_menu.aboutToShow.connect(self._fill_more_menu)
        self.more_btn.setMenu(self.more_menu)
        for b in (self.files_btn, self.procs_btn, self.more_btn, self.connect_btn):
            b.setMinimumHeight(38)
            head.addWidget(b, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(head)

        # telemetry ----------------------------------------------------------
        self.metrics = QWidget()
        grid = QHBoxLayout(self.metrics)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)
        self.cpu_card = MetricCard("CPU", self.theme, sparkline=True)
        self.mem_card = MetricCard("Memory", self.theme)
        self.disk_card = MetricCard("Disk /", self.theme)
        self.up_card = MetricCard("Uptime", self.theme)
        for card in (self.cpu_card, self.mem_card, self.disk_card, self.up_card):
            grid.addWidget(card, 1)
        lay.addWidget(self.metrics)

        self.agent_banner = QFrame()
        self.agent_banner.setObjectName("Banner")
        bl = QHBoxLayout(self.agent_banner)
        bl.setContentsMargins(16, 12, 16, 12)
        txt = QVBoxLayout()
        self.banner_title = _label("<b>Live metrics are off for this server</b>")
        self.banner_text = _label("Deploy the tiny telemetry agent (Python, no dependencies) to see CPU, memory, "
                                  "disk and uptime here and in the tray.", "Muted")
        self.banner_text.setWordWrap(True)
        txt.addWidget(self.banner_title)
        txt.addWidget(self.banner_text)
        bl.addLayout(txt, 1)
        deploy = QPushButton("Deploy agent")
        self.banner_btn = deploy
        deploy.setObjectName("Primary")
        deploy.clicked.connect(lambda: self._with(self.ctrl.deploy_agent))
        bl.addWidget(deploy)
        lay.addWidget(self.agent_banner)

        self.top_card = QFrame()
        self.top_card.setObjectName("Card")
        tl = QVBoxLayout(self.top_card)
        tl.setContentsMargins(20, 14, 20, 14)
        tl.setSpacing(6)
        th = QHBoxLayout()
        th.addWidget(_label("TOP PROCESSES", "Caption"))
        th.addStretch()
        see_all = QPushButton("See all")
        see_all.setObjectName("Flat")
        see_all.clicked.connect(lambda: self._with(self.open_processes))
        th.addWidget(see_all)
        tl.addLayout(th)
        self.top_grid = QGridLayout()
        self.top_grid.setHorizontalSpacing(18)
        self.top_grid.setVerticalSpacing(4)
        self.top_rows: list[tuple[QLabel, QLabel, QLabel, QLabel]] = []
        for r in range(5):
            cells = (_label("", "Value"), _label("", "Muted"), _label(""), _label("", "Muted"))
            cells[2].setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            for c, w in enumerate(cells):
                self.top_grid.addWidget(w, r, c)
            self.top_rows.append(cells)
        self.top_grid.setColumnStretch(2, 1)
        tl.addLayout(self.top_grid)
        lay.addWidget(self.top_card)

        self.container_card = ContainerCard(self)
        lay.addWidget(self.container_card)

        # info card -----------------------------------------------------------
        info = QFrame()
        info.setObjectName("Card")
        ig = QGridLayout(info)
        ig.setContentsMargins(20, 16, 20, 16)
        ig.setHorizontalSpacing(24)
        ig.setVerticalSpacing(10)
        self.info_values: dict[str, QLabel] = {}
        fields = [("Status", "status"), ("SSH server", "banner"), ("User", "user"), ("Port", "port"),
                  ("Identity", "key"), ("Jump host", "jump"), ("MAC address", "mac"), ("Remote folder", "path"),
                  ("Files", "files"), ("Last connected", "last"), ("System", "os"), ("Uptime 24h · 7d", "uptime")]
        for i, (label, key) in enumerate(fields):
            r, c = divmod(i, 2)
            ig.addWidget(_label(label.upper(), "Caption"), r * 2, c)
            v = _label("—", "Value", selectable=True)
            v.setWordWrap(True)
            ig.addWidget(v, r * 2 + 1, c)
            self.info_values[key] = v
        ig.setColumnStretch(0, 1)
        ig.setColumnStretch(1, 1)
        lay.addWidget(info)

        self.notes = _label("", "Muted")
        self.notes.setWordWrap(True)
        lay.addWidget(self.notes)

        # tabs -----------------------------------------------------------------
        self.tabs = QTabWidget()
        self.tabs.setMinimumHeight(220)
        self.tabs.addTab(self._build_commands_tab(), "Commands")
        self.tabs.addTab(self._build_tunnels_tab(), "Tunnels")
        self.containers_tab = ContainersTab(self)
        self.tabs.addTab(self.containers_tab, "Containers")
        lay.addWidget(self.tabs)
        lay.addStretch()
        return scroll

    def _build_commands_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(14, 14, 14, 14)
        self.cmd_list = QListWidget()
        self.cmd_list.itemDoubleClicked.connect(lambda _i: self.run_command())
        lay.addWidget(self.cmd_list, 1)
        row = QHBoxLayout()
        run = QPushButton("Run")
        run.setObjectName("Primary")
        run.clicked.connect(self.run_command)
        add = QPushButton("Add…")
        add.clicked.connect(self.add_command)
        edit = QPushButton("Edit…")
        edit.clicked.connect(self.edit_command)
        rm = QPushButton("Delete")
        rm.setObjectName("Danger")
        rm.clicked.connect(self.delete_command)
        row.addWidget(add)
        row.addWidget(edit)
        row.addWidget(rm)
        row.addStretch()
        row.addWidget(run)
        lay.addLayout(row)
        return w

    def _build_tunnels_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(14, 14, 14, 14)
        self.tunnel_list = QListWidget()
        lay.addWidget(self.tunnel_list, 1)
        row = QHBoxLayout()
        new = QPushButton("New tunnel…")
        new.setObjectName("Primary")
        new.clicked.connect(self.new_tunnel)
        stop = QPushButton("Stop selected")
        stop.setObjectName("Danger")
        stop.clicked.connect(self.stop_tunnel)
        row.addStretch()
        row.addWidget(stop)
        row.addWidget(new)
        lay.addLayout(row)
        return w

    def _shortcuts(self) -> None:
        def sc(seq: QKeySequence | str, slot) -> None:
            QShortcut(QKeySequence(seq), self, activated=slot)

        sc("Ctrl+K", self.focus_search)
        sc(QKeySequence.StandardKey.Find, self.focus_search)
        sc(QKeySequence.StandardKey.New, self.add_server)
        sc(QKeySequence.StandardKey.Refresh, lambda: self.ctrl.refresh())
        sc("Ctrl+R", lambda: self.ctrl.refresh())
        sc("Ctrl+E", self.edit_selected)
        sc("Delete", self.delete_selected)
        sc("Ctrl+T", lambda: self._with(lambda s: self.ctrl.connect(s, tmux=True)))
        sc("Ctrl+,", self.open_settings)
        sc("Ctrl+P", lambda: self._with(self.open_processes))
        sc("Ctrl+Shift+R", self.open_fleet)
        sc(QKeySequence.StandardKey.Quit, self.quit_app)
        sc("Escape", lambda: self.search.clear())
        delete = QShortcut(QKeySequence("Delete"), self.list, activated=self.delete_selected)
        delete.setContext(Qt.ShortcutContext.WidgetShortcut)
        self.list.activated.connect(lambda _idx: self.connect_selected())

    # ============================================================== theming
    def apply_theme(self) -> None:
        self.theme = get_theme(self.ctrl.settings.theme)
        app = QApplication.instance()
        apply_palette(app, self.theme)
        app.setStyleSheet(stylesheet(self.theme))
        for widget in (self.delegate, self.cpu_card.spark, self.cpu_card.meter, self.mem_card.meter,
                       self.disk_card.meter, self.up_card.meter):
            if widget is not None:
                widget.theme = self.theme
        self.setWindowIcon(app_icon("ok", self.theme.accent))
        self.refresh_view()

    # ================================================================ data
    def visible_servers(self) -> list[Server]:
        servers = self.ctrl.servers
        tag = self.tag_combo.currentData()
        if tag:
            servers = [s for s in servers if s.tag == tag]
        q = self.search.text().strip()
        if q:
            scored = sorted(((fuzzy_score(q, s.search_text), s) for s in servers), key=lambda t: -t[0])
            return sorted([s for score, s in scored if score > 0], key=lambda s: not s.favorite)
        key = self.sort_combo.currentData() or "name"

        def status_rank(s: Server) -> tuple:
            st = self.ctrl.status(s)
            return (0 if st and st.online else 1, s.name.lower())

        def latency_rank(s: Server) -> tuple:
            st = self.ctrl.status(s)
            ok = st and st.online and st.latency_ms is not None
            return (st.latency_ms if ok else 1e9, s.name.lower())

        keyfn = {"name": lambda s: s.name.lower(), "status": status_rank, "latency": latency_rank,
                 "recent": lambda s: -s.last_connected}[key]
        return sorted(sorted(servers, key=keyfn), key=lambda s: not s.favorite)

    def current(self) -> Server | None:
        return self.ctrl.store.get(self.selected_id) if self.selected_id else None

    def _with(self, fn) -> None:
        srv = self.current()
        if srv:
            fn(srv)

    def rebuild_list(self) -> None:
        # tag filter options
        tags = self.ctrl.store.tags()
        cur_tag = self.tag_combo.currentData()
        self.tag_combo.blockSignals(True)
        self.tag_combo.clear()
        self.tag_combo.addItem("All tags", None)
        for t in tags:
            self.tag_combo.addItem(t, t)
        idx = self.tag_combo.findData(cur_tag) if cur_tag else 0
        self.tag_combo.setCurrentIndex(max(0, idx))
        self.tag_combo.blockSignals(False)

        servers = self.visible_servers()
        self.list.blockSignals(True)
        self.list.clear()
        select_row = 0
        for row, s in enumerate(servers):
            item = QListWidgetItem()
            item.setData(ROLE_ID, s.id)
            item.setData(ROLE_SERVER, s)
            item.setData(ROLE_STATUS, self.ctrl.status(s))
            item.setData(ROLE_LINK, self._link_label(s.id))
            item.setSizeHint(QSize(300, ServerDelegate.ROW_H))
            item.setToolTip(f"{s.name}\n{s.endpoint}" + (f"\n{s.notes}" if s.notes else ""))
            self.list.addItem(item)
            if s.id == self.selected_id:
                select_row = row
        self.list.blockSignals(False)
        if servers:
            self.list.setCurrentRow(select_row)
            self.selected_id = servers[select_row].id
        else:
            self.selected_id = None
        self.refresh_view()

    def _on_current_changed(self, item: QListWidgetItem | None, _prev) -> None:
        if item is not None:
            self.selected_id = item.data(ROLE_ID)
            self.refresh_view()

    def _link_label(self, server_id: str) -> str | None:
        link = self._links.get(server_id)
        return f"{link.container.name} on {link.host.name}" if link else None

    def refresh_view(self) -> None:
        self._hosts = self.ctrl.hub.host_containers()
        self._links = self.ctrl.hub.links()
        # list rows (statuses change constantly; servers are re-read for freshness)
        for i in range(self.list.count()):
            item = self.list.item(i)
            srv = self.ctrl.store.get(item.data(ROLE_ID))
            if srv:
                item.setData(ROLE_SERVER, srv)
                item.setData(ROLE_STATUS, self.ctrl.status(srv))
                item.setData(ROLE_LINK, self._link_label(srv.id))
        self.list.viewport().update()

        online, total = self.ctrl.hub.summary()
        t = self.theme
        color = t.success if total and online == total else t.warning if online else t.muted if not total else t.danger
        self.summary.setText(f"{online}/{total} online")
        self.summary.setStyleSheet(f"color: {color}; background: transparent; border: 1px solid {color};")

        right = []
        if self.ctrl.hub.probing:
            right.append("Checking servers…")
        elif self.ctrl.hub.last_probe:
            right.append(f"Updated {int(time.monotonic() - self.ctrl.hub.last_probe)}s ago")
        port = self.ctrl.settings.telemetry_port
        right.append(f"Telemetry :{port}/udp" if self.ctrl.listening else "Telemetry via another sshm instance")
        self.status_right.setText("   ·   ".join(right))
        active = self._active_alerts()
        self.alert_btn.setVisible(bool(active))
        if active:
            crit = any(e.severity == "critical" for e in active)
            self.alert_btn.setText(f"⚠ {len(active)} active alert{'s' if len(active) != 1 else ''}")
            self.alert_btn.setStyleSheet(f"color: {t.danger if crit else t.warning}; padding: 2px 8px;")

        srv = self.current()
        if srv is None:
            self.stack.setCurrentIndex(0)
            return
        self.stack.setCurrentIndex(1)
        st = self.ctrl.status(srv)
        self.title.setText(("★ " if srv.favorite else "") + srv.name)
        self.endpoint.setText(srv.endpoint + (f"   via {srv.jump}" if srv.jump else ""))
        self.tag_chip.setVisible(bool(srv.tag))
        self.tag_chip.setText(srv.tag)
        if st is None:
            self.pill.set_state("Checking…", t.muted, t)
        elif st.online:
            self.pill.set_state(f"● Online · {st.latency_label}", t.success, t)
        elif st.state == "degraded":
            self.pill.set_state("◐ Host up, SSH down", t.warning, t)
        else:
            self.pill.set_state("○ Offline", t.danger, t)

        tel = st.telemetry if st else None
        link = self._links.get(srv.id)
        hc = self._hosts.get(srv.id)
        if link is not None:
            ctr = link.container
            self.pill.set_state(*self._container_pill(ctr), t)
            self.tag_chip.setVisible(True)
            self.tag_chip.setText(f"⬢ {ctr.name} on {link.host.name}" + (f" · {srv.tag}" if srv.tag else ""))
            tel = None  # in-container agents report the host's /proc; container cgroup stats are the truth
        self.container_card.show_link(link, self.ctrl.hub, t)
        self.containers_tab.show_host(srv, hc, self.ctrl.hub.links(), self.ctrl.hub)
        self.tabs.setTabVisible(2, link is None and hc is not None)
        if hc is not None and link is None:
            running = sum(1 for c in hc.containers if c.running)
            self.tabs.setTabText(2, f"Containers ({running}/{len(hc.containers)})" if hc.containers else "Containers")
        self.disk_card.setVisible(link is None)
        if link is not None and link.container.running:
            ctr = link.container
            key = f"{link.host.id}/{ctr.id}"
            hist = self._ctr_hist.setdefault(key, [])
            stamp = (self._hosts.get(link.host.id).fetched if self._hosts.get(link.host.id) else 0.0)
            if ctr.cpu is not None and self._ctr_seen.get(key) != stamp:
                self._ctr_seen[key] = stamp
                hist.append(ctr.cpu)
                del hist[:-60]
            self.metrics.setVisible(True)
            self.agent_banner.setVisible(False)
            self.cpu_card.set(f"{ctr.cpu:.0f}%" if ctr.cpu is not None else "--", "container CPU (of one core)",
                              min(100.0, ctr.cpu) if ctr.cpu is not None else None, hist)
            self.mem_card.set(f"{ctr.mem_pct:.0f}%" if ctr.mem_pct is not None else "--", ctr.mem_label, ctr.mem_pct)
            self.up_card.set(ctr.status.split("(")[0].replace("Up ", "") or ctr.state,
                             ctr.health or f"via {self._hosts[link.host.id].source}", None)
            self.up_card.meter.hide()
        elif link is not None:
            self.metrics.setVisible(False)
            self.agent_banner.setVisible(False)
        else:
            outdated = tel is not None and agent.is_outdated(tel.agent_version)
            self.metrics.setVisible(tel is not None)
            self.agent_banner.setVisible((tel is None and bool(st and st.online)) or outdated)
            if outdated:
                self.banner_title.setText(f"<b>Agent update available</b> ({tel.agent_version or 'pre-3.3'} → "
                                          f"{agent.bundled_version()})")
                self.banner_text.setText("The new agent adds container stats, top processes, reboot detection and "
                                         "signed packets. Takes a few seconds.")
                self.banner_btn.setText("Update agent")
            else:
                self.banner_title.setText("<b>Live metrics are off for this server</b>")
                self.banner_text.setText("Deploy the tiny telemetry agent (Python, no dependencies) to see CPU, "
                                         "memory, disk and uptime here and in the tray.")
                self.banner_btn.setText("Deploy agent")
        self.reboot_chip.setVisible(bool(tel and tel.reboot_required))
        if tel:
            self.cpu_card.set(f"{tel.cpu:.0f}%" if tel.cpu is not None else "--",
                              f"load {tel.load_label}", tel.cpu, tel.history)
            self.mem_card.set(f"{tel.mem_pct:.0f}%" if tel.mem_pct is not None else "--", tel.mem_label, tel.mem_pct)
            self.disk_card.set(f"{tel.disk_pct:.0f}%" if tel.disk_pct is not None else "--", tel.disk_label,
                               tel.disk_pct)
            swap = f"swap {tel.swap_used / 1024**3:.1f} GiB" if tel.swap_total else ""
            self.up_card.set(tel.uptime_label, swap or ("signed agent" if tel.signed else "legacy agent"), None)
            self.up_card.meter.hide()
        top = tel.top("cpu", 5) if tel else []
        self.top_card.setVisible(bool(top))
        for i, cells in enumerate(self.top_rows):
            if i < len(top):
                tp = top[i]
                cpu_color = t.danger if tp.cpu >= 80 else t.warning if tp.cpu >= 25 else t.text
                cells[0].setText(f"{tp.cpu:.1f}%")
                cells[0].setStyleSheet(f"color: {cpu_color};")
                cells[1].setText(tp.rss_label)
                cells[2].setText(tp.name)
                cells[3].setText(f"pid {tp.pid}")
            for w in cells:
                w.setVisible(i < len(top))

        bookmarked = mounts.is_bookmarked(srv, self.ctrl.settings)
        sshfs_on = mounts.sshfs_available() and mounts.is_sshfs_mounted(srv, self.ctrl.settings)
        files = [x for x, on in (("Bookmarked", bookmarked), ("SSHFS mounted", sshfs_on)) if on]
        v = self.info_values
        v["status"].setText(st.summary if st else "Checking…")
        v["status"].setStyleSheet(f"color: {state_color(t, st)};")
        v["banner"].setText(st.banner if st and st.banner else "—")
        v["user"].setText(srv.user or "(ssh default)")
        v["port"].setText(str(srv.port))
        key_txt = srv.key or "ssh-agent / default keys"
        if srv.key and not srv.key_path:
            key_txt += "  ⚠ file not found"
        v["key"].setText(key_txt)
        v["jump"].setText(srv.jump or "—")
        v["mac"].setText(srv.mac or "not set")
        v["path"].setText(srv.home_path)
        v["files"].setText(" · ".join(files) or "—")
        v["last"].setText(time.strftime("%b %d, %H:%M", time.localtime(srv.last_connected))
                          if srv.last_connected else "never")
        v["os"].setText(f"{tel.os_name} · {tel.kernel}" if tel and tel.os_name else "—")
        avail = self._availability(srv)
        if avail is not None and avail.uptime_24h is not None:
            from sshm.core.history import Availability

            pct = avail.uptime_24h
            v["uptime"].setText(f"{Availability.label(pct)} · {Availability.label(avail.uptime_7d)}")
            v["uptime"].setStyleSheet(f"color: {t.success if pct >= 99.5 else t.warning if pct >= 95 else t.danger};")
        else:
            v["uptime"].setText("collecting…" if self.ctrl.hub.recording else "—")
            v["uptime"].setStyleSheet("")
        self.notes.setVisible(bool(srv.notes))
        self.notes.setText(srv.notes)

        # commands / tunnels: only rebuild when they actually changed (keeps selection stable)
        cmd_sig = (srv.id, tuple((c.label, c.command) for c in srv.commands))
        tunnels = self.ctrl.hub.tunnels.list(srv.id)
        tun_sig = (srv.id, tuple(t.id for t in tunnels))
        if cmd_sig != self._cmd_sig:
            self._cmd_sig = cmd_sig
            self._fill_commands(srv)
        if tun_sig != self._tun_sig:
            self._tun_sig = tun_sig
            self._fill_tunnels(tunnels)

    def _fill_commands(self, srv: Server) -> None:
        cur_cmd = self.cmd_list.currentRow()
        self.cmd_list.clear()
        for c in srv.commands:
            item = QListWidgetItem(f"{c.label}\n{c.command}")
            item.setToolTip(c.command)
            self.cmd_list.addItem(item)
        if srv.commands:
            self.cmd_list.setCurrentRow(min(max(0, cur_cmd), len(srv.commands) - 1))
        self.tabs.setTabText(0, f"Commands ({len(srv.commands)})" if srv.commands else "Commands")

    def _fill_tunnels(self, tunnels: list) -> None:
        self.tunnel_list.clear()
        for tun in tunnels:
            item = QListWidgetItem(f"-{tun.kind} {tun.spec}    {tun.description}")
            item.setData(ROLE_ID, tun.id)
            self.tunnel_list.addItem(item)
        self.tabs.setTabText(1, f"Tunnels ({len(tunnels)})" if tunnels else "Tunnels")

    # ============================================================== menus
    def _container_pill(self, ctr) -> tuple[str, str]:
        t = self.theme
        if ctr.running and ctr.health == "unhealthy":
            return "● Running · unhealthy", t.warning
        if ctr.running:
            return "● Running" + (" · healthy" if ctr.health == "healthy" else ""), t.success
        if ctr.state in ("paused", "restarting"):
            return f"◐ {ctr.state.capitalize()}", t.warning
        return f"○ {ctr.state.capitalize() or 'Stopped'}", t.danger

    def select_server(self, server_id: str) -> None:
        self.search.clear()
        self.tag_combo.setCurrentIndex(0)
        self.selected_id = server_id
        self.rebuild_list()

    def _fill_files_menu(self) -> None:
        m = self.files_menu
        m.clear()
        srv = self.current()
        if not srv:
            return
        m.addAction(themed_icon("system-file-manager-symbolic", "system-file-manager"), "Open in file manager",
                    lambda: self.ctrl.open_files(srv))
        bookmarked = mounts.is_bookmarked(srv, self.ctrl.settings)
        m.addAction("Remove file-manager bookmark" if bookmarked else "Bookmark in file manager",
                    lambda: self.ctrl.toggle_bookmark(srv))
        if mounts.sshfs_available():
            on = mounts.is_sshfs_mounted(srv, self.ctrl.settings)
            m.addAction("Unmount SSHFS" if on else "Mount with SSHFS", lambda: self.ctrl.toggle_sshfs(srv))
        else:
            act = m.addAction("Mount with SSHFS (install sshfs)")
            act.setEnabled(False)
        m.addSeparator()
        m.addAction("SFTP shell", lambda: self.ctrl.sftp(srv))

    def _fill_more_menu(self) -> None:
        m = self.more_menu
        m.clear()
        srv = self.current()
        if not srv:
            return
        m.addAction("Processes…", lambda: self.open_processes(srv))
        link = self.ctrl.hub.links().get(srv.id)
        if link is not None:
            cm = m.addMenu(f"Container: {link.container.name}")
            self._container_actions(cm, link.host, link.container)
            cm.addSeparator()
            cm.addAction(f"Go to host: {link.host.name}", lambda: self.select_server(link.host.id))
        else:
            m.addAction("Find docker containers", lambda: self.ctrl.detect_containers(srv))
        m.addAction("htop in terminal", lambda: self.ctrl.launch(procs.top_argv(srv), f"htop · {srv.name}"))
        m.addSeparator()
        m.addAction("Port forward…", self.new_tunnel)
        wake = m.addAction(f"Wake-on-LAN ({srv.mac})" if srv.mac else "Wake-on-LAN (no MAC set)",
                           lambda: self.ctrl.wake(srv))
        wake.setEnabled(bool(srv.mac))
        m.addAction("Push SSH key…", lambda: self.ctrl.push_key(srv))
        agent = m.addMenu("Telemetry agent")
        agent.addAction("Deploy / update", lambda: self.ctrl.deploy_agent(srv))
        agent.addAction("Show status", lambda: self.ctrl.agent_status(srv))
        agent.addAction("Remove", lambda: self.ctrl.deploy_agent(srv, remove=True))
        m.addSeparator()
        fav = QAction("Favorite", m)
        fav.setCheckable(True)
        fav.setChecked(srv.favorite)
        fav.triggered.connect(lambda: self.toggle_flag(srv, "favorite"))
        m.addAction(fav)
        tray = QAction("Show in tray", m)
        tray.setCheckable(True)
        tray.setChecked(srv.tray)
        tray.triggered.connect(lambda: self.toggle_flag(srv, "tray"))
        m.addAction(tray)
        m.addSeparator()
        m.addAction("Edit…", self.edit_selected)
        m.addAction("Duplicate", lambda: self.duplicate(srv))
        m.addAction("Delete…", self.delete_selected)

    def _container_actions(self, menu: QMenu, host: Server, ctr) -> None:
        if ctr.running:
            menu.addAction("Restart", lambda: self.ctrl.container_action(host, ctr, "restart"))
            menu.addAction("Stop", lambda: self._confirm_stop(host, ctr))
        else:
            menu.addAction("Start", lambda: self.ctrl.container_action(host, ctr, "start"))
        menu.addAction("Follow logs", lambda: self.ctrl.container_logs(host, ctr))
        menu.addAction("Shell inside container", lambda: self.ctrl.container_shell(host, ctr))
        menu.addAction("Live stats", lambda: self.ctrl.container_stats(host, ctr))

    def _confirm_stop(self, host: Server, ctr) -> None:
        ok = QMessageBox.question(self, "Stop container", f"Stop {ctr.name} on {host.name}?")
        if ok == QMessageBox.StandardButton.Yes:
            self.ctrl.container_action(host, ctr, "stop")

    def _list_menu(self, pos) -> None:
        item = self.list.itemAt(pos)
        if not item:
            return
        self.list.setCurrentItem(item)
        self._fill_more_menu()
        menu = QMenu(self)
        menu.addAction("Connect", self.connect_selected)
        menu.addAction("Connect in tmux", lambda: self._with(lambda s: self.ctrl.connect(s, tmux=True)))
        menu.addSeparator()
        for act in self.more_menu.actions():
            menu.addAction(act)
        menu.exec(self.list.viewport().mapToGlobal(pos))

    # ============================================================ actions
    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def connect_selected(self) -> None:
        self._with(lambda s: self.ctrl.connect(s))

    def show_message(self, text: str, level: str) -> None:
        color = {"success": self.theme.success, "error": self.theme.danger, "warning": self.theme.warning}.get(
            level, self.theme.muted)
        icon = {"success": "✔", "error": "✖", "warning": "⚠"}.get(level, "ℹ")
        self.status_msg.setStyleSheet(f"color: {color};")
        self.status_msg.setText(f"{icon}  {text}")
        self._msg_timer.start(7000 if level == "error" else 4500)
        if level == "error" and self.isActiveWindow():
            QApplication.beep()

    def add_server(self) -> None:
        tag = self.tag_combo.currentData() or ""
        dlg = ServerDialog(self.ctrl.store, None, self, default_tag=tag)
        if dlg.exec() and dlg.result_server:
            self.ctrl.store.add(dlg.result_server)
            self.selected_id = dlg.result_server.id
            self.ctrl.saved()
            self.show_message(f"Added {dlg.result_server.name}", "success")

    def edit_selected(self) -> None:
        srv = self.current()
        if not srv:
            return
        dlg = ServerDialog(self.ctrl.store, srv, self)
        if dlg.exec() and dlg.result_server:
            self.ctrl.store.update(dlg.result_server)
            self.ctrl.saved()
            self.show_message(f"Saved {dlg.result_server.name}", "success")

    def duplicate(self, srv: Server) -> None:
        data = srv.to_dict()
        data.pop("id")
        data["name"] = self.ctrl.store.unique_name(f"{srv.name} copy")
        data["last_connected"] = 0
        copy = Server.from_dict(data)
        self.ctrl.store.add(copy)
        self.selected_id = copy.id
        self.ctrl.saved()

    def delete_selected(self) -> None:
        srv = self.current()
        if not srv or self.search.hasFocus():
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Delete server")
        box.setText(f"Delete <b>{html.escape(srv.name)}</b>?")
        box.setInformativeText(f"{srv.endpoint}\n\nThis only removes the profile from sshm; "
                               "nothing on the server is touched.")
        delete = box.addButton("Delete", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is delete:
            self.ctrl.store.remove(srv.id)
            self.selected_id = None
            self.ctrl.saved()
            self.show_message(f"Deleted {srv.name}", "success")

    def toggle_flag(self, srv: Server, flag: str) -> None:
        setattr(srv, flag, not getattr(srv, flag))
        self.ctrl.store.update(srv)
        self.ctrl.saved()

    def scan(self) -> None:
        dlg = ScanDialog(self.ctrl.store, self)
        if not dlg.exec():
            return
        existing = {(s.host, s.port): s for s in self.ctrl.store.servers}
        added = updated = 0
        for d in dlg.selected():
            saved = existing.get((d.ip, d.port))
            if saved:
                if d.mac and not saved.mac:
                    saved.mac = d.mac
                    self.ctrl.store.update(saved)
                    updated += 1
                continue
            self.ctrl.store.add(Server(name=self.ctrl.store.unique_name(d.suggested_name), host=d.ip, port=d.port,
                                       user=dlg.user.text().strip(), tag=dlg.tag.text().strip(), mac=d.mac))
            added += 1
        self.ctrl.saved()
        self.show_message(f"Added {added} server(s), filled in {updated} MAC address(es)", "success")

    def import_ssh_config(self) -> None:
        candidates = sshconfig.import_servers(self.ctrl.servers)
        if not candidates:
            self.show_message("Nothing new to import from ~/.ssh/config", "info")
            return
        dlg = ImportDialog(candidates, self)
        if dlg.exec():
            picked = dlg.selected()
            for srv in picked:
                srv.name = self.ctrl.store.unique_name(srv.name)
                self.ctrl.store.add(srv)
            self.ctrl.saved()
            self.show_message(f"Imported {len(picked)} host(s)", "success")

    def run_command(self) -> None:
        srv = self.current()
        row = self.cmd_list.currentRow()
        if srv and 0 <= row < len(srv.commands):
            c = srv.commands[row]
            self.ctrl.run_command(srv, c.label, c.command)

    def add_command(self) -> None:
        srv = self.current()
        if not srv:
            return
        dlg = CommandDialog(None, self)
        if dlg.exec() and dlg.command:
            srv.commands.append(dlg.command)
            self.ctrl.store.update(srv)
            self.ctrl.saved()

    def edit_command(self) -> None:
        srv = self.current()
        row = self.cmd_list.currentRow()
        if not srv or not 0 <= row < len(srv.commands):
            return
        dlg = CommandDialog(srv.commands[row], self)
        if dlg.exec() and dlg.command:
            srv.commands[row] = dlg.command
            self.ctrl.store.update(srv)
            self.ctrl.saved()

    def delete_command(self) -> None:
        srv = self.current()
        row = self.cmd_list.currentRow()
        if srv and 0 <= row < len(srv.commands):
            srv.commands.pop(row)
            self.ctrl.store.update(srv)
            self.ctrl.saved()

    def new_tunnel(self) -> None:
        srv = self.current()
        if not srv:
            return
        dlg = TunnelDialog(srv, self)
        if dlg.exec() and dlg.spec:
            self.tabs.setCurrentIndex(1)
            self.ctrl.start_tunnel(srv, dlg.spec)

    def stop_tunnel(self) -> None:
        item = self.tunnel_list.currentItem()
        if not item:
            return
        tid = item.data(ROLE_ID)
        tun = next((t for t in self.ctrl.hub.tunnels.list() if t.id == tid), None)
        if tun:
            self.ctrl.stop_tunnel(tun)

    def show_all_tunnels(self) -> None:
        tunnels = self.ctrl.hub.tunnels.list()
        if not tunnels:
            self.show_message("No active tunnels", "info")
            return
        lines = "\n".join(f"• -{t.kind} {t.spec}  —  {t.server_name} (pid {t.pid})" for t in tunnels)
        box = QMessageBox(self)
        box.setWindowTitle("Active tunnels")
        box.setText(f"{len(tunnels)} active tunnel(s)")
        box.setInformativeText(lines)
        stop_all = box.addButton("Stop all", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Close)
        box.exec()
        if box.clickedButton() is stop_all:
            n = self.ctrl.hub.tunnels.stop_all()
            self.ctrl.tunnels_changed.emit()
            self.show_message(f"Stopped {n} tunnel(s)", "success")

    def _availability(self, srv: Server):
        now = time.monotonic()
        hit = self._avail_cache.get(srv.id)
        if hit is None or now - hit[0] > 15:
            try:
                hit = (now, self.ctrl.hub.history.availability(srv.id))
            except Exception:
                hit = (now, None)
            self._avail_cache[srv.id] = hit
        return hit[1]

    def _active_alerts(self) -> list:
        now = time.monotonic()
        if now - self._alerts_t > 3:
            self._alerts_t = now
            try:
                self._alerts = self.ctrl.hub.history.active()
            except Exception:
                self._alerts = []
        return self._alerts

    def open_fleet(self) -> None:
        from sshm.gui.fleet import FleetDialog

        srv = self.current()
        tag = self.tag_combo.currentData()
        pre = [s.id for s in self.ctrl.servers if s.tag == tag] if tag else ([srv.id] if srv else [])
        FleetDialog(self.ctrl, pre, self).show()

    def open_activity(self) -> None:
        from sshm.gui.fleet import ActivityDialog

        self.bring_to_front()
        ActivityDialog(self.ctrl, self).show()

    def export_backup(self) -> None:
        from pathlib import Path

        from PyQt6.QtWidgets import QFileDialog

        from sshm.core import fleet

        default = str(Path.home() / f"sshm-backup-{time.strftime('%Y%m%d')}.json")
        path, _ = QFileDialog.getSaveFileName(self, "Back up servers", default, "sshm backup (*.json)")
        if path:
            n = fleet.export_backup(self.ctrl.store, Path(path))
            self.show_message(f"Saved {n} server(s) to {path} (no keys or secrets included)", "success")

    def import_backup(self) -> None:
        from pathlib import Path

        from PyQt6.QtWidgets import QFileDialog

        from sshm.core import fleet

        path, _ = QFileDialog.getOpenFileName(self, "Restore servers", str(Path.home()), "sshm backup (*.json)")
        if not path:
            return
        try:
            added, updated = fleet.import_backup(self.ctrl.store, Path(path))
        except ValueError as exc:
            QMessageBox.warning(self, "Restore failed", str(exc))
            return
        self.ctrl.saved()
        self.show_message(f"Restored: {added} added, {updated} updated", "success")

    def open_processes(self, srv: Server) -> None:
        from sshm.gui.procview import ProcessWindow

        existing = self._proc_windows.get(srv.id)
        if existing is not None:
            existing.show()
            existing.raise_()
            existing.activateWindow()
            return
        win = ProcessWindow(self.ctrl, srv, self)
        self._proc_windows[srv.id] = win
        win.destroyed.connect(lambda *_a, sid=srv.id: self._proc_windows.pop(sid, None))
        win.show()

    def open_settings(self) -> None:
        dlg = SettingsDialog(self.ctrl.settings, autostart.is_enabled(), self)
        if dlg.exec():
            autostart.set_enabled(dlg.autostart.isChecked())
            self.apply_theme()
            self.ctrl.settings_changed.emit()
            self.show_message("Settings saved", "success")

    def about(self) -> None:
        QMessageBox.about(
            self, "About sshm",
            f"<h3>sshm {__version__}</h3><p>{APP_TITLE} — SSH server manager, tray monitor, "
            "terminal UI and CLI for Linux.</p>"
            "<p><a href='https://github.com/marioman68/sshm'>github.com/marioman68/sshm</a></p>"
            "<p>MIT licensed.</p>",
        )

    # ============================================================ closing
    def _restore_geometry(self) -> None:
        """Reopen at the last size/position; first launch: ~1440x920, capped to 90% of the screen."""
        saved = QSettings("sshm", "sshm").value("window/geometry")
        if saved is not None and self.restoreGeometry(saved):
            return
        screen = QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        w, h = 1440, 920
        if avail is not None:
            w = min(w, int(avail.width() * 0.9))
            h = min(h, int(avail.height() * 0.9))
        self.resize(max(w, self.minimumWidth()), max(h, self.minimumHeight()))
        if avail is not None:
            x = avail.x() + (avail.width() - self.width()) // 2
            y = avail.y() + (avail.height() - self.height()) // 2
            self.move(x, y)

    def _save_geometry(self) -> None:
        QSettings("sshm", "sshm").setValue("window/geometry", self.saveGeometry())

    def quit_app(self) -> None:
        self._save_geometry()
        self.quitting = True
        QApplication.instance().quit()

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self.quitting and self.ctrl.settings.close_to_tray and self.tray_available:
            event.ignore()
            self.hide()
            self.show_message("sshm is still running in the tray", "info")
            return
        event.accept()
        if not self.tray_available:
            QApplication.instance().quit()

    def bring_to_front(self) -> None:
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive)
        self.raise_()
        self.activateWindow()

