#!/usr/bin/env python3
import os
import sys
import time
import json
import socket
import subprocess
import concurrent.futures
import xml.etree.ElementTree as ET
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QLineEdit, QPushButton, QMessageBox, QListWidget,
    QListWidgetItem, QFileDialog, QFormLayout, QProgressBar, QMainWindow,
    QWidget, QFrame, QGridLayout, QInputDialog, QSplitter, QCheckBox
)
from PyQt6.QtGui import QIcon, QAction, QPixmap, QPainter, QColor, QBrush, QPen, QFont
from PyQt6.QtCore import QTimer, QThread, pyqtSignal, Qt, QSize

APP_VERSION = "2.2.0"
CONFIG_FILE = Path.home() / ".ssh_servers"
CUSTOM_CMD_FILE = Path.home() / ".ssh_custom_commands.json"
TRAY_HIDDEN_FILE = Path.home() / ".ssh_tray_hidden.json"
THEME_FILE = Path.home() / ".ssh_hub_theme"
MOUNT_DIR = Path.home() / "Network_Servers"
AUTOSTART_FILE = Path.home() / ".config/autostart/sshm-tray.desktop"
BIN_PATH = Path.home() / ".local/bin/sshm-tray"
TELEM_FILE = Path("/dev/shm/sshm_telemetry.json")
TELEM_PORT = 55889

THEMES = [
    {"name": "Royal Purple", "accent": "#b48ead", "bg": "#181825", "card": "#1e1e2e", "border": "#45475a"},
    {"name": "Cyber Neon",   "accent": "#00f0ff", "bg": "#0d1117", "card": "#161b22", "border": "#238636"},
    {"name": "Matrix Green", "accent": "#52ff52", "bg": "#0c140c", "card": "#121f12", "border": "#2a522a"},
    {"name": "Solar Amber",  "accent": "#ffb833", "bg": "#1c1813", "card": "#262018", "border": "#664d1a"},
    {"name": "Crimson Red",  "accent": "#ff5555", "bg": "#1c1214", "card": "#28191c", "border": "#6e2932"},
    {"name": "Oceanic Blue", "accent": "#58a6ff", "bg": "#0f172a", "card": "#1e293b", "border": "#334155"},
    {"name": "Rose Pink",    "accent": "#f38ba8", "bg": "#1e1620", "card": "#281d2b", "border": "#5c3d63"},
    {"name": "Stealth Slate","accent": "#94a3b8", "bg": "#111318", "card": "#1a1d24", "border": "#323846"},
]


def load_theme_index():
    if THEME_FILE.exists():
        try:
            idx = int(THEME_FILE.read_text().strip())
            if 0 <= idx < len(THEMES):
                return idx
        except Exception:
            pass
    return 0


def save_theme_index(idx):
    try:
        THEME_FILE.write_text(f"{idx}\n")
    except Exception:
        pass

def load_tray_hidden():
    if TRAY_HIDDEN_FILE.exists():
        try:
            data = json.loads(TRAY_HIDDEN_FILE.read_text())
            if isinstance(data, list):
                return set(data)
        except Exception:
            pass
    return set()


def save_tray_hidden(hidden_set):
    try:
        TRAY_HIDDEN_FILE.write_text(json.dumps(sorted(list(hidden_set)), indent=2))
    except Exception:
        pass



def get_theme_icon(names, fallback_color=None):
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
        badge_col = QColor("#52ff52")
    elif state == "PARTIAL":
        badge_col = QColor("#ffb833")
    elif state == "ALL_OFF":
        badge_col = QColor("#ff4d4d")
    else:
        badge_col = QColor("#888888")

    painter.setPen(QPen(QColor("#1e1e2e"), 2.0))
    painter.setBrush(QBrush(badge_col))
    painter.drawEllipse(20, 20, 10, 10)
    painter.end()
    return QIcon(pix)


def read_telemetry_cache():
    if not TELEM_FILE.exists():
        return {}
    try:
        return json.loads(TELEM_FILE.read_text())
    except Exception:
        return {}


def check_host_status(host, port=22, telem_cache=None):
    port_str = str(port)
    if telem_cache:
        entry = telem_cache.get(f"{host}:{port_str}")
        if not entry and port_str == "22":
            entry = telem_cache.get(host)
        if entry:
            age = time.time() - float(entry.get("ts", 0))
            if age <= 6.0:
                if int(entry.get("ssh", 1)) == 0:
                    return False, "OFFLINE", None
                try:
                    with socket.create_connection((host, int(port)), timeout=0.6):
                        return True, "Live", entry
                except Exception:
                    return False, "OFFLINE", None

    try:
        t0 = time.monotonic()
        with socket.create_connection((host, int(port)), timeout=1.0):
            tcp_ms = (time.monotonic() - t0) * 1000.0
    except Exception:
        return False, "OFFLINE", None

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
                    return True, f"{ms:.0f}ms", None
    except Exception:
        pass

    return True, f"{tcp_ms:.0f}ms", None


class TelemetryListenerThread(QThread):
    instant_state_change = pyqtSignal()
    show_gui_signal = pyqtSignal()

    def run(self):
        subprocess.run(["pkill", "-f", "sshm-telem-daemon"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.1)

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind(("0.0.0.0", TELEM_PORT))
        except Exception:
            return

        cache = read_telemetry_cache()
        while True:
            try:
                data, addr = sock.recvfrom(1024)
                msg = json.loads(data.decode("utf-8", errors="ignore"))
                if msg.get("cmd") == "SHOW_GUI":
                    self.show_gui_signal.emit()
                    continue
                ip = addr[0]
                hname = msg.get("host", "")
                ssh_port = str(msg.get("port", "22"))
                key_ip = f"{ip}:{ssh_port}"
                new_ssh = int(msg.get("ssh", 1))
                prev_ssh = cache.get(key_ip, {}).get("ssh", -1)

                entry = {
                    "ts": time.time(),
                    "cpu": msg.get("cpu", "--"),
                    "ram": msg.get("ram", "--"),
                    "up": msg.get("up", "--"),
                    "ssh": new_ssh,
                    "port": ssh_port
                }
                cache[key_ip] = entry
                if hname:
                    cache[f"{hname}:{ssh_port}"] = entry

                tmp = TELEM_FILE.with_suffix(".tmp")
                tmp.write_text(json.dumps(cache))
                os.replace(tmp, TELEM_FILE)

                if new_ssh != prev_ssh:
                    self.instant_state_change.emit()
            except Exception:
                pass


class StatusScannerThread(QThread):
    results_ready = pyqtSignal(dict)

    def __init__(self, servers, scan_all=False):
        super().__init__()
        self.servers = servers
        self.scan_all = scan_all

    def run(self):
        results = {}
        telem_cache = read_telemetry_cache()
        hidden = load_tray_hidden()
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
            future_map = {}
            for idx, srv in enumerate(self.servers):
                if not self.scan_all and srv["name"] in hidden:
                    continue
                future_map[executor.submit(check_host_status, srv["host"], srv["port"], telem_cache)] = idx

            for future in concurrent.futures.as_completed(future_map):
                idx = future_map[future]
                try:
                    results[idx] = future.result()
                except Exception:
                    results[idx] = (False, "OFFLINE", None)
        self.results_ready.emit(results)


class LanScanWorkerThread(QThread):
    scan_finished = pyqtSignal(list, str)

    def __init__(self, ports_spec="22, 2222, 2200, 22222, 8022"):
        super().__init__()
        self.ports = self.parse_ports(ports_spec)

    def parse_ports(self, spec):
        ports = set()
        for part in spec.replace(" ", "").split(","):
            if not part:
                continue
            if "-" in part:
                try:
                    a, b = part.split("-", 1)
                    for p in range(int(a), int(b) + 1):
                        if 1 <= p <= 65535:
                            ports.add(p)
                except Exception:
                    pass
            elif part.isdigit():
                p = int(part)
                if 1 <= p <= 65535:
                    ports.add(p)
        return sorted(ports) if ports else [22, 2222]

    def get_local_subnet(self):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("1.1.1.1", 80))
                my_ip = s.getsockname()[0]
                prefix = ".".join(my_ip.split(".")[:3])
                return prefix, my_ip
        except Exception:
            return "192.168.1", ""

    def probe_ip_port(self, ip, port):
        banner = ""
        try:
            with socket.create_connection((ip, port), timeout=0.45) as sock:
                sock.settimeout(0.45)
                try:
                    data = sock.recv(64).decode("utf-8", errors="ignore").strip()
                    banner = data.splitlines()[0] if data else ""
                except Exception:
                    banner = ""
        except Exception:
            return None

        if port != 22 and not banner.startswith("SSH-"):
            return None

        hostname = ""
        try:
            hostname = socket.gethostbyaddr(ip)[0].split(".")[0]
        except Exception:
            pass

        if not hostname or hostname == ip:
            hostname = f"node-{ip.split('.')[-1]}"
        if port != 22:
            hostname = f"{hostname}-p{port}"

        clean_banner = banner.replace("SSH-2.0-", "") if banner.startswith("SSH-") else "SSH"
        return {
            "ip": ip,
            "hostname": hostname,
            "port": str(port),
            "mac": "",
            "banner": clean_banner[:24]
        }

    def run(self):
        prefix, _my_ip = self.get_local_subnet()
        ips = [f"{prefix}.{i}" for i in range(1, 255)]
        found = []

        targets = [(ip, port) for ip in ips for port in self.ports]
        with concurrent.futures.ThreadPoolExecutor(max_workers=96) as executor:
            futures = [executor.submit(self.probe_ip_port, ip, port) for ip, port in targets]
            for fut in concurrent.futures.as_completed(futures):
                res = fut.result()
                if res:
                    found.append(res)

        arp_map = {}
        try:
            out = subprocess.run(
                ["ip", "neigh", "show"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=1.5
            ).stdout
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 5 and "lladdr" in parts:
                    ip_addr = parts[0]
                    idx = parts.index("lladdr")
                    if idx + 1 < len(parts):
                        arp_map[ip_addr] = parts[idx + 1].lower()
        except Exception:
            pass

        for item in found:
            item["mac"] = arp_map.get(item["ip"], "")

        found.sort(key=lambda x: (int(x["ip"].split(".")[-1]), int(x["port"])))
        self.scan_finished.emit(found, f"{prefix}.0/24")


class LanScanDialog(QDialog):
    def __init__(self, existing_servers, parent=None):
        super().__init__(parent)
        self.existing_servers = existing_servers
        self.discovered = []
        self.selected_to_add = []
        self.single_fill_node = None
        self.worker = None

        self.setWindowTitle("Scan Local Network for SSH Servers (Multi-Port Banner Probe)")
        self.resize(640, 420)
        self.setModal(True)

        layout = QVBoxLayout(self)

        top_bar = QHBoxLayout()
        self.status_lbl = QLabel("Initializing subnet scan...")
        top_bar.addWidget(self.status_lbl)
        top_bar.addStretch()

        top_bar.addWidget(QLabel("SSH Ports (comma or range):"))
        self.port_input = QLineEdit("22, 2222, 2200, 22222, 8022")
        self.port_input.setFixedWidth(210)
        self.port_input.setToolTip("Enter comma-separated ports or a range like: 22, 2222, 2200-2210")
        top_bar.addWidget(self.port_input)

        self.rescan_btn = QPushButton("Rescan Subnet")
        self.rescan_btn.clicked.connect(self.start_scan)
        top_bar.addWidget(self.rescan_btn)
        layout.addLayout(top_bar)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        layout.addWidget(self.progress)

        layout.addWidget(QLabel("Discovered SSH Hosts (Verifies 'SSH-2.0' banner on non-standard ports):"))
        self.host_list = QListWidget()
        layout.addWidget(self.host_list)

        bottom_bar = QHBoxLayout()
        self.user_lbl = QLabel("Default SSH User:")
        self.default_user_input = QLineEdit(os.environ.get("USER", "root"))
        self.default_user_input.setFixedWidth(110)
        bottom_bar.addWidget(self.user_lbl)
        bottom_bar.addWidget(self.default_user_input)

        bottom_bar.addStretch()

        self.fill_btn = QPushButton("Load Highlighted into Form")
        self.fill_btn.clicked.connect(self.handle_single_fill)
        self.add_checked_btn = QPushButton("Add Checked Servers")
        self.add_checked_btn.clicked.connect(self.handle_add_checked)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)

        bottom_bar.addWidget(self.cancel_btn)
        bottom_bar.addWidget(self.fill_btn)
        bottom_bar.addWidget(self.add_checked_btn)
        layout.addLayout(bottom_bar)

        self.start_scan()

    def start_scan(self):
        ports_spec = self.port_input.text().strip() or "22, 2222, 2200, 22222, 8022"
        self.host_list.clear()
        self.progress.setVisible(True)
        self.rescan_btn.setEnabled(False)
        self.add_checked_btn.setEnabled(False)
        self.fill_btn.setEnabled(False)
        self.status_lbl.setText(f"Scanning local /24 network on ports [{ports_spec}]...")

        self.worker = LanScanWorkerThread(ports_spec=ports_spec)
        self.worker.scan_finished.connect(self.on_scan_done)
        self.worker.start()

    def on_scan_done(self, found, subnet_str):
        self.discovered = found
        self.progress.setVisible(False)
        self.rescan_btn.setEnabled(True)
        self.add_checked_btn.setEnabled(True)
        self.fill_btn.setEnabled(True)

        existing_keys = {(s["host"], str(s["port"])) for s in self.existing_servers}
        self.status_lbl.setText(f"Scan complete on {subnet_str} — Found {len(found)} active SSH endpoint(s).")

        for node in found:
            is_saved = (node["ip"], node["port"]) in existing_keys
            mac_str = node["mac"] if node["mac"] else "MAC unknown"
            banner_str = node.get("banner", "SSH")
            state_tag = "[Already Saved]" if is_saved else "[NEW]"
            label = f"{state_tag}  {node['hostname']}  —  {node['ip']}:{node['port']}  [{banner_str}]  ({mac_str})"

            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked if is_saved else Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, node)
            self.host_list.addItem(item)

        if self.host_list.count() > 0:
            self.host_list.setCurrentRow(0)

    def handle_single_fill(self):
        row = self.host_list.currentRow()
        if 0 <= row < self.host_list.count():
            item = self.host_list.item(row)
            node = dict(item.data(Qt.ItemDataRole.UserRole))
            node["user"] = self.default_user_input.text().strip() or os.environ.get("USER", "root")
            self.single_fill_node = node
            self.accept()

    def handle_add_checked(self):
        user = self.default_user_input.text().strip() or os.environ.get("USER", "root")
        picked = []
        for i in range(self.host_list.count()):
            item = self.host_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                node = dict(item.data(Qt.ItemDataRole.UserRole))
                node["user"] = user
                picked.append(node)

        if not picked:
            QMessageBox.information(self, "No Hosts Checked", "Please check at least one discovered host to add, or click 'Load Highlighted into Form'.")
            return

        self.selected_to_add = picked
        self.accept()


