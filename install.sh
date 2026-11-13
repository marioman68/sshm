#!/usr/bin/env bash

# ==============================================================================
# sshm & sshm-tray Interactive Checkbox Installer (v2.1.0)
# ==============================================================================

C_RESET="\e[0m"
C_BOLD="\e[1m"
C_HEADER="\e[38;5;39m"
C_BORDER="\e[38;5;240m"
C_CYAN="\e[38;5;51m"
C_GREEN="\e[38;5;82m"
C_YELLOW="\e[38;5;226m"
C_PURPLE="\e[38;5;141m"
C_RED="\e[38;5;196m"
C_MUTED="\e[38;5;245m"
BG_HOVER="\e[48;5;237m"

BIN_DIR="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/applications"
AUTOSTART_DIR="$HOME/.config/autostart"

enable_mouse() {
    printf "\e[?1003h\e[?1015h\e[?1006h\e[?25l"
}

disable_mouse() {
    printf "\e[?1003l\e[?1015l\e[?1006l\e[?25h"
}

cleanup_and_exit() {
    disable_mouse
    echo ""
    exit 0
}
trap cleanup_and_exit SIGINT SIGTERM

# Default selection state (On Termux, only select sshm TUI by default)
if [ -n "${TERMUX_VERSION:-}" ]; then
    declare -a comp_selected=(1 0 0)
else
    declare -a comp_selected=(1 1 1)
fi

declare -a comp_names=(
    "sshm (Terminal UI)"
    "sshm-tray (Tray App)"
    "Autostart Tray App"
)

declare -a comp_descs=(
    "Interactive SSH & SFTP Hub (~/.local/bin/sshm)"
    "System Tray Monitor (~/.local/bin/sshm-tray)"
    "Launch sshm-tray automatically on desktop login"
)

count=3
ROW_LIST_START=7
btn_row=$(( ROW_LIST_START + count + 1 ))
hover_idx=-1
hover_btn=0

render_row() {
    local idx="$1"
    local is_hov="$2"
    local r=$(( ROW_LIST_START + idx ))
    local bg=""
    [ "$is_hov" -eq 1 ] && bg="${BG_HOVER}"

    local chk="${C_MUTED}[ ]${C_RESET}${bg}"
    [ "${comp_selected[$idx]}" -eq 1 ] && chk="${C_GREEN}${C_BOLD}[✓]${C_RESET}${bg}"

    local name="${comp_names[$idx]}"
    local desc="${comp_descs[$idx]}"

    printf "\e[%d;1H${bg}  %b  ${C_CYAN}[%d]${C_RESET}${bg}  ${C_BOLD}%-22s${C_RESET}${bg} %-48s ${C_RESET}" \
        "$r" "$chk" "$((idx + 1))" "$name" "$desc"
}

render_buttons() {
    local b_hov="$1"
    local bg_apply=""
    local bg_cancel=""
    [ "$b_hov" -eq 1 ] && bg_apply="${BG_HOVER}"
    [ "$b_hov" -eq 2 ] && bg_cancel="${BG_HOVER}"

    printf "\e[%d;1H%*s" "$btn_row" 88 ""
    printf "\e[%d;3H${bg_apply} ${C_GREEN}${C_BOLD}[ ➔ CLICK HERE OR PRESS ENTER TO INSTALL SELECTED ]${C_RESET}${bg_apply} ${C_RESET}    ${bg_cancel} ${C_RED}${C_BOLD}[ ✕ CANCEL (q) ]${C_RESET}${bg_cancel} ${C_RESET}" "$btn_row"
}

draw_installer_screen() {
    clear
    printf "\e[1;1H${C_PURPLE}${C_BOLD}◆ SSH CONNECTION HUB — COMPONENT INSTALLER (v2.1.0)${C_RESET}"
    printf "\e[2;1H${C_MUTED}  Click any row (or press 1-3) to toggle [✓].${C_RESET}"
    printf "\e[3;1H${C_CYAN}  [Enter]${C_RESET} Install Selected   ${C_YELLOW}[a]${C_RESET} Toggle All   ${C_RED}[q]${C_RESET} Cancel & Exit"
    printf "\e[5;1H  ${C_BOLD}%-4s %-4s %-22s %s${C_RESET}" "SEL" "ID" "COMPONENT" "DESCRIPTION"
    printf "\e[6;1H  ${C_BORDER}──────────────────────────────────────────────────────────────────────────────${C_RESET}"

    for ((i=0; i<count; i++)); do
        render_row "$i" 0
    done

    render_buttons 0
}

