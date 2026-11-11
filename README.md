# ❖ SSH Connection Hub (`sshm`)

A lightweight, mouse-friendly Terminal User Interface (TUI) for managing remote SSH servers. Built entirely in Bash, it provides a sleek dashboard to connect, manage, and seamlessly integrate your remote nodes directly into your desktop environment's file manager.

##  Features

* **Interactive TUI:** Clean, dual-pane interface with auto-refreshing active/offline status indicators.
* **Full Mouse Support:** Click to select servers, navigate menus, or interact with specific UI elements.
* **Live Ping Latencies:** Real-time round-trip time measurements displayed next to active status indicators.
* **Tag Filtering:** Categorize your nodes and press `[F]` to instantly filter your active view.
* **Wake-on-LAN (WoL):** Fire magic packets directly to offline nodes using saved MAC addresses.
* **Background Port Tunneling:** Securely bind remote ports or web UIs with custom local port forwarding.
* **Universal Desktop Integration:** Auto-detects KDE Dolphin network folders or standard GTK bookmarks (GNOME, XFCE, Cinnamon) to mount remote SFTP directories.
* **Quick Actions:**
  * Launch SSH terminal sessions with auto-attach support for remote `tmux` sessions.
  * Open a GUI file browser for the remote server.
  * Open an interactive CLI SFTP shell.
  * Push your public SSH key (`ssh-copy-id`) to new servers with custom key path support.
  * Add, Edit, and Delete server profiles directly from the UI.
* **Smart Installer:** Includes a version-aware `install.sh` that safely installs the script to your local path and prompts you for updates without breaking file permissions.

##  Prerequisites

* **Bash** (v4.0+)
* **SSH Client** (`ssh`, `sftp`, `ssh-copy-id`)
* **KDE Plasma / Dolphin:** Required specifically for the "Mount to Dolphin" GUI features (uses `~/.local/share/remoteview`). Other core SSH features will work on any Linux desktop environment.

##  Installation

To install or update `sshm`, run the following commands in your terminal:

```bash
# Clone the repository
git clone https://github.com/marioman68/sshm.git
cd sshm

# Run the smart installer
chmod +x install.sh
./install.sh
```

The installer will copy the tool to `~/.local/bin/sshm`. You can then safely delete the cloned folder if you wish.

##  Usage

Simply type `sshm` in your terminal from anywhere:

```bash
sshm
```

* **Keyboard:** Type the number of the server to quick-connect, or type a letter (`a`-`q`) to trigger an Action Center command.
* **Mouse:** Click on a server to select it, then click an action on the right. 
* **Quick Mount:** Click directly on the blue/open indicator dot next to a server's number to instantly mount/unmount it to Dolphin's Network Folders!

##  Configuration

`sshm` stores your server list securely in a simple plaintext file located at:
`~/.ssh_servers`

Format: `Friendly Name|Username|Host_IP|Port`
