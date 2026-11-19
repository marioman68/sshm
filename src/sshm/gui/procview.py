"""Live process viewer window for the desktop app.

Uses a model/view table (QAbstractTableModel + QSortFilterProxyModel) so a
refresh only swaps a Python list and emits one reset — no per-cell widgets,
and column widths are sized once instead of being re-measured on every update.
"""

from __future__ import annotations

import html
import time

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
)

from sshm.core import procs
from sshm.core.models import Server
from sshm.gui.controller import Controller

REFRESH_MS = 3000
HEADERS = ["PID", "User", "CPU %", "Mem %", "RSS", "Running", "Command"]
WIDTHS = [70, 110, 70, 70, 80, 80]  # last column stretches
SORT_ROLE = Qt.ItemDataRole.UserRole.value + 10
DISPLAY = Qt.ItemDataRole.DisplayRole.value
ALIGN = Qt.ItemDataRole.TextAlignmentRole.value
FOREGROUND = Qt.ItemDataRole.ForegroundRole.value
TOOLTIP = Qt.ItemDataRole.ToolTipRole.value
RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter


def _role(role) -> int:
    """Qt may hand us an enum member or a plain int; compare as ints."""
    return int(getattr(role, "value", role))


class ProcessModel(QAbstractTableModel):
    def __init__(self, theme=None, parent=None) -> None:
        super().__init__(parent)
        self.rows: list[procs.Process] = []
        self.theme = theme

    def set_rows(self, rows: list[procs.Process]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return len(HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role=DISPLAY):
        role = _role(role)
        if orientation == Qt.Orientation.Horizontal and role == DISPLAY:
            return HEADERS[section]
        if orientation == Qt.Orientation.Horizontal and role == ALIGN:
            return LEFT if section in (1, 6) else RIGHT
        return None

    def data(self, index: QModelIndex, role=DISPLAY):
        if not index.isValid() or index.row() >= len(self.rows):
            return None
        role = _role(role)
        p = self.rows[index.row()]
        col = index.column()
        if role == DISPLAY:
            return (
                str(p.pid), p.user,
                "--" if p.cpu is None else f"{p.cpu:.1f}",
                "--" if p.mem is None else f"{p.mem:.1f}",
                p.rss_label, p.elapsed_label, p.command,
            )[col]
        if role == SORT_ROLE:
            return (p.pid, p.user.lower(), p.cpu or 0.0, p.mem or 0.0, p.rss, p.elapsed or 0,
                    p.command.lower())[col]
        if role == ALIGN:
            return LEFT if col in (1, 6) else RIGHT
        if role == FOREGROUND and col == 2 and self.theme and p.cpu is not None and p.cpu >= 25:
            return QColor(self.theme.danger if p.cpu >= 80 else self.theme.warning)
        if role == TOOLTIP and col == 6:
            return p.command
        return None


class ProcessFilter(QSortFilterProxyModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.query = ""
        self._exact_pid: int | None = None  # computed once per filter pass, not once per row
        self.setSortRole(SORT_ROLE)
        self.setDynamicSortFilter(True)

    def setSourceModel(self, model: ProcessModel) -> None:
        super().setSourceModel(model)
        model.modelAboutToBeReset.connect(lambda: setattr(self, "_exact_pid", None))
        model.modelReset.connect(self._recompute)

    def _recompute(self) -> None:
        model: ProcessModel = self.sourceModel()  # type: ignore[assignment]
        q = self.query
        self._exact_pid = int(q) if q.isdigit() and any(r.pid == int(q) for r in model.rows) else None

    def set_query(self, text: str) -> None:
        self.query = text.strip().lower()
        self._recompute()
        self.invalidateFilter()

    def filterAcceptsRow(self, row: int, parent: QModelIndex) -> bool:
        if not self.query:
            return True
        model: ProcessModel = self.sourceModel()  # type: ignore[assignment]
        p = model.rows[row]
        if self._exact_pid is not None:
            return p.pid == self._exact_pid
        return self.query in p.command.lower() or self.query in p.name.lower() or self.query == p.user.lower()


class ProcessWindow(QDialog):
    def __init__(self, ctrl: Controller, server: Server, parent=None) -> None:
        super().__init__(parent)
        self.ctrl = ctrl
        self.server = server
        self.busy = False
        self.closed = False
        self.loaded_at = 0.0
        self.setWindowTitle(f"Processes — {server.name}")
        self.resize(980, 620)
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        head = QHBoxLayout()
        title = QLabel(f"<b style='font-size:15pt'>{html.escape(server.name)}</b>&nbsp;&nbsp;"
                       f"<span style='opacity:.7'>{html.escape(server.endpoint)}</span>")
        head.addWidget(title)
        head.addStretch()
        self.status = QLabel("Connecting…")
        self.status.setObjectName("Muted")
        head.addWidget(self.status)
        lay.addLayout(head)

        bar = QHBoxLayout()
        self.filter = QLineEdit()
        self.filter.setObjectName("Search")
        self.filter.setPlaceholderText("Filter by command, user or PID…")
        self.filter.setClearButtonEnabled(True)
        bar.addWidget(self.filter, 1)
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setCheckable(True)
        self.pause_btn.toggled.connect(self._pause_toggled)
        bar.addWidget(self.pause_btn)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        bar.addWidget(refresh)
        lay.addLayout(bar)

        self.model = ProcessModel(getattr(parent, "theme", None), self)
        self.proxy = ProcessFilter(self)
        self.proxy.setSourceModel(self.model)
        self.filter.textChanged.connect(self._filter_changed)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(2, Qt.SortOrder.DescendingOrder)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)  # never ResizeToContents: O(rows) per update
        for col, width in enumerate(WIDTHS):
            hdr.resizeSection(col, width)
        hdr.setStretchLastSection(True)
        self.table.doubleClicked.connect(lambda _i: self.show_details())
        lay.addWidget(self.table, 1)

        foot = QHBoxLayout()
        self.error = QLabel("")
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #f87171;")
        foot.addWidget(self.error, 1)
        htop = QPushButton("Open htop")
        htop.setToolTip("Interactive htop/top in a terminal")
        htop.clicked.connect(lambda: self.ctrl.launch(procs.top_argv(server), f"htop · {server.name}"))
        self.kill_btn = QPushButton("End process")
        self.kill_btn.setObjectName("Danger")
        self.kill_btn.clicked.connect(lambda: self.kill(False))
        self.force_btn = QPushButton("Force kill")
        self.force_btn.setObjectName("Danger")
        self.force_btn.clicked.connect(lambda: self.kill(True))
        for b in (htop, self.kill_btn, self.force_btn):
            foot.addWidget(b)
        lay.addLayout(foot)
        self.table.selectionModel().selectionChanged.connect(lambda *_a: self._selection_changed())
        self._selection_changed()

        # single-shot rescheduling: the next refresh is queued only after the previous one
        # finished, so slow servers can never pile up requests
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._tick)
        self.age_timer = QTimer(self)
        self.age_timer.timeout.connect(self._update_status)
        self.age_timer.start(1000)
        self.refresh()

    # ------------------------------------------------------------ data
    def _tick(self) -> None:
        if self.closed:
            return
        if self.pause_btn.isChecked() or not self.isVisible() or self.isMinimized():
            self.timer.start(REFRESH_MS)  # check again later without fetching
            return
        self.refresh()

    def _pause_toggled(self, on: bool) -> None:
        self.pause_btn.setText("Resume" if on else "Pause")
        if not on:
            self.refresh()

    def refresh(self) -> None:
        if self.busy or self.closed:
            return
        self.busy = True
        self.timer.stop()
        server = self.server
        self.ctrl.run_async(lambda: procs.fetch(server), self._loaded)

    def _loaded(self, res: object) -> None:
        self.busy = False
        if self.closed:
            return  # window was closed while the request was in flight
        if isinstance(res, Exception):
            self.error.setText(f"{res}\nYou can still use “Open htop”, which runs in a terminal.")
            self.status.setText("Not connected")
        else:
            self.error.setText("")
            self._apply(res)  # type: ignore[arg-type]
            self.loaded_at = time.monotonic()
            self._update_status()
        self.timer.start(REFRESH_MS)

    def _apply(self, rows: list[procs.Process]) -> None:
        keep = self.selected_pid()
        scroll = self.table.verticalScrollBar().value()
        self.model.set_rows(rows)
        if keep is not None:
            self._select_pid(keep)
        self.table.verticalScrollBar().setValue(scroll)

    def _filter_changed(self, text: str) -> None:
        self.proxy.set_query(text)
        self._update_status()

    def _update_status(self) -> None:
        if not self.loaded_at:
            return
        total = self.model.rowCount()
        shown = self.proxy.rowCount()
        count = f"{shown} of {total}" if self.proxy.query else f"{total}"
        age = int(time.monotonic() - self.loaded_at)
        state = "paused" if self.pause_btn.isChecked() else f"updated {age}s ago"
        self.status.setText(f"{count} processes · {state}")

    # ------------------------------------------------------- selection
    def selected_proc(self) -> procs.Process | None:
        idx = self.table.selectionModel().currentIndex()
        if not idx.isValid() or not self.table.selectionModel().isRowSelected(idx.row(), QModelIndex()):
            return None
        src = self.proxy.mapToSource(idx)
        return self.model.rows[src.row()] if 0 <= src.row() < len(self.model.rows) else None

    def selected_pid(self) -> int | None:
        p = self.selected_proc()
        return p.pid if p else None

    def _select_pid(self, pid: int) -> None:
        for row, p in enumerate(self.model.rows):
            if p.pid == pid:
                idx = self.proxy.mapFromSource(self.model.index(row, 0))
                if idx.isValid():
                    self.table.selectRow(idx.row())
                return

    def _selection_changed(self) -> None:
        has = self.selected_pid() is not None
        self.kill_btn.setEnabled(has)
        self.force_btn.setEnabled(has)

    # --------------------------------------------------------- actions
    def show_details(self) -> None:
        proc = self.selected_proc()
        if not proc:
            return
        cpu = "--" if proc.cpu is None else f"{proc.cpu:.1f}"
        mem = "--" if proc.mem is None else f"{proc.mem:.1f}"
        QMessageBox.information(
            self, proc.name,
            f"<b>{html.escape(proc.name)}</b> — PID {proc.pid}<br>User: {html.escape(proc.user)}<br>"
            f"CPU: {cpu} % · Memory: {mem} % ({proc.rss_label})<br>Running: {proc.elapsed_label}"
            f"<br><br><code>{html.escape(proc.command)}</code>",
        )

    def kill(self, force: bool) -> None:
        proc = self.selected_proc()
        if not proc:
            return
        sig = "SIGKILL" if force else "SIGTERM"
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(f"Send {sig}")
        box.setText(f"{'Force kill' if force else 'End'} <b>{html.escape(proc.name)}</b> (PID {proc.pid}) "
                    f"on {html.escape(self.server.name)}?")
        box.setInformativeText(proc.command[:300])
        go = box.addButton("Force kill" if force else "End process", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is not go:
            return

        def done(res: object) -> None:
            if self.closed:
                return
            if isinstance(res, procs.ProcError) and "another user" in str(res):
                again = QMessageBox.question(
                    self, "Permission denied",
                    f"{proc.name} belongs to {proc.user}. Retry with sudo in a terminal?")
                if again == QMessageBox.StandardButton.Yes:
                    self.ctrl.launch(procs.sudo_kill_argv(self.server, proc.pid, force),
                                     f"sudo kill {proc.pid} · {self.server.name}", pause=True)
            elif isinstance(res, Exception):
                self.error.setText(str(res))
            else:
                self.ctrl.message.emit(str(res), "success")
            self.refresh()

        self.ctrl.run_async(lambda: procs.kill(self.server, proc.pid, force), done)

    def closeEvent(self, event) -> None:
        self.closed = True
        self.timer.stop()
        self.age_timer.stop()
        super().closeEvent(event)
