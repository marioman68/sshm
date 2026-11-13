#!/usr/bin/env bash

# ==============================================================================
# MODULE 01: Header, Configuration, Colors & State
# ==============================================================================

VERSION="2.1.0"
CONFIG_FILE="$HOME/.ssh_servers"
MOUNT_DIR="$HOME/Network_Servers"

# ANSI Color Palette
C_RESET="\e[0m"
C_BOLD="\e[1m"
C_HEADER="\e[38;5;39m"
C_BORDER="\e[38;5;240m"
C_BORDER_ACT="\e[38;5;39m"
C_GREEN="\e[38;5;82m"
C_RED="\e[38;5;196m"
C_YELLOW="\e[38;5;226m"
C_CYAN="\e[38;5;51m"
C_BLUE="\e[38;5;33m"
C_PURPLE="\e[38;5;141m"
C_ORANGE="\e[38;5;208m"
C_MUTED="\e[38;5;245m"

# Background Highlights
BG_HOVER="\e[48;5;237m"
BG_SELECTED="\e[48;5;235m"
BG_MNT_HOVER="\e[48;5;25m"

# Global State Arrays
declare -a all_lines=()
declare -a srv_real_idx=()
declare -a srv_names=()
declare -a srv_users=()
declare -a srv_hosts=()
declare -a srv_ports=()
declare -a srv_tags=()
declare -a srv_macs=()
declare -a srv_keys=()
declare -a srv_online=()
declare -a srv_latencies=()
declare -a srv_mounted=()
declare -a unique_tags=("ALL")

server_count=0
selected_idx=0
FILTER_TAG="ALL"
RESIZE_TRIGGERED=0
IS_MOBILE=0
active_hover_side=""
active_hover_row=0
active_hover_mode=0

repeat_char() {
    local char="$1"
    local count="$2"
    [ "$count" -le 0 ] && return
    local str
    printf -v str "%*s" "$count" ""
    printf "%s" "${str// /$char}"
}

expand_path() {
    local p="$1"
    echo "${p/#\~/$HOME}"
}

enable_mouse() {
    printf "\e[?1003h\e[?1015h\e[?1006h\e[?25l"
}

disable_mouse() {
    printf "\e[?1003l\e[?1015l\e[?1006l\e[?25h"
}

cleanup_and_exit() {
    disable_mouse
    clear
    exit 0
}


# Theme Configuration & Persistence
THEME_FILE="$HOME/.ssh_hub_theme"
CURRENT_THEME_IDX=0

declare -a THEME_NAMES=(
    "Royal Purple (Classic)"
    "Cyber Neon (Electric Cyan)"
    "Matrix Green (Hacker)"
    "Solar Amber (Warm Gold)"
    "Crimson Red (High Alert)"
    "Oceanic Blue (Deep Sea)"
    "Rose Pink (Synthwave)"
    "Stealth Slate (Minimal)"
)
declare -a THEME_BORDERS=(
    "\e[38;5;141m"
    "\e[38;5;51m"
    "\e[38;5;82m"
    "\e[38;5;214m"
    "\e[38;5;196m"
    "\e[38;5;33m"
    "\e[38;5;205m"
    "\e[38;5;240m"
)
declare -a THEME_HEADERS=(
    "\e[38;5;177m"
    "\e[38;5;39m"
    "\e[38;5;120m"
    "\e[38;5;226m"
    "\e[38;5;203m"
    "\e[38;5;75m"
    "\e[38;5;213m"
    "\e[38;5;39m"
)

apply_theme() {
    local idx="${1:-0}"
    if ! [[ "$idx" =~ ^[0-7]$ ]]; then
        idx=0
    fi
    CURRENT_THEME_IDX="$idx"
    C_BORDER="${THEME_BORDERS[$idx]}"
    C_HEADER="${THEME_HEADERS[$idx]}"
}

load_saved_theme

# Auto-Refresh Configuration & Persistence (0 = OFF, default = 10s)
REFRESH_FILE="$HOME/.ssh_hub_refresh"
AUTO_REFRESH_SEC=10

load_saved_refresh() {
    if [ -f "$REFRESH_FILE" ]; then
        local val
        val=$(cat "$REFRESH_FILE" 2>/dev/null | tr -d '[:space:]')
        if [[ "$val" =~ ^[0-9]+$ ]]; then
            AUTO_REFRESH_SEC="$val"
        fi
    fi
}

save_refresh() {
    local val="$1"
    if [[ "$val" =~ ^[0-9]+$ ]]; then
        AUTO_REFRESH_SEC="$val"
        echo "$val" > "$REFRESH_FILE"
    fi
}

load_saved_refresh
() {
    if [ -f "$THEME_FILE" ]; then
        local saved
        saved=$(cat "$THEME_FILE" 2>/dev/null | tr -d '[:space:]')
        apply_theme "$saved"
    else
        apply_theme 0
    fi
}

save_theme() {
    local idx="$1"
    apply_theme "$idx"
    echo "$idx" > "$THEME_FILE"
}

load_saved_theme

# Auto-Refresh Configuration & Persistence (0 = OFF, default = 10s)
REFRESH_FILE="$HOME/.ssh_hub_refresh"
AUTO_REFRESH_SEC=10

load_saved_refresh() {
    if [ -f "$REFRESH_FILE" ]; then
        local val
        val=$(cat "$REFRESH_FILE" 2>/dev/null | tr -d '[:space:]')
        if [[ "$val" =~ ^[0-9]+$ ]]; then
            AUTO_REFRESH_SEC="$val"
        fi
    fi
}

save_refresh() {
    local val="$1"
    if [[ "$val" =~ ^[0-9]+$ ]]; then
        AUTO_REFRESH_SEC="$val"
        echo "$val" > "$REFRESH_FILE"
    fi
}

load_saved_refresh


trap cleanup_and_exit SIGINT SIGTERM
trap 'RESIZE_TRIGGERED=1' SIGWINCH