draw_installer_screen
enable_mouse

apply_install=0

while true; do
    if IFS= read -rsn1 -t 1 char; then
        if [[ "$char" == $'\e' ]]; then
            read -rsn2 -t 0.05 seq
            if [[ "$seq" == "[<" ]]; then
                mouse_event=""
                while IFS= read -rsn1 mchar; do
                    mouse_event+="$mchar"
                    [[ "$mchar" == "M" || "$mchar" == "m" ]] && break
                done
                if [[ "$mouse_event" =~ ^([0-9]+)\;([0-9]+)\;([0-9]+)([Mm])$ ]]; then
                    btn="${BASH_REMATCH[1]}"
                    cx="${BASH_REMATCH[2]}"
                    cy="${BASH_REMATCH[3]}"
                    act="${BASH_REMATCH[4]}"

                    r_idx=$(( cy - ROW_LIST_START ))
                    if [ "$r_idx" -ge 0 ] && [ "$r_idx" -lt "$count" ]; then
                        if [ "$hover_btn" -ne 0 ]; then
                            render_buttons 0
                            hover_btn=0
                        fi
                        if [ "$r_idx" -ne "$hover_idx" ]; then
                            [ "$hover_idx" -ge 0 ] && render_row "$hover_idx" 0
                            render_row "$r_idx" 1
                            hover_idx="$r_idx"
                        fi
                        if [ "$btn" -eq 0 ] && [ "$act" == "M" ]; then
                            if [ "${comp_selected[$r_idx]}" -eq 1 ]; then
                                comp_selected[$r_idx]=0
                            else
                                comp_selected[$r_idx]=1
                            fi
                            render_row "$r_idx" 1
                        fi
                    else
                        if [ "$hover_idx" -ge 0 ]; then
                            render_row "$hover_idx" 0
                            hover_idx=-1
                        fi

                        new_btn_hov=0
                        if [ "$cy" -eq "$btn_row" ]; then
                            if [ "$cx" -ge 3 ] && [ "$cx" -le 56 ]; then
                                new_btn_hov=1
                            elif [ "$cx" -ge 60 ] && [ "$cx" -le 79 ]; then
                                new_btn_hov=2
                            fi
                        fi

                        if [ "$new_btn_hov" -ne "$hover_btn" ]; then
                            render_buttons "$new_btn_hov"
                            hover_btn="$new_btn_hov"
                        fi

                        if [ "$btn" -eq 0 ] && [ "$act" == "M" ]; then
                            if [ "$new_btn_hov" -eq 1 ]; then
                                apply_install=1
                                break
                            elif [ "$new_btn_hov" -eq 2 ]; then
                                apply_install=0
                                break
                            fi
                        fi
                    fi
                fi
            else
                apply_install=0
                break
            fi
        elif [[ "$char" == "" ]]; then
            apply_install=1
            break
        elif [[ "$char" =~ ^[Qq]$ ]]; then
            apply_install=0
            break
        elif [[ "$char" =~ ^[Aa]$ ]]; then
            any_unselected=0
            for ((i=0; i<count; i++)); do
                [ "${comp_selected[$i]}" -eq 0 ] && any_unselected=1
            done
            for ((i=0; i<count; i++)); do
                comp_selected[$i]=$any_unselected
                render_row "$i" 0
            done
        elif [[ "$char" =~ ^[1-3]$ ]]; then
            t_idx=$(( char - 1 ))
            if [ "${comp_selected[$t_idx]}" -eq 1 ]; then
                comp_selected[$t_idx]=0
            else
                comp_selected[$t_idx]=1
            fi
            render_row "$t_idx" 0
        fi
    fi
done

disable_mouse
printf "\e[%d;1H\n" "$(( btn_row + 1 ))"

if [ "$apply_install" -eq 0 ]; then
    echo -e "  ${C_MUTED}[ INFO ] Installation cancelled.${C_RESET}"
    exit 0
fi

if [ "${comp_selected[0]}" -eq 0 ] && [ "${comp_selected[1]}" -eq 0 ] && [ "${comp_selected[2]}" -eq 0 ]; then
    echo -e "  ${C_YELLOW}[ WARN ] No components were selected to install.${C_RESET}"
    exit 0
fi

mkdir -p "$BIN_DIR"

