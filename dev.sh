#!/usr/bin/env bash

# ==============================================================================
# sshm Development Test Runner
# Sources all src/*.sh modules directly in memory without building or installing
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$SCRIPT_DIR/src"

if [ ! -d "$SRC_DIR" ]; then
    echo -e "\e[38;5;196m[ FAIL ] Source directory '$SRC_DIR' not found!\e[0m"
    exit 1
fi

# Load each module in numerical order right into the current shell session
for module in "$SRC_DIR"/[0-9][0-9]_*.sh; do
    source "$module"
done
