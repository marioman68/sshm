#!/usr/bin/env python3
import os
import sys
import time
import socket
import subprocess
import concurrent.futures
import xml.etree.ElementTree as ET
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PyQt6.QtGui import QIcon, QAction, QPixmap, QPainter, QColor, QBrush, QPen
from PyQt6.QtCore import QTimer, QThread, pyqtSignal, Qt

CONFIG_FILE = Path.home() / ".ssh_servers"
MOUNT_DIR = Path.home() / "Network_Servers"
AUTOSTART_FILE = Path.home() / ".config/autostart/sshm-tray.desktop"
BIN_PATH = Path.home() / ".local/bin/sshm-tray"


def get_theme_icon(names, fallback_color=None):
    """Resolves native symbolic/desktop icons first (KDE Breeze / GTK)."""
    for name in names:
        if QIcon.hasThemeIcon(name):
            return QIcon.fromTheme(name)
    for name in names:
        base = name.replace("-symbolic", "")
        if QIcon.hasThemeIcon(base):
            return QIcon.fromTheme(base)
    if fallback_color:
        return make_status_dot(fallback_color)
    return QIcon()


def make_status_dot(hex_color, hollow=False):
    """Draws a crisp anti-aliased status LED icon for Online/Offline server rows."""
    pix = QPixmap(22, 22)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    color = QColor(hex_color)
    if hollow:
        pen = QPen(color, 2.2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(4, 4, 14, 14)
    else:
        glow = QColor(color)
        glow.setAlpha(65)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(glow))
        painter.drawEllipse(2, 2, 18, 18)

        painter.setBrush(QBrush(color))
        painter.drawEllipse(5, 5, 12, 12)

    painter.end()
    return QIcon(pix)


def make_tray_badge_icon(state):
    """Overlays a live Green / Amber / Red status dot onto the native network-server tray icon."""
    base_icon = get_theme_icon([
        "network-server-symbolic",
        "utilities-terminal-symbolic",
        "network-workgroup-symbolic",
        "network-server"
    ])
    pix = base_icon.pixmap(32, 32)
    if pix.isNull():
        pix = QPixmap(32, 32)
        pix.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    if state == "ALL_ON":
        badge_col = QColor("#52ff52")  # Bright Green
    elif state == "PARTIAL":
        badge_col = QColor("#ffb833")  # Amber Warning
    elif state == "ALL_OFF":
        badge_col = QColor("#ff4d4d")  # Crimson Offline
    else:
        badge_col = QColor("#888888")  # Muted Gray

    painter.setPen(QPen(QColor("#1e1e2e"), 2.0))
    painter.setBrush(QBrush(badge_col))
    painter.drawEllipse(20, 20, 10, 10)
    painter.end()
    return QIcon(pix)


def check_host_status(host, port=22):
    """
    Verifies the actual SSH TCP port is open FIRST (so powered-off WoL NICs or
    stale router caches don't fake an ONLINE ping), and measures live latency!
    """
    try:
        t0 = time.monotonic()
        with socket.create_connection((host, int(port)), timeout=1.0):
            tcp_ms = (time.monotonic() - t0) * 1000.0
    except Exception:
        return False, "OFFLINE"

    # Optional ICMP ping for exact network latency if available
    try:
        res = subprocess.run(
            ["ping", "-c", "1", "-W", "1", host],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=1.2
        )
        if res.returncode == 0:
            for part in res.stdout.split():
                if part.startswith("time="):
                    ms = float(part.split("=")[1])
                    return True, f"{ms:.0f}ms"
    except Exception:
        pass

    return True, f"{tcp_ms:.0f}ms"


class StatusScannerThread(QThread):
    """Runs parallel server checks in the background so the tray UI never stutters."""
    results_ready = pyqtSignal(dict)

    def __init__(self, servers):
        super().__init__()
        self.servers = servers

    def run(self):
        results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
            future_map = {
                executor.submit(check_host_status, srv["host"], srv["port"]): idx
                for idx, srv in enumerate(self.servers)
            }
            for future in concurrent.futures.as_completed(future_map):
                idx = future_map[future]
                try:
                    results[idx] = future.result()
                except Exception:
                    results[idx] = (False, "OFFLINE")
        self.results_ready.emit(results)


