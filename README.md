# sshm — Advanced SSH Connection Hub & System Tray Monitor (v2.1.0)

A high-performance, modular terminal user interface (`sshm`) and native Linux system tray companion (`sshm-tray.py`) designed for robust remote server management, SFTP network folder orchestration, Wake-on-LAN routing, and automated local subnet discovery.

Engineered to operate seamlessly across standard **Linux Desktop Environments** (KDE Plasma, GNOME, XFCE) as well as mobile terminals (**Android / Termux**), featuring automatic geometry scaling and adaptive layout switching.

---

## Architecture & Modular Design

The core application breaks away from monolithic script designs by utilizing a decoupled, modular Bash architecture. The build system compiles individual source modules into a single, highly optimized standalone executable binary.

```text
sshm/
├── src/
│   ├── 01_header.sh    # Global state arrays, ANSI color definitions, 8 UI themes & signal traps
│   ├── 02_ui.sh        # Desktop and Termux responsive geometry calculation & pane renderers
│   ├── 03_backend.sh   # Parallel ping diagnostics, ARP MAC prober, Dolphin/GTK mount sync
│   ├── 04_actions.sh   # SSH/SFTP orchestration, port forwarding tunnels, LAN scanner, theme engine
│   └── 05_main.sh      # Main event loop, SGR 1006 mouse coordinate tracking & input dispatcher
├── sshm                # Compiled standalone executable (compiled via build.sh)
├── sshm-tray.py        # PyQt6 system tray monitor with native desktop environment integration
├── dev.sh              # Live test runner assembling src/* modules into a temporary session
├── build.sh            # Production compiler bundling src/* modules into the standalone ./sshm binary
└── install.sh          # Deployment script installing binaries to ~/.local/bin and generating desktop entries
```

---

## Core Features & Technical Breakdown

### 1. Hybrid Telemetry & Live Monitoring
* **Instant Status Updates:** Features an integrated background UDP listener operating on port `55889`. Target nodes running the lightweight Python heartbeat daemon push real-time status packets directly into shared memory (`/dev/shm/sshm_telemetry.json`), allowing sub-millisecond status reads with zero SSD wear.
* **Port Isolation:** Supports complex multi-instance environments where multiple server profiles share a single IP address across distinct SSH ports (such as bare-metal host operating systems versus isolated Docker containers), evaluating each unique target endpoint independently.
* **Dual-Tier Probing:** If a target does not have the telemetry agent installed, the engine gracefully falls back to a parallelized asynchronous TCP socket handshake and ICMP ping check.

### 2. Subnet Discovery & Auto-MAC Probing
* **Parallel LAN Scanner (`[n]`):** Executes an asynchronous network sweep across the local `/24` subnet in approximately 1.5 seconds, probing standard TCP port `22` to discover unlisted SSH nodes.
* **ARP Table Resolution:** Automatically queries the local kernel routing table and ARP cache (`ip neigh`) to resolve hardware MAC addresses instantly, eliminating manual administrative data entry.

### 3. Desktop Integration & Mounting
* **Cross-Environment Mounting:** Integrates directly with File Manager standards. Toggling a server mount generates a desktop link in `~/Network_Servers/` while simultaneously syncing native sidebar bookmarks across KDE Dolphin (`user-places.xbel`) and GTK-based file managers (`~/.config/gtk-3.0/bookmarks`).
* **Native Symbolic Tray Icons (`sshm-tray.py`):** Queries `$XDG_CURRENT_DESKTOP` to render crisp, monochrome wireframe symbolic icons via `QIcon.fromTheme`, ensuring visual consistency across modern panel themes.

---

## Complete Controls & Keyboard/Mouse Reference

| Input Method | Action / Execution |
| :--- | :--- |
| **Left-Click Server Row** | Designate selected server as the active target inspector node |
| **Double-Click / Enter / c** | Establish direct SSH connection to active target (with optional automatic `tmux` session attachment) |
| **Click Mount Diamond** | Toggle remote SFTP network folder mount status inside the desktop file manager sidebar |
| **Numeric Keys `1`–`9`** | Quickly switch active target index by position |
| **Arrow Keys `↑` / `↓`** | Navigate through the remote nodes roster sequentially |
| **`b`** | Open target home directory immediately in the default GUI file manager via `sftp://` |
| **`s`** | Initialize an interactive SFTP terminal shell session |
| **`t`** | Configure and launch a background local port forwarding tunnel (`localhost:LPORT -> remote:RPORT`) |
| **`w`** | Transmit a Wake-on-LAN magic UDP packet to the target's configured MAC address |
| **`k`** | Provision and push your local SSH public key to the target node via `ssh-copy-id` |
| **`e` / `d`** | Edit parameters or permanently delete the active target server profile |
| **`a`** | Launch wizard to add a new server profile with automated IP host and MAC probing |
| **`n`** | Initialize the parallel subnet network scanner to discover unconfigured hosts |
| **`p`** | Open the live border and UI color theme switcher interface |
| **`f`** | Cycle through active server tag filters (e.g., `ALL`, production groups, custom categories) |
| **`r` / `q`** | Force an immediate global status refresh / Safely terminate application session |

---

## Installation & Deployment

### Step 1: Clone and Build
Ensure execution permissions are set, then execute the installation script to compile the modular source files and deploy binaries to your local path:

```bash
cd ~/Projects/sshm
chmod +x dev.sh build.sh install.sh sshm-tray.py
./install.sh
```
*(Verify that `~/.local/bin` is included in your user environment `$PATH`).*

### Step 2: Development & Live Testing
To test modular source modifications made inside the `src/` directory without performing a full reinstall, use the live test runner wrapper:

```bash
./dev.sh
```

### Step 3: Execution
* **Terminal Interface:** Run the core TUI application from any terminal emulator (Konsole, Ptyxis, Alacritty, Termux):
  ```bash
  sshm
  ```
* **System Tray Monitor:** Launch the background tray companion as a daemon process:
  ```bash
  sshm-tray &
  ```

---

## Configuration File Specifications

* **Server Profiles (`~/.ssh_servers`):** Structured as a flat, pipe-delimited configuration database:
  ```text
  Name|Username|HostAddress|Port|Tag|MACAddress|KeyPath
  ```
* **Theme Configuration (`~/.ssh_hub_theme`):** Stores the active integer identifier corresponding to your selected border and accent palette (`0` through `7`).
* **Mount Directories (`~/Network_Servers/`):** Contains localized desktop shortcut definitions facilitating system file manager integration.

---

## Acknowledgments & Development Attribution

This software project was developed with the assistance of artificial intelligence systems, which contributed to architectural planning, modular script refactoring, asynchronous queue handling, and telemetry socket synchronization algorithms.
