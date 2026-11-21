<div align="center">

<img src="assets/io.github.marioman68.sshm.svg" width="96" alt="sshm icon">

# sshm — SSH Connection Hub

**One place for every server you SSH into.** A desktop app and tray monitor for Linux, written in Rust.

</div>

## What it does

- **Server list:** fuzzy search (Ctrl+K), tags, favourites, and sorting by name, status, latency or recent use.
- **Real status:** TCP latency plus the SSH banner (e.g. `OpenSSH_9.8`). A host that is up with sshd stopped shows as *SSH down*.
- **Live metrics:** CPU (with history), memory, disk, uptime, OS and top processes, from a tiny agent on each server.
  Its UDP packets are HMAC-SHA256 signed.
- **Tray monitor:**
  - The icon has a status dot: green when every monitored server is up, amber when some are, red when none are.
  - Each server gets a menu with its metrics, connect, files, processes, saved commands and Wake-on-LAN.
  - You get desktop notifications for alerts.
  - The icon is drawn to fit your desktop: in the panel's text colour on KDE (it follows light/dark),
    white on GNOME-style bars, and a colour tile on XFCE, MATE and Cinnamon. You can change this in Settings → Tray icon.
- **Connect:** plain SSH or a persistent tmux session, ProxyJump hosts and per-server keys, in your own terminal.
- **Files:** open `sftp://` in your file manager, bookmark the server in Dolphin or GTK file managers, or mount it with SSHFS.
- **Processes:** a live, sortable list of every process on a server over one multiplexed SSH connection, with end, kill and htop.
- **Docker and Podman:**
  - A saved server that is really a container's published port shows as *⬢ container on host*.
  - It offers restart, stop, logs and shell, shows Minecraft players and status, and links to published web UIs.
- **Alerts and history:**
  - Alerts fire when a server goes down, CPU or memory stays high, a disk fills up, a container stops or turns unhealthy,
    or a reboot is needed.
  - 24-hour and 7-day uptime, plus an activity log.
- **More:** run one command on many servers, port forwards (-L, -R, -D), a network scan, `~/.ssh/config` import and export,
  backup and restore, Wake-on-LAN, pushing an SSH key, and ten themes.

## Install

Needs a Rust toolchain (`sudo dnf install cargo` on Fedora).

```bash
git clone https://github.com/marioman68/sshm.git
cd sshm
./install.sh            # builds and installs sshm-gui, starts the tray, and enables it at login
./install.sh --uninstall
```

Open **SSH Connection Hub** from your app menu, or run `sshm-gui`.

**One program:** `sshm-gui` is the only program.
- Run on its own (or from the menu), it opens the window and makes sure the tray monitor is running.
- `sshm-gui --tray` runs just the monitor; this is what starts at login.
- The monitor keeps watching your servers in the background. The window can be closed and reopened any time.
- **File → Quit sshm** stops both.

Optional extras: `tmux` (persistent sessions), `sshfs` (real mounts).

## Telemetry agent

The agent (`agent/sshm_agent.py`) runs on your servers. It is plain Python 3 with no dependencies and runs as a systemd
user service. Install or update it from a server's **More → Telemetry agent** menu, or from the banner on its page.

## Files

| What | Where |
|---|---|
| Servers, settings | `~/.config/sshm/servers.json`, `settings.json` |
| Uptime history, alerts | `~/.local/state/sshm/history.db` |
| Live telemetry, tunnels | `$XDG_RUNTIME_DIR/sshm/` |

## Keyboard

<kbd>Enter</kbd> connect · <kbd>Ctrl</kbd>+<kbd>T</kbd> tmux · <kbd>Ctrl</kbd>+<kbd>P</kbd> processes · <kbd>Ctrl</kbd>+<kbd>K</kbd> search ·
<kbd>↑</kbd>/<kbd>↓</kbd> move · <kbd>Ctrl</kbd>+<kbd>N</kbd> add · <kbd>Ctrl</kbd>+<kbd>E</kbd> edit · <kbd>Del</kbd> delete · <kbd>F5</kbd> refresh ·
<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>R</kbd> run on many servers · <kbd>Ctrl</kbd>+<kbd>,</kbd> settings · <kbd>Ctrl</kbd>+<kbd>W</kbd> close window · <kbd>Ctrl</kbd>+<kbd>Q</kbd> quit

## Development

```bash
cargo test              # unit tests (includes a packet signed by the Python agent)
cargo run -- --no-tray  # window without starting the tray
```

## Legacy

The previous Python version (PyQt desktop app, curses terminal UI, CLI, packaging) is in [`legacy/`](legacy/). It reads
the same config files.
