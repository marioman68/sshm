#!/usr/bin/env python3
import os
import sys
import socket
import subprocess
from pathlib import Path
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PyQt6.QtGui import QIcon, QAction, QPixmap, QPainter, QColor
from PyQt6.QtCore import QTimer, QThread, pyqtSignal, Qt

VERSION = "2.0.3"
CONFIG_FILE = Path.home() / ".ssh_servers"


def make_fallback_dot(online: bool) -> QIcon:
    """Fallback painted dot only used if a barebones WM has no icon theme installed."""
    pix = QPixmap(16, 16)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    color = QColor("#5fd700") if online else QColor("#ff3b30")
    painter.setBrush(color)
    painter.drawEllipse(2, 2, 12, 12)
    painter.end()
    return QIcon(pix)


def get_theme_icon(candidates: list[str], fallback: QIcon = None) -> QIcon:
    """Returns the first available icon from the active desktop theme."""
    for name in candidates:
        if QIcon.hasThemeIcon(name):
            return QIcon.fromTheme(name)
    return fallback if fallback else QIcon()


def resolve_status_icons() -> tuple[QIcon, QIcon]:
    """Detects the current DE ($XDG_CURRENT_DESKTOP) and selects native status icons."""
    de = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()

    if "KDE" in de:
        online_list = ["user-online", "state-ok", "emblem-checked", "network-connect"]
        offline_list = ["user-offline", "state-error", "emblem-error", "network-disconnect"]
    elif any(g in de for g in ("GNOME", "UNITY", "PANTHEON", "COSMIC", "CINNAMON", "XFCE", "MATE")):
        online_list = ["user-available", "emblem-default", "network-transmit-receive", "user-online"]
        offline_list = ["user-offline", "network-offline", "network-error", "dialog-error"]
    else:
        online_list = ["user-online", "state-ok", "user-available", "emblem-default"]
        offline_list = ["user-offline", "state-error", "network-offline", "dialog-error"]

    online_icon = get_theme_icon(online_list, make_fallback_dot(True))
    offline_icon = get_theme_icon(offline_list, make_fallback_dot(False))
    return online_icon, offline_icon


class StatusWorker(QThread):
    """Pings servers in the background so the tray menu stays buttery smooth."""
    results_ready = pyqtSignal(list)

    def check_server(self, host, port):
        try:
            res = subprocess.run(
                ["ping", "-c", "1", "-W", "1", host],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True
            )
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    if "time=" in line:
                        ms = line.split("time=")[1].split()[0]
                        return True, f"{int(float(ms) + 0.5)}ms"
                return True, "ON"
        except Exception:
            pass

        try:
            with socket.create_connection((host, int(port)), timeout=1):
                return True, "TCP"
        except Exception:
            return False, "Offline"

    def run(self):
        servers = []
        if CONFIG_FILE.exists():
            for line in CONFIG_FILE.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = (line.split("|") + [""] * 7)[:7]
                name, user, host, port, tag, mac, key = parts
                port = port if port else "22"
                online, lat = self.check_server(host, port)
                servers.append({
                    "name": name,
                    "user": user,
                    "host": host,
                    "port": port,
                    "tag": tag,
                    "mac": mac,
                    "key": key,
                    "online": online,
                    "lat": lat
                })
        self.results_ready.emit(servers)


