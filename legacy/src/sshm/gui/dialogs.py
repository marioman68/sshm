"""Dialogs: server editor, LAN scan, ssh_config import, tunnels, commands, settings."""

from __future__ import annotations

import os
import threading

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sshm.core import netscan, paths, sshconfig
from sshm.core.models import CustomCommand, Server, normalize_mac
from sshm.core.settings import REFRESH_CHOICES, Settings
from sshm.core.store import ServerStore
from sshm.core.themes import theme_names
from sshm.core.tunnels import TunnelError, TunnelSpec


def _header(title: str, subtitle: str = "") -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 8)
    lay.setSpacing(2)
    t = QLabel(title)
    t.setObjectName("Title")
    t.setStyleSheet("font-size: 15pt;")
    lay.addWidget(t)
    if subtitle:
        s = QLabel(subtitle)
        s.setObjectName("Muted")
        s.setWordWrap(True)
        lay.addWidget(s)
    return w


def _buttons(dialog: QDialog, ok_text: str = "Save") -> QDialogButtonBox:
    box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    ok = box.button(QDialogButtonBox.StandardButton.Ok)
    ok.setText(ok_text)
    ok.setObjectName("Primary")
    ok.setDefault(True)
    box.rejected.connect(dialog.reject)
    return box


# ================================================================== server
class ServerDialog(QDialog):
    def __init__(self, store: ServerStore, server: Server | None = None, parent=None, default_tag: str = "") -> None:
        super().__init__(parent)
        self.store = store
        self.base = server or Server(name="", host="", user=os.environ.get("USER", ""), tag=default_tag)
        self.result_server: Server | None = None
        self.setWindowTitle("Edit server" if server else "Add server")
        self.setMinimumWidth(560)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.addWidget(_header("Edit server" if server else "Add server",
                              "Only a name and host are required. Everything else is optional."))
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        b = self.base

        self.name = QLineEdit(b.name)
        self.name.setPlaceholderText("e.g. Homelab NAS")
        self.host = QLineEdit(b.host)
        self.host.setPlaceholderText("192.168.1.10 or nas.lan")
        self.user = QLineEdit(b.user)
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(b.port)
        conn = QHBoxLayout()
        conn.addWidget(self.user, 3)
        conn.addWidget(QLabel("Port"))
        conn.addWidget(self.port, 1)

        self.tag = QComboBox()
        self.tag.setEditable(True)
        self.tag.addItems(["", *store.tags()])
        self.tag.setCurrentText(b.tag)

        self.key = QLineEdit(b.key)
        self.key.setPlaceholderText("default: ssh-agent / ~/.ssh/id_*")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_key)
        key_row = QHBoxLayout()
        key_row.addWidget(self.key)
        key_row.addWidget(browse)

        self.jump = QLineEdit(b.jump)
        self.jump.setPlaceholderText("ProxyJump, e.g. me@bastion.example.com")

        self.mac = QLineEdit(b.mac)
        self.mac.setPlaceholderText("aa:bb:cc:dd:ee:ff — for Wake-on-LAN")
        detect = QPushButton("Detect")
        detect.setToolTip("Look the MAC address up in the ARP cache (host must be on your LAN)")
        detect.clicked.connect(self._detect_mac)
        mac_row = QHBoxLayout()
        mac_row.addWidget(self.mac)
        mac_row.addWidget(detect)

        self.remote_path = QLineEdit(b.remote_path)
        self.remote_path.setPlaceholderText(f"default {b.home_path if b.user else '/home/<user>'}")
        self.tmux = QCheckBox("Open a tmux session by default")
        self.tmux.setChecked(b.tmux)
        self.tray = QCheckBox("Monitor in the system tray")
        self.tray.setChecked(b.tray)
        self.notes = QPlainTextEdit(b.notes)
        self.notes.setPlaceholderText("Anything worth remembering about this machine")
        self.notes.setFixedHeight(64)

        form.addRow("Name", self.name)
        form.addRow("Host", self.host)
        form.addRow("User", conn)
        form.addRow("Tag", self.tag)
        form.addRow("Identity file", key_row)
        form.addRow("Jump host", self.jump)
        form.addRow("MAC address", mac_row)
        form.addRow("Remote folder", self.remote_path)
        form.addRow("", self.tmux)
        form.addRow("", self.tray)
        form.addRow("Notes", self.notes)
        lay.addLayout(form)

        self.error = QLabel("")
        self.error.setStyleSheet("color: #f87171; font-weight: 600;")
        lay.addWidget(self.error)
        box = _buttons(self, "Save" if server else "Add server")
        box.accepted.connect(self._accept)
        lay.addWidget(box)
        (self.host if server else self.name).setFocus()

    def _browse_key(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose identity file", str(paths.home() / ".ssh"))
        if path:
            home = str(paths.home())
            self.key.setText("~" + path[len(home):] if path.startswith(home) else path)

    def _detect_mac(self) -> None:
        host = self.host.text().strip()
        if not host:
            self.error.setText("Enter a host first")
            return
        mac = netscan.mac_for(host)
        if mac:
            self.mac.setText(mac)
            self.error.setText("")
        else:
            self.error.setText("No MAC found — the host must be awake and on your local network")

    def _accept(self) -> None:
        data = self.base.to_dict()
        data.update(
            name=self.name.text().strip(), host=self.host.text().strip(), user=self.user.text().strip(),
            port=self.port.value(), tag=self.tag.currentText().strip(), key=self.key.text().strip(),
            jump=self.jump.text().strip(), remote_path=self.remote_path.text().strip(),
            tmux=self.tmux.isChecked(), tray=self.tray.isChecked(), notes=self.notes.toPlainText().strip(),
        )
        try:
            data["mac"] = normalize_mac(self.mac.text())
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        srv = Server.from_dict(data)
        errors = srv.validate()
        clash = self.store.by_name(srv.name)
        if clash and clash.id != srv.id:
            errors.insert(0, f"A server named '{srv.name}' already exists")
        if errors:
            self.error.setText(errors[0])
            return
        self.result_server = srv
        self.accept()


# ==================================================================== scan
class _ScanSignals(QObject):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(object)


class ScanDialog(QDialog):
    def __init__(self, store: ServerStore, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.found: list[netscan.Discovered] = []
        self.cancel = threading.Event()
        self.sig = _ScanSignals()
        self.sig.progress.connect(self._progress)
        self.sig.finished.connect(self._finished)
        self.setWindowTitle("Scan network")
        self.resize(820, 560)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.addWidget(_header("Discover SSH servers",
                              "Probes every address in parallel and lists only hosts that answer with an SSH banner."))
        row = QHBoxLayout()
        self.net = QLineEdit(netscan.local_network())
        self.net.setToolTip("CIDR (192.168.1.0/24), prefix (192.168.1) or range (10.0.0.5-40)")
        self.ports = QLineEdit(netscan.DEFAULT_PORTS)
        self.scan_btn = QPushButton("Scan")
        self.scan_btn.setObjectName("Primary")
        self.scan_btn.clicked.connect(self.start)
        row.addWidget(QLabel("Network"))
        row.addWidget(self.net, 2)
        row.addWidget(QLabel("Ports"))
        row.addWidget(self.ports, 2)
        row.addWidget(self.scan_btn)
        lay.addLayout(row)

        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.hide()
        lay.addWidget(self.bar)
        self.status = QLabel("Ready.")
        self.status.setObjectName("Muted")
        lay.addWidget(self.status)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Address", "Hostname", "SSH server", "MAC", "Status"])
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.table, 1)

        opts = QHBoxLayout()
        self.user = QLineEdit(os.environ.get("USER", ""))
        self.tag = QLineEdit("LAN")
        opts.addWidget(QLabel("Default user"))
        opts.addWidget(self.user)
        opts.addWidget(QLabel("Tag"))
        opts.addWidget(self.tag)
        opts.addStretch()
        lay.addLayout(opts)
        self.box = _buttons(self, "Add selected")
        self.box.accepted.connect(self.accept)
        self.box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        lay.addWidget(self.box)

    def start(self) -> None:
        try:
            targets = netscan.parse_targets(self.net.text())
            ports = netscan.parse_ports(self.ports.text())
        except ValueError as exc:
            self.status.setText(f"✖ {exc}")
            return
        self.cancel.clear()
        self.table.setRowCount(0)
        self.scan_btn.setEnabled(False)
        self.bar.show()
        self.bar.setRange(0, len(targets) * len(ports))
        self.status.setText(f"Probing {len(targets)} addresses on {len(ports)} port(s)…")

        def work() -> None:
            try:
                res = netscan.scan(targets, ports, progress=self.sig.progress.emit, cancel=self.cancel)
            except Exception as exc:  # shown in the dialog
                res = exc
            self.sig.finished.emit(res)

        threading.Thread(target=work, daemon=True).start()

    def _progress(self, done: int, total: int) -> None:
        self.bar.setMaximum(total)
        self.bar.setValue(done)

    def _finished(self, res: object) -> None:
        self.scan_btn.setEnabled(True)
        self.bar.hide()
        if isinstance(res, Exception):
            self.status.setText(f"✖ Scan failed: {res}")
            return
        self.found = list(res)  # type: ignore[arg-type]
        existing = {(s.host, s.port): s for s in self.store.servers}
        self.table.setRowCount(len(self.found))
        for row, d in enumerate(self.found):
            saved = existing.get((d.ip, d.port))
            addr = QTableWidgetItem(f"{d.ip}:{d.port}")
            addr.setFlags(addr.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            addr.setCheckState(Qt.CheckState.Unchecked if saved else Qt.CheckState.Checked)
            self.table.setItem(row, 0, addr)
            for col, text in enumerate([d.hostname or "—", d.banner, d.mac or "—",
                                        f"saved as {saved.name}" if saved else "new"], start=1):
                self.table.setItem(row, col, QTableWidgetItem(text))
        n = len(self.found)
        self.status.setText(f"Found {n} SSH server{'s' if n != 1 else ''}." if n else "No SSH servers found.")
        self.box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(n))

    def selected(self) -> list[netscan.Discovered]:
        return [d for row, d in enumerate(self.found)
                if self.table.item(row, 0).checkState() == Qt.CheckState.Checked]

    def reject(self) -> None:
        self.cancel.set()
        super().reject()


# ================================================================== import
class ImportDialog(QDialog):
    def __init__(self, candidates: list[Server], parent=None) -> None:
        super().__init__(parent)
        self.candidates = candidates
        self.setWindowTitle("Import from ~/.ssh/config")
        self.resize(560, 480)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.addWidget(_header("Import from ~/.ssh/config", f"{len(candidates)} host(s) are not in sshm yet."))
        self.list = QListWidget()
        for s in candidates:
            item = QListWidgetItem(f"{s.name}    {s.endpoint}" + (f"  via {s.jump}" if s.jump else ""))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.list.addItem(item)
        lay.addWidget(self.list, 1)
        box = _buttons(self, "Import")
        box.accepted.connect(self.accept)
        lay.addWidget(box)

    def selected(self) -> list[Server]:
        return [s for i, s in enumerate(self.candidates)
                if self.list.item(i).checkState() == Qt.CheckState.Checked]


# ================================================================= tunnels
class TunnelDialog(QDialog):
    KINDS = (("Local forward (-L)", "L", "8080:localhost:80", "Reach a service on the remote side at localhost:<port>"),
             ("Remote forward (-R)", "R", "9000:localhost:3000", "Expose a local service on the remote host"),
             ("SOCKS proxy (-D)", "D", "1080", "Route traffic through the server via SOCKS5 on localhost"))

    def __init__(self, server: Server, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Port forward — {server.name}")
        self.setMinimumWidth(500)
        self.spec: TunnelSpec | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.addWidget(_header("New tunnel", f"Runs in the background through {server.endpoint}. "
                                            "Background tunnels need key-based login."))
        form = QFormLayout()
        self.kind = QComboBox()
        for label, *_ in self.KINDS:
            self.kind.addItem(label)
        self.text = QLineEdit(self.KINDS[0][2])
        self.help = QLabel(self.KINDS[0][3])
        self.help.setObjectName("Muted")
        self.kind.currentIndexChanged.connect(self._kind_changed)
        form.addRow("Type", self.kind)
        form.addRow("Forward", self.text)
        form.addRow("", self.help)
        lay.addLayout(form)
        self.error = QLabel("")
        self.error.setStyleSheet("color: #f87171; font-weight: 600;")
        lay.addWidget(self.error)
        box = _buttons(self, "Start tunnel")
        box.accepted.connect(self._accept)
        lay.addWidget(box)

    def _kind_changed(self, i: int) -> None:
        self.text.setText(self.KINDS[i][2])
        self.help.setText(self.KINDS[i][3])

    def _accept(self) -> None:
        try:
            self.spec = TunnelSpec.parse(self.KINDS[self.kind.currentIndex()][1], self.text.text())
        except TunnelError as exc:
            self.error.setText(str(exc))
            return
        self.accept()


# ================================================================ commands
class CommandDialog(QDialog):
    def __init__(self, command: CustomCommand | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Saved command")
        self.setMinimumWidth(520)
        self.command: CustomCommand | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.addWidget(_header("Edit command" if command else "New command",
                              "Runs on the server over SSH with a terminal attached."))
        form = QFormLayout()
        self.label = QLineEdit(command.label if command else "")
        self.label.setPlaceholderText("e.g. System update")
        self.cmd = QLineEdit(command.command if command else "")
        self.cmd.setPlaceholderText("e.g. sudo dnf upgrade -y")
        self.cmd.setObjectName("Mono")
        form.addRow("Label", self.label)
        form.addRow("Command", self.cmd)
        lay.addLayout(form)
        box = _buttons(self)
        box.accepted.connect(self._accept)
        lay.addWidget(box)

    def _accept(self) -> None:
        if not self.label.text().strip() or not self.cmd.text().strip():
            QMessageBox.warning(self, "Missing information", "Both a label and a command are required.")
            return
        self.command = CustomCommand(self.label.text().strip(), self.cmd.text().strip())
        self.accept()


# ================================================================ settings
class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, autostart: bool, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Settings")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.addWidget(_header("Settings", "Shared by the desktop app, tray and terminal UI."))
        form = QFormLayout()
        form.setVerticalSpacing(10)

        self.theme = QComboBox()
        self.theme.addItems(theme_names())
        self.theme.setCurrentText(settings.theme)
        self.refresh = QComboBox()
        for v in REFRESH_CHOICES:
            self.refresh.addItem(f"Every {v} seconds" if v else "Manual only", v)
        idx = self.refresh.findData(settings.refresh_interval)
        if idx < 0:
            self.refresh.addItem(f"Every {settings.refresh_interval} seconds", settings.refresh_interval)
            idx = self.refresh.count() - 1
        self.refresh.setCurrentIndex(idx)
        self.timeout = QDoubleSpinBox()
        self.timeout.setRange(0.2, 10.0)
        self.timeout.setSingleStep(0.1)
        self.timeout.setSuffix(" s")
        self.timeout.setValue(settings.probe_timeout)
        self.terminal = QLineEdit(settings.terminal)
        self.terminal.setPlaceholderText("auto-detect (e.g. konsole, kitty, ghostty -e)")
        self.tmux = QLineEdit(settings.tmux_session)
        self.mount = QLineEdit(settings.mount_dir)
        self.notify = QCheckBox("Notify when a tray-monitored server goes up or down")
        self.notify.setChecked(settings.notifications)
        self.close_tray = QCheckBox("Closing the window keeps sshm running in the tray")
        self.close_tray.setChecked(settings.close_to_tray)
        self.autostart = QCheckBox("Start the tray monitor when I log in")
        self.autostart.setChecked(autostart)
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(settings.telemetry_port)
        self.legacy = QCheckBox("Accept unsigned telemetry from sshm 2.x agents")
        self.legacy.setChecked(settings.accept_legacy_agents)
        self.alerts = QCheckBox("Alert when a server goes down, runs hot, fills its disk or a container stops")
        self.alerts.setChecked(settings.alerts_enabled)
        thresholds = QHBoxLayout()
        self.a_cpu, self.a_mem, self.a_disk = QSpinBox(), QSpinBox(), QSpinBox()
        for label, box, value in (("CPU", self.a_cpu, settings.alert_cpu), ("Memory", self.a_mem, settings.alert_mem),
                                  ("Disk", self.a_disk, settings.alert_disk)):
            box.setRange(10, 100)
            box.setSuffix(" %")
            box.setValue(value)
            thresholds.addWidget(QLabel(label))
            thresholds.addWidget(box)
        self.a_sustain = QSpinBox()
        self.a_sustain.setRange(1, 60)
        self.a_sustain.setSuffix(" min")
        self.a_sustain.setValue(settings.alert_sustain_minutes)
        thresholds.addWidget(QLabel("for"))
        thresholds.addWidget(self.a_sustain)
        thresholds.addStretch()

        form.addRow("Theme", self.theme)
        form.addRow("Auto-refresh", self.refresh)
        form.addRow("Probe timeout", self.timeout)
        form.addRow("Terminal", self.terminal)
        form.addRow("tmux session", self.tmux)
        form.addRow("Mount folder", self.mount)
        form.addRow("Telemetry port", self.port)
        form.addRow("", self.legacy)
        form.addRow("Alerts", self.alerts)
        form.addRow("Thresholds", thresholds)
        form.addRow("", self.notify)
        form.addRow("", self.close_tray)
        form.addRow("", self.autostart)
        lay.addLayout(form)
        note = QLabel("Changing the telemetry port requires redeploying agents and restarting sshm.")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        lay.addWidget(note)
        box = _buttons(self)
        box.accepted.connect(self._accept)
        lay.addWidget(box)

    def _accept(self) -> None:
        s = self.settings
        s.theme = self.theme.currentText()
        s.refresh_interval = int(self.refresh.currentData())
        s.probe_timeout = round(self.timeout.value(), 1)
        s.terminal = self.terminal.text().strip()
        s.tmux_session = self.tmux.text().strip() or "sshm"
        s.mount_dir = self.mount.text().strip() or "~/Network_Servers"
        s.telemetry_port = self.port.value()
        s.accept_legacy_agents = self.legacy.isChecked()
        s.alerts_enabled = self.alerts.isChecked()
        s.alert_cpu, s.alert_mem, s.alert_disk = self.a_cpu.value(), self.a_mem.value(), self.a_disk.value()
        s.alert_sustain_minutes = self.a_sustain.value()
        s.notifications = self.notify.isChecked()
        s.close_to_tray = self.close_tray.isChecked()
        s.save()
        self.accept()


def show_export(parent: QWidget, servers: list[Server]) -> None:
    dlg = QDialog(parent)
    dlg.setWindowTitle("Export as ssh_config")
    dlg.resize(640, 520)
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(24, 20, 24, 20)
    lay.addWidget(_header("ssh_config export", "Paste into ~/.ssh/config to use these hosts with plain ssh/scp/rsync."))
    text = QPlainTextEdit(sshconfig.export(servers))
    text.setReadOnly(True)
    text.setObjectName("Mono")
    lay.addWidget(text, 1)
    row = QHBoxLayout()
    copy = QPushButton("Copy to clipboard")
    copy.setObjectName("Primary")

    def do_copy() -> None:
        from PyQt6.QtWidgets import QApplication

        QApplication.clipboard().setText(text.toPlainText())
        copy.setText("Copied ✓")

    copy.clicked.connect(do_copy)
    close = QPushButton("Close")
    close.clicked.connect(dlg.accept)
    row.addStretch()
    row.addWidget(close)
    row.addWidget(copy)
    lay.addLayout(row)
    dlg.exec()
