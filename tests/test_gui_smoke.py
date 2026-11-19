"""Offscreen smoke test for the desktop app (skipped when PyQt6 is unavailable)."""

import os

import pytest

pytest.importorskip("PyQt6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from sshm.core.models import CustomCommand, Server
from sshm.core.store import ServerStore


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication(["sshm-test"])


def test_main_window_lifecycle(app):
    store = ServerStore()
    store.add(Server(name="nas", host="127.0.0.1", port=1, tag="Homelab", mac="aa:bb:cc:dd:ee:ff",
                     commands=[CustomCommand("Uptime", "uptime")]))
    store.add(Server(name="pi", host="192.0.2.1", favorite=True))

    from sshm.gui.controller import Controller
    from sshm.gui.main_window import MainWindow
    from sshm.gui.style import app_icon, dot_icon
    from sshm.gui.tray import Tray

    ctrl = Controller()
    win = MainWindow(ctrl)
    win.show()
    app.processEvents()
    assert win.list.count() == 2
    win.search.setText("nas")
    app.processEvents()
    assert win.list.count() == 1
    win.search.clear()
    for theme in ("Daylight", "Cyber Neon"):
        ctrl.settings.theme = theme
        win.apply_theme()
    win.refresh_view()
    win._fill_files_menu()
    win._fill_more_menu()
    tray = Tray(ctrl, win.bring_to_front, lambda: None)
    tray._rebuild()
    tray._update_icon(force=True)
    assert not app_icon("partial").isNull() and not dot_icon("#00ff00").isNull()
    win.quitting = True
    win.close()
    ctrl.shutdown()


def test_dialogs_construct(app):
    from sshm.core.settings import Settings
    from sshm.gui.dialogs import CommandDialog, ImportDialog, ServerDialog, SettingsDialog, TunnelDialog

    store = ServerStore()
    srv = Server(name="x", host="h")
    for dlg in (ServerDialog(store), ServerDialog(store, srv), TunnelDialog(srv), CommandDialog(),
                SettingsDialog(Settings.load(), False), ImportDialog([srv])):
        dlg.show()
        app.processEvents()
        dlg.reject()
    d = ServerDialog(store)
    d.name.setText("new")
    d.host.setText("10.0.0.1")
    d._accept()
    assert d.result_server and d.result_server.host == "10.0.0.1"


def test_process_window(app):
    from sshm.gui.controller import Controller
    from sshm.gui.procview import ProcessWindow

    srv = ServerStore().add(Server(name="box", host="192.0.2.1"))
    ctrl = Controller()
    win = ProcessWindow(ctrl, srv)
    win._loaded(__import__("sshm.core.procs", fromlist=["parse"]).parse(
        "SSHM_GNU\n  1 root 0.5 0.1 1000 60 init /sbin/init\n 42 me 55.0 2.0 2048 5 python python app.py\n"))
    assert win.proxy.rowCount() == 2
    win.filter.setText("python")
    assert win.proxy.rowCount() == 1
    win.filter.setText("42")            # exact PID wins over substring matches
    assert win.proxy.rowCount() == 1
    win.filter.clear()
    win.table.selectRow(0)
    pid = win.selected_pid()
    win._apply(list(reversed(win.model.rows)))   # refresh keeps the selection on the same process
    assert win.selected_pid() == pid
    win.close()
    win._loaded([])                     # late result after close must be ignored
    win.timer.stop()
    win.close()
    ctrl.shutdown()


def test_container_widgets(app):
    from sshm.core import containers as ct
    from sshm.gui.controller import Controller
    from sshm.gui.main_window import MainWindow

    store = ServerStore()
    host = store.add(Server(name="Homelab Node", host="10.9.9.9"))
    mc = store.add(Server(name="Minecraft_server", host="10.9.9.9", port=2222))
    ctrl = Controller()
    hc = ct.parse_discovery("SSHM_RT docker\n" + __import__("json").dumps(
        {"ID": "a" * 64, "Names": "minecraft", "Image": "itzg/minecraft-server", "State": "running",
         "Status": "Up 1 hour", "Ports": "0.0.0.0:2222->22/tcp, 0.0.0.0:25565->25565/tcp, 0.0.0.0:8080->80/tcp"})
        + "\nSSHM_STATS\n")
    hc.host_id = host.id
    ctrl.hub.ssh_containers[host.id] = hc
    win = MainWindow(ctrl)
    win.select_server(mc.id)
    win.refresh_view()
    assert win.container_card.isVisibleTo(win) and win.container_card.link.container.name == "minecraft"
    win.select_server(host.id)
    win.refresh_view()
    assert win.containers_tab.table.rowCount() == 1
    win.quitting = True
    win.close()
    ctrl.shutdown()


def test_fleet_and_activity_dialogs(app):
    from sshm.core.history import Event
    from sshm.gui.controller import Controller
    from sshm.gui.fleet import ActivityDialog, FleetDialog

    store = ServerStore()
    a = store.add(Server(name="alpha", host="192.0.2.1", tag="Lab"))
    store.add(Server(name="beta", host="192.0.2.2"))
    ctrl = Controller()
    dlg = FleetDialog(ctrl, [a.id])
    assert [s.name for s in dlg.selected_servers()] == ["alpha"]
    dlg._check(lambda s: True)
    assert len(dlg.selected_servers()) == 2
    dlg.close()
    ctrl.hub.history.add_event(Event(1.8e9, a.id, "alpha", "offline", "critical", "alpha is down"))
    act = ActivityDialog(ctrl)
    assert act.table.rowCount() == 1 and "1 active" in act.active.text()
    act.close()
    ctrl.events_raised.emit([])   # must not touch the closed dialog
    ctrl.shutdown()