class SSHMTray:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)

        self.tray = QSystemTrayIcon()
        tray_icon = get_theme_icon(["network-server-symbolic", "network-server", "network-workgroup"])
        self.tray.setIcon(tray_icon)
        self.tray.setToolTip(f"SSH Connection Hub Monitor (v{VERSION})")

        self.menu = QMenu()
        self.tray.setContextMenu(self.menu)

        self.icon_online, self.icon_offline = resolve_status_icons()

        self.servers = []
        self.worker = StatusWorker()
        self.worker.results_ready.connect(self.on_status_updated)

        self.build_menu()
        self.tray.show()

        self.refresh_status()
        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh_status)
        self.timer.start(30000)

    def refresh_status(self):
        if not self.worker.isRunning():
            self.worker.start()

    def on_status_updated(self, servers):
        self.servers = servers
        online_count = sum(1 for s in servers if s["online"])
        self.tray.setToolTip(f"sshm: {online_count}/{len(servers)} Servers Online")
        self.build_menu()

    def build_menu(self):
        self.menu.clear()

        header_icon = get_theme_icon(["network-workgroup-symbolic", "network-server-symbolic", "network-workgroup"])
        header = QAction(header_icon, "SSH CONNECTION HUB", self.menu)
        header.setEnabled(False)
        self.menu.addAction(header)
        self.menu.addSeparator()

        if not self.servers:
            empty = QAction("No servers configured in ~/.ssh_servers", self.menu)
            empty.setEnabled(False)
            self.menu.addAction(empty)
        else:
            for srv in self.servers:
                tag_str = f" [{srv['tag']}]" if srv["tag"] else ""
                title = f"{srv['name']}{tag_str}  —  {srv['lat']}"

                sub = QMenu(title, self.menu)
                sub.setIcon(self.icon_online if srv["online"] else self.icon_offline)

                # 1. Open Folder in GUI File Manager (Flat monochrome symbolic icon)
                act_folder = QAction(
                    get_theme_icon(["folder-symbolic", "folder-remote-symbolic", "document-open-folder"]),
                    "Open Network Folder",
                    sub
                )
                act_folder.triggered.connect(lambda checked=False, s=srv: self.open_folder(s))
                sub.addAction(act_folder)

                # 2. Connect via SSH in Terminal (Flat monochrome wireframe icon)
                act_ssh = QAction(
                    get_theme_icon(["utilities-terminal-symbolic", "run-build", "system-run-symbolic"]),
                    "Connect via SSH",
                    sub
                )
                act_ssh.triggered.connect(lambda checked=False, s=srv: self.connect_ssh(s))
                sub.addAction(act_ssh)

                # 3. Wake-on-LAN
                if srv["mac"]:
                    act_wol = QAction(
                        get_theme_icon(["network-wired-symbolic", "system-reboot-symbolic", "network-connect"]),
                        f"Wake-on-LAN ({srv['mac']})",
                        sub
                    )
                    act_wol.triggered.connect(lambda checked=False, s=srv: self.send_wol(s))
                    sub.addAction(act_wol)

                self.menu.addMenu(sub)

        self.menu.addSeparator()

        # Flat monochrome wireframe icon instead of the 3D terminal box
        act_hub = QAction(
            get_theme_icon(["utilities-terminal-symbolic", "window-new-symbolic", "configure"]),
            "Open sshm Console",
            self.menu
        )
        act_hub.triggered.connect(self.launch_hub)
        self.menu.addAction(act_hub)

        act_refresh = QAction(
            get_theme_icon(["view-refresh-symbolic", "view-refresh"]),
            "Refresh Status",
            self.menu
        )
        act_refresh.triggered.connect(self.refresh_status)
        self.menu.addAction(act_refresh)

        self.menu.addSeparator()

        # Clean flat monochrome close 'X' instead of the bright red box
        act_quit = QAction(
            get_theme_icon(["window-close-symbolic", "dialog-close", "process-stop-symbolic"]),
            "Exit Monitor",
            self.menu
        )
        act_quit.triggered.connect(self.app.quit)
        self.menu.addAction(act_quit)

    def launch_term_cmd(self, cmd_list):
        if subprocess.call(["which", "konsole"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
            subprocess.Popen(["konsole", "-e"] + cmd_list)
        elif subprocess.call(["which", "ptyxis"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
            subprocess.Popen(["ptyxis", "--"] + cmd_list)
        else:
            subprocess.Popen(["x-terminal-emulator", "-e"] + cmd_list)

    def open_folder(self, srv):
        target_dir = "/root" if srv["user"] == "root" else f"/home/{srv['user']}"
        url = f"sftp://{srv['user']}@{srv['host']}:{srv['port']}{target_dir}"
        subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def connect_ssh(self, srv):
        cmd = ["ssh", "-p", srv["port"]]
        if srv["key"]:
            key_path = os.path.expanduser(srv["key"])
            if os.path.exists(key_path):
                cmd.extend(["-i", key_path])
        cmd.append(f"{srv['user']}@{srv['host']}")
        self.launch_term_cmd(cmd)

    def send_wol(self, srv):
        try:
            mac_clean = srv["mac"].replace(":", "").replace("-", "")
            data = bytes.fromhex("FF" * 6 + mac_clean * 16)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                s.sendto(data, ("255.255.255.255", 9))
            self.tray.showMessage(
                "Wake-on-LAN",
                f"Magic packet sent to {srv['name']} ({srv['mac']}).",
                QSystemTrayIcon.MessageIcon.Information,
                2500
            )
        except Exception as e:
            self.tray.showMessage(
                "WoL Error",
                str(e),
                QSystemTrayIcon.MessageIcon.Critical,
                3000
            )

    def launch_hub(self):
        sshm_bin = str(Path.home() / ".local/bin/sshm")
        self.launch_term_cmd([sshm_bin])

    def run(self):
        sys.exit(self.app.exec())


if __name__ == "__main__":
    SSHMTray().run()
