#!/bin/sh
# Build and install the Rust desktop app + tray as sshm-gui / sshm-tray in ~/.local/bin.
# The Python launchers they replace are kept as sshm-gui.python / sshm-tray.python; --uninstall puts them back.
# The terminal UI and CLI (sshm) stay the Python ones; everything shares ~/.config/sshm.
set -eu
cd "$(dirname "$0")"
BIN="${HOME}/.local/bin"
ICONS="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"

stop_trays() {
  # the Python tray and any running Rust tray/window (exact command lines, never this script)
  pgrep -f '^python3 -m sshm\.gui\.app' >/dev/null 2>&1 && pkill -f '^python3 -m sshm\.gui\.app' || true
  pgrep -x sshm-gui >/dev/null 2>&1 && pkill -x sshm-gui || true
  sleep 1
}

if [ "${1:-}" = "--uninstall" ]; then
  stop_trays
  for f in sshm-gui sshm-tray; do [ -f "$BIN/$f.python" ] && mv -f "$BIN/$f.python" "$BIN/$f"; done
  echo "Restored the Python sshm-gui / sshm-tray."
  command -v sshm-tray >/dev/null && (setsid sshm-tray >/dev/null 2>&1 &) || true
  exit 0
fi

cargo build --release
mkdir -p "$BIN" "$ICONS"
for f in sshm-gui sshm-tray; do
  if [ -f "$BIN/$f" ] && [ ! -f "$BIN/$f.python" ] && head -c 2 "$BIN/$f" | grep -q '#!' && grep -q 'python3' "$BIN/$f"; then cp -p "$BIN/$f" "$BIN/$f.python"; fi
done
stop_trays
install -m 755 target/release/sshm-gui "$BIN/sshm-gui"
printf '#!/bin/sh\nexec "%s/sshm-gui" --tray "$@"\n' "$BIN" > "$BIN/sshm-tray" && chmod 755 "$BIN/sshm-tray"
install -m 644 ../src/sshm/data/sshm.svg "$ICONS/sshm.svg"
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" 2>/dev/null || true
command -v kbuildsycoca6 >/dev/null && kbuildsycoca6 >/dev/null 2>&1 || true
(setsid "$BIN/sshm-gui" --tray >/dev/null 2>&1 &)
echo "Installed: sshm-gui (window), sshm-tray (tray monitor). The tray is running."
