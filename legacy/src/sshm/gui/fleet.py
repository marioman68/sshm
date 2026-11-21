"""Desktop dialogs: run a command on many servers, and the alerts / activity log."""

from __future__ import annotations

import html
import threading
from typing import ClassVar

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sshm.core import fleet
from sshm.core.models import Server
from sshm.gui.controller import Controller

ROLE = Qt.ItemDataRole.UserRole.value + 20


class _Signals(QObject):
    result = pyqtSignal(object)
    finished = pyqtSignal()


class FleetDialog(QDialog):
    """Pick servers, type a command, see every server's output side by side."""

    history: ClassVar[list[str]] = ["uptime", "df -h /", "free -h", "sudo -n dnf -y upgrade --refresh",
                          "sudo -n apt-get update && sudo -n apt-get -y upgrade", "docker ps"]

    def __init__(self, ctrl: Controller, preselect: list[str] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.ctrl = ctrl
        self.results: dict[str, fleet.RunResult] = {}
        self.cancel = threading.Event()
        self.running = False
        self.sig = _Signals()
        self.sig.result.connect(self._on_result)
        self.sig.finished.connect(self._on_finished)
        self.setWindowTitle("Run on many servers")
        self.resize(1040, 660)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        title = QLabel("<b style='font-size:15pt'>Run on many servers</b>")
        lay.addWidget(title)
        sub = QLabel("Runs in parallel over key-based SSH without a terminal — <code>sudo</code> needs "
                     "NOPASSWD (use <code>sudo -n</code> to fail fast instead of hanging).")
        sub.setObjectName("Muted")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 8, 0)
        quick = QHBoxLayout()
        for label, fn in (("All", lambda: self._check(lambda s: True)), ("None", lambda: self._check(lambda s: False)),
                          ("Online", lambda: self._check(self._is_online))):
            b = QPushButton(label)
            b.setObjectName("Flat")
            b.clicked.connect(fn)
            quick.addWidget(b)
        self.tag_pick = QComboBox()
        self.tag_pick.addItem("Select tag…", None)
        for t in ctrl.store.tags():
            self.tag_pick.addItem(t, t)
        self.tag_pick.activated.connect(self._pick_tag)
        quick.addWidget(self.tag_pick, 1)
        ll.addLayout(quick)
        self.servers = QListWidget()
        for srv in ctrl.servers:
            item = QListWidgetItem(f"{srv.name}    {srv.endpoint}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if preselect and srv.id in preselect else Qt.CheckState.Unchecked)
            item.setData(ROLE, srv.id)
            self.servers.addItem(item)
        ll.addWidget(self.servers, 1)
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        cmd_row = QHBoxLayout()
        self.command = QComboBox()
        self.command.setEditable(True)
        self.command.addItems(self.history)
        self.command.setCurrentText(self.history[0])
        self.command.lineEdit().returnPressed.connect(self.run)
        self.command.lineEdit().setObjectName("Mono")
        cmd_row.addWidget(self.command, 1)
        self.run_btn = QPushButton("Run")
        self.run_btn.setObjectName("Primary")
        self.run_btn.clicked.connect(self.run)
        cmd_row.addWidget(self.run_btn)
        rl.addLayout(cmd_row)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Server", "Result", "Time", "Last line"])
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for i, w in enumerate((160, 90, 60)):
            hdr.resizeSection(i, w)
        hdr.setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._show_output)
        rl.addWidget(self.table, 2)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setObjectName("Mono")
        self.output.setPlaceholderText("Select a server above to see its full output")
        rl.addWidget(self.output, 3)
        split.addWidget(right)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 5)
        lay.addWidget(split, 1)

        foot = QHBoxLayout()
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        foot.addWidget(self.status, 1)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        foot.addWidget(close)
        lay.addLayout(foot)

    # ------------------------------------------------------------ selection
    def _is_online(self, srv: Server) -> bool:
        st = self.ctrl.status(srv)
        return bool(st and st.online)

    def _check(self, pred) -> None:
        for i in range(self.servers.count()):
            item = self.servers.item(i)
            srv = self.ctrl.store.get(item.data(ROLE))
            item.setCheckState(Qt.CheckState.Checked if srv and pred(srv) else Qt.CheckState.Unchecked)

    def _pick_tag(self, idx: int) -> None:
        tag = self.tag_pick.itemData(idx)
        if tag:
            self._check(lambda s: s.tag == tag)
        self.tag_pick.setCurrentIndex(0)

    def selected_servers(self) -> list[Server]:
        out = []
        for i in range(self.servers.count()):
            item = self.servers.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                srv = self.ctrl.store.get(item.data(ROLE))
                if srv:
                    out.append(srv)
        return out

    # ------------------------------------------------------------- running
    def run(self) -> None:
        if self.running:
            self.cancel.set()
            return
        command = self.command.currentText().strip()
        servers = self.selected_servers()
        if not command or not servers:
            self.status.setText("Pick at least one server and enter a command.")
            return
        if command not in type(self).history:
            type(self).history.insert(0, command)
        self.results.clear()
        self.output.clear()
        self.table.setRowCount(len(servers))
        self._rows = {s.id: i for i, s in enumerate(servers)}
        for i, s in enumerate(servers):
            for col, text in enumerate((s.name, "running…", "", "")):
                self.table.setItem(i, col, QTableWidgetItem(text))
        self.running = True
        self.cancel.clear()
        self.run_btn.setText("Cancel")
        self.status.setText(f"Running on {len(servers)} server(s)…")

        def work() -> None:
            fleet.run_many(servers, command, on_result=self.sig.result.emit, cancel=self.cancel)
            self.sig.finished.emit()

        threading.Thread(target=work, daemon=True, name="sshm-fleet").start()

    def _on_result(self, res: fleet.RunResult) -> None:
        self.results[res.server.id] = res
        row = getattr(self, "_rows", {}).get(res.server.id)
        if row is None:
            return
        theme = getattr(self.parent(), "theme", None)
        status = "✔ ok" if res.ok else (f"✖ exit {res.returncode}" if res.returncode is not None else "✖ failed")
        for col, text in ((1, status), (2, f"{res.seconds:.1f}s"), (3, res.summary)):
            item = self.table.item(row, col)
            if item is not None:
                item.setText(text)
        if theme is not None and self.table.item(row, 1) is not None:
            self.table.item(row, 1).setForeground(QColor(theme.success if res.ok else theme.danger))
        if self.table.currentRow() == row:
            self._show_output()
        done = len(self.results)
        self.status.setText(f"{done}/{self.table.rowCount()} finished · {sum(r.ok for r in self.results.values())} ok")

    def _on_finished(self) -> None:
        self.running = False
        self.run_btn.setText("Run")
        ok = sum(r.ok for r in self.results.values())
        self.status.setText(f"Done — {ok}/{len(self.results)} succeeded" +
                            (" (cancelled)" if self.cancel.is_set() else ""))
        if self.table.currentRow() < 0 and self.table.rowCount():
            self.table.selectRow(0)

    def _show_output(self) -> None:
        row = self.table.currentRow()
        sid = next((k for k, v in getattr(self, "_rows", {}).items() if v == row), None)
        res = self.results.get(sid) if sid else None
        if res is None:
            self.output.setPlainText("still running…" if self.running else "")
            return
        text = res.stdout
        if res.stderr.strip():
            text += ("\n" if text and not text.endswith("\n") else "") + "── stderr ──\n" + res.stderr
        self.output.setPlainText(text or "(no output)")

    def closeEvent(self, event) -> None:
        self.cancel.set()
        super().closeEvent(event)


