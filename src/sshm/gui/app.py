"""Desktop entry points: ``sshm-gui`` (window) and ``sshm-tray`` (tray first).

A single process serves both: launching ``sshm-gui`` while the tray is
running just raises the existing window, via a per-user local socket.
"""

from __future__ import annotations

import argparse
import signal
import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication, QStyleFactory, QSystemTrayIcon

from sshm import APP_ID, APP_TITLE, __version__
from sshm.core import paths


def _notify_running_instance(command: bytes) -> bool:
    sock = QLocalSocket()
    sock.connectToServer(paths.ipc_socket_name())
    if not sock.waitForConnected(400):
        return False
    sock.write(command)
    sock.flush()
    sock.waitForBytesWritten(400)
    sock.disconnectFromServer()
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sshm-gui", description=f"{APP_TITLE} desktop app")
    parser.add_argument("--tray", action="store_true", help="start hidden in the system tray")
    parser.add_argument("--gui", action="store_true", help="open the main window (default)")
    parser.add_argument("--no-tray", action="store_true", help="do not create a tray icon")
    parser.add_argument("--version", action="version", version=f"sshm {__version__}")
    args, qt_args = parser.parse_known_args(sys.argv[1:] if argv is None else argv)

    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName("sshm")
    app.setApplicationDisplayName(APP_TITLE)
    app.setApplicationVersion(__version__)
    app.setDesktopFileName(APP_ID)
    if "Fusion" in QStyleFactory.keys():  # noqa: SIM118 - Qt returns a list
        app.setStyle("Fusion")

    show_window = not args.tray
    if _notify_running_instance(b"show" if show_window else b"ping"):
        return 0

    server = QLocalServer()
    QLocalServer.removeServer(paths.ipc_socket_name())
    server.listen(paths.ipc_socket_name())

    # heavy imports after the single-instance check keeps a second launch instant
    from sshm.gui.controller import Controller
    from sshm.gui.main_window import MainWindow
    from sshm.gui.tray import Tray

    ctrl = Controller()
    window = MainWindow(ctrl)
    tray_ok = not args.no_tray and QSystemTrayIcon.isSystemTrayAvailable()
    window.tray_available = tray_ok
    app.setQuitOnLastWindowClosed(not tray_ok)

    def quit_app() -> None:
        window._save_geometry()
        window.quitting = True
        app.quit()

    tray = Tray(ctrl, window.bring_to_front, quit_app, window.open_processes, window.open_activity) \
        if tray_ok else None
    if tray:
        tray.show()

    def on_connection() -> None:
        conn = server.nextPendingConnection()
        if conn is None:
            return

        def read() -> None:
            if bytes(conn.readAll()).strip() == b"show":
                window.bring_to_front()

        conn.readyRead.connect(read)
        conn.disconnected.connect(conn.deleteLater)

    server.newConnection.connect(on_connection)

    if show_window or not tray_ok:
        window.show()

    # let Ctrl+C in a terminal quit cleanly
    signal.signal(signal.SIGINT, lambda *_: quit_app())
    keepalive = QTimer()
    keepalive.timeout.connect(lambda: None)
    keepalive.start(400)

    rc = app.exec()
    ctrl.shutdown()
    server.close()
    return rc


def main_gui() -> int:
    return main(["--gui", *sys.argv[1:]])


def main_tray() -> int:
    return main(["--tray", *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