class ServerManagerDialog(QDialog):
    def __init__(self, initial_idx=-1, start_scanner=False, parent=None):
        super().__init__(parent)
        self.servers = []
        self.editing_idx = -1

        self.setWindowTitle("Manage Server Profiles")
        self.resize(560, 490)
        self.setModal(True)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("1. Saved Server Profiles (Click one to edit, or click '+ New Server'):"))
        self.srv_list = QListWidget()
        self.srv_list.currentRowChanged.connect(self.on_srv_selected)
        layout.addWidget(self.srv_list)

        list_btn_layout = QHBoxLayout()
        self.new_btn = QPushButton("+ New Server")
        self.new_btn.clicked.connect(self.prepare_new_server)
        self.scan_lan_btn = QPushButton("Scan Local Network (SSH)")
        self.scan_lan_btn.clicked.connect(self.open_lan_scanner)
        self.del_btn = QPushButton("Delete Selected")
        self.del_btn.clicked.connect(self.delete_selected_server)
        self.del_btn.setEnabled(False)
        list_btn_layout.addWidget(self.new_btn)
        list_btn_layout.addWidget(self.scan_lan_btn)
        list_btn_layout.addWidget(self.del_btn)
        list_btn_layout.addStretch()
        layout.addLayout(list_btn_layout)

        form = QFormLayout()

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. Homelab Node")
        form.addRow("Server Name:", self.name_input)

        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("e.g. lucas")
        form.addRow("SSH Username:", self.user_input)

        self.host_input = QLineEdit()
        self.host_input.setPlaceholderText("e.g. 192.168.4.100")
        form.addRow("Host / IP Address:", self.host_input)

        self.port_input = QLineEdit()
        self.port_input.setPlaceholderText("22")
        form.addRow("SSH Port:", self.port_input)

        self.tag_input = QLineEdit()
        self.tag_input.setPlaceholderText("e.g. Main Server (Optional)")
        form.addRow("Category / Tag:", self.tag_input)

        mac_layout = QHBoxLayout()
        self.mac_input = QLineEdit()
        self.mac_input.setPlaceholderText("aa:bb:cc:dd:ee:ff (Optional for Wake-on-LAN)")
        self.scan_mac_btn = QPushButton("Auto-Detect MAC")
        self.scan_mac_btn.clicked.connect(self.auto_detect_mac)
        mac_layout.addWidget(self.mac_input)
        mac_layout.addWidget(self.scan_mac_btn)
        form.addRow("MAC Address:", mac_layout)

        key_layout = QHBoxLayout()
        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText("~/.ssh/id_ed25519 (Optional)")
        self.browse_key_btn = QPushButton("Browse...")
        self.browse_key_btn.clicked.connect(self.browse_ssh_key)
        key_layout.addWidget(self.key_input)
        key_layout.addWidget(self.browse_key_btn)
        form.addRow("SSH Key Path:", key_layout)

        self.tray_chk = QCheckBox("Show && Monitor in System Tray (Uncheck to only show in GUI/TUI)")
        self.tray_chk.setChecked(True)
        form.addRow("Tray Tracking:", self.tray_chk)

        layout.addLayout(form)

        btn_layout = QHBoxLayout()
        self.save_btn = QPushButton("Save New Server")
        self.save_btn.clicked.connect(self.handle_save)
        self.close_btn = QPushButton("Done / Close")
        self.close_btn.clicked.connect(self.accept)

        btn_layout.addStretch()
        btn_layout.addWidget(self.close_btn)
        btn_layout.addWidget(self.save_btn)
        layout.addLayout(btn_layout)

        self.load_servers_from_disk()
        self.refresh_list_widget()

        if 0 <= initial_idx < len(self.servers):
            self.srv_list.setCurrentRow(initial_idx)

        if start_scanner:
            QTimer.singleShot(100, self.open_lan_scanner)

    def load_servers_from_disk(self):
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

    def save_servers_to_disk(self):
        lines = []
        for s in self.servers:
            port = s["port"] if s["port"] else "22"
            line = "|".join([
                s["name"].replace("|", ""),
                s["user"].replace("|", ""),
                s["host"].replace("|", ""),
                port.replace("|", ""),
                s["tag"].replace("|", ""),
                s["mac"].replace("|", ""),
                s["key"].replace("|", ""),
            ])
            lines.append(line)
        CONFIG_FILE.write_text("\n".join(lines) + ("\n" if lines else ""))

    def refresh_list_widget(self):
        hidden = load_tray_hidden()
        self.srv_list.blockSignals(True)
        self.srv_list.clear()
        for s in self.servers:
            tag_str = f" [{s['tag']}]" if s["tag"] else ""
            tray_tag = " [GUI Only]" if s["name"] in hidden else " [Tray+GUI]"
            self.srv_list.addItem(f"{s['name']}{tag_str}{tray_tag}   ->   {s['user']}@{s['host']}:{s['port']}")
        self.srv_list.blockSignals(False)
        self.prepare_new_server()

    def prepare_new_server(self):
        self.srv_list.blockSignals(True)
        self.srv_list.clearSelection()
        self.srv_list.setCurrentRow(-1)
        self.srv_list.blockSignals(False)
        self.editing_idx = -1
        self.name_input.clear()
        self.user_input.setText(os.environ.get("USER", "root"))
        self.host_input.clear()
        self.port_input.setText("22")
        self.tag_input.clear()
        self.mac_input.clear()
        self.key_input.clear()
        self.tray_chk.setChecked(True)
        self.save_btn.setText("Save New Server")
        self.del_btn.setEnabled(False)
        self.name_input.setFocus()

    def on_srv_selected(self, row):
        if 0 <= row < len(self.servers):
            hidden = load_tray_hidden()
            self.editing_idx = row
            s = self.servers[row]
            self.name_input.setText(s["name"])
            self.user_input.setText(s["user"])
            self.host_input.setText(s["host"])
            self.port_input.setText(s["port"])
            self.tag_input.setText(s["tag"])
            self.mac_input.setText(s["mac"])
            self.key_input.setText(s["key"])
            self.tray_chk.setChecked(s["name"] not in hidden)
            self.save_btn.setText("Update Selected Server")
            self.del_btn.setEnabled(True)
        else:
            self.prepare_new_server()

    def open_lan_scanner(self):
        dlg = LanScanDialog(self.servers, self)
        if dlg.exec():
            if dlg.single_fill_node:
                n = dlg.single_fill_node
                self.prepare_new_server()
                self.name_input.setText(n["hostname"])
                self.user_input.setText(n["user"])
                self.host_input.setText(n["ip"])
                self.port_input.setText(n["port"])
                self.mac_input.setText(n["mac"])
                self.tag_input.setText("LAN")
            elif dlg.selected_to_add:
                added_count = 0
                updated_macs = 0
                for n in dlg.selected_to_add:
                    existing = next((s for s in self.servers if s["host"] == n["ip"] and str(s["port"]) == str(n["port"])), None)
                    if existing:
                        if n["mac"] and not existing["mac"]:
                            existing["mac"] = n["mac"]
                            updated_macs += 1
                    else:
                        self.servers.append({
                            "name": n["hostname"],
                            "user": n["user"],
                            "host": n["ip"],
                            "port": n["port"],
                            "tag": "LAN",
                            "mac": n["mac"],
                            "key": "",
                        })
                        added_count += 1
                self.save_servers_to_disk()
                self.refresh_list_widget()
                QMessageBox.information(
                    self,
                    "LAN Import Complete",
                    f"Added {added_count} new server(s) and updated {updated_macs} MAC address(es)."
                )

    def auto_detect_mac(self):
        host = self.host_input.text().strip()
        if not host:
            QMessageBox.warning(self, "Missing Host", "Enter a Host / IP Address first so we can probe its MAC.")
            return
        try:
            subprocess.run(["ping", "-c", "1", "-W", "1", host], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.5)
            res = subprocess.run(["ip", "neigh", "show", host], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=1.5)
            for line in res.stdout.splitlines():
                parts = line.split()
                if "lladdr" in parts:
                    idx = parts.index("lladdr")
                    if idx + 1 < len(parts):
                        self.mac_input.setText(parts[idx + 1].lower())
                        return
            QMessageBox.information(self, "MAC Not Found", f"Could not detect a local LAN MAC address for {host}.")
        except Exception as e:
            QMessageBox.warning(self, "Scan Error", str(e))

    def browse_ssh_key(self):
        ssh_dir = str(Path.home() / ".ssh")
        path, _ = QFileDialog.getOpenFileName(self, "Select SSH Private Key", ssh_dir)
        if path:
            self.key_input.setText(path)

    def delete_selected_server(self):
        if 0 <= self.editing_idx < len(self.servers):
            srv = self.servers[self.editing_idx]
            reply = QMessageBox.question(
                self,
                "Confirm Delete",
                f"Are you sure you want to delete '{srv['name']}' ({srv['user']}@{srv['host']})?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.servers.pop(self.editing_idx)
                self.save_servers_to_disk()
                self.refresh_list_widget()

    def handle_save(self):
        name = self.name_input.text().strip()
        user = self.user_input.text().strip()
        host = self.host_input.text().strip()
        port = self.port_input.text().strip() or "22"
        tag = self.tag_input.text().strip()
        mac = self.mac_input.text().strip()
        key = self.key_input.text().strip()

        if not name or not user or not host:
            QMessageBox.warning(self, "Validation Error", "Server Name, SSH Username, and Host / IP Address are required.")
            return

        new_entry = {
            "name": name,
            "user": user,
            "host": host,
            "port": port,
            "tag": tag,
            "mac": mac,
            "key": key,
        }

        hidden = load_tray_hidden()
        if 0 <= self.editing_idx < len(self.servers):
            old_name = self.servers[self.editing_idx]["name"]
            self.servers[self.editing_idx] = new_entry
            if old_name != name:
                if old_name in hidden:
                    hidden.discard(old_name)
                    hidden.add(name)
                if CUSTOM_CMD_FILE.exists():
                    try:
                        customs = json.loads(CUSTOM_CMD_FILE.read_text())
                        if old_name in customs and name not in customs:
                            customs[name] = customs.pop(old_name)
                            CUSTOM_CMD_FILE.write_text(json.dumps(customs, indent=2))
                    except Exception:
                        pass
        else:
            self.servers.append(new_entry)

        if self.tray_chk.isChecked():
            hidden.discard(name)
        else:
            hidden.add(name)
        save_tray_hidden(hidden)

        self.save_servers_to_disk()
        self.refresh_list_widget()


class CustomCommandDialog(QDialog):
    def __init__(self, servers, initial_server_name="", parent=None):
        super().__init__(parent)
        self.servers = servers
        self.customs = {}
        self.editing_idx = -1

        self.setWindowTitle("Manage Custom Server Commands")
        self.resize(520, 400)
        self.setModal(True)

        self.load_customs()

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("1. Select Target Server:"))
        self.server_combo = QComboBox()
        selected_combo_idx = 0
        for i, srv in enumerate(self.servers):
            self.server_combo.addItem(f"{srv['name']} ({srv['user']}@{srv['host']})", srv)
            if srv["name"] == initial_server_name:
                selected_combo_idx = i
        self.server_combo.setCurrentIndex(selected_combo_idx)
        self.server_combo.currentIndexChanged.connect(self.on_server_changed)
        layout.addWidget(self.server_combo)

        layout.addWidget(QLabel("2. Saved Commands for This Server (Click one to edit, or click '+ New'):"))
        self.cmd_list = QListWidget()
        self.cmd_list.currentRowChanged.connect(self.on_cmd_selected)
        layout.addWidget(self.cmd_list)

        list_btn_layout = QHBoxLayout()
        self.new_btn = QPushButton("+ New Command")
        self.new_btn.clicked.connect(self.prepare_new_command)
        self.del_btn = QPushButton("Delete Selected")
        self.del_btn.clicked.connect(self.delete_selected_command)
        self.del_btn.setEnabled(False)
        list_btn_layout.addWidget(self.new_btn)
        list_btn_layout.addWidget(self.del_btn)
        list_btn_layout.addStretch()
        layout.addLayout(list_btn_layout)

        layout.addWidget(QLabel("Menu Label Name (e.g. 'Run Topgrade Update'):"))
        self.label_input = QLineEdit()
        self.label_input.setPlaceholderText("e.g. Run Topgrade Update")
        layout.addWidget(self.label_input)

        layout.addWidget(QLabel("Shell Command to Run over SSH:"))
        self.cmd_input = QLineEdit()
        self.cmd_input.setPlaceholderText("e.g. topgrade")
        layout.addWidget(self.cmd_input)

        btn_layout = QHBoxLayout()
        self.save_btn = QPushButton("Save New Command")
        self.save_btn.clicked.connect(self.handle_save)
        self.close_btn = QPushButton("Done / Close")
        self.close_btn.clicked.connect(self.accept)

        btn_layout.addStretch()
        btn_layout.addWidget(self.close_btn)
        btn_layout.addWidget(self.save_btn)
        layout.addLayout(btn_layout)

        self.on_server_changed()

    def load_customs(self):
        self.customs = {}
        if CUSTOM_CMD_FILE.exists():
            try:
                self.customs = json.loads(CUSTOM_CMD_FILE.read_text())
            except Exception:
                self.customs = {}

    def save_customs(self):
        CUSTOM_CMD_FILE.write_text(json.dumps(self.customs, indent=2))

    def current_server_name(self):
        srv_data = self.server_combo.currentData()
        return srv_data["name"] if srv_data else ""

    def on_server_changed(self):
        self.cmd_list.blockSignals(True)
        self.cmd_list.clear()
        srv_name = self.current_server_name()
        cmds = self.customs.get(srv_name, [])
        for c in cmds:
            self.cmd_list.addItem(f"{c.get('label', '')}   ->   {c.get('cmd', '')}")
        self.cmd_list.blockSignals(False)
        self.prepare_new_command()

    def prepare_new_command(self):
        self.cmd_list.blockSignals(True)
        self.cmd_list.clearSelection()
        self.cmd_list.setCurrentRow(-1)
        self.cmd_list.blockSignals(False)
        self.editing_idx = -1
        self.label_input.clear()
        self.cmd_input.clear()
        self.save_btn.setText("Save New Command")
        self.del_btn.setEnabled(False)
        self.label_input.setFocus()

    def on_cmd_selected(self, row):
        srv_name = self.current_server_name()
        cmds = self.customs.get(srv_name, [])
        if 0 <= row < len(cmds):
            self.editing_idx = row
            self.label_input.setText(cmds[row].get("label", ""))
            self.cmd_input.setText(cmds[row].get("cmd", ""))
            self.save_btn.setText("Update Selected Command")
            self.del_btn.setEnabled(True)
        else:
            self.prepare_new_command()

    def delete_selected_command(self):
        srv_name = self.current_server_name()
        cmds = self.customs.get(srv_name, [])
        if 0 <= self.editing_idx < len(cmds):
            cmds.pop(self.editing_idx)
            self.customs[srv_name] = cmds
            self.save_customs()
            self.on_server_changed()

    def handle_save(self):
        srv_name = self.current_server_name()
        if not srv_name:
            return
        label = self.label_input.text().strip()
        cmd = self.cmd_input.text().strip()

        if not label or not cmd:
            QMessageBox.warning(self, "Validation Error", "Please provide both a menu label and a command.")
            return

        if srv_name not in self.customs:
            self.customs[srv_name] = []

        if 0 <= self.editing_idx < len(self.customs[srv_name]):
            self.customs[srv_name][self.editing_idx] = {"label": label, "cmd": cmd}
        else:
            self.customs[srv_name].append({"label": label, "cmd": cmd})

        self.save_customs()
        self.on_server_changed()