class ActivityDialog(QDialog):
    """Active alerts plus the event log."""

    def __init__(self, ctrl: Controller, parent=None) -> None:
        super().__init__(parent)
        self.ctrl = ctrl
        self.setWindowTitle("Alerts & activity")
        self.resize(820, 560)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        head = QHBoxLayout()
        head.addWidget(QLabel("<b style='font-size:15pt'>Alerts &amp; activity</b>"))
        head.addStretch()
        self.owner = QLabel("")
        self.owner.setObjectName("Muted")
        head.addWidget(self.owner)
        lay.addLayout(head)
        self.active = QLabel("")
        self.active.setWordWrap(True)
        self.active.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.active)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["When", "", "Event"])
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hdr.resizeSection(0, 120)
        hdr.resizeSection(1, 30)
        hdr.setStretchLastSection(True)
        lay.addWidget(self.table, 1)
        foot = QHBoxLayout()
        note = QLabel("Thresholds and on/off: Settings → Alerts. Only servers shown in the tray are watched.")
        note.setObjectName("Muted")
        foot.addWidget(note, 1)
        clear = QPushButton("Clear log")
        clear.clicked.connect(self._clear)
        foot.addWidget(clear)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        foot.addWidget(close)
        lay.addLayout(foot)
        ctrl.events_raised.connect(self._on_events)
        self.reload()

    def _on_events(self, _events) -> None:
        self.reload()

    def closeEvent(self, event) -> None:
        try:
            self.ctrl.events_raised.disconnect(self._on_events)
        except (TypeError, RuntimeError):
            pass
        super().closeEvent(event)

    def reload(self) -> None:
        theme = getattr(self.parent(), "theme", None)
        hist = self.ctrl.hub.history
        self.owner.setText("recording here" if self.ctrl.hub.recording else "recorded by another sshm window")
        active = hist.active()
        if active:
            color = theme.danger if theme else "#f87171"
            rows = "".join(f"<br>● {html.escape(e.message)}" for e in active)
            self.active.setText(f"<b style='color:{color}'>{len(active)} active alert(s)</b>{rows}")
        else:
            ok = theme.success if theme else "#4ade80"
            self.active.setText(f"<span style='color:{ok}'>✔ No active alerts</span>")
        events = hist.events(500)
        self.table.setRowCount(len(events))
        for r, ev in enumerate(events):
            icon = "✔" if ev.resolved else {"critical": "✖", "warning": "⚠"}.get(ev.severity, "ℹ")
            items = [QTableWidgetItem(ev.time_label), QTableWidgetItem(icon), QTableWidgetItem(ev.message)]
            if theme is not None:
                col = theme.success if ev.resolved else {"critical": theme.danger, "warning": theme.warning}.get(
                    ev.severity, theme.info)
                items[1].setForeground(QColor(col))
            for c, it in enumerate(items):
                self.table.setItem(r, c, it)

    def _clear(self) -> None:
        if QMessageBox.question(self, "Clear log", "Delete the whole event log?") == QMessageBox.StandardButton.Yes:
            self.ctrl.hub.history.clear_events()
            self.reload()
