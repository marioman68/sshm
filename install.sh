#!/usr/bin/env bash

# ==============================================================================
# sshm Modular Builder & Installer
# Combines src/*.sh into a single standalone executable
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$SCRIPT_DIR/src"
OUT_BIN="$SCRIPT_DIR/sshm"
INSTALL_DIR="$HOME/.local/bin"

echo -e "\e[38;5;213m\e[1m◆ Building sshm from modular source files...\e[0m"

if [ ! -d "$SRC_DIR" ]; then
    echo -e "\e[38;5;196m[ FAIL ] Source directory '$SRC_DIR' not found!\e[0m"
    exit 1
fi

# Combine all module files in numerical order into the standalone sshm script
> "$OUT_BIN"
for module in "$SRC_DIR"/[0-9][0-9]_*.sh; do
    echo -e "  \e[38;5;51m[+]\e[0m Merging $(basename "$module")..."
    cat "$module" >> "$OUT_BIN"
    echo "" >> "$OUT_BIN"
done

chmod +x "$OUT_BIN"
echo -e "\e[38;5;82m[  OK  ] Standalone script built at: $OUT_BIN\e[0m"

# Copy to ~/.local/bin
mkdir -p "$INSTALL_DIR"
cp "$OUT_BIN" "$INSTALL_DIR/sshm"
chmod +x "$INSTALL_DIR/sshm"

echo -e "\e[38;5;82m\e[1m[  OK  ] Installed successfully to: $INSTALL_DIR/sshm\e[0m"