class PortTunnelDialog(QDialog):
    def __init__(self, srv, parent=None):
        super().__init__(parent)
        self.srv = srv
        self.setWindowTitle(f"SSH Port Tunnel — {srv['name']}")
        self.resize(420, 220)
        self.setModal(True)

        layout = QVBoxLayout(self)
        info = QLabel(
            f"Forward a local port on your desktop to a remote port on {srv['user']}@{srv['host']}:{srv['port']}."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()
        self.local_port = QLineEdit("8080")
        self.remote_host = QLineEdit("127.0.0.1")
        self.remote_port = QLineEdit("8080")

        form.addRow("Local Desktop Port:", self.local_port)
        form.addRow("Remote Bind Host:", self.remote_host)
        form.addRow("Remote Target Port:", self.remote_port)
        layout.addLayout(form)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        start_btn = QPushButton("Launch Background Tunnel")
        start_btn.clicked.connect(self.accept)
        btns.addWidget(cancel_btn)
        btns.addWidget(start_btn)
        layout.addLayout(btns)


class SSHHubMainWindow(QMainWindow):
    def __init__(self, controller):
        super().__init__()
        self.ctrl = controller
        self.selected_server_idx = 0
        self.active_tag_filter = "ALL"
        self.theme_idx = load_theme_index()

        self.setWindowTitle(f"sshm — SSH Connection Hub & Telemetry Control Center (v{APP_VERSION})")
        self.resize(980, 640)
        self.setWindowIcon(make_tray_badge_icon("ALL_ON"))

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(12)

        # ----------------------------------------------------------------------
        # Top Header Bar
        # ----------------------------------------------------------------------
        self.header_frame = QFrame()
        self.header_frame.setObjectName("HeaderCard")
        header_layout = QHBoxLayout(self.header_frame)
        header_layout.setContentsMargins(16, 10, 16, 10)

        self.title_lbl = QLabel(f"◆ SSH CONNECTION HUB (v{APP_VERSION})")
        title_font = QFont()
        title_font.setPointSize(13)
        title_font.setBold(True)
        self.title_lbl.setFont(title_font)
        header_layout.addWidget(self.title_lbl)

        self.summary_badge = QLabel("0/0 Online")
        self.summary_badge.setObjectName("SummaryBadge")
        header_layout.addWidget(self.summary_badge)

        header_layout.addStretch()

        header_layout.addWidget(QLabel("Tag Filter:"))
        self.tag_combo = QComboBox()
        self.tag_combo.setMinimumWidth(120)
        self.tag_combo.currentTextChanged.connect(self.on_tag_filter_changed)
        header_layout.addWidget(self.tag_combo)

        header_layout.addSpacing(8)
        header_layout.addWidget(QLabel("Theme:"))
        self.theme_combo = QComboBox()
        for t in THEMES:
            self.theme_combo.addItem(t["name"])
        self.theme_combo.setCurrentIndex(self.theme_idx)
        self.theme_combo.currentIndexChanged.connect(self.on_theme_changed)
        header_layout.addWidget(self.theme_combo)

        self.refresh_btn = QPushButton("Refresh [R]")
        self.refresh_btn.clicked.connect(lambda: self.ctrl.refresh_all(force=True))
        header_layout.addWidget(self.refresh_btn)

        self.tui_btn = QPushButton("Open Terminal TUI")
        self.tui_btn.clicked.connect(self.ctrl.launch_sshm_tui)
        header_layout.addWidget(self.tui_btn)

        main_layout.addWidget(self.header_frame)

        # ----------------------------------------------------------------------
        # Middle Dual-Pane Splitter (Left: Remote Nodes | Right: Target Inspector)
        # ----------------------------------------------------------------------
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # LEFT PANE: Remote Nodes List + Fleet Actions
        self.left_card = QFrame()
        self.left_card.setObjectName("PaneCard")
        left_layout = QVBoxLayout(self.left_card)
        left_layout.setContentsMargins(14, 14, 14, 14)
        left_layout.setSpacing(10)

        left_hdr = QHBoxLayout()
        self.nodes_hdr_lbl = QLabel("REMOTE NODES (0)")
        hdr_font = QFont()
        hdr_font.setBold(True)
        self.nodes_hdr_lbl.setFont(hdr_font)
        left_hdr.addWidget(self.nodes_hdr_lbl)
        left_hdr.addStretch()
        left_hdr.addWidget(QLabel("Double-click to SSH"))
        left_layout.addLayout(left_hdr)

        self.server_list = QListWidget()
        self.server_list.setObjectName("ServerList")
        self.server_list.setIconSize(QSize(18, 18))
        self.server_list.currentRowChanged.connect(self.on_list_row_changed)
        self.server_list.itemDoubleClicked.connect(self.on_item_double_clicked)
        left_layout.addWidget(self.server_list)

        fleet_grid = QGridLayout()
        fleet_grid.setSpacing(8)

        self.btn_add_srv = QPushButton("+ Add / Manage Servers")
        self.btn_add_srv.clicked.connect(lambda: self.ctrl.open_server_manager_dialog(initial_idx=-1, start_scanner=False))

        self.btn_scan_lan = QPushButton("Scan LAN (Multi-Port SSH)")
        self.btn_scan_lan.clicked.connect(lambda: self.ctrl.open_server_manager_dialog(initial_idx=-1, start_scanner=True))

        fleet_grid.addWidget(self.btn_add_srv, 0, 0)
        fleet_grid.addWidget(self.btn_scan_lan, 0, 1)
        left_layout.addLayout(fleet_grid)

        splitter.addWidget(self.left_card)

        # RIGHT PANE: Target Inspector & Action Deck
        self.right_card = QFrame()
        self.right_card.setObjectName("PaneCard")
        right_layout = QVBoxLayout(self.right_card)
        right_layout.setContentsMargins(16, 14, 16, 14)
        right_layout.setSpacing(12)

        self.target_title_lbl = QLabel("TARGET: None Selected")
        target_font = QFont()
        target_font.setPointSize(12)
        target_font.setBold(True)
        self.target_title_lbl.setFont(target_font)
        right_layout.addWidget(self.target_title_lbl)

        # Telemetry & Endpoint Info Box
        self.info_box = QFrame()
        self.info_box.setObjectName("SubCard")
        info_grid = QGridLayout(self.info_box)
        info_grid.setContentsMargins(12, 10, 12, 10)
        info_grid.setVerticalSpacing(6)
        info_grid.setHorizontalSpacing(14)

        info_grid.addWidget(QLabel("Endpoint:"), 0, 0)
        self.lbl_endpoint = QLabel("--")
        self.lbl_endpoint.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        info_grid.addWidget(self.lbl_endpoint, 0, 1)

        info_grid.addWidget(QLabel("Status:"), 1, 0)
        self.lbl_status = QLabel("--")
        info_grid.addWidget(self.lbl_status, 1, 1)

        info_grid.addWidget(QLabel("Live Telemetry:"), 2, 0)
        self.lbl_telemetry = QLabel("--")
        info_grid.addWidget(self.lbl_telemetry, 2, 1)

        info_grid.addWidget(QLabel("Hardware / Key:"), 3, 0)
        self.lbl_hardware = QLabel("--")
        info_grid.addWidget(self.lbl_hardware, 3, 1)

        info_grid.addWidget(QLabel("Tray Monitor:"), 4, 0)
        self.chk_tray_monitor = QCheckBox("Pin && Track this server in the System Tray")
        self.chk_tray_monitor.toggled.connect(self.on_tray_monitor_toggled)
        info_grid.addWidget(self.chk_tray_monitor, 4, 1)

        info_grid.setColumnStretch(1, 1)
        right_layout.addWidget(self.info_box)

        # Primary Operations Grid
        act_lbl = QLabel("SERVER ACTIONS & OPERATIONS")
        act_lbl.setFont(hdr_font)
        right_layout.addWidget(act_lbl)

        act_grid = QGridLayout()
        act_grid.setSpacing(8)

        self.btn_ssh = QPushButton("Connect via SSH (Terminal)")
        self.btn_ssh.setObjectName("PrimaryButton")
        self.btn_ssh.clicked.connect(lambda: self.run_for_selected(lambda s: self.ctrl.connect_ssh_terminal(s, use_tmux=False)))

        self.btn_tmux = QPushButton("Connect via SSH (Auto-tmux)")
        self.btn_tmux.setObjectName("PrimaryButton")
        self.btn_tmux.clicked.connect(lambda: self.run_for_selected(lambda s: self.ctrl.connect_ssh_terminal(s, use_tmux=True)))

        self.btn_browse = QPushButton("Open SFTP in File Manager")
        self.btn_browse.clicked.connect(lambda: self.run_for_selected(self.ctrl.browse_sftp))

        self.btn_mount = QPushButton("Mount to Network Places")
        self.btn_mount.clicked.connect(self.toggle_selected_mount)

        self.btn_sftp_shell = QPushButton("Interactive SFTP Shell")
        self.btn_sftp_shell.clicked.connect(lambda: self.run_for_selected(self.ctrl.connect_sftp_shell))

        self.btn_tunnel = QPushButton("Port Tunneling (Local Fwd)")
        self.btn_tunnel.clicked.connect(self.open_tunnel_for_selected)

        self.btn_wol = QPushButton("Wake-on-LAN Magic Packet")
        self.btn_wol.clicked.connect(lambda: self.run_for_selected(self.ctrl.send_wol))

        self.btn_push_key = QPushButton("Push SSH Public Key")
        self.btn_push_key.clicked.connect(lambda: self.run_for_selected(self.ctrl.push_ssh_key))

        self.btn_agent = QPushButton("Deploy / Remove Telemetry Agent")
        self.btn_agent.clicked.connect(self.manage_agent_for_selected)

        self.btn_edit_srv = QPushButton("Edit / Delete Target Profile")
        self.btn_edit_srv.clicked.connect(self.edit_selected_server)

        act_grid.addWidget(self.btn_ssh, 0, 0)
        act_grid.addWidget(self.btn_tmux, 0, 1)
        act_grid.addWidget(self.btn_browse, 1, 0)
        act_grid.addWidget(self.btn_mount, 1, 1)
        act_grid.addWidget(self.btn_sftp_shell, 2, 0)
        act_grid.addWidget(self.btn_tunnel, 2, 1)
        act_grid.addWidget(self.btn_wol, 3, 0)
        act_grid.addWidget(self.btn_push_key, 3, 1)
        act_grid.addWidget(self.btn_agent, 4, 0)
        act_grid.addWidget(self.btn_edit_srv, 4, 1)

        right_layout.addLayout(act_grid)

        # Custom Server Commands Section
        cmd_hdr_layout = QHBoxLayout()
        cmd_hdr = QLabel("CUSTOM SERVER COMMANDS")
        cmd_hdr.setFont(hdr_font)
        cmd_hdr_layout.addWidget(cmd_hdr)
        cmd_hdr_layout.addStretch()

        self.btn_manage_cmds = QPushButton("Manage Custom Commands...")
        self.btn_manage_cmds.clicked.connect(self.open_custom_cmds_for_selected)
        cmd_hdr_layout.addWidget(self.btn_manage_cmds)
        right_layout.addLayout(cmd_hdr_layout)

        self.custom_cmd_list = QListWidget()
        self.custom_cmd_list.setMaximumHeight(110)
        self.custom_cmd_list.itemDoubleClicked.connect(self.run_selected_custom_cmd)
        right_layout.addWidget(self.custom_cmd_list)

        self.btn_run_cmd = QPushButton("Run Selected Custom Command")
        self.btn_run_cmd.clicked.connect(self.run_selected_custom_cmd)
        right_layout.addWidget(self.btn_run_cmd)

        splitter.addWidget(self.right_card)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 6)
        main_layout.addWidget(splitter, 1)

        # Bottom Status Bar
        self.footer_lbl = QLabel("Tip: Closing this window keeps sshm-tray running in your system tray. Press Enter or Double-Click a server to connect.")
        self.footer_lbl.setObjectName("FooterLabel")
        main_layout.addWidget(self.footer_lbl)

        self.apply_theme(self.theme_idx)
        self.sync_from_controller()

    def apply_theme(self, idx):
        self.theme_idx = idx
        save_theme_index(idx)
        t = THEMES[idx]
        accent = t["accent"]
        bg = t["bg"]
        card = t["card"]
        border = t["border"]

        qss = f"""
        QMainWindow, QDialog {{
            background-color: {bg};
            color: #cdd6f4;
        }}
        QFrame#HeaderCard, QFrame#PaneCard {{
            background-color: {card};
            border: 1px solid {border};
            border-radius: 8px;
        }}
        QFrame#SubCard {{
            background-color: {bg};
            border: 1px solid {border};
            border-radius: 6px;
        }}
        QLabel {{
            color: #cdd6f4;
        }}
        QLabel#SummaryBadge {{
            background-color: {bg};
            color: {accent};
            border: 1px solid {accent};
            border-radius: 4px;
            padding: 3px 8px;
            font-weight: bold;
        }}
        QLabel#FooterLabel {{
            color: #9399b2;
            font-size: 11px;
            padding: 2px 4px;
        }}
        QListWidget {{
            background-color: {bg};
            color: #cdd6f4;
            border: 1px solid {border};
            border-radius: 6px;
            padding: 4px;
            outline: none;
        }}
        QListWidget::item {{
            padding: 7px 8px;
            border-radius: 4px;
        }}
        QListWidget::item:selected {{
            background-color: {border};
            color: #ffffff;
            border-left: 3px solid {accent};
            font-weight: bold;
        }}
        QListWidget::item:hover {{
            background-color: #2a2b3d;
        }}
        QPushButton {{
            background-color: #262837;
            color: #cdd6f4;
            border: 1px solid {border};
            border-radius: 5px;
            padding: 7px 12px;
            font-weight: 500;
        }}
        QPushButton:hover {{
            border: 1px solid {accent};
            background-color: #313449;
        }}
        QPushButton#PrimaryButton {{
            border: 1px solid {accent};
            color: #ffffff;
            font-weight: bold;
        }}
        QCheckBox {{
            color: #cdd6f4;
            spacing: 8px;
        }}
        QComboBox, QLineEdit {{
            background-color: {bg};
            color: #cdd6f4;
            border: 1px solid {border};
            border-radius: 4px;
            padding: 5px 8px;
        }}
        QComboBox:hover, QLineEdit:focus {{
            border: 1px solid {accent};
        }}
        """
        self.setStyleSheet(qss)
        self.title_lbl.setStyleSheet(f"color: {accent};")
        self.target_title_lbl.setStyleSheet(f"color: {accent};")

    def on_theme_changed(self, idx):
        if 0 <= idx < len(THEMES):
            self.apply_theme(idx)

    def on_tag_filter_changed(self, tag_text):
        self.active_tag_filter = tag_text if tag_text else "ALL"
        self.sync_from_controller()

    def get_filtered_indices(self):
        indices = []
        for idx, srv in enumerate(self.ctrl.servers):
            if self.active_tag_filter == "ALL" or srv.get("tag") == self.active_tag_filter:
                indices.append(idx)
        return indices

    def sync_from_controller(self):
        servers = self.ctrl.servers
        results = self.ctrl.status_cache

        # Rebuild tag filter options cleanly
        tags = ["ALL"] + sorted({s["tag"] for s in servers if s.get("tag")})
        self.tag_combo.blockSignals(True)
        cur_tag = self.active_tag_filter if self.active_tag_filter in tags else "ALL"
        self.tag_combo.clear()
        for t in tags:
            self.tag_combo.addItem(t)
        self.tag_combo.setCurrentText(cur_tag)
        self.active_tag_filter = cur_tag
        self.tag_combo.blockSignals(False)

        online_count = sum(1 for idx in range(len(servers)) if results.get(idx, (False, "", None))[0])
        self.summary_badge.setText(f"{online_count}/{len(servers)} Online")

        filtered = self.get_filtered_indices()
        self.nodes_hdr_lbl.setText(f"REMOTE NODES ({len(filtered)})")

        self.server_list.blockSignals(True)
        self.server_list.clear()

        selected_row_to_restore = 0
        for row_idx, srv_idx in enumerate(filtered):
            srv = servers[srv_idx]
            is_on, lat, telem = results.get(srv_idx, (False, "OFFLINE", None))
            icon = self.ctrl.icon_online if is_on else self.ctrl.icon_offline
            mnt_symbol = "◆" if self.ctrl.is_mounted(srv) else "◇"
            tag_str = f" [{srv['tag']}]" if srv["tag"] else ""

            if is_on and telem:
                right_info = f"CPU {telem.get('cpu', '--')}% • RAM {telem.get('ram', '--')}"
            elif is_on:
                right_info = f"{lat}"
            else:
                right_info = "OFFLINE"

            label = f"{mnt_symbol} [{srv_idx + 1}]  {srv['name']}{tag_str}   —   {right_info}"
            item = QListWidgetItem(icon, label)
            item.setData(Qt.ItemDataRole.UserRole, srv_idx)
            self.server_list.addItem(item)

            if srv_idx == self.selected_server_idx:
                selected_row_to_restore = row_idx

        if self.server_list.count() > 0:
            self.server_list.setCurrentRow(selected_row_to_restore)
            sel_item = self.server_list.item(selected_row_to_restore)
            if sel_item:
                self.selected_server_idx = sel_item.data(Qt.ItemDataRole.UserRole)
        else:
            self.selected_server_idx = -1

        self.server_list.blockSignals(False)
        self.update_inspector_pane()

    def on_list_row_changed(self, row):
        if 0 <= row < self.server_list.count():
            item = self.server_list.item(row)
            self.selected_server_idx = item.data(Qt.ItemDataRole.UserRole)
            self.update_inspector_pane()

    def on_item_double_clicked(self, item):
        srv_idx = item.data(Qt.ItemDataRole.UserRole)
        if 0 <= srv_idx < len(self.ctrl.servers):
            self.ctrl.connect_ssh_terminal(self.ctrl.servers[srv_idx], use_tmux=False)

    def current_server(self):
        if 0 <= self.selected_server_idx < len(self.ctrl.servers):
            return self.ctrl.servers[self.selected_server_idx]
        return None

    def update_inspector_pane(self):
        srv = self.current_server()
        if not srv:
            self.target_title_lbl.setText("TARGET: No Server Selected")
            self.lbl_endpoint.setText("--")
            self.lbl_status.setText("--")
            self.lbl_telemetry.setText("--")
            self.lbl_hardware.setText("--")
            self.custom_cmd_list.clear()
            return

        tag_str = f" [{srv['tag']}]" if srv["tag"] else ""
        self.target_title_lbl.setText(f"TARGET: {srv['name']}{tag_str}")
        self.lbl_endpoint.setText(f"{srv['user']}@{srv['host']}:{srv['port']}")

        is_on, lat, telem = self.ctrl.status_cache.get(self.selected_server_idx, (False, "OFFLINE", None))
        mounted = self.ctrl.is_mounted(srv)
        mnt_str = "◆ Mounted in File Manager" if mounted else "◇ Not Mounted"

        if is_on:
            self.lbl_status.setText(f"● ONLINE ({lat})   •   {mnt_str}")
            self.lbl_status.setStyleSheet("color: #52ff52; font-weight: bold;")
        else:
            self.lbl_status.setText(f"○ OFFLINE   •   {mnt_str}")
            self.lbl_status.setStyleSheet("color: #ff5555; font-weight: bold;")

        if is_on and telem:
            self.lbl_telemetry.setText(
                f"CPU: {telem.get('cpu', '--')}%   •   RAM: {telem.get('ram', '--')}   •   Uptime: {telem.get('up', '--')}  (Live UDP Agent)"
            )
        elif is_on:
            self.lbl_telemetry.setText("Agent not deployed (Click 'Deploy / Remove Telemetry Agent' below)")
        else:
            self.lbl_telemetry.setText("Host unreachable")

        mac_txt = srv["mac"] if srv["mac"] else "No MAC saved"
        key_txt = srv["key"] if srv["key"] else "Default SSH Key / Agent"
        self.lbl_hardware.setText(f"MAC: {mac_txt}   •   Key: {key_txt}")

        hidden = load_tray_hidden()
        self.chk_tray_monitor.blockSignals(True)
        self.chk_tray_monitor.setChecked(srv["name"] not in hidden)
        self.chk_tray_monitor.blockSignals(False)

        self.btn_mount.setText("Unmount from Network Places" if mounted else "Mount to Network Places")
        self.btn_wol.setText(f"Wake-on-LAN ({srv['mac']})" if srv["mac"] else "Wake-on-LAN (No MAC Set)")

        # Load custom commands for this target
        self.custom_cmd_list.clear()
        customs = {}
        if CUSTOM_CMD_FILE.exists():
            try:
                customs = json.loads(CUSTOM_CMD_FILE.read_text())
            except Exception:
                customs = {}

        for cc in customs.get(srv["name"], []):
            item = QListWidgetItem(f"{cc['label']}   ->   {cc['cmd']}")
            item.setData(Qt.ItemDataRole.UserRole, cc["cmd"])
            self.custom_cmd_list.addItem(item)

        if self.custom_cmd_list.count() > 0:
            self.custom_cmd_list.setCurrentRow(0)

    def run_for_selected(self, func):
        srv = self.current_server()
        if srv:
            func(srv)

    def on_tray_monitor_toggled(self, checked):
        srv = self.current_server()
        if not srv:
            return
        hidden = load_tray_hidden()
        if checked:
            hidden.discard(srv["name"])
        else:
            hidden.add(srv["name"])
        save_tray_hidden(hidden)
        self.ctrl.refresh_all(force=True)

    def toggle_selected_mount(self):
        srv = self.current_server()
        if srv:
            self.ctrl.toggle_mount(srv)
            self.sync_from_controller()

    def edit_selected_server(self):
        if 0 <= self.selected_server_idx < len(self.ctrl.servers):
            self.ctrl.open_server_manager_dialog(initial_idx=self.selected_server_idx, start_scanner=False)

    def open_custom_cmds_for_selected(self):
        srv = self.current_server()
        srv_name = srv["name"] if srv else ""
        self.ctrl.open_custom_command_dialog(initial_server_name=srv_name)

    def run_selected_custom_cmd(self):
        srv = self.current_server()
        row = self.custom_cmd_list.currentRow()
        if srv and 0 <= row < self.custom_cmd_list.count():
            cmd = self.custom_cmd_list.item(row).data(Qt.ItemDataRole.UserRole)
            self.ctrl.run_custom_command(srv, cmd)

    def open_tunnel_for_selected(self):
        srv = self.current_server()
        if not srv:
            return
        dlg = PortTunnelDialog(srv, self)
        if dlg.exec():
            lport = dlg.local_port.text().strip()
            rhost = dlg.remote_host.text().strip() or "127.0.0.1"
            rport = dlg.remote_port.text().strip()
            if lport and rport:
                self.ctrl.start_port_tunnel(srv, lport, rhost, rport)

    def manage_agent_for_selected(self):
        srv = self.current_server()
        if not srv:
            return
        msg = QMessageBox(self)
        msg.setWindowTitle(f"Telemetry Agent — {srv['name']}")
        msg.setText(
            f"Deploy or remove the lightweight UDP telemetry agent (sshm-agent.service) on {srv['user']}@{srv['host']}:{srv['port']}?"
        )
        deploy_btn = msg.addButton("Deploy / Update Agent", QMessageBox.ButtonRole.AcceptRole)
        remove_btn = msg.addButton("Uninstall Agent", QMessageBox.ButtonRole.DestructiveRole)
        msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        msg.exec()

        if msg.clickedButton() == deploy_btn:
            self.ctrl.deploy_telemetry_agent(srv)
        elif msg.clickedButton() == remove_btn:
            self.ctrl.remove_telemetry_agent(srv)


