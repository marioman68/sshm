#!/usr/bin/env bash

# ==============================================================================
# SSH Connection Hub (sshm)
# Lightweight, mouse-friendly TUI for managing remote SSH servers
# ==============================================================================

VERSION="2.0.3"
CONFIG_FILE="$HOME/.ssh_servers"
REMOTEVIEW_DIR="$HOME/.local/share/remoteview"
GTK_BOOKMARKS="$HOME/.config/gtk-3.0/bookmarks"
FILTER_TAG="ALL"

# Color Palette Definitions
C_RESET="\e[0m"
C_BOLD="\e[1m"
C_BORDER="\e[38;5;99m"      # Subtle purple/indigo window frame
C_HEADER="\e[38;5;213m"     # Bright neon magenta title
C_CYAN="\e[38;5;51m"
C_BLUE="\e[38;5;39m"
C_PURPLE="\e[38;5;141m"
C_GREEN="\e[38;5;82m"
C_YELLOW="\e[38;5;220m"
C_ORANGE="\e[38;5;208m"
C_RED="\e[38;5;196m"
C_MUTED="\e[38;5;244m"
BG_HOVER="\e[48;5;236m"     # Standard row hover highlight
BG_MNT_HOVER="\e[48;5;60m"  # Distinct purple-blue highlight for mount icon

RESIZE_TRIGGERED=0

enable_mouse() {
    printf "\e[?1003h\e[?1006h\e[?25l\e[?7l"
}

disable_mouse() {
    printf "\e[?1003l\e[?1006l\e[?25h\e[?7h"
    stty echo 2>/dev/null
    sleep 0.05
    local garbage
    while read -t 0.05 -rsn1 garbage; do : ; done
}

on_resize() {
    RESIZE_TRIGGERED=1
}

trap 'on_resize' WINCH
trap 'disable_mouse; clear; echo ""; exit' EXIT INT TERM

repeat_char() {
    local char="$1"
    local count="$2"
    local str=""
    for ((i=0; i<count; i++)); do
        str="${str}${char}"
    done
    echo -n "$str"
}

expand_path() {
    local p="$1"
    p="${p/#\~/$HOME}"
    echo "${p%/}"
}
