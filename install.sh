#!/bin/sh
# Build and install sshm: one program, `sshm-gui`. It opens the window; `sshm-gui --tray` is the background monitor
# (started automatically when you open the window, and at login).
#   ./install.sh               build + install to ~/.local
#   ./install.sh --uninstall   remove it (your servers and settings in ~/.config/sshm are kept)
set -eu
cd "$(dirname "$0")"
BIN="$HOME/.local/bin"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
APP_ID=io.github.marioman68.sshm
AUTOSTART="$HOME/.config/autostart/sshm-tray.desktop"

stop_running() {
  pgrep -f '^python3 -m sshm\.gui\.app' >/dev/null 2>&1 && pkill -f '^python3 -m sshm\.gui\.app' || true   # the old Python tray
  pgrep -x sshm-gui >/dev/null 2>&1 && pkill -x sshm-gui || true
  sleep 1
}
refresh_caches() {
  command -v update-desktop-database >/dev/null && update-desktop-database "$DATA/applications" 2>/dev/null || true
  command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t "$DATA/icons/hicolor" 2>/dev/null || true
  command -v kbuildsycoca6 >/dev/null && kbuildsycoca6 >/dev/null 2>&1 || true
}

if [ "${1:-}" = "--uninstall" ]; then
  stop_running
  rm -f "$BIN/sshm-gui" "$BIN/sshm-tray" "$DATA/applications/$APP_ID.desktop" "$DATA/icons/hicolor/scalable/apps/sshm.svg" "$DATA/icons/hicolor/scalable/apps/$APP_ID.svg" "$AUTOSTART"
  refresh_caches
  echo "sshm removed. Your servers and settings in ~/.config/sshm are still there."
  exit 0
fi

cargo build --release
mkdir -p "$BIN" "$DATA/applications" "$DATA/icons/hicolor/scalable/apps" "$(dirname "$AUTOSTART")"
stop_running
install -m 755 target/release/sshm-gui "$BIN/sshm-gui"
# older installs had a separate sshm-tray launcher; it's the same program now
rm -f "$BIN/sshm-tray"
install -m 644 assets/$APP_ID.svg "$DATA/icons/hicolor/scalable/apps/$APP_ID.svg"
install -m 644 assets/$APP_ID.svg "$DATA/icons/hicolor/scalable/apps/sshm.svg"   # older name, for anything still asking for it
install -m 644 assets/$APP_ID.desktop "$DATA/applications/$APP_ID.desktop"
cat > "$AUTOSTART" <<AEOF
[Desktop Entry]
Type=Application
Name=sshm tray monitor
Comment=Watch your SSH servers from the system tray
Exec=$BIN/sshm-gui --tray
Icon=io.github.marioman68.sshm
Terminal=false
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=5
X-KDE-autostart-after=panel
AEOF
refresh_caches
(setsid "$BIN/sshm-gui" --tray >/dev/null 2>&1 &)
echo "Installed sshm-gui. The tray monitor is running and starts at login; open the window from your app menu (SSH Connection Hub)."