class SSHHubTray(QSystemTrayIcon):
    def __init__(self, app, start_gui=False, enable_tray=True):
        super().__init__()
        self.app = app
        self.enable_tray = enable_tray
        self.servers = []
        self.last_servers_sig = None
        self.status_cache = {}
        self.scanner_thread = None
        self.main_window = None

        self.server_ui = {}
        self.auto_act = None

        self.last_interaction = 0.0

        self.icon_online = make_status_dot("#52ff52", hollow=False)
        self.icon_offline = make_status_dot("#ff4d4d", hollow=True)
        self.icon_muted = make_status_dot("#7f849c", hollow=True)

        self.setIcon(make_tray_badge_icon("NONE"))
        self.setToolTip("SSH Connection Hub — Checking servers...")

        self.menu = QMenu()
        self.menu.aboutToShow.connect(self.on_menu_show)
        self.menu.aboutToHide.connect(self.on_menu_hide)
        self.menu.hovered.connect(self.on_menu_hovered)

        self.setContextMenu(self.menu)
        self.activated.connect(self.on_tray_activated)

        self.telem_thread = TelemetryListenerThread()
        self.telem_thread.instant_state_change.connect(lambda: self.refresh_all(force=False))
        self.telem_thread.show_gui_signal.connect(self.show_gui_window)
        self.telem_thread.start()

        self.refresh_all(force=True)
        self.timer = QTimer()
        self.timer.timeout.connect(self.on_timer_tick)
        self.timer.start(3000)

        if self.enable_tray:
            self.show()

        if start_gui:
            self.show_gui_window()

    def show_gui_window(self):
        was_closed = self.main_window is None
        if self.main_window is None:
            self.main_window = SSHHubMainWindow(self)
            self.main_window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            self.main_window.destroyed.connect(self.on_gui_closed)
        self.main_window.sync_from_controller()
        self.main_window.show()
        self.main_window.raise_()
        self.main_window.activateWindow()
        if was_closed:
            self.refresh_all(force=False)

    def on_gui_closed(self):
        self.main_window = None
        if not self.enable_tray:
            self.app.quit()

    def on_menu_show(self):
        self.last_interaction = time.monotonic()
        self.update_menu_in_place()
        self.refresh_all(force=False)

    def on_menu_hide(self):
        self.last_interaction = 0.0

    def on_menu_hovered(self, _action):
        self.last_interaction = time.monotonic()

    def is_user_browsing_menu(self):
        if (time.monotonic() - self.last_interaction) < 3.5:
            return True
        return False

    def on_timer_tick(self):
        if self.is_user_browsing_menu():
            return
        self.refresh_all(force=False)

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

    def get_servers_sig(self):
        custom_mtime = CUSTOM_CMD_FILE.stat().st_mtime if CUSTOM_CMD_FILE.exists() else 0
        hidden_mtime = TRAY_HIDDEN_FILE.stat().st_mtime if TRAY_HIDDEN_FILE.exists() else 0
        sig_servers = tuple(
            (s["name"], s["user"], s["host"], s["port"], s["tag"], s["mac"], s["key"])
            for s in self.servers
        )
        return (sig_servers, custom_mtime, hidden_mtime)

    def is_mounted(self, srv):
        safe_name = srv["name"].replace(" ", "_")
        if (MOUNT_DIR / f"{safe_name}.desktop").exists():
            return True
        remote_dir = Path.home() / ".local/share/remoteview"
        if (remote_dir / f"{safe_name}.desktop").exists():
            return True
        xbel = Path.home() / ".local/share/user-places.xbel"
        target_str = f"sftp://{srv['user']}@{srv['host']}:{srv['port']}"
        if xbel.exists() and target_str in xbel.read_text(errors="ignore"):
            return True
        gtk = Path.home() / ".config/gtk-3.0/bookmarks"
        if gtk.exists() and target_str in gtk.read_text(errors="ignore"):
            return True
        return False

    def refresh_all(self, force=False):
        self.load_servers()
        sig = self.get_servers_sig()

        if force or sig != self.last_servers_sig:
            self.last_servers_sig = sig
            self.build_menu_structure()
            if self.main_window:
                self.main_window.sync_from_controller()

        if not self.servers:
            self.setIcon(make_tray_badge_icon("NONE"))
            self.setToolTip("SSH Connection Hub (0 servers configured)")
            return

        if self.scanner_thread and self.scanner_thread.isRunning():
            return
        scan_all = self.main_window is not None
        self.scanner_thread = StatusScannerThread(self.servers, scan_all=scan_all)
        self.scanner_thread.results_ready.connect(self.on_scan_finished)
        self.scanner_thread.start()

    def on_scan_finished(self, results):
        self.status_cache.update(results)
        hidden = load_tray_hidden()
        tracked_indices = [idx for idx, s in enumerate(self.servers) if s["name"] not in hidden]
        online_count = sum(1 for idx in tracked_indices if self.status_cache.get(idx, (False, "", None))[0])
        total = len(tracked_indices)

        if total == 0:
            state = "NONE"
        elif online_count == total:
            state = "ALL_ON"
        elif online_count == 0:
            state = "ALL_OFF"
        else:
            state = "PARTIAL"

        self.setIcon(make_tray_badge_icon(state))
        self.setToolTip(f"SSH Connection Hub — {online_count}/{total} Tracked Online")

        if not self.is_user_browsing_menu():
            self.update_menu_in_place()

        if self.main_window:
            self.main_window.sync_from_controller()

    def build_menu_structure(self):
        self.menu.clear()
        self.server_ui.clear()

        open_gui_act = QAction(
            get_theme_icon(["network-server-symbolic", "applications-system"]),
            "Open SSH Connection Hub (GUI)",
            self.menu
        )
        font = open_gui_act.font()
        font.setBold(True)
        open_gui_act.setFont(font)
        open_gui_act.triggered.connect(self.show_gui_window)
        self.menu.addAction(open_gui_act)

        open_tui_act = QAction(
            get_theme_icon(["utilities-terminal-symbolic", "utilities-terminal"]),
            "Open Terminal TUI (sshm)",
            self.menu
        )
        open_tui_act.triggered.connect(self.launch_sshm_tui)
        self.menu.addAction(open_tui_act)

        self.menu.addSeparator()

        customs = {}
        if CUSTOM_CMD_FILE.exists():
            try:
                customs = json.loads(CUSTOM_CMD_FILE.read_text())
            except Exception:
                customs = {}

        hidden = load_tray_hidden()
        tracked_servers = [(idx, srv) for idx, srv in enumerate(self.servers) if srv["name"] not in hidden]

        if not tracked_servers:
            empty_act = QAction("No servers pinned to tray (Enable in GUI)", self.menu)
            empty_act.setEnabled(False)
            self.menu.addAction(empty_act)
        else:
            for idx, srv in tracked_servers:
                sub = QMenu(srv["name"], self.menu)
                sub.aboutToShow.connect(self.on_menu_show)
                sub.aboutToHide.connect(self.on_menu_hide)
                sub.hovered.connect(self.on_menu_hovered)

                ep_act = QAction(
                    get_theme_icon(["network-server-symbolic", "network-wired-symbolic"]),
                    f"{srv['user']}@{srv['host']}:{srv['port']}",
                    sub
                )
                ep_act.setEnabled(False)
                sub.addAction(ep_act)

                metrics_act = QAction(
                    get_theme_icon(["utilities-system-monitor-symbolic", "speedometer"]),
                    "Telemetry: Checking...",
                    sub
                )
                metrics_act.setEnabled(False)
                metrics_act.setVisible(False)
                sub.addAction(metrics_act)

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

                mnt_act = QAction(
                    get_theme_icon(["folder-saved-search-symbolic", "bookmark-new-symbolic"]),
                    "Mount to Network Places",
                    sub
                )
                mnt_act.triggered.connect(lambda checked=False, s=srv: self.toggle_mount(s))
                sub.addAction(mnt_act)

                srv_customs = customs.get(srv["name"], [])
                if srv_customs:
                    sub.addSeparator()
                    for cc in srv_customs:
                        cc_act = QAction(
                            get_theme_icon(["system-run-symbolic", "utilities-terminal"]),
                            cc["label"],
                            sub
                        )
                        cc_act.triggered.connect(lambda checked=False, s=srv, cmd=cc["cmd"]: self.run_custom_command(s, cmd))
                        sub.addAction(cc_act)

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
                self.server_ui[idx] = {
                    "sub": sub,
                    "ep_act": ep_act,
                    "metrics_act": metrics_act,
                    "mnt_act": mnt_act,
                }

        self.menu.addSeparator()

        manage_srv_act = QAction(
            get_theme_icon(["network-server-symbolic", "preferences-system-network"]),
            "Manage Server Profiles...",
            self.menu
        )
        manage_srv_act.triggered.connect(lambda: self.open_server_manager_dialog())
        self.menu.addAction(manage_srv_act)

        add_cmd_act = QAction(
            get_theme_icon(["document-new-symbolic", "system-run"]),
            "Manage Custom Server Commands...",
            self.menu
        )
        add_cmd_act.triggered.connect(lambda: self.open_custom_command_dialog())
        self.menu.addAction(add_cmd_act)

        ref_act = QAction(
            get_theme_icon(["view-refresh-symbolic", "reload"]),
            "Refresh Server Statuses Now",
            self.menu
        )
        ref_act.triggered.connect(lambda: self.refresh_all(force=True))
        self.menu.addAction(ref_act)

        self.auto_act = QAction(self.icon_online, "Launch at Login", self.menu)
        self.auto_act.triggered.connect(self.toggle_autostart)
        self.menu.addAction(self.auto_act)

        self.menu.addSeparator()

        quit_act = QAction(
            get_theme_icon(["application-exit-symbolic", "window-close-symbolic"]),
            "Quit Tray Monitor",
            self.menu
        )
        quit_act.triggered.connect(self.app.quit)
        self.menu.addAction(quit_act)

        self.update_menu_in_place()

    def update_menu_in_place(self):
        for idx, srv in enumerate(self.servers):
            ui = self.server_ui.get(idx)
            if not ui:
                continue

            is_on, lat, telem = self.status_cache.get(idx, (False, "OFFLINE", None))
            status_icon = self.icon_online if is_on else self.icon_offline
            tag_str = f" [{srv['tag']}]" if srv["tag"] else ""

            if is_on and telem:
                status_label = f"CPU {telem.get('cpu', '--')}% • {telem.get('ram', '--')}"
            elif is_on:
                status_label = "Live"
            else:
                status_label = "OFFLINE"

            ui["sub"].setTitle(f"{srv['name']}{tag_str}  ({status_label})")
            ui["sub"].setIcon(status_icon)

            ui["ep_act"].setText(
                f"{srv['user']}@{srv['host']}:{srv['port']}  —  {'ONLINE (' + lat + ')' if is_on else 'OFFLINE'}"
            )

            if is_on and telem:
                ui["metrics_act"].setText(
                    f"CPU: {telem.get('cpu', '--')}%   •   RAM: {telem.get('ram', '--')}   •   Up: {telem.get('up', '--')}"
                )
                ui["metrics_act"].setVisible(True)
            else:
                ui["metrics_act"].setVisible(False)

            mounted = self.is_mounted(srv)
            ui["mnt_act"].setText("Unmount from Network Places" if mounted else "Mount to Network Places")

        if self.auto_act:
            is_auto = AUTOSTART_FILE.exists()
            self.auto_act.setIcon(self.icon_online if is_auto else self.icon_muted)
            self.auto_act.setText(
                "Launch at Login: Enabled (Click to Disable)"
                if is_auto else
                "Launch at Login: Disabled (Click to Enable)"
            )

    def open_server_manager_dialog(self, initial_idx=-1, start_scanner=False):
        dialog = ServerManagerDialog(initial_idx=initial_idx, start_scanner=start_scanner, parent=self.main_window)
        dialog.exec()
        self.refresh_all(force=True)

    def open_custom_command_dialog(self, initial_server_name=""):
        self.load_servers()
        dialog = CustomCommandDialog(self.servers, initial_server_name=initial_server_name, parent=self.main_window)
        dialog.exec()
        self.refresh_all(force=True)

    def run_custom_command(self, srv, cmd):
        ssh_cmd = ["ssh", "-t", "-p", str(srv["port"])]
        if srv["key"]:
            key_path = os.path.expanduser(srv["key"])
            if os.path.exists(key_path):
                ssh_cmd += ["-i", key_path]
        target = f"{srv['user']}@{srv['host']}"
        full_cmd = (
            f"export PATH=\"$PATH:$HOME/.local/bin:$HOME/.cargo/bin:/home/linuxbrew/.linuxbrew/bin\"; "
            f"echo '=== Running: {cmd} ==='; {cmd}; echo ''; echo 'Press Enter to close...'; read"
        )
        ssh_cmd += [target, full_cmd]
        self.launch_in_terminal(ssh_cmd)

    def connect_sftp_shell(self, srv):
        cmd = ["sftp", "-P", str(srv["port"])]
        if srv["key"]:
            key_path = os.path.expanduser(srv["key"])
            if os.path.exists(key_path):
                cmd += ["-i", key_path]
        cmd.append(f"{srv['user']}@{srv['host']}")
        self.launch_in_terminal(cmd)

    def start_port_tunnel(self, srv, lport, rhost, rport):
        cmd = [
            "ssh", "-p", str(srv["port"]),
            "-L", f"{lport}:{rhost}:{rport}"
        ]
        if srv["key"]:
            key_path = os.path.expanduser(srv["key"])
            if os.path.exists(key_path):
                cmd += ["-i", key_path]
        target = f"{srv['user']}@{srv['host']}"
        hold_cmd = (
            f"echo '=== Active SSH Port Tunnel ==='; "
            f"echo 'Local Desktop: http://localhost:{lport}  -->  Remote: {rhost}:{rport}'; "
            f"echo 'Keep this terminal open while using the tunnel. Press Enter to close tunnel...'; read"
        )
        cmd += [target, hold_cmd]
        self.launch_in_terminal(cmd)

    def push_ssh_key(self, srv):
        cmd = ["ssh-copy-id", "-p", str(srv["port"])]
        if srv["key"]:
            key_path = os.path.expanduser(srv["key"])
            if os.path.exists(key_path):
                cmd += ["-i", key_path]
        target = f"{srv['user']}@{srv['host']}"
        wrapped = [
            "bash", "-c",
            f"echo '=== Pushing SSH Public Key to {target} ==='; "
            f"{' '.join(cmd)} {target}; echo ''; echo 'Press Enter to close...'; read"
        ]
        self.launch_in_terminal(wrapped)

    def get_hub_ip_for_target(self, target_host):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((target_host, 80))
                return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"

    def deploy_telemetry_agent(self, srv):
        hub_ip = self.get_hub_ip_for_target(srv["host"])
        ssh_opts = ["-t", "-p", str(srv["port"])]
        if srv["key"]:
            key_path = os.path.expanduser(srv["key"])
            if os.path.exists(key_path):
                ssh_opts += ["-i", key_path]
        target = f"{srv['user']}@{srv['host']}"

        remote_install = (
            f"mkdir -p ~/.local/bin ~/.config/systemd/user && "
            f"cat << 'AGENTEOF' > ~/.local/bin/sshm-agent.py\n"
            f"import os, sys, time, json, socket\n"
            f"HUB_IP = sys.argv[1]\n"
            f"HUB_PORT = int(sys.argv[2])\n"
            f"HOST_LBL = sys.argv[3]\n"
            f"SSH_PORT = sys.argv[4] if len(sys.argv) > 4 else '22'\n"
            f"sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\n"
            f"def get_cpu():\n"
            f"    with open('/proc/stat') as f: fields = [float(x) for x in f.readline().split()[1:]]\n"
            f"    return fields[3], sum(fields)\n"
            f"idle1, tot1 = get_cpu()\n"
            f"while True:\n"
            f"    time.sleep(2.0)\n"
            f"    idle2, tot2 = get_cpu()\n"
            f"    cpu = max(0.0, min(100.0, 100.0 * (1.0 - (idle2 - idle1) / max(1.0, tot2 - tot1))))\n"
            f"    idle1, tot1 = idle2, tot2\n"
            f"    mem = {{}}\n"
            f"    with open('/proc/meminfo') as f:\n"
            f"        for line in f:\n"
            f"            parts = line.split()\n"
            f"            if len(parts) >= 2: mem[parts[0].rstrip(':')] = int(parts[1])\n"
            f"    tot_g = mem.get('MemTotal', 1) / 1048576.0\n"
            f"    used_g = (mem.get('MemTotal', 1) - mem.get('MemAvailable', 0)) / 1048576.0\n"
            f"    ram = f'{{used_g:.1f}}/{{tot_g:.0f}}G'\n"
            f"    with open('/proc/uptime') as f: up_sec = int(float(f.readline().split()[0]))\n"
            f"    d, rem = divmod(up_sec, 86400); h, rem = divmod(rem, 3600); m, _ = divmod(rem, 60)\n"
            f"    up = f'{{d}}d {{h}}h' if d > 0 else f'{{h}}h {{m}}m'\n"
            f"    pkt = json.dumps({{'host': HOST_LBL, 'port': SSH_PORT, 'ssh': 1, 'cpu': f'{{cpu:.0f}}', 'ram': ram, 'up': up}}).encode()\n"
            f"    sock.sendto(pkt, (HUB_IP, HUB_PORT))\n"
            f"AGENTEOF\n"
            f"chmod +x ~/.local/bin/sshm-agent.py && "
            f"cat << 'SVCEOF' > ~/.config/systemd/user/sshm-agent.service\n"
            f"[Unit]\nDescription=SSHM Live Telemetry Agent\nAfter=network.target\n\n"
            f"[Service]\nExecStart=/usr/bin/env python3 %h/.local/bin/sshm-agent.py {hub_ip} {TELEM_PORT} {srv['host']} {srv['port']}\n"
            f"Restart=always\nRestartSec=3\n\n[Install]\nWantedBy=default.target\nSVCEOF\n"
            f"systemctl --user daemon-reload && systemctl --user enable --now sshm-agent.service && "
            f"loginctl enable-linger $USER 2>/dev/null || true; "
            f"echo '=== Telemetry Agent Deployed Successfully! ==='; echo 'Press Enter to close...'; read"
        )
        self.launch_in_terminal(["ssh"] + ssh_opts + [target, remote_install])

    def remove_telemetry_agent(self, srv):
        ssh_opts = ["-t", "-p", str(srv["port"])]
        if srv["key"]:
            key_path = os.path.expanduser(srv["key"])
            if os.path.exists(key_path):
                ssh_opts += ["-i", key_path]
        target = f"{srv['user']}@{srv['host']}"
        remote_rm = (
            "systemctl --user disable --now sshm-agent.service 2>/dev/null || true; "
            "rm -f ~/.config/systemd/user/sshm-agent.service ~/.local/bin/sshm-agent.py; "
            "systemctl --user daemon-reload 2>/dev/null || true; "
            "echo '=== Telemetry Agent Removed ==='; echo 'Press Enter to close...'; read"
        )
        self.launch_in_terminal(["ssh"] + ssh_opts + [target, remote_rm])

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_gui_window()

    def _resolve_default_terminal(self):
        import shutil
        import configparser

        def normalize_term_cmd(raw_parts):
            if not raw_parts:
                return []
            bin_path = raw_parts[0]
            b = Path(bin_path).name.lower()
            if b == "ghostty":
                return [bin_path, "-e"]
            if b == "wezterm":
                return [bin_path, "start", "--"]
            if b in ("ptyxis", "gnome-terminal", "kgx"):
                return [bin_path, "--"]
            if b in ("xfce4-terminal", "mate-terminal", "tilix", "terminator"):
                return [bin_path, "-x"]
            if len(raw_parts) == 1:
                return [bin_path, "-e"]
            return raw_parts

        de = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()

        # 1. Query KDE Plasma Default Applications (~/.config/kdeglobals)
        if "KDE" in de or (Path.home() / ".config/kdeglobals").exists():
            kdeglobals = Path.home() / ".config/kdeglobals"
            if kdeglobals.exists():
                try:
                    cfg = configparser.ConfigParser(interpolation=None, strict=False)
                    cfg.read(kdeglobals)
                    if cfg.has_section("General") and cfg.has_option("General", "TerminalApplication"):
                        term_app = cfg.get("General", "TerminalApplication").strip()
                        if term_app:
                            parts = term_app.split()
                            if shutil.which(parts[0]):
                                return normalize_term_cmd(parts)
                except Exception:
                    pass

        # 2. Check user $TERMINAL environment variable
        env_term = os.environ.get("TERMINAL", "").strip()
        if env_term:
            parts = env_term.split()
            if shutil.which(parts[0]):
                return normalize_term_cmd(parts)

        # 3. Query GNOME / Cinnamon / MATE GSettings Default Terminal
        if any(x in de for x in ("GNOME", "CINNAMON", "MATE", "BUDGIE", "UNITY", "PANTHEON")):
            schemas = [
                ("org.cinnamon.desktop.default-applications.terminal", "exec"),
                ("org.gnome.desktop.default-applications.terminal", "exec"),
                ("org.mate.applications-terminal", "exec"),
            ]
            for schema, key in schemas:
                try:
                    res = subprocess.run(
                        ["gsettings", "get", schema, key],
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=0.5
                    )
                    if res.returncode == 0:
                        val = res.stdout.strip().strip("'")
                        if val:
                            parts = val.split()
                            if shutil.which(parts[0]):
                                return normalize_term_cmd(parts)
                except Exception:
                    pass

        # 4. Query XFCE Default Terminal Helper
        if "XFCE" in de and shutil.which("exo-open"):
            return ["exo-open", "--launch", "TerminalEmulator"]

        # 5. Check universal terminal wrappers
        for wrapper in ("xdg-terminal-exec", "x-terminal-emulator", "sensible-terminal"):
            if shutil.which(wrapper):
                return [wrapper]

        # 6. Fallback to installed terminals if no DE preference is set
        fallbacks = [
            ["konsole", "-e"],
            ["ghostty", "-e"],
            ["ptyxis", "--"],
            ["kgx", "--"],
            ["gnome-terminal", "--"],
            ["xfce4-terminal", "-x"],
            ["cosmic-term", "-e"],
            ["kitty", "-e"],
            ["alacritty", "-e"],
            ["wezterm", "start", "--"],
            ["xterm", "-e"],
        ]
        for f in fallbacks:
            if shutil.which(f[0]):
                return f
        return []

    def launch_in_terminal(self, cmd_list):
        term_prefix = self._resolve_default_terminal()
        if term_prefix:
            subprocess.Popen(term_prefix + cmd_list)

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
        remote_dir = Path.home() / ".local/share/remoteview"
        remote_dir.mkdir(parents=True, exist_ok=True)

        safe_name = srv["name"].replace(" ", "_")
        desktop_file = MOUNT_DIR / f"{safe_name}.desktop"
        remote_file = remote_dir / f"{safe_name}.desktop"

        target_dir = "/root" if srv["user"] == "root" else f"/home/{srv['user']}"
        url = f"sftp://{srv['user']}@{srv['host']}:{srv['port']}{target_dir}"
        match_prefix = f"sftp://{srv['user']}@{srv['host']}:{srv['port']}"

        xbel_file = Path.home() / ".local/share/user-places.xbel"
        gtk_file = Path.home() / ".config/gtk-3.0/bookmarks"

        if self.is_mounted(srv):
            desktop_file.unlink(missing_ok=True)
            remote_file.unlink(missing_ok=True)
            if gtk_file.exists():
                lines = [
                    l for l in gtk_file.read_text(errors="ignore").splitlines()
                    if match_prefix not in l
                ]
                gtk_file.write_text("\n".join(lines) + ("\n" if lines else ""))
            if xbel_file.exists():
                try:
                    raw_xml = xbel_file.read_text(errors="ignore")
                    import re
                    pattern = re.compile(
                        r'\s*<bookmark[^>]*href="' + re.escape(match_prefix) + r'[^"]*"[^>]*>.*?</bookmark>',
                        re.DOTALL
                    )
                    new_xml = pattern.sub("", raw_xml)
                    xbel_file.write_text(new_xml)
                except Exception:
                    pass
        else:
            desktop_content = (
                f"[Desktop Entry]\n"
                f"Charset=\n"
                f"Icon=folder-remote\n"
                f"Name={srv['name']} ({srv['user']}@{srv['host']}:{srv['port']})\n"
                f"Type=Link\n"
                f"URL[$e]={url}\n"
            )
            desktop_file.write_text(desktop_content)
            desktop_file.chmod(0o755)

            remote_file.write_text(desktop_content)
            remote_file.chmod(0o755)

            gtk_file.parent.mkdir(parents=True, exist_ok=True)
            existing_gtk = gtk_file.read_text(errors="ignore").splitlines() if gtk_file.exists() else []
            if not any(match_prefix in l for l in existing_gtk):
                existing_gtk.append(f"{url} SSH: {srv['name']}")
                gtk_file.write_text("\n".join(existing_gtk) + "\n")

            if xbel_file.exists():
                try:
                    raw_xml = xbel_file.read_text(errors="ignore")
                    if match_prefix not in raw_xml and "</xbel>" in raw_xml:
                        bookmark_snippet = (
                            f' <bookmark href="{url}">\n'
                            f'  <title>SSH: {srv["name"]}</title>\n'
                            f'  <info>\n'
                            f'   <metadata owner="http://freedesktop.org">\n'
                            f'    <bookmark:icon name="folder-remote"/>\n'
                            f'   </metadata>\n'
                            f'   <metadata owner="http://www.kde.org">\n'
                            f'    <ID>{int(time.time())}/{safe_name}</ID>\n'
                            f'    <isSystemItem>false</isSystemItem>\n'
                            f'   </metadata>\n'
                            f'  </info>\n'
                            f' </bookmark>\n'
                            f'</xbel>'
                        )
                        raw_xml = raw_xml.replace("</xbel>", bookmark_snippet)
                        xbel_file.write_text(raw_xml)
                except Exception:
                    pass
        self.update_menu_in_place()

    def send_wol(self, srv):
        if not srv.get("mac"):
            QMessageBox.warning(self.main_window, "Missing MAC", f"No MAC address saved for {srv['name']}. Edit the server profile to auto-detect or enter its MAC.")
            return
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
        self.update_menu_in_place()


def notify_existing_instance(start_gui=False):
    test_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        test_sock.bind(("0.0.0.0", TELEM_PORT))
        test_sock.close()
        return False
    except OSError:
        test_sock.close()
        if start_gui:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                    s.sendto(json.dumps({"cmd": "SHOW_GUI"}).encode(), ("127.0.0.1", TELEM_PORT))
            except Exception:
                pass
        return True


if __name__ == "__main__":
    invoked_name = Path(sys.argv[0]).name
    args = set(sys.argv[1:])

    enable_tray = "--no-tray" not in args
    start_gui = ("--gui" in args) or ("--no-tray" in args) or ("gui" in invoked_name.lower())

    if notify_existing_instance(start_gui=start_gui):
        sys.exit(0)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(not enable_tray)
    tray = SSHHubTray(app, start_gui=start_gui, enable_tray=enable_tray)
    sys.exit(app.exec())
