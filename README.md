# ◆ sshm — SSH Connection Hub & System Tray Monitor (v2.1.0)

A fast, modular, mouse-driven terminal UI (`sshm`) and native Linux system tray companion (`sshm-tray.py`) for managing SSH servers, SFTP network folder mounts, Wake-on-LAN, and local subnet discovery.

Built for both **Linux Desktops** (KDE Plasma / GNOME / XFCE) and **Android / Termux** with an automatic responsive layout.

---

## ✨ What's New in v2.1.0

* **🎯 Server-First Target Inspector:** Click any server on the left (or press `1–9` / `↑`/`↓`) to make it the active target. The right-hand inspector updates live with its endpoint, ping latency, mount state, and 1-click actions. Double-click an active server (or press `Enter`) to jump straight into SSH!
* **📡 Parallel LAN SSH & Hardware MAC Scanner (`[n]`):** Sweeps your local `/24` network in ~1.5 seconds for open Port 22 nodes, resolves hostnames, and queries the ARP cache (`ip neigh`) for hardware MAC addresses. Click rows to multi-select new nodes or sync missing MAC addresses to existing profiles.
* **🔍 Auto-MAC & Hostname Probing:** Adding (`[a]`) or editing (`[e]`) a server automatically probes the IP on your local network to fill in its hostname and Wake-on-LAN MAC address (or type `scan` in the MAC prompt anytime).
* **🎨 Live Border & UI Theme Picker (`[p]`):** Choose from 8 built-in color palettes (*Royal Purple*, *Cyber Neon*, *Matrix Green*, *Solar Amber*, *Crimson Red*, *Oceanic Blue*, *Rose Pink*, *Stealth Slate*) with live on-screen preview. Saved automatically to `~/.ssh_hub_theme`.
* **📱 Auto-Mobile / Termux Portrait Mode:** Automatically detects narrow screens (`< 88` columns or Termux portrait mode) and stacks the **Remote Nodes** and **Target Inspector** panes vertically for thumb-friendly touch navigation.
* **🖥️ Native Symbolic Tray Icons (`sshm-tray.py`):** Dynamically detects `$XDG_CURRENT_DESKTOP` to use crisp, monochrome wireframe symbolic icons (`QIcon.fromTheme`) that match KDE Breeze and GTK system menus.

---

## 🖥️ Interface Preview (Desktop Mode)

```text
╭────────────────────────────────────────────────────────────────────────────╮
│ ◆ SSH CONNECTION HUB (v2.1.0)                                   [Tag: ALL] │
╰────────────────────────────────────────────────────────────────────────────╯
╭─ REMOTE NODES (2) ─────────────────╮ ╭─ TARGET: Homelab Node [Homelab] ────╮
│ ▸ ● ◆ [ 1]  Homelab Node      1ms  │ │  Endpoint : lucas@192.168.4.50:22   │
│   ● ◇ [ 2]  Minecraft_server  0ms  │ │  Status   : ● ONLINE (1ms) • ◆ Mnt  │
│                                    │ ├─────────────────────────────────────┤
│                                    │ │  [c]   Connect via SSH (Auto-tmux)  │
│                                    │ │  [b]   Open Network Folder in GUI   │
│                                    │ │  [s]   Interactive SFTP Shell       │
│                                    │ │  [t]   Port Tunneling (Local Fwd)   │
│                                    │ │  [w]   Wake-on-LAN (d4:be:d9:...)   │
│                                    │ │  [k]   Push SSH Public Key          │
│                                    │ │  [e]   Edit Target Server Profile   │
│                                    │ │  [d]   Delete Target Server Profile │
├────────────────────────────────────┤ ├─────────────────────────────────────┤
│ ● Online  ○ Offline  ◆ /◇ Click Mnt│ │  [a]   Add New Server Profile       │
│ Click server to target • 2x-Click  │ │  [n]   Scan Local Network (SSH)     │
│                                    │ │  [p]   Border & UI Theme (Purple)   │
│                                    │ │  [r]   Refresh All Server Statuses  │
│                                    │ │  [q]   Exit SSH Connection Hub      │
╰────────────────────────────────────╯ ╰─────────────────────────────────────╯
╭────────────────────────────────────────────────────────────────────────────╮
│ Target: Homelab Node  |  [Enter/c] SSH  [n] Scan LAN  [a] Add  [q] Quit:   │
╰────────────────────────────────────────────────────────────────────────────╯

Modular Project Structure
Plaintext

sshm/
├── src/
│   ├── 01_header.sh    # State arrays, ANSI colors, 8 UI themes & mouse traps
│   ├── 02_ui.sh        # Desktop & Termux responsive geometry + pane renderers
│   ├── 03_backend.sh   # Parallel ping, ARP MAC prober, Dolphin/GTK mount sync
│   ├── 04_actions.sh   # SSH/SFTP, port tunnels, LAN scanner, theme picker
│   └── 05_main.sh      # Main event loop, SGR 1006 mouse tracking & dispatcher
├── sshm                # Compiled standalone executable (built via build.sh)
├── sshm-tray.py        # PyQt6 system tray monitor with native DE icons
├── dev.sh              # Live test runner (assembles src/* into a temp run)
├── build.sh            # Compiles src/* modules into the standalone ./sshm script
└── install.sh          # Installs sshm to ~/.local/bin and sets up desktop entries

Installation & Usage
1. Build & Install
Bash

chmod +x dev.sh build.sh install.sh sshm-tray.py
./install.sh

(Make sure ~/.local/bin is in your $PATH.)
2. Development & Live Testing

When editing individual modules inside src/, test your changes immediately without reinstalling:
Bash

./dev.sh

3. Launch the Hub or Tray Monitor

    Terminal UI: Run sshm in any terminal (Konsole, Ptyxis, Termux, etc.).

    System Tray Companion: Run ./sshm-tray.py & (requires python3-pyqt6).

Controls & Mouse Shortcuts
Input	Action
Left-Click Server Row	Select server as active Target (▸)
2x-Click Server / Enter / c	Connect to active Target via SSH (with optional tmux attach)
Click ◆ / ◇ Diamond	Toggle GUI File Manager network bookmark (KDE Dolphin / GTK)
1 – 9 or ↑ / ↓ Arrows	Switch active Target server via keyboard
b	Open Target's home folder in GUI File Manager (sftp://)
s	Open interactive SFTP shell to Target
t	Create a background local port tunnel (localhost:LPORT -> remote:RPORT)
w	Send Wake-on-LAN magic packet to Target's saved MAC address
k	Push SSH public key to Target (ssh-copy-id)
e / d	Edit or Delete active Target profile
a	Add a new server profile (auto-probes Hostname & MAC from IP)
n	Launch Parallel /24 Local Network SSH & MAC Scanner
p	Open Live Border & UI Theme Picker (1–8)
f	Cycle server tag filters ([Tag: ALL], [Tag: Homelab], etc.)
r / q	Refresh all server statuses / Exit Hub

Configuration Files

    ~/.ssh_servers: Pipe-delimited server profiles (Name|User|Host|Port|Tag|MAC|KeyPath).

    ~/.ssh_hub_theme: Stores your selected border theme index (0–7).

    ~/Network_Servers/: Stores .desktop network links alongside native KDE Dolphin (user-places.xbel) and GTK (~/.config/gtk-3.0/bookmarks) sidebar entries.
    EOF
