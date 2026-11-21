# Changelog

## 4.0.0 — 2026-11-21

- Rewritten in Rust: the desktop window and a native tray monitor in one program, `sshm-gui` (`--tray` for the monitor).
- New server-stack icon. The tray icon matches the desktop: panel colour on KDE (follows light/dark), white on GNOME-style
  bars, a colour tile elsewhere; green / amber / red status dot.
- Same config, telemetry, history and tunnels as before; existing agents keep reporting.
- The Python GUI, terminal UI and CLI are retired and kept under `legacy/`.
- COPR: offline RPM build from vendored crates; upgrades in place from the 3.x Python package.

## 3.3.0 — 2026-11-18

### Added
- **Alerts** with desktop notifications: server down (after a grace period), CPU / memory high for a sustained time, disk nearly full, container stopped or unhealthy, and reboot required. Alerts fire only on observed changes (never just because sshm started), resolve automatically, and apply to servers shown in the tray. Thresholds are in Settings. A flood of simultaneous alerts becomes one summary notification.
- **Uptime history**: 24-hour and 7-day availability per server, plus latency history, stored in `~/.local/state/sshm/history.db` (SQLite, kept for 30 days). Shown in the GUI, the TUI and `sshm history`.
- **Activity log**: every alert and resolution, in the GUI (status-bar button and ••• menu), the tray ("Alerts" submenu), the TUI (<kbd>!</kbd>, plus a header chip while alerts are active) and `sshm events`.
- **Run on many servers**: one command on a tag, a selection or all servers in parallel, with per-server output and exit codes. GUI window (<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>R</kbd>), TUI (<kbd>X</kbd>) and `sshm exec -t TAG -- command`.
- **Backup & restore** of all servers (tags, MACs, saved commands; never secrets): `sshm backup` / `sshm restore`, and the GUI ••• menu.
- **Agent 3.3.0** reports its version and whether a reboot is needed (Debian's `reboot-required` flag, or a newer installed kernel on Fedora/Arch). sshm shows a ⟳ reboot chip and offers **Update agent** when a deployed agent is older than the bundled one.

## 3.2.1 — 2026-11-18

- README and RELEASING point to the lucasdunham85/sshm COPR project; COPR build badge

## 3.2.0 — 2026-11-18

### Added
- **COPR SCM builds**: `.copr/Makefile` (build method *make_srpm*) builds the source tarball straight from the git checkout, so every push or tag can build on COPR without a GitHub release first.
- **RPM build in CI**: a `fedora:latest` job builds the SRPM and binary RPMs the same way COPR does (including `%check`), installs them and smoke-tests `sshm`.
- **Tag-driven releases**: pushing `vX.Y.Z` verifies the tag matches the version, runs the tests, publishes a GitHub release (tarball, zip, CHANGELOG notes) and optionally triggers COPR via the `COPR_WEBHOOK_URL` secret.
- `scripts/release_notes.py`, `make srpm`, `make release-notes`, and `RELEASING.md` describing the whole flow.

### Changed
- The RPM is split into **`sshm`** (terminal UI + CLI, no Qt) and **`sshm-gui`** (desktop app + tray). `sshm-gui` is a weak dependency, so desktop users still get it automatically, while servers can skip PyQt6.
- The spec lists every build dependency the test suite needs (`procps-ng`, `ncurses-base`), checks that all modules import, and skips GUI tests in the build root.

## 3.1.0 — 2026-11-18

### Added
- **Process viewer** for any server, available in the desktop app (<kbd>Ctrl</kbd>+<kbd>P</kbd>), the TUI (<kbd>P</kbd>), the tray, and the CLI (`sshm ps`, `sshm top`). It refreshes live, sorts, filters, ends or force-kills processes with a sudo fallback, and opens htop. It works on GNU procps and BusyBox systems, and refreshes reuse a multiplexed SSH connection.
- **Docker / Podman awareness**: saved servers that are really containers (a port published on a sibling host) are detected automatically and shown with the container's own CPU/memory, status, health, image, ports and compose project. Restart, stop/start, logs and shell (through the host via `docker exec`) are available in the GUI, TUI (<kbd>D</kbd>), tray and CLI (`sshm docker`). Docker hosts get a Containers view. Data comes from the agent (API socket + cgroups) when installed, otherwise from SSH discovery.
- **Minecraft status** (players, version, MOTD) for containers that publish the Minecraft port, plus clickable links for published web UIs.
- **Agent reports top processes** by CPU and memory, shown on the server page and in the tray.
- Version number shown in the window title and TUI header; `scripts/bump_version.py` / `make bump` keep the package, RPM spec and changelog in sync, and `make zip` names the archive after the version.

### Changed
- The desktop window opens larger (up to 1440×920, capped to 90% of the screen) and remembers its size and position.

### Fixed
- Process window froze a few seconds after opening (table rebuilt every refresh with auto-sized columns); rewritten as a model/view table.
- First process-list load stalled until timeout because the SSH ControlPersist master inherited the output pipes; the same issue could make SSHFS mounts report a false timeout.
- Container auto-detection missed hosts whose SSH port was higher than the container's published port.

## 3.0.0 — 2026-11-18

A ground-up rewrite. Every front-end now shares one tested core library.

### Added
- **CLI**: `ls`, `status`, `connect`, `sftp`, `add`, `rm`, `scan`, `import`, `export`, `tunnel`, `wake --wait`, `run`, `agent`, `paths`. Server names can be abbreviated, and the listing commands support `--json`.
- **Background tunnels**: local, remote and SOCKS (`-L/-R/-D`), tracked across processes and stoppable from the GUI, TUI and CLI.
- **SSHFS mounts**, alongside the existing file-manager bookmarks.
- **ProxyJump** (jump host), a per-server remote folder, notes, favourites, a per-server tmux default and last-connected tracking.
- **`~/.ssh/config` import/export**, including `Include` directives.
- **SSH banner detection** (server software and version) and a *degraded* state for hosts that are up while sshd is down.
- **Telemetry v2**: swap, disk, load average, OS and kernel; a CPU history sparkline; HMAC-SHA256 signatures with replay protection.
- **Tray notifications** when a monitored server goes down or comes back.
- **TUI**: fuzzy search, sort modes, tag picker, live theme preview, settings screen, a help overlay, saved-command management, a tunnel list, copy-ssh-command (Wayland, X11 or OSC 52), responsive stacked layout and a scrollbar.
- **GUI**: redesigned main window with painted server cards, metric cards, split Connect button, commands/tunnels tabs, keyboard shortcuts, duplicate server and a context menu.
- Two new themes: Nordic Frost and Daylight (light).
- Test suite (core, CLI, TUI in a pty, GUI offscreen), ruff config and GitHub Actions CI.

### Changed
- Config moved to `~/.config/sshm/servers.json` and `settings.json`. Files from 2.x are migrated automatically and left untouched.
- Runtime state moved from the shared `/dev/shm/sshm_telemetry.json` to the per-user `$XDG_RUNTIME_DIR/sshm/`.
- Single-instance IPC uses a per-user `QLocalServer` instead of the telemetry UDP port, which anyone on the LAN could reach.
- The TUI no longer blocks while probing servers.
- Terminal commands are built as argv lists and passed positionally, so server names and commands containing quotes or `$` work correctly.
- KDE `user-places.xbel` is edited with a real XML parser, namespaces are preserved, and a backup is made before the first change.
- The installer no longer uses pip, cleans up 2.x files, and gives distro-specific PyQt6 install hints.
- The RPM is built from a release tarball with the pyproject macros and no longer installs a system-wide autostart entry.

### Fixed
- The 2.x curses TUI agent sent packets to port 55888 with different field names, so the hub never received them.
- The TUI and GUI used different mount folders (`~/Network_Places` vs `~/Network_Servers`) and different theme files.
- The TUI's *push key* ignored the server's identity file; *connect* always forced tmux.
- Unused `launch_in_terminal` wrapper code left terminals open without resetting the mouse mode.

### Removed
- The Bash TUI (`src/0*_*.sh`, `dev.sh`), superseded by the Python TUI.
