<div align="center">

<img src="src/sshm/data/sshm.svg" width="96" alt="sshm icon">

# sshm — SSH Connection Hub

**One place for every server you SSH into.**
Desktop app · tray monitor · terminal UI · scriptable CLI, all sharing one config.

[![CI](https://github.com/marioman68/sshm/actions/workflows/ci.yml/badge.svg)](https://github.com/marioman68/sshm/actions/workflows/ci.yml)
[![COPR](https://copr.fedorainfracloud.org/coprs/lucasdunham85/sshm/package/sshm/status_image/last_build.png)](https://copr.fedorainfracloud.org/coprs/lucasdunham85/sshm/)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![Linux](https://img.shields.io/badge/platform-Linux-informational)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

</div>

---

## Contents

- [Highlights](#highlights)
- [Screenshots](#screenshots)
- [Install](#install)
- [Upgrading from 2.x](#upgrading-from-2x)
- [Using sshm](#using-sshm)
- [Desktop app in Rust](#desktop-app-in-rust-desktop)
- [Live telemetry](#live-telemetry)
- [Files & settings](#files--settings)
- [Architecture](#architecture)
- [Development](#development)

## Highlights

| | |
|---|---|
| **Four front-ends, one brain** | A PyQt6 desktop app, a system-tray monitor, a curses terminal UI that works over SSH, and a CLI. They share one core library and one config file, so a change made in one shows up in the others right away. |
| **Never blocks** | Status probes, LAN scans, SSHFS mounts and tunnels all run on background threads, so the UI never freezes waiting on a slow host. |
| **Real status** | A TCP probe measures latency and reads each server's SSH banner (e.g. `OpenSSH_9.8`). A host that is up but has sshd stopped shows as *degraded*. |
| **Live metrics** | An optional zero-dependency agent reports CPU, memory, swap, disk, load, uptime and OS. Packets are **HMAC-SHA256 signed** with a per-install key. |
| **Find anything fast** | Fuzzy search, tags, favourites, and sorting by name, status, latency or most recently used. |
| **Connect your way** | Plain SSH or a persistent `tmux` session per server, ProxyJump / bastion hosts, and per-server identity files. |
| **Process viewer** | A live, sortable, filterable process list for any server, with end/force-kill (and a sudo fallback) or one-click `htop`. It needs no agent, and refreshes reuse one multiplexed SSH connection. When the agent is installed, the top processes also appear on the dashboard and in the tray. |
| **Docker & Podman aware** | sshm notices when a saved server is really a container: a profile on the same machine as another one, on a port that a container publishes. It shows that profile as ⬢ *container on host*, with the container's own CPU and memory (from cgroups, not the host's numbers), its status and health, image, ports and compose project. It also offers restart, stop/start, logs, and a shell that goes through the host even if the container's sshd is down. Docker hosts get a Containers view of every container. |
| **Game & web services** | Containers that publish Minecraft show live **players, version and MOTD**. Published web UIs (Jellyfin, Home Assistant, Portainer…) show as clickable links. |
| **Alerts & history** | Notifications when a server goes down, CPU or memory stays high, a disk fills up, a container stops or turns unhealthy, or a machine needs a reboot after a kernel update. Alerts fire only on real changes, so machines that are always off don't nag. Every server shows 24-hour and 7-day **uptime**, and the full activity log is one click away. |
| **Run on many servers** | Run one command on a tag, a hand-picked set or every server at once (updates, `df -h`, `docker ps`…). Output appears side by side with exit codes, in the GUI, TUI (<kbd>X</kbd>) and CLI (`sshm exec`). |
| **Backup & restore** | Export every server, with tags, MAC addresses and saved commands, to a JSON file and restore it on another machine. Keys and secrets are never included. |
| **Tunnels** | Background `-L` / `-R` / `-D` (SOCKS) forwards, listed and stoppable from any front-end. |
| **Files** | Open `sftp://` in your file manager, bookmark the server in Dolphin, Nautilus, Thunar, Nemo or Caja, or do a real **SSHFS** mount. |
| **Discovery** | A parallel LAN scan across several ports keeps only hosts that answer with an SSH banner, and fills in MAC addresses from ARP. |
| **Interop** | Import from and export to `~/.ssh/config` (`Include` directives are followed). |
| **Saved commands** | Per-server one-click commands (`topgrade`, `docker ps`, updates…), available in the GUI, tray, TUI and CLI. |
| **Wake-on-LAN** | Magic packets go to UDP 9 and 7; `sshm wake nas --wait` blocks until SSH answers. |
| **Themes** | Ten themes, including a light one, shared between the GUI and TUI. |

## Screenshots

> Add your own captures to `screenshots/` and they will appear here.

| Desktop app | Terminal UI |
|---|---|
| ![GUI](screenshots/gui.png) | ![TUI](screenshots/tui.png) |

## Install

### Any distro (user install, no root)

```bash
git clone https://github.com/marioman68/sshm.git
cd sshm
./install.sh                # or: ./install.sh --no-autostart
```

The installer copies sshm to `~/.local/share/sshm` and creates the `sshm`, `sshm-gui` and `sshm-tray` commands in `~/.local/bin`. It also adds a menu entry and an icon, and enables the tray at login. It does not use pip, so it works on PEP 668 distros, Silverblue and Bazzite.

The terminal UI and CLI use only the Python standard library. The desktop app needs PyQt6:

| Distro | Command |
|---|---|
| Fedora | `sudo dnf install python3-pyqt6` |
| Debian / Ubuntu | `sudo apt install python3-pyqt6` |
| Arch / CachyOS | `sudo pacman -S python-pyqt6` |
| openSUSE | `sudo zypper install python3-PyQt6` |

Optional extras: `tmux` (persistent sessions), `sshfs` (real mounts), `wl-clipboard` or `xclip` (copying commands from the TUI).

Uninstall with `./install.sh --uninstall`. Your servers and settings are kept.

### Fedora (COPR)

Packages are published at [copr.fedorainfracloud.org/coprs/lucasdunham85/sshm](https://copr.fedorainfracloud.org/coprs/lucasdunham85/sshm/).

```bash
sudo dnf copr enable lucasdunham85/sshm
sudo dnf install sshm                  # terminal UI + CLI, and the desktop app via sshm-gui
```

The package is split in two: `sshm` (terminal UI and CLI, no Qt) and `sshm-gui` (desktop app and tray). `sshm-gui` is pulled in automatically as a weak dependency. On a headless server, skip it with `sudo dnf install --setopt=install_weak_deps=False sshm`.

### pip / pipx

```bash
pipx install git+https://github.com/marioman68/sshm
pipx inject sshm PyQt6        # only needed for the desktop app
```

## Upgrading from 2.x

There's nothing to do. On first launch sshm 3 imports `~/.ssh_servers`, `~/.ssh_custom_commands.json`, `~/.ssh_tray_hidden.json`, your theme and your refresh interval into `~/.config/sshm/`. The old files are left untouched so you can roll back.

Agents deployed by 2.x keep reporting: their unsigned packets are accepted while **Settings → Accept unsigned telemetry** is on. Redeploy each agent (`g` in the TUI, **More → Telemetry agent** in the GUI) to switch it to signed packets, then turn that setting off.

The old Bash TUI (`src/0*_*.sh`) has been retired. The Python TUI replaces it.

## Using sshm

### Desktop app — `sshm-gui`

- The sidebar has fuzzy search (<kbd>Ctrl</kbd>+<kbd>K</kbd>), a tag filter, sorting, and status cards showing latency and a CPU bar for every server.
- The detail view shows a status pill, metric cards (CPU sparkline, memory, disk, uptime), connection details, saved commands and active tunnels.
- **Processes** (<kbd>Ctrl</kbd>+<kbd>P</kbd>) opens a live table of every process on the server. Click a column to sort, filter by name, user or PID, and use **End process** / **Force kill**, or **Open htop**. With the agent installed, a *Top processes* card also shows on the server page.
- **Containers**: a container server shows a *Container* card (status, image, ports, compose project, Minecraft players and web links) with **Restart**, **Stop/Start**, **Logs** and **Shell**. Its metric cards show the container's own CPU and memory. A Docker host gets a **Containers** tab listing every container; double-click one that is saved in sshm to jump to it. **More → Find docker containers** checks any server on demand.
- **Connect** is a split button: plain, tmux, SFTP, or copy the ssh command. **Files** opens the server in your file manager, toggles a bookmark, or mounts it with SSHFS. **More** has tunnels, Wake-on-LAN, key push, the agent, and edit/duplicate/delete.
- Shortcuts: <kbd>Enter</kbd> connect · <kbd>Ctrl</kbd>+<kbd>T</kbd> tmux · <kbd>Ctrl</kbd>+<kbd>N</kbd> add · <kbd>Ctrl</kbd>+<kbd>E</kbd> edit · <kbd>Del</kbd> delete · <kbd>F5</kbd> refresh · <kbd>Ctrl</kbd>+<kbd>,</kbd> settings.
- Closing the window keeps sshm in the tray. Launching `sshm-gui` again just raises the existing window.

### Tray — `sshm-tray`

The badge on the tray icon turns green, amber or red depending on whether all, some, or none of your pinned servers are up. Each server gets a submenu with its top processes (when the agent is installed), connect, tmux, files, SFTP, the process viewer, saved commands and Wake-on-LAN. You get a desktop notification when a pinned server goes down or comes back. Turn **Show in tray** off for any server you don't want polled or shown there.

### Terminal UI — `sshm`

```
 ◆ sshm  SSH Connection Hub                        ⟳ 10s  ⇅ Name  ⚑ All  ● 3/4 online
╭─ Servers (4) ─────────────────────────╮╭─ nas ──────────────────────── ● Online ─╮
│▌ ● ★ nas            Homelab  48% 1 ms ││  Endpoint  lucas@192.168.4.10:22         │
│  ○ · backup         Offsite        -- ││  Status    ● Online · 1 ms · OpenSSH_9.8  │
│  ● · pihole         Lab      12% 2 ms ││  SYSTEM ──────────────────────────────    │
│  ○ · router         Network        -- ││  CPU     ██████████░░░░░░ 47.5% ▁▂▃▅▇▅▄   │
╰───────────────────────────────────────╯╰───────────────────────────────────────────╯
 ⏎ connect  / search  a add  n scan  e edit  t tunnel  ? help  q quit   updated 2s ago
```

Press <kbd>?</kbd> for the full key reference. The most useful keys:

| Key | Action | Key | Action |
|---|---|---|---|
| <kbd>Enter</kbd> | connect | <kbd>m</kbd> | connect in tmux |
| <kbd>/</kbd> | fuzzy search | <kbd>f</kbd> / <kbd>F</kbd> | next tag / pick tag |
| <kbd>s</kbd> | SFTP shell | <kbd>o</kbd> | open in file manager |
| <kbd>b</kbd> | bookmark | <kbd>M</kbd> | SSHFS mount |
| <kbd>t</kbd> / <kbd>T</kbd> | new tunnel / list tunnels | <kbd>w</kbd> | Wake-on-LAN |
| <kbd>k</kbd> | push SSH key | <kbd>g</kbd> | telemetry agent |
| <kbd>P</kbd> | process viewer | <kbd>D</kbd> | containers (restart / stop / logs / shell) |
| <kbd>X</kbd> | run a command on many servers | <kbd>!</kbd> | alerts & activity log |
| <kbd>x</kbd> | saved commands | <kbd>y</kbd> | copy ssh command |
| <kbd>a</kbd> / <kbd>e</kbd> / <kbd>d</kbd> | add / edit / delete | <kbd>*</kbd> | favourite |
| <kbd>n</kbd> | scan network | <kbd>i</kbd> / <kbd>E</kbd> | import / export ssh_config |
| <kbd>p</kbd> | theme (live preview) | <kbd>,</kbd> | settings |

In the process viewer (<kbd>P</kbd>): <kbd>c</kbd>/<kbd>m</kbd>/<kbd>p</kbd>/<kbd>n</kbd>/<kbd>u</kbd>/<kbd>t</kbd> sort by CPU, memory, PID, name, user or running time · <kbd>/</kbd> filter · <kbd>Enter</kbd> details · <kbd>k</kbd> end process · <kbd>K</kbd> force kill · <kbd>h</kbd> htop.

Mouse support: click to select, double-click to connect, scroll the wheel, and click any action or header chip. The layout switches to stacked panes on narrow terminals.

### CLI

```bash
sshm ls --status                     # table with latency and CPU
sshm c nas                           # connect (names can be abbreviated)
sshm c nas -m                        # ...in tmux
sshm c nas -- df -h                  # run a one-off remote command
sshm c nas -p                        # print the ssh command instead
sshm add me@10.0.0.5:2222 -n nas -t Homelab -J bastion
sshm scan 192.168.1.0/24 --add       # discover and add
sshm import --dry-run                # preview ~/.ssh/config import
sshm export -t Homelab >> ~/.ssh/config
sshm tunnel start nas -L 8080:localhost:80
sshm tunnel                          # list;  sshm tunnel stop all
sshm ps nas                          # top 25 processes by CPU
sshm ps nas -s mem -f postgres -w    # filter, sort by memory, refresh every 3s
sshm ps nas --kill 4242 [--force]    # SIGTERM / SIGKILL
sshm top nas                         # htop (or top) on the server
sshm docker homelab                  # containers on a host (docker or podman)
sshm docker minecraft                # a saved server that is a container → its details
sshm docker minecraft restart        # ...acting through its host;  also stop/start/logs/shell/stats
sshm exec -t Homelab -- 'df -h /'     # run on every server tagged Homelab
sshm exec --all -s -- uptime         # every server, one line each as they finish
sshm history                         # 24h / 7d uptime and latency for all servers
sshm events                          # active alerts and the activity log
sshm backup ~/sshm.json              # export servers (no secrets);  sshm restore ~/sshm.json
sshm wake nas --wait                 # WoL, then wait for SSH
sshm run nas --add 'sudo dnf upgrade -y' Update
sshm run nas Update
sshm agent deploy nas                # or: status / remove
sshm ls --json | jq '.[].host'
```

## Desktop app in Rust (`desktop/`)

The desktop window and tray monitor are rewritten in Rust (egui, plus a native StatusNotifierItem tray). They are a
drop-in replacement for the PyQt `sshm-gui` / `sshm-tray`, use the same `~/.config/sshm` files, the same signed
telemetry, history database and tunnel list, so the Python terminal UI and CLI keep working alongside.

```bash
cd desktop && ./install.sh        # builds, installs sshm-gui + sshm-tray, keeps the Python ones as *.python
./install.sh --uninstall          # puts the Python launchers back
```

- **Tray icon that fits the desktop:**
  - The icon is a line-drawn server stack. A status dot shows green (all servers up), amber (some up) or red (none up).
  - On KDE it is drawn in your panel's text colour, read from the Plasma theme, and redrawn when you switch light/dark.
  - On GNOME, Ubuntu and COSMIC it is white. On XFCE, MATE, Cinnamon and others it is a small colour tile.
  - Override it in **Settings → Tray icon**.
- **Two processes:**
  - `sshm-gui --tray` is the long-running monitor: it receives telemetry, records uptime history and sends alert notifications.
  - The window is its own process. Closing it leaves the tray running, and **File → Quit sshm** stops both.
- **Requirements:** a Rust toolchain to build. Running needs no Python or Qt. Agents on your servers stay the
  zero-dependency Python agent.

## Live telemetry

```
 remote host                                   your desktop
┌──────────────────────┐   UDP 55889 (signed)  ┌──────────────────────┐
│ sshm-agent.service   │ ────────────────────▶ │ sshm tray / GUI / TUI │
│ (systemd --user, py) │   every 3 s           │ verifies HMAC, caches │
└──────────────────────┘                       └──────────────────────┘
```

- **Reports** CPU, memory, swap, disk, load, uptime, OS, whether a reboot is needed, its own version (sshm offers an update when a newer agent is bundled), and the top processes by CPU and memory, which it computes from `/proc` without spawning anything. On Docker/Podman hosts it also reports every container with live CPU and memory read from the API socket and cgroups. The agent's user needs access to the socket (e.g. membership of the `docker` group). Without the agent, sshm discovers containers over SSH instead, about once a minute.
- **Deploy** with `g` (TUI), **More → Telemetry agent** (GUI) or `sshm agent deploy NAME`. The installer runs as `bash -s` over SSH and needs only `python3` on the remote host; no root is required. It installs a systemd user service and enables lingering. On hosts without a systemd user session it falls back to `nohup`.
- **Security**: every packet carries an HMAC-SHA256 signature made with a secret generated on your machine (`~/.config/sshm/settings.json`, mode 0600). Packets older than 5 minutes are dropped. The secret is sent to the remote host over SSH stdin, so it never appears on a command line. Single-instance IPC uses a per-user local socket, not the network.
- **Firewall**: allow UDP 55889 in, e.g. `sudo firewall-cmd --add-port=55889/udp --permanent && sudo firewall-cmd --reload`.

## Files & settings

| Path | Contents |
|---|---|
| `~/.config/sshm/servers.json` | Server profiles (including saved commands) |
| `~/.config/sshm/settings.json` | Theme, refresh interval, terminal, telemetry key… |
| `$XDG_RUNTIME_DIR/sshm/telemetry.json` | Latest metrics (RAM-backed, per user) |
| `$XDG_RUNTIME_DIR/sshm/tunnels.json` | Active background tunnels |
| `~/.local/state/sshm/history.db` | Uptime / latency history and the alert log (SQLite, 30 days) |
| `~/Network_Servers/` | SFTP bookmark links and SSHFS mount points |

Run `sshm paths` to print the actual locations on your system. Writes are atomic and use a file lock, so the GUI, tray and TUI can all be open at once. Set `SSHM_CONFIG_DIR` / `SSHM_RUNTIME_DIR` to use a different profile.

The **terminal** sshm opens is detected from `$TERMINAL`, KDE/GNOME defaults and `xdg-terminal-exec`, with Konsole, Ptyxis, GNOME Console, Ghostty, Kitty, WezTerm, Alacritty, foot, COSMIC and others as fallbacks. Override it in Settings.

## Architecture

```
src/sshm/
├── core/            UI-independent library (stdlib only)
│   ├── models.py    Server / CustomCommand dataclasses, validation, fuzzy match
│   ├── store.py     JSON store, locking, legacy migration
│   ├── hub.py       background probing + telemetry controller shared by front-ends
│   ├── status.py    TCP latency + SSH banner probes
│   ├── telemetry.py signed packet protocol, UDP listener, cache
│   ├── agent.py     remote installer / remover   (agent source: data/sshm_agent.py)
│   ├── sshcmd.py    argv builders — never shell strings
│   ├── tunnels.py   -L/-R/-D lifecycle across processes
│   ├── containers.py docker/podman discovery, container ↔ server linking, actions
│   ├── minecraft.py Minecraft server-list ping (players / version / MOTD)
│   ├── history.py   SQLite uptime/latency samples + event log      alerts.py  alert rules
│   ├── fleet.py     parallel command runner, backup / restore
│   ├── procs.py     remote ps (GNU + BusyBox), kill, htop — over a ControlMaster session
│   ├── mounts.py    file-manager bookmarks + SSHFS
│   ├── netscan.py   LAN discovery     sshconfig.py  ~/.ssh/config import/export
│   └── terminal.py  terminal detection   wol.py  clipboard.py  themes.py  settings.py
├── tui/             curses UI (widgets.py: modals, palette, canvas)
├── gui/             PyQt6 app, tray, dialogs, painted widgets
└── cli.py           argparse front door (`sshm` with no args → TUI)
```

## Development

```bash
make run          # TUI from the source tree
make gui          # desktop app from the source tree
make test         # pytest: core, CLI, TUI (in a pseudo-terminal), GUI (offscreen, if PyQt6 is present)
make lint         # ruff
make dist         # release tarball for the RPM spec
make srpm         # source RPM, built exactly the way COPR builds it
```

See [RELEASING.md](RELEASING.md) for how versions, GitHub releases and COPR builds fit together.

The TUI tests drive the real app in a pty and rebuild the screen with a small VT emulator (`tests/tui_harness.py`). Running `python tests/tui_harness.py` prints what the TUI draws.

## License

MIT © Lucas Dunham. This project was built with the help of AI tools; every feature was directed and tested by the author.
