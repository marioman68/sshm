#!/usr/bin/env bash
set -e

SHARE_DIR="$HOME/.local/share/sshm"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
AUTOSTART_DIR="$HOME/.config/autostart"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"

echo "[  *  ] Installing SSH Connection Hub (GUI + Tray + Python TUI)..."
mkdir -p "$SHARE_DIR" "$BIN_DIR" "$DESKTOP_DIR" "$AUTOSTART_DIR" "$ICON_DIR"

# 1. Install core Python scripts
if [ -f "sshm-tray.py" ]; then
    cp -f sshm-tray.py "$SHARE_DIR/sshm-tray.py"
    chmod 755 "$SHARE_DIR/sshm-tray.py"
fi

if [ -f "sshm.py" ]; then
    cp -f sshm.py "$SHARE_DIR/sshm.py"
    chmod 755 "$SHARE_DIR/sshm.py"
fi

# 2. Install SVG Icon
cat << 'IEOF' > "$SHARE_DIR/sshm-hub.svg"
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
IEOF
cp -f "$SHARE_DIR/sshm-hub.svg" "$ICON_DIR/sshm-hub.svg"

# 3. Create CLI wrappers in ~/.local/bin
cat << 'WEOF' > "$BIN_DIR/sshm"
#!/usr/bin/env bash
printf '\033[?1000l\033[?1002l\033[?1003l\033[?1006l\033[?1015l'
exec /usr/bin/python3 "$HOME/.local/share/sshm/sshm.py" "$@"
WEOF
chmod 755 "$BIN_DIR/sshm"

cat << 'GEOF' > "$BIN_DIR/sshm-gui"
#!/usr/bin/env bash
exec /usr/bin/python3 "$HOME/.local/share/sshm/sshm-tray.py" --gui "$@"
GEOF
chmod 755 "$BIN_DIR/sshm-gui"

ln -sf "$SHARE_DIR/sshm-tray.py" "$BIN_DIR/sshm-tray"

# 4. Create Application Menu Launcher (.desktop)
rm -f "$DESKTOP_DIR"/sshm*.desktop
cat << DEOF > "$DESKTOP_DIR/sshm-gui.desktop"
[Desktop Entry]
Version=1.0
Type=Application
Name=SSH Connection Hub
GenericName=SSH Server Manager & Telemetry Hub
Comment=Manage SSH servers, mount SFTP folders, scan LAN, and monitor live CPU/RAM telemetry
Exec=/usr/bin/python3 $SHARE_DIR/sshm-tray.py --gui
Icon=$SHARE_DIR/sshm-hub.svg
Terminal=false
Categories=System;Network;RemoteAccess;
Keywords=ssh;sftp;server;homelab;terminal;tray;telemetry;sshm;
StartupNotify=false
DEOF
chmod 644 "$DESKTOP_DIR/sshm-gui.desktop"

# 5. Create Autostart Entry (Runs Tray Monitor Automatically on Reboot/Login)
cat << AEOF > "$AUTOSTART_DIR/sshm-tray.desktop"
[Desktop Entry]
Name=SSH Hub Tray Monitor
Comment=System Tray Monitor for SSH Connection Hub
Exec=/usr/bin/python3 $SHARE_DIR/sshm-tray.py
Icon=$SHARE_DIR/sshm-hub.svg
Terminal=false
Type=Application
X-GNOME-Autostart-enabled=true
X-KDE-autostart-after=panel
StartupNotify=false
AEOF
chmod 644 "$AUTOSTART_DIR/sshm-tray.desktop"

# 6. Refresh Desktop Menu Cache & Restart Background Tray
update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
kbuildsycoca6 --noincremental 2>/dev/null || true

pkill -f "sshm-tray.py" 2>/dev/null || true
sleep 0.3
nohup /usr/bin/python3 "$SHARE_DIR/sshm-tray.py" >/dev/null 2>&1 &

echo "[  OK  ] Installation complete!"
echo "  • Terminal TUI : run 'sshm'"
echo "  • Desktop GUI  : run 'sshm-gui' or click 'SSH Connection Hub' in your app menu"
echo "  • System Tray  : running now & set to auto-start on reboot/login"