# 1. Install sshm (Terminal UI)
if [ "${comp_selected[0]}" -eq 1 ]; then
    echo -e "${C_CYAN}[ INFO ] Building standalone 'sshm' executable from src/ modules...${C_RESET}"
    if [ -f "./build.sh" ]; then
        chmod +x ./build.sh
        ./build.sh
    elif [ -d "./src" ]; then
        cat src/01_header.sh src/02_ui.sh src/03_backend.sh src/04_actions.sh src/05_main.sh > ./sshm
        chmod +x ./sshm
    fi

    cp -f ./sshm "$BIN_DIR/sshm"
    chmod +x "$BIN_DIR/sshm"
    echo -e "${C_GREEN}[  OK  ] Installed 'sshm' to ${BIN_DIR}/sshm${C_RESET}"

    if [ -z "${TERMUX_VERSION:-}" ]; then
        mkdir -p "$APP_DIR"
        cat << DESKTOP > "$APP_DIR/sshm.desktop"
[Desktop Entry]
Name=SSH Connection Hub (sshm)
Comment=Interactive Terminal SSH & SFTP Manager
Exec=$BIN_DIR/sshm
Icon=utilities-terminal
Terminal=true
Type=Application
Categories=System;Network;TerminalEmulator;
StartupNotify=false
DESKTOP
        echo -e "${C_GREEN}[  OK  ] Created desktop launcher at ${APP_DIR}/sshm.desktop${C_RESET}"
    fi
fi

# 2. Install sshm-tray (System Tray Monitor)
if [ "${comp_selected[1]}" -eq 1 ]; then
    if [ ! -f "./sshm-tray.py" ]; then
        echo -e "${C_RED}[ FAIL ] './sshm-tray.py' not found in current directory.${C_RESET}"
    else
        echo -e "${C_CYAN}[ INFO ] Installing 'sshm-tray' System Tray Monitor...${C_RESET}"
        cp -f ./sshm-tray.py "$BIN_DIR/sshm-tray"
        cp -f ./sshm-tray.py "$BIN_DIR/sshm-tray.py"
        chmod +x "$BIN_DIR/sshm-tray" "$BIN_DIR/sshm-tray.py"
        echo -e "${C_GREEN}[  OK  ] Installed 'sshm-tray' to ${BIN_DIR}/sshm-tray${C_RESET}"

        mkdir -p "$APP_DIR"
        cat << DESKTOP > "$APP_DIR/sshm-tray.desktop"
[Desktop Entry]
Name=SSH Hub Tray Monitor
Comment=System Tray Monitor for SSH Connection Hub
Exec=$BIN_DIR/sshm-tray
Icon=network-server
Terminal=false
Type=Application
Categories=System;Network;
StartupNotify=false
DESKTOP
        echo -e "${C_GREEN}[  OK  ] Created app menu launcher at ${APP_DIR}/sshm-tray.desktop${C_RESET}"

        if [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; then
            echo -e "${C_CYAN}[ INFO ] Launching / restarting sshm-tray in the background...${C_RESET}"
            pkill -f "sshm-tray" 2>/dev/null || true
            sleep 0.3
            nohup "$BIN_DIR/sshm-tray" >/dev/null 2>&1 &
            echo -e "${C_GREEN}[  OK  ] 'sshm-tray' is running in your system tray!${C_RESET}"
        fi
    fi
fi

# 3. Configure Login Autostart for sshm-tray
if [ "${comp_selected[2]}" -eq 1 ]; then
    mkdir -p "$AUTOSTART_DIR"
    cat << AUTOSTART > "$AUTOSTART_DIR/sshm-tray.desktop"
[Desktop Entry]
Name=SSH Hub Tray Monitor
Comment=System Tray Monitor for SSH Connection Hub
Exec=$BIN_DIR/sshm-tray
Icon=network-server
Terminal=false
Type=Application
X-GNOME-Autostart-enabled=true
X-KDE-autostart-after=panel
StartupNotify=false
AUTOSTART
    echo -e "${C_GREEN}[  OK  ] Enabled login autostart at ${AUTOSTART_DIR}/sshm-tray.desktop${C_RESET}"
else
    if [ -f "$AUTOSTART_DIR/sshm-tray.desktop" ]; then
        rm -f "$AUTOSTART_DIR/sshm-tray.desktop"
        echo -e "${C_MUTED}[ INFO ] Removed login autostart (${AUTOSTART_DIR}/sshm-tray.desktop).${C_RESET}"
    fi
fi

echo -e "\n${C_GREEN}${C_BOLD}✨ Installation complete!${C_RESET}"
