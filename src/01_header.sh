#!/usr/bin/env bash

# ==============================================================================
# MODULE 01: Header, Global State, Themes, Refresh & Telemetry Setup
# ==============================================================================

VERSION="2.1.0"
CONFIG_FILE="$HOME/.ssh_servers"
MOUNT_DIR="$HOME/Network_Servers"

# Ensure config file exists
touch "$CONFIG_FILE"
mkdir -p "$MOUNT_DIR"

# Base ANSI Colors
C_RESET="\e[0m"
C_BOLD="\e[1m"
C_BORDER="\e[38;5;141m"
C_HEADER="\e[38;5;177m"
C_CYAN="\e[38;5;51m"
C_GREEN="\e[38;5;82m"
C_YELLOW="\e[38;5;226m"
C_RED="\e[38;5;196m"
C_PURPLE="\e[38;5;141m"
C_BLUE="\e[38;5;39m"
C_MUTED="\e[38;5;245m"
BG_HOVER="\e[48;5;237m"
BG_SELECT="\e[48;5;236m"

# Server State Arrays
declare -a all_lines=()
declare -a srv_real_idx=()
declare -a srv_names=()
declare -a srv_users=()
declare -a srv_hosts=()
declare -a srv_ports=()
declare -a srv_tags=()
declare -a srv_macs=()
declare -a srv_keys=()
declare -a srv_latencies=()
declare -a srv_online=()
declare -a srv_mounted=()

# Hybrid Telemetry Cache & Agent Configuration
TELEM_FILE="/dev/shm/sshm_telemetry.json"
TELEM_PORT=55889
declare -a srv_cpu=()
declare -a srv_ram=()
declare -a srv_uptime=()
declare -a srv_has_agent=()

# UI & Navigation State
server_count=0
selected_idx=0
FILTER_TAG="ALL"
active_hover_side=""
active_hover_row=0
active_hover_mode=0
RESIZE_TRIGGERED=0
IS_MOBILE=0


# String & Path Helper Functions
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

# Mouse & Terminal Helpers
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

trap cleanup_and_exit SIGINT SIGTERM
trap 'RESIZE_TRIGGERED=1' SIGWINCH

# ------------------------------------------------------------------------------
# 1. Theme Configuration & Persistence (~/.ssh_hub_theme)
# ------------------------------------------------------------------------------
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

load_saved_theme() {
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

# ------------------------------------------------------------------------------
# 2. Auto-Refresh Configuration & Persistence (~/.ssh_hub_refresh)
# ------------------------------------------------------------------------------
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

# ------------------------------------------------------------------------------
# 3. Fallback Background UDP Telemetry Listener
# ------------------------------------------------------------------------------
ensure_telemetry_listener() {
    if ! pgrep -f "sshm-tray" >/dev/null 2>&1 && ! pgrep -f "sshm-telem-daemon" >/dev/null 2>&1; then
        nohup python3 -c '
import socket, json, time, os
from pathlib import Path
p = Path("/dev/shm/sshm_telemetry.json")
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind(("0.0.0.0", 55889))
except Exception:
    raise SystemExit()
cache = {}
while True:
    try:
        data, addr = s.recvfrom(1024)
        msg = json.loads(data.decode("utf-8", errors="ignore"))
        ip = addr[0]
        hname = msg.get("host", "")
        ssh_port = str(msg.get("port", "22"))
        entry = {
            "ts": time.time(),
            "cpu": msg.get("cpu", "--"),
            "ram": msg.get("ram", "--"),
            "up": msg.get("up", "--"),
            "ssh": msg.get("ssh", 1),
            "port": ssh_port
        }
        cache[f"{ip}:{ssh_port}"] = entry
        if hname:
            cache[f"{hname}:{ssh_port}"] = entry
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache))
        os.replace(tmp, p)
    except Exception:
        pass
' --sshm-telem-daemon >/dev/null 2>&1 &
    fi
}

# Initialize all startup settings
load_saved_theme
load_saved_refresh
ensure_telemetry_listener