class SSHHubTray(QSystemTrayIcon):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.servers = []
        self.status_cache = {}
        self.scanner_thread = None

        self.icon_online = make_status_dot("#52ff52", hollow=False)
        self.icon_offline = make_status_dot("#ff4d4d", hollow=True)

        self.setIcon(make_tray_badge_icon("NONE"))
        self.setToolTip("SSH Connection Hub — Checking servers...")

        self.menu = QMenu()
        self.setContextMenu(self.menu)
        self.activated.connect(self.on_tray_activated)

        self.refresh_all(initial=True)
        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh_all)
        self.timer.start(10000)

        self.show()

    def load_servers(self):
        self.servers = []
        if not CONFIG_FILE.exists():
            return
        for line in CONFIG_FILE.read_text(errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = (line.split("|") + [""] * 7)[:7]
            name, user, host, port, tag, mac, key = parts
            self.servers.append({
                "name": name,
                "user": user,
                "host": host,
                "port": port if port else "22",
                "tag": tag,
                "mac": mac,
                "key": key,
            })

    def is_mounted(self, srv):
        safe_name = srv["name"].replace(" ", "_")
        if (MOUNT_DIR / f"{safe_name}.desktop").exists():
            return True
        xbel = Path.home() / ".local/share/user-places.xbel"
        target_str = f"sftp://{srv['user']}@{srv['host']}"
        if xbel.exists() and target_str in xbel.read_text(errors="ignore"):
            return True
        gtk = Path.home() / ".config/gtk-3.0/bookmarks"
        if gtk.exists() and target_str in gtk.read_text(errors="ignore"):
            return True
        return False

    def refresh_all(self, initial=False):
        self.load_servers()
        if initial:
            self.rebuild_menu()
        if not self.servers:
            self.setIcon(make_tray_badge_icon("NONE"))
            self.setToolTip("SSH Connection Hub (0 servers configured)")
            self.rebuild_menu()
            return
        if self.scanner_thread and self.scanner_thread.isRunning():
            return
        self.scanner_thread = StatusScannerThread(self.servers)
        self.scanner_thread.results_ready.connect(self.on_scan_finished)
        self.scanner_thread.start()

    def on_scan_finished(self, results):
        self.status_cache = results
        online_count = sum(1 for idx in range(len(self.servers)) if results.get(idx, (False, ""))[0])
        total = len(self.servers)

        if total == 0:
            state = "NONE"
        elif online_count == total:
            state = "ALL_ON"
        elif online_count == 0:
            state = "ALL_OFF"
        else:
            state = "PARTIAL"

        self.setIcon(make_tray_badge_icon(state))
        self.setToolTip(f"SSH Connection Hub — {online_count}/{total} Online")

        if not self.menu.isVisible():
            self.rebuild_menu()

    def rebuild_menu(self):
        self.menu.clear()

        # Header Action: Open Main TUI
        open_hub_act = QAction(
            get_theme_icon(["utilities-terminal-symbolic", "utilities-terminal"]),
            "Open SSH Connection Hub (sshm)",
            self.menu
        )
        font = open_hub_act.font()
        font.setBold(True)
        open_hub_act.setFont(font)
        open_hub_act.triggered.connect(self.launch_sshm_tui)
        self.menu.addAction(open_hub_act)
        self.menu.addSeparator()

        if not self.servers:
            empty_act = QAction("No servers configured yet", self.menu)
            empty_act.setEnabled(False)
            self.menu.addAction(empty_act)
        else:
            for idx, srv in enumerate(self.servers):
                is_on, lat = self.status_cache.get(idx, (False, "OFFLINE"))
                status_icon = self.icon_online if is_on else self.icon_offline
                tag_str = f" [{srv['tag']}]" if srv["tag"] else ""
                status_label = f"{lat}" if is_on else "OFFLINE"

                sub = QMenu(f"{srv['name']}{tag_str}  ({status_label})", self.menu)
                sub.setIcon(status_icon)

                ep_act = QAction(
                    get_theme_icon(["network-server-symbolic", "network-wired-symbolic"]),
                    f"{srv['user']}@{srv['host']}:{srv['port']}  —  {'ONLINE (' + lat + ')' if is_on else 'OFFLINE'}",
                    sub
                )
                ep_act.setEnabled(False)
                sub.addAction(ep_act)
                sub.addSeparator()

                ssh_act = QAction(
                    get_theme_icon(["utilities-terminal-symbolic", "terminal-symbolic"]),
                    "Connect via SSH (Terminal)",
                    sub
                )
                ssh_act.triggered.connect(lambda checked=False, s=srv: self.connect_ssh_terminal(s, use_tmux=False))
                sub.addAction(ssh_act)

                tmux_act = QAction(
                    get_theme_icon(["view-split-left-right-symbolic", "utilities-terminal-symbolic"]),
                    "Connect via SSH (Auto-tmux)",
                    sub
                )
                tmux_act.triggered.connect(lambda checked=False, s=srv: self.connect_ssh_terminal(s, use_tmux=True))
                sub.addAction(tmux_act)

                browse_act = QAction(
                    get_theme_icon(["folder-remote-symbolic", "system-file-manager-symbolic"]),
                    "Open Network Folder in File Manager",
                    sub
                )
                browse_act.triggered.connect(lambda checked=False, s=srv: self.browse_sftp(s))
                sub.addAction(browse_act)

                mounted = self.is_mounted(srv)
                mnt_act = QAction(
                    get_theme_icon(["folder-saved-search-symbolic", "bookmark-new-symbolic"]),
                    "Unmount from Network Places" if mounted else "Mount to Network Places",
                    sub
                )
                mnt_act.triggered.connect(lambda checked=False, s=srv: self.toggle_mount(s))
                sub.addAction(mnt_act)

                if srv["mac"]:
                    sub.addSeparator()
                    wol_act = QAction(
                        get_theme_icon(["system-reboot-symbolic", "network-wireless-hotspot-symbolic"]),
                        f"Wake-on-LAN ({srv['mac']})",
                        sub
                    )
                    wol_act.triggered.connect(lambda checked=False, s=srv: self.send_wol(s))
                    sub.addAction(wol_act)

                self.menu.addMenu(sub)

        self.menu.addSeparator()

        # Refresh Now
        ref_act = QAction(
            get_theme_icon(["view-refresh-symbolic", "reload"]),
            "Refresh Server Statuses Now",
            self.menu
        )
        ref_act.triggered.connect(lambda: self.refresh_all(initial=False))
        self.menu.addAction(ref_act)

        # Autostart Toggle (Uses the regular icon column instead of setCheckable
        # so Qt/KDE doesn't create an ugly double-gutter gap on the left!)
        is_auto = AUTOSTART_FILE.exists()
        auto_icon = self.icon_online if is_auto else make_status_dot("#7f849c", hollow=True)
        auto_label = "Launch at Login: Enabled (Click to Disable)" if is_auto else "Launch at Login: Disabled (Click to Enable)"
        auto_act = QAction(auto_icon, auto_label, self.menu)
        auto_act.triggered.connect(self.toggle_autostart)
        self.menu.addAction(auto_act)

        self.menu.addSeparator()

        # Quit
        quit_act = QAction(
            get_theme_icon(["application-exit-symbolic", "window-close-symbolic"]),
            "Quit Tray Monitor",
            self.menu
        )
        quit_act.triggered.connect(self.app.quit)
        self.menu.addAction(quit_act)

        # Force KDE DBusMenu to sync updated icons & labels
        self.setContextMenu(self.menu)

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.launch_sshm_tui()

    def launch_in_terminal(self, cmd_list):
        terms = [
            ["konsole", "-e"],
            ["ptyxis", "--"],
            ["gnome-terminal", "--"],
            ["xfce4-terminal", "-x"],
            ["kitty", "-e"],
            ["alacritty", "-e"],
            ["xterm", "-e"],
        ]
        for t in terms:
            if subprocess.run(["which", t[0]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
                subprocess.Popen(t + cmd_list)
                return

    def launch_sshm_tui(self):
        sshm_bin = str(Path.home() / ".local/bin/sshm")
        if not Path(sshm_bin).exists():
            sshm_bin = str(Path(__file__).resolve().parent / "sshm")
        self.launch_in_terminal([sshm_bin])

    def connect_ssh_terminal(self, srv, use_tmux=False):
        cmd = ["ssh", "-p", str(srv["port"])]
        if srv["key"]:
            key_path = os.path.expanduser(srv["key"])
            if os.path.exists(key_path):
                cmd += ["-i", key_path]
        target = f"{srv['user']}@{srv['host']}"
        if use_tmux:
            cmd += ["-t", target, "tmux attach || tmux new || $SHELL"]
        else:
            cmd.append(target)
        self.launch_in_terminal(cmd)

    def browse_sftp(self, srv):
        target_dir = "/root" if srv["user"] == "root" else f"/home/{srv['user']}"
        url = f"sftp://{srv['user']}@{srv['host']}:{srv['port']}{target_dir}"
        subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def toggle_mount(self, srv):
        MOUNT_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = srv["name"].replace(" ", "_")
        desktop_file = MOUNT_DIR / f"{safe_name}.desktop"
        target_dir = "/root" if srv["user"] == "root" else f"/home/{srv['user']}"
        url = f"sftp://{srv['user']}@{srv['host']}:{srv['port']}{target_dir}"
        xbel_file = Path.home() / ".local/share/user-places.xbel"
        gtk_file = Path.home() / ".config/gtk-3.0/bookmarks"

        if self.is_mounted(srv):
            desktop_file.unlink(missing_ok=True)
            if gtk_file.exists():
                lines = [
                    l for l in gtk_file.read_text(errors="ignore").splitlines()
                    if f"sftp://{srv['user']}@{srv['host']}" not in l
                ]
                gtk_file.write_text("\n".join(lines) + ("\n" if lines else ""))
            if xbel_file.exists():
                try:
                    tree = ET.parse(xbel_file)
                    root = tree.getroot()
                    for b in list(root.findall("bookmark")):
                        if f"sftp://{srv['user']}@{srv['host']}" in b.attrib.get("href", ""):
                            root.remove(b)
                    tree.write(xbel_file, encoding="UTF-8", xml_declaration=True)
                except Exception:
                    pass
        else:
            desktop_file.write_text(
                f"[Desktop Entry]\nIcon=folder-remote\nName={srv['name']} ({srv['user']}@{srv['host']})\nType=Link\nURL[$e]={url}\n"
            )
            desktop_file.chmod(0o755)
            if xbel_file.exists():
                try:
                    tree = ET.parse(xbel_file)
                    root = tree.getroot()
                    exists = any(
                        f"sftp://{srv['user']}@{srv['host']}" in b.attrib.get("href", "")
                        for b in root.findall("bookmark")
                    )
                    if not exists:
                        bm = ET.SubElement(root, "bookmark", {"href": url})
                        title = ET.SubElement(bm, "title")
                        title.text = f"SSH: {srv['name']}"
                        info = ET.SubElement(bm, "info")
                        meta = ET.SubElement(info, "metadata", {"owner": "http://freedesktop.org"})
                        ET.SubElement(
                            meta,
                            "{http://www.freedesktop.org/standards/shared-mime-info}icon",
                            {"name": "folder-remote"}
                        )
                        tree.write(xbel_file, encoding="UTF-8", xml_declaration=True)
                except Exception:
                    pass
        self.rebuild_menu()

    def send_wol(self, srv):
        mac = srv["mac"].replace(":", "").replace("-", "")
        try:
            data = bytes.fromhex("FF" * 6 + mac * 16)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                s.sendto(data, ("255.255.255.255", 9))
            self.showMessage("Wake-on-LAN Sent", f"Magic packet sent to {srv['name']} ({srv['mac']})")
        except Exception as e:
            self.showMessage("Wake-on-LAN Failed", str(e))

    def toggle_autostart(self):
        AUTOSTART_FILE.parent.mkdir(parents=True, exist_ok=True)
        if AUTOSTART_FILE.exists():
            AUTOSTART_FILE.unlink(missing_ok=True)
        else:
            exec_path = str(BIN_PATH) if BIN_PATH.exists() else str(Path(__file__).resolve())
            AUTOSTART_FILE.write_text(
                f"[Desktop Entry]\n"
                f"Name=SSH Hub Tray Monitor\n"
                f"Comment=System Tray Monitor for SSH Connection Hub\n"
                f"Exec={exec_path}\n"
                f"Icon=network-server\n"
                f"Terminal=false\n"
                f"Type=Application\n"
                f"X-GNOME-Autostart-enabled=true\n"
                f"X-KDE-autostart-after=panel\n"
                f"StartupNotify=false\n"
            )
        self.rebuild_menu()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    tray = SSHHubTray(app)
    sys.exit(app.exec())
