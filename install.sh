#!/usr/bin/env bash
# ==============================================================================
# sshm & sshm-tray — Universal Linux Desktop Installer & Uninstaller
# Supports: KDE Plasma, GNOME, XFCE, Cinnamon, MATE, Cosmic, LXQt, Hyprland/Sway
# ==============================================================================
set -e

APP_VERSION="2.2.0"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Standard XDG / FreeDesktop User Directories
SHARE_DIR="$HOME/.local/share/sshm"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
AUTOSTART_DIR="$HOME/.config/autostart"

GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${CYAN}[ INFO ]${NC} $1"; }
ok()    { echo -e "${GREEN}[  OK  ]${NC} $1"; }
warn()  { echo -e "${YELLOW}[ WARN ]${NC} $1"; }
err()   { echo -e "${RED}[ERROR ]${NC} $1"; exit 1; }

# ------------------------------------------------------------------------------
# Uninstall Routine (--uninstall)
# ------------------------------------------------------------------------------
if [[ "${1:-}" == "--uninstall" || "${1:-}" == "uninstall" ]]; then
    info "Stopping running sshm-tray processes..."
    pkill -f "python3.*sshm-tray" 2>/dev/null || true

    info "Removing installed files and shortcuts..."
    rm -rf "$SHARE_DIR"
    rm -f "$BIN_DIR/sshm" "$BIN_DIR/sshm-tray" "$BIN_DIR/sshm-tray.py" "$BIN_DIR/sshm-gui"
    rm -f "$APPS_DIR/sshm.desktop" "$APPS_DIR/sshm-gui.desktop" "$APPS_DIR/sshm-tui.desktop" "$APPS_DIR/sshm-tray.desktop"
    rm -f "$ICON_DIR/sshm-hub.svg"
    rm -f "$AUTOSTART_DIR/sshm-tray.desktop"

    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS_DIR" 2>/dev/null || true
    command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
    command -v kbuildsycoca6 >/dev/null 2>&1 && kbuildsycoca6 >/dev/null 2>&1 || true

    ok "sshm has been cleanly uninstalled (your ~/.ssh_servers config was preserved)."
    exit 0
fi

echo -e "${CYAN}==================================================================${NC}"
echo -e "${CYAN}   Installing SSH Connection Hub (v${APP_VERSION}) — Universal Setup   ${NC}"
echo -e "${CYAN}==================================================================${NC}"

# ------------------------------------------------------------------------------
# 1. Dependency Check
# ------------------------------------------------------------------------------
info "Checking Python3 and PyQt6 availability..."
if ! python3 -c "import PyQt6.QtWidgets" >/dev/null 2>&1; then
    warn "PyQt6 is not installed. Attempting automatic installation..."
    if command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y python3-pyqt6
    elif command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update && sudo apt-get install -y python3-pyqt6
    elif command -v pacman >/dev/null 2>&1; then
        sudo pacman -S --noconfirm python-pyqt6
    elif command -v zypper >/dev/null 2>&1; then
        sudo zypper install -y python3-qt6
    elif command -v pip3 >/dev/null 2>&1; then
        pip3 install --user PyQt6
    else
        err "Could not auto-install PyQt6. Please install 'python3-pyqt6' using your package manager."
    fi
fi
ok "PyQt6 runtime verified."

# ------------------------------------------------------------------------------
# 2. Build / Verify Source Files
# ------------------------------------------------------------------------------
if [[ ! -f "$SCRIPT_DIR/sshm-tray.py" ]]; then
    err "Cannot find sshm-tray.py in $SCRIPT_DIR"
fi

if [[ -d "$SCRIPT_DIR/src" ]]; then
    info "Assembling latest 'sshm' TUI binary from src/ modules..."
    cat "$SCRIPT_DIR"/src/*.sh > "$SCRIPT_DIR/sshm"
    chmod +x "$SCRIPT_DIR/sshm"
fi

# ------------------------------------------------------------------------------
# 3. Install Application Payload into ~/.local/share/sshm & ~/.local/bin
# ------------------------------------------------------------------------------
info "Installing application files into $SHARE_DIR and $BIN_DIR..."
mkdir -p "$SHARE_DIR" "$BIN_DIR" "$APPS_DIR" "$ICON_DIR" "$AUTOSTART_DIR"

cp -f "$SCRIPT_DIR/sshm-tray.py" "$SHARE_DIR/sshm-tray.py"
chmod 755 "$SHARE_DIR/sshm-tray.py"

if [[ -f "$SCRIPT_DIR/sshm" ]]; then
    cp -f "$SCRIPT_DIR/sshm" "$SHARE_DIR/sshm"
    chmod 755 "$SHARE_DIR/sshm"
    ln -sf "$SHARE_DIR/sshm" "$BIN_DIR/sshm"
fi

ln -sf "$SHARE_DIR/sshm-tray.py" "$BIN_DIR/sshm-tray"
ln -sf "$SHARE_DIR/sshm-tray.py" "$BIN_DIR/sshm-tray.py"

rm -f "$BIN_DIR/sshm-gui"
cat << EOF > "$BIN_DIR/sshm-gui"
#!/usr/bin/env bash
exec /usr/bin/env python3 "$SHARE_DIR/sshm-tray.py" --gui "\$@"
EOF
chmod 755 "$BIN_DIR/sshm-gui"

ok "Installed CLI commands: 'sshm-gui', 'sshm-tray', and 'sshm'."

# ------------------------------------------------------------------------------
# 4. Install Custom Scalable SVG App Icon
# ------------------------------------------------------------------------------
info "Installing scalable vector icon ($ICON_DIR/sshm-hub.svg)..."
cat << 'EOF' > "$ICON_DIR/sshm-hub.svg"
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" width="128" height="128">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#1e1e2e"/>
      <stop offset="100%" stop-color="#11111b"/>
    </linearGradient>
    <linearGradient id="accent" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#b48ead"/>
      <stop offset="100%" stop-color="#89b4fa"/>
    </linearGradient>
  </defs>
  <rect x="8" y="8" width="112" height="112" rx="24" fill="url(#bg)" stroke="url(#accent)" stroke-width="5"/>
  <rect x="24" y="28" width="80" height="26" rx="6" fill="#313244" stroke="#45475a" stroke-width="2"/>
  <circle cx="38" cy="41" r="5" fill="#52ff52"/>
  <rect x="52" y="38" width="40" height="6" rx="3" fill="#cdd6f4"/>
  <rect x="24" y="64" width="80" height="36" rx="6" fill="#181825" stroke="#45475a" stroke-width="2"/>
  <path d="M 34 76 L 44 82 L 34 88" fill="none" stroke="#52ff52" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/>
  <line x1="50" y1="88" x2="66" y2="88" stroke="#89b4fa" stroke-width="3.5" stroke-linecap="round"/>
  <circle cx="100" cy="100" r="14" fill="#1e1e2e" stroke="#11111b" stroke-width="3"/>
  <circle cx="100" cy="100" r="9" fill="#52ff52"/>
</svg>
EOF
cp -f "$ICON_DIR/sshm-hub.svg" "$SHARE_DIR/sshm-hub.svg"

# ------------------------------------------------------------------------------
# 5. Clean Up Old Duplicate Shortcuts & Create ONE Single GUI Launcher Entry
# ------------------------------------------------------------------------------
info "Cleaning up old duplicate launcher entries..."
rm -f "$APPS_DIR/sshm.desktop" "$APPS_DIR/sshm-tui.desktop" "$APPS_DIR/sshm-tray.desktop" "$APPS_DIR/sshm-gui.desktop"

info "Creating single 'SSH Connection Hub' GUI Launcher shortcut..."
cat << EOF > "$APPS_DIR/sshm-gui.desktop"
[Desktop Entry]
Version=1.0
Type=Application
Name=SSH Connection Hub
GenericName=SSH Server Manager & Telemetry Hub
Comment=Manage SSH servers, mount SFTP folders, scan LAN, and monitor live CPU/RAM telemetry
Exec=/usr/bin/env python3 $SHARE_DIR/sshm-tray.py --gui
Icon=$SHARE_DIR/sshm-hub.svg
Terminal=false
Categories=System;Network;RemoteAccess;
Keywords=ssh;sftp;server;homelab;terminal;tray;telemetry;
StartupNotify=false
EOF
chmod 644 "$APPS_DIR/sshm-gui.desktop"

# Refresh Desktop Databases
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS_DIR" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
command -v kbuildsycoca6 >/dev/null 2>&1 && kbuildsycoca6 >/dev/null 2>&1 || true
command -v kbuildsycoca5 >/dev/null 2>&1 && kbuildsycoca5 >/dev/null 2>&1 || true

ok "Registered single 'SSH Connection Hub' GUI entry in your Application Launcher."

# ------------------------------------------------------------------------------
# 6. Update Autostart Entry (Hidden from App Menu via NoDisplay=true) & Restart
# ------------------------------------------------------------------------------
cat << EOF > "$AUTOSTART_DIR/sshm-tray.desktop"
[Desktop Entry]
Name=SSH Hub Tray Monitor
Comment=System Tray Monitor for SSH Connection Hub
Exec=/usr/bin/env python3 $SHARE_DIR/sshm-tray.py
Icon=$SHARE_DIR/sshm-hub.svg
Terminal=false
Type=Application
NoDisplay=true
X-GNOME-Autostart-enabled=true
X-KDE-autostart-after=panel
StartupNotify=false
EOF

info "Restarting background tray service..."
pkill -f "python3.*sshm-tray" 2>/dev/null || true
sleep 0.3
nohup /usr/bin/env python3 "$SHARE_DIR/sshm-tray.py" >/dev/null 2>&1 &

echo ""
echo -e "${GREEN}✨ Installation complete!${NC}"
echo -e "  • ${CYAN}App Launcher:${NC} Only ${YELLOW}'SSH Connection Hub'${NC} (GUI + Tray) is shown in your launcher."
echo -e "  • ${CYAN}Terminal CLI:${NC} Type ${YELLOW}sshm${NC} in any terminal whenever you want the TUI."
