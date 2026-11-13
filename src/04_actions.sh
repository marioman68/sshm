# ==============================================================================
# MODULE 04: User Actions, Auto-MAC Probing & Interactive Network SSH Scanner
# ==============================================================================

connect_ssh() {
    local idx="$1"
    local name="${srv_names[$idx]}"
    local user="${srv_users[$idx]}"
    local host="${srv_hosts[$idx]}"
    local port="${srv_ports[$idx]}"
    local key="${srv_keys[$idx]}"

    disable_mouse
    clear
    echo -e "${C_HEADER}${C_BOLD}◆ CONNECTING TO: ${name} (${user}@${host}:${port})${C_RESET}"
    echo -e "${C_MUTED}(Tip: Type [q] and press Enter to cancel and return to hub)${C_RESET}\n"

    local ssh_opts=("-p" "$port")
    if [ -n "$key" ]; then
        local exp_key
        exp_key=$(expand_path "$key")
        [ -f "$exp_key" ] && ssh_opts+=("-i" "$exp_key")
    fi

    echo -ne "${C_YELLOW}[INPUT] Auto-attach to remote tmux session if available? (y/N, or [q] cancel): ${C_RESET}"
    read -r use_tmux
    if [[ "$use_tmux" =~ ^[Qq]$ ]]; then
        return
    fi
    echo ""

    if [[ "$use_tmux" =~ ^[Yy]$ ]]; then
        ssh -t "${ssh_opts[@]}" "${user}@${host}" "tmux attach || tmux new || \$SHELL"
    else
        ssh "${ssh_opts[@]}" "${user}@${host}"
    fi
}

browse_gui() {
    local idx="$1"
    local name="${srv_names[$idx]}"
    local user="${srv_users[$idx]}"
    local host="${srv_hosts[$idx]}"
    local port="${srv_ports[$idx]}"
    local target_dir="/home/${user}"
    [ "$user" = "root" ] && target_dir="/root"
    local url="sftp://${user}@${host}:${port}${target_dir}"

    if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$url" &>/dev/null &
        temp_message "[  OK  ] Opening '$name' (${target_dir}) in File Manager..."
    elif command -v dolphin >/dev/null 2>&1; then
        dolphin "$url" &>/dev/null &
        temp_message "[  OK  ] Opening '$name' (${target_dir}) in Dolphin..."
    else
        temp_message "[ FAIL ] No compatible GUI file manager opener found."
    fi
}

connect_sftp() {
    local idx="$1"
    local name="${srv_names[$idx]}"
    local user="${srv_users[$idx]}"
    local host="${srv_hosts[$idx]}"
    local port="${srv_ports[$idx]}"
    local key="${srv_keys[$idx]}"

    disable_mouse
    clear
    echo -e "${C_HEADER}${C_BOLD}◆ SFTP SESSION: ${name}${C_RESET}"
    echo -e "${C_MUTED}(Tip: Type 'exit' or press Ctrl+D inside SFTP to return to hub)${C_RESET}\n"

    local sftp_opts=("-P" "$port")
    if [ -n "$key" ]; then
        local exp_key
        exp_key=$(expand_path "$key")
        [ -f "$exp_key" ] && sftp_opts+=("-i" "$exp_key")
    fi

    sftp "${sftp_opts[@]}" "${user}@${host}"
}

port_tunnel_flow() {
    local idx="$1"
    local name="${srv_names[$idx]}"
    local user="${srv_users[$idx]}"
    local host="${srv_hosts[$idx]}"
    local port="${srv_ports[$idx]}"
    local key="${srv_keys[$idx]}"

    disable_mouse
    clear
    echo -e "${C_HEADER}${C_BOLD}◆ BACKGROUND PORT TUNNELING: ${name}${C_RESET}"
    echo -e "${C_MUTED}  Forward a local port on this PC to a service running on ${host}.${C_RESET}"
    echo -e "${C_CYAN}  ➔ To cancel and go back: Leave blank and press [Enter], or type [q].${C_RESET}\n"

    echo -ne "${C_YELLOW}[INPUT] Local port to bind (e.g. 8080) [Enter/q to cancel]: ${C_RESET}"
    read -erp "" lport
    if [[ -z "$lport" || "$lport" =~ ^[Qq]$ ]]; then
        echo -e "\n${C_MUTED}[ INFO ] Port tunneling cancelled. Returning to hub...${C_RESET}"
        sleep 0.6
        return
    fi

    echo -ne "${C_YELLOW}[INPUT] Remote target port (e.g. 80)   [Enter/q to cancel]: ${C_RESET}"
    read -erp "" rport
    if [[ -z "$rport" || "$rport" =~ ^[Qq]$ ]]; then
        echo -e "\n${C_MUTED}[ INFO ] Port tunneling cancelled. Returning to hub...${C_RESET}"
        sleep 0.6
        return
    fi

    if ! [[ "$lport" =~ ^[0-9]+$ && "$rport" =~ ^[0-9]+$ ]]; then
        echo -e "\n${C_RED}[ FAIL ] Ports must be valid numbers.${C_RESET}"
        sleep 1.2
        return
    fi

    local ssh_opts=("-p" "$port" "-f" "-N" "-L" "${lport}:localhost:${rport}")
    if [ -n "$key" ]; then
        local exp_key
        exp_key=$(expand_path "$key")
        [ -f "$exp_key" ] && ssh_opts+=("-i" "$exp_key")
    fi

    echo -e "\n${C_CYAN}[ INFO ] Establishing background tunnel (localhost:${lport} -> ${host}:${rport})...${C_RESET}"
    if ssh "${ssh_opts[@]}" "${user}@${host}"; then
        echo -e "${C_GREEN}${C_BOLD}[  OK  ] Tunnel active in background!${C_RESET}"
    else
        echo -e "${C_RED}${C_BOLD}[ FAIL ] Could not establish port tunnel.${C_RESET}"
    fi
    echo -ne "\n${C_MUTED}Press Enter to return to hub...${C_RESET}"
    read -r
}

wake_on_lan_flow() {
    local idx="$1"
    local name="${srv_names[$idx]}"
    local mac="${srv_macs[$idx]}"

    if [ -z "$mac" ]; then
        temp_message "[ FAIL ] No MAC address saved for '$name'. Use [e] Edit or [n] Scan first."
        return
    fi

    if command -v wakeonlan >/dev/null 2>&1; then
        wakeonlan "$mac" >/dev/null 2>&1
        temp_message "[  OK  ] Magic packet sent to $name ($mac)!"
    elif command -v wol >/dev/null 2>&1; then
        wol "$mac" >/dev/null 2>&1
        temp_message "[  OK  ] Magic packet sent to $name ($mac)!"
    elif command -v python3 >/dev/null 2>&1; then
        python3 -c "
import socket
mac = '$mac'.replace(':', '').replace('-', '')
data = bytes.fromhex('FF' * 6 + mac * 16)
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
s.sendto(data, ('255.255.255.255', 9))
" 2>/dev/null
        temp_message "[  OK  ] Magic packet sent via UDP broadcast to $mac!"
    else
        temp_message "[ FAIL ] No WoL tool or python3 available."
    fi
}

push_ssh_key_flow() {
    local idx="$1"
    local name="${srv_names[$idx]}"
    local user="${srv_users[$idx]}"
    local host="${srv_hosts[$idx]}"
    local port="${srv_ports[$idx]}"
    local key="${srv_keys[$idx]}"

    disable_mouse
    clear
    echo -e "${C_HEADER}${C_BOLD}◆ PUSH SSH KEY TO: ${name}${C_RESET}"
    echo -e "${C_CYAN}  ➔ To cancel and go back: Type [q] and press [Enter].${C_RESET}"
    echo -e "${C_MUTED}  (Tip: Press [Tab] to auto-complete file paths)${C_RESET}\n"
    echo -ne "${C_YELLOW}[INPUT] SSH Public Key path [Default: ${key:-~/.ssh/id_ed25519.pub}, or [q] cancel]: ${C_RESET}"
    read -erp "" custom_key

    if [[ "$custom_key" =~ ^[Qq]$ ]]; then
        echo -e "\n${C_MUTED}[ INFO ] Cancelled. Returning to hub...${C_RESET}"
        sleep 0.5
        return
    fi

    local target_key="${custom_key:-$key}"
    local copy_opts=("-p" "$port")
    if [ -n "$target_key" ]; then
        local exp_key
        exp_key=$(expand_path "$target_key")
        copy_opts+=("-i" "$exp_key")
    fi

    echo ""
    ssh-copy-id "${copy_opts[@]}" "${user}@${host}"
    echo -ne "\n${C_MUTED}Press Enter to return to hub...${C_RESET}"
    read -r
}

add_server_flow() {
    disable_mouse
    clear
    echo -e "${C_HEADER}${C_BOLD}◆ ADD NEW SERVER PROFILE${C_RESET}"
    echo -e "${C_CYAN}  ➔ To cancel: Leave Host / IP or Name blank and press [Enter], or type [q].${C_RESET}\n"

    echo -ne "${C_YELLOW}Host / IP Address (Enter first to auto-detect Name & MAC): ${C_RESET}"
    read -erp "" host
    [[ -z "$host" || "$host" =~ ^[Qq]$ ]] && return

    echo -ne "${C_CYAN}[ INFO ] Probing ${host} for Hostname & Hardware MAC...${C_RESET}\r"
    local auto_mac=""
    local auto_name=""
    auto_mac=$(probe_host_mac "$host")
    auto_name=$(probe_host_name "$host")
    printf "%*s\r" 68 ""

    if [ -n "$auto_name" ] || [ -n "$auto_mac" ]; then
        echo -e "${C_GREEN}[  OK  ] Discovered — Hostname: ${auto_name:-N/A}  |  MAC: ${auto_mac:-N/A}${C_RESET}\n"
    fi

    local default_name="${auto_name%%.*}"
    read -erp "Friendly Name: " -i "$default_name" name
    [[ -z "$name" || "$name" =~ ^[Qq]$ ]] && return

    read -erp "Username: " -i "$USER" user
    [[ -z "$user" || "$user" =~ ^[Qq]$ ]] && return

    read -erp "SSH Port: " -i "22" port
    [ -z "$port" ] && port=22

    read -erp "Tag / Category (optional, e.g. Homelab): " tag

    while true; do
        echo -e "${C_MUTED}(Tip: Type 'scan' and press Enter to re-probe ${host} for its MAC)${C_RESET}"
        read -erp "MAC Address for WoL: " -i "$auto_mac" mac
        if [[ "${mac,,}" == "scan" ]]; then
            echo -ne "${C_CYAN}[ INFO ] Scanning ${host} for MAC address...${C_RESET}\r"
            auto_mac=$(probe_host_mac "$host")
            printf "%*s\r" 55 ""
            if [ -n "$auto_mac" ]; then
                echo -e "${C_GREEN}[  OK  ] Found MAC: ${auto_mac}${C_RESET}"
            else
                echo -e "${C_RED}[ FAIL ] Could not detect MAC (host offline or on another subnet).${C_RESET}"
            fi
        else
            break
        fi
    done

    echo -e "${C_MUTED}(Tip: Press [Tab] to auto-complete key path)${C_RESET}"
    read -erp "SSH Private Key Path (optional): " key

    echo "${name}|${user}|${host}|${port}|${tag}|${mac}|${key}" >> "$CONFIG_FILE"
    echo -e "\n${C_GREEN}[  OK  ] Server '$name' saved!${C_RESET}"
    sleep 1
}

edit_server_flow() {
    local idx="$1"
    local real_idx="${srv_real_idx[$idx]}"

    IFS='|' read -r c_name c_user c_host c_port c_tag c_mac c_key <<< "${all_lines[$real_idx]}"
    [ -z "$c_port" ] && c_port=22

    disable_mouse
    clear
    echo -e "${C_HEADER}${C_BOLD}◆ EDIT SERVER PROFILE: ${c_name}${C_RESET}"
    echo -e "${C_MUTED}(Edit values below and press Enter, or type [q] as Friendly Name to cancel)${C_RESET}\n"

    read -erp "Friendly Name: " -i "$c_name" name
    if [[ -z "$name" || "$name" =~ ^[Qq]$ ]]; then
        echo -e "\n${C_MUTED}[ INFO ] Edit cancelled.${C_RESET}"
        sleep 0.5
        return
    fi
    read -erp "Username: " -i "$c_user" user

    echo -e "${C_MUTED}(Tip: If you change or confirm the IP, sshm can auto-probe its MAC below)${C_RESET}"
    read -erp "Host / IP: " -i "$c_host" host
    read -erp "SSH Port: " -i "$c_port" port
    read -erp "Tag / Category: " -i "$c_tag" tag

    # Auto-probe MAC if currently empty or if the IP was changed!
    local sug_mac="$c_mac"
    if [ -z "$sug_mac" ] || [ "$host" != "$c_host" ]; then
        echo -ne "${C_CYAN}[ INFO ] Probing ${host} for hardware MAC address...${C_RESET}\r"
        local found_mac
        found_mac=$(probe_host_mac "$host")
        printf "%*s\r" 60 ""
        if [ -n "$found_mac" ]; then
            sug_mac="$found_mac"
            echo -e "${C_GREEN}[  OK  ] Auto-detected MAC from ${host}: ${sug_mac}${C_RESET}"
        fi
    fi

    while true; do
        echo -e "${C_MUTED}(Tip: Type 'scan' and press Enter to probe ${host} on the network for its MAC)${C_RESET}"
        read -erp "MAC Address: " -i "$sug_mac" mac
        if [[ "${mac,,}" == "scan" ]]; then
            echo -ne "${C_CYAN}[ INFO ] Probing ${host} ARP & network info...${C_RESET}\r"
            local scanned_mac
            scanned_mac=$(probe_host_mac "$host")
            local scanned_name
            scanned_name=$(probe_host_name "$host")
            printf "%*s\r" 60 ""
            if [ -n "$scanned_mac" ]; then
                sug_mac="$scanned_mac"
                echo -e "${C_GREEN}[  OK  ] Found MAC: ${scanned_mac} ${scanned_name:+(Hostname: $scanned_name)}${C_RESET}"
            else
                echo -e "${C_RED}[ FAIL ] Could not reach ${host} on local L2 subnet to read MAC.${C_RESET}"
            fi
        else
            break
        fi
    done

    echo -e "${C_MUTED}(Tip: Press [Tab] to auto-complete key path)${C_RESET}"
    read -erp "SSH Key Path: " -i "$c_key" key

    all_lines[$real_idx]="${name}|${user}|${host}|${port:-22}|${tag}|${mac}|${key}"
    printf "%s\n" "${all_lines[@]}" > "$CONFIG_FILE"

    echo -e "\n${C_GREEN}[  OK  ] Profile updated!${C_RESET}"
    sleep 1
}

# ==============================================================================
# Interactive Local Network SSH & MAC Scanner ([n])
# ==============================================================================
scan_network_flow() {
    local default_prefix
    default_prefix=$(get_default_subnet_prefix)
    local prefix=""

    # Step 1: Interactive Right-Pane Scanner Menu (Supports Mouse Hover & Click!)
    for ((r=ROW_R_INFO_1; r<=ROW_TWIN_END; r++)); do
        render_right_scan_pane "$r" 0 "$default_prefix"
    done

    prompt_in_dialog "Network Scan: Click or press [Enter] for ${default_prefix}.0/24, [c] Custom Subnet, or [q] Cancel: "
    enable_mouse

    local scan_choice=""
    local hover_row=0
    local row_def="$ROW_R_ACT_START"
    local row_cus="$(( ROW_R_ACT_START + 1 ))"
    local row_can="$(( ROW_R_ACT_START + 2 ))"

    while true; do
        if IFS= read -rsn1 -t 1 char; then
            if [[ "$char" == $'\e' ]]; then
                read -rsn2 -t 0.05 seq
                if [[ "$seq" == "[<" ]]; then
                    local mouse_event=""
                    local mchar=""
                    while IFS= read -rsn1 mchar; do
                        mouse_event+="$mchar"
                        [[ "$mchar" == "M" || "$mchar" == "m" ]] && break
                    done
                    if [[ "$mouse_event" =~ ^([0-9]+)\;([0-9]+)\;([0-9]+)([Mm])$ ]]; then
                        local btn="${BASH_REMATCH[1]}"
                        local cx="${BASH_REMATCH[2]}"
                        local cy="${BASH_REMATCH[3]}"
                        local action="${BASH_REMATCH[4]}"

                        if [ "$cx" -ge "$RIGHT_START" ] && [ "$cx" -le "$RIGHT_END" ] && \
                           { [ "$cy" -eq "$row_def" ] || [ "$cy" -eq "$row_cus" ] || [ "$cy" -eq "$row_can" ]; }; then
                            if [ "$hover_row" -ne "$cy" ]; then
                                [ "$hover_row" -ne 0 ] && render_right_scan_pane "$hover_row" 0 "$default_prefix"
                                render_right_scan_pane "$cy" 1 "$default_prefix"
                                hover_row="$cy"
                            fi
                            if [ "$btn" -eq 0 ] && [ "$action" == "M" ]; then
                                if [ "$cy" -eq "$row_def" ]; then
                                    scan_choice="default"
                                elif [ "$cy" -eq "$row_cus" ]; then
                                    scan_choice="custom"
                                else
                                    scan_choice="cancel"
                                fi
                                break
                            fi
                        else
                            if [ "$hover_row" -ne 0 ]; then
                                render_right_scan_pane "$hover_row" 0 "$default_prefix"
                                hover_row=0
                            fi
                        fi
                    fi
                else
                    scan_choice="cancel"
                    break
                fi
            elif [[ "$char" == "" ]]; then
                scan_choice="default"
                break
            elif [[ "$char" =~ ^[Cc]$ ]]; then
                scan_choice="custom"
                break
            elif [[ "$char" =~ ^[Qq]$ ]]; then
                scan_choice="cancel"
                break
            fi
        fi
    done

    disable_mouse

    if [ "$scan_choice" == "cancel" ]; then
        return
    elif [ "$scan_choice" == "default" ]; then
        prefix="$default_prefix"
        clear
        echo -e "${C_HEADER}${C_BOLD}◆ LOCAL NETWORK SSH & HARDWARE MAC SCANNER${C_RESET}"
    elif [ "$scan_choice" == "custom" ]; then
        clear
        echo -e "${C_HEADER}${C_BOLD}◆ LOCAL NETWORK SSH & HARDWARE MAC SCANNER${C_RESET}"
        echo -e "${C_CYAN}  ➔ Press [Enter] for ${default_prefix}.0/24, type another subnet, or [q] to cancel.${C_RESET}\n"
        read -erp "Target Network [Default: ${default_prefix}.0/24]: " net_input
        if [[ "$net_input" =~ ^[Qq]$ ]]; then
            return
        fi
        [ -z "$net_input" ] && net_input="${default_prefix}.0/24"
        if [[ "$net_input" =~ ^([0-9]+\.[0-9]+\.[0-9]+) ]]; then
            prefix="${BASH_REMATCH[1]}"
        else
            prefix="${net_input%.*}"
        fi
    fi

    echo -e "\n${C_CYAN}[ INFO ] Sweeping ${prefix}.1 - ${prefix}.254 for open SSH (Port 22)...${C_RESET}"

    local scan_dir
    scan_dir=$(mktemp -d)

    for i in {1..254}; do
        (
            local ip="${prefix}.${i}"
            if timeout 0.65 bash -c "cat < /dev/null > /dev/tcp/${ip}/22" 2>/dev/null; then
                ping -c 1 -W 1 "$ip" >/dev/null 2>&1
                local mac
                mac=$(ip neigh show "$ip" 2>/dev/null | grep -oE '([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}' | head -n1)
                local hname
                hname=$(probe_host_name "$ip")
                [ -z "$hname" ] && hname="ssh-node-${i}"
                printf "%s|%s|%s\n" "$ip" "${hname}" "${mac,,}" > "$scan_dir/$i"
            fi
        ) &
    done
    wait

    local -a found_ips=()
    local -a found_names=()
    local -a found_macs=()
    local -a found_status=()
    local -a found_real_idx=()
    local -a found_selected=()

    local count=0
    for i in {1..254}; do
        if [ -f "$scan_dir/$i" ]; then
            IFS='|' read -r f_ip f_name f_mac < "$scan_dir/$i"
            found_ips[$count]="$f_ip"
            found_names[$count]="$f_name"
            found_macs[$count]="$f_mac"

            local match_real=-1
            local existing_mac=""
            local existing_name=""
            for r_idx in "${!all_lines[@]}"; do
                IFS='|' read -r s_name s_user s_host s_port s_tag s_mac s_key <<< "${all_lines[$r_idx]}"
                if [ "$s_host" == "$f_ip" ] || [ "${s_name,,}" == "${f_name%%.*}" ]; then
                    match_real="$r_idx"
                    existing_mac="$s_mac"
                    existing_name="$s_name"
                    break
                fi
            done

            found_real_idx[$count]="$match_real"
            if [ "$match_real" -ge 0 ]; then
                if [ -n "$f_mac" ] && [ "${existing_mac,,}" != "${f_mac,,}" ]; then
                    found_status[$count]="SYNC"
                    found_selected[$count]=1
                else
                    found_status[$count]="SAVED"
                    found_selected[$count]=0
                fi
            else
                found_status[$count]="NEW"
                found_selected[$count]=1
            fi
            ((count++))
        fi
    done
    rm -rf "$scan_dir"

    if [ "$count" -eq 0 ]; then
        echo -e "${C_RED}[ FAIL ] No active SSH servers found on ${prefix}.0/24.${C_RESET}"
        echo -ne "\n${C_MUTED}Press Enter to return to hub...${C_RESET}"
        read -r
        return
    fi

    # Step 2: Interactive Mouse + Keyboard Multi-Select Loop with Button Hover Highlights!
    local hover_idx=-1
    local hover_btn=0   # 0 = none, 1 = Apply button, 2 = Cancel button
    local ROW_LIST_START=7
    local btn_row=$(( ROW_LIST_START + count + 1 ))

    render_scan_buttons() {
        local b_hov="$1"
        local bg_apply=""
        local bg_cancel=""
        [ "$b_hov" -eq 1 ] && bg_apply="${BG_HOVER}"
        [ "$b_hov" -eq 2 ] && bg_cancel="${BG_HOVER}"

        printf "\e[%d;1H%*s" "$btn_row" 92 ""
        printf "\e[%d;3H${bg_apply} ${C_GREEN}${C_BOLD}[ ➔ CLICK HERE OR PRESS ENTER TO ADD / UPDATE SELECTED NODES ]${C_RESET}${bg_apply} ${C_RESET}    ${bg_cancel} ${C_RED}${C_BOLD}[ ✕ CANCEL (q) ]${C_RESET}${bg_cancel} ${C_RESET}" "$btn_row"
    }

    render_scan_row() {
        local idx="$1"
        local is_hov="$2"
        local r=$(( ROW_LIST_START + idx ))
        local bg=""
        [ "$is_hov" -eq 1 ] && bg="${BG_HOVER}"

        local chk="${C_MUTED}[ ]${C_RESET}${bg}"
        [ "${found_selected[$idx]}" -eq 1 ] && chk="${C_GREEN}${C_BOLD}[✓]${C_RESET}${bg}"

        local ip="${found_ips[$idx]}"
        local hname="${found_names[$idx]}"
        [ ${#hname} -gt 24 ] && hname="${hname:0:23}…"
        local mac="${found_macs[$idx]:--- (Unreachable L2)}"

        local st="${found_status[$idx]}"
        local badge=""
        if [ "$st" == "NEW" ]; then
            badge="${C_GREEN}[NEW — Add to Hub]${C_RESET}${bg}"
        elif [ "$st" == "SYNC" ]; then
            badge="${C_YELLOW}[EXISTING — Update MAC]${C_RESET}${bg}"
        else
            badge="${C_MUTED}[ALREADY SAVED — Add Copy?]${C_RESET}${bg}"
        fi

        printf "\e[%d;1H${bg}  %b  ${C_CYAN}[%2d]${C_RESET}${bg} %-16s ${C_BOLD}%-26s${C_RESET}${bg} %-19s %b   ${C_RESET}" \
            "$r" "$chk" "$((idx + 1))" "$ip" "$hname" "$mac" "$badge"
    }

    draw_scan_screen() {
        clear
        printf "\e[1;1H${C_HEADER}${C_BOLD}◆ DISCOVERED SSH NODES ON ${prefix}.0/24 (${count} Found)${C_RESET}"
        printf "\e[2;1H${C_MUTED}  Click any row (or press 1-${count}) to toggle [✓]. Existing nodes with new MACs can be synced!${C_RESET}"
        printf "\e[3;1H${C_CYAN}  [Enter]${C_RESET} Apply Selected   ${C_YELLOW}[a]${C_RESET} Toggle All   ${C_RED}[q]${C_RESET} Cancel & Return"
        printf "\e[5;1H  ${C_BOLD}%-4s %-4s %-16s %-26s %-19s %s${C_RESET}" "SEL" "ID" "IP ADDRESS" "HOSTNAME" "MAC ADDRESS" "ACTION STATUS"
        printf "\e[6;1H  ${C_BORDER}%s${C_RESET}" "$(repeat_char "─" 88)"

        for ((idx=0; idx<count; idx++)); do
            render_scan_row "$idx" 0
        done

        render_scan_buttons 0
    }

    draw_scan_screen
    enable_mouse

    local apply_changes=0

    while true; do
        local char=""
        if IFS= read -rsn1 -t 1 char; then
            if [[ "$char" == $'\e' ]]; then
                local seq=""
                read -rsn2 -t 0.05 seq
                if [[ "$seq" == "[<" ]]; then
                    local mouse_event=""
                    local mchar=""
                    while IFS= read -rsn1 mchar; do
                        mouse_event+="$mchar"
                        [[ "$mchar" == "M" || "$mchar" == "m" ]] && break
                    done
                    if [[ "$mouse_event" =~ ^([0-9]+)\;([0-9]+)\;([0-9]+)([Mm])$ ]]; then
                        local btn="${BASH_REMATCH[1]}"
                        local cx="${BASH_REMATCH[2]}"
                        local cy="${BASH_REMATCH[3]}"
                        local act="${BASH_REMATCH[4]}"

                        local r_idx=$(( cy - ROW_LIST_START ))
                        if [ "$r_idx" -ge 0 ] && [ "$r_idx" -lt "$count" ]; then
                            if [ "$hover_btn" -ne 0 ]; then
                                render_scan_buttons 0
                                hover_btn=0
                            fi
                            if [ "$r_idx" -ne "$hover_idx" ]; then
                                [ "$hover_idx" -ge 0 ] && render_scan_row "$hover_idx" 0
                                render_scan_row "$r_idx" 1
                                hover_idx="$r_idx"
                            fi
                            if [ "$btn" -eq 0 ] && [ "$act" == "M" ]; then
                                if [ "${found_selected[$r_idx]}" -eq 1 ]; then
                                    found_selected[$r_idx]=0
                                else
                                    found_selected[$r_idx]=1
                                fi
                                render_scan_row "$r_idx" 1
                            fi
                        else
                            if [ "$hover_idx" -ge 0 ]; then
                                render_scan_row "$hover_idx" 0
                                hover_idx=-1
                            fi

                            local new_btn_hov=0
                            if [ "$cy" -eq "$btn_row" ]; then
                                if [ "$cx" -ge 3 ] && [ "$cx" -le 66 ]; then
                                    new_btn_hov=1
                                elif [ "$cx" -ge 69 ] && [ "$cx" -le 88 ]; then
                                    new_btn_hov=2
                                fi
                            fi

                            if [ "$new_btn_hov" -ne "$hover_btn" ]; then
                                render_scan_buttons "$new_btn_hov"
                                hover_btn="$new_btn_hov"
                            fi

                            if [ "$btn" -eq 0 ] && [ "$act" == "M" ]; then
                                if [ "$new_btn_hov" -eq 1 ]; then
                                    apply_changes=1
                                    break
                                elif [ "$new_btn_hov" -eq 2 ]; then
                                    apply_changes=0
                                    break
                                fi
                            fi
                        fi
                    fi
                else
                    apply_changes=0
                    break
                fi
            elif [[ "$char" == "" ]]; then
                apply_changes=1
                break
            elif [[ "$char" =~ ^[Qq]$ ]]; then
                apply_changes=0
                break
            elif [[ "$char" =~ ^[Aa]$ ]]; then
                local any_unselected=0
                for ((idx=0; idx<count; idx++)); do
                    [ "${found_selected[$idx]}" -eq 0 ] && any_unselected=1
                done
                for ((idx=0; idx<count; idx++)); do
                    found_selected[$idx]=$any_unselected
                    render_scan_row "$idx" 0
                done
            elif [[ "$char" =~ ^[1-9]$ ]]; then
                local t_idx=$(( char - 1 ))
                if [ "$t_idx" -lt "$count" ]; then
                    if [ "${found_selected[$t_idx]}" -eq 1 ]; then
                        found_selected[$t_idx]=0
                    else
                        found_selected[$t_idx]=1
                    fi
                    render_scan_row "$t_idx" 0
                fi
            fi
        fi
    done

    disable_mouse
    [ "$apply_changes" -eq 0 ] && return

    local new_selected=0
    local sync_selected=0
    for ((idx=0; idx<count; idx++)); do
        if [ "${found_selected[$idx]}" -eq 1 ]; then
            if [ "${found_status[$idx]}" == "SYNC" ]; then
                ((sync_selected++))
            else
                ((new_selected++))
            fi
        fi
    done

    if [ "$new_selected" -eq 0 ] && [ "$sync_selected" -eq 0 ]; then
        return
    fi

    clear
    echo -e "${C_HEADER}${C_BOLD}◆ CONFIGURING SELECTED NODES${C_RESET}\n"

    local added_cnt=0
    local synced_cnt=0
    local cur_new_num=0
    local last_user="$USER"
    local last_tag="Homelab"

    for ((idx=0; idx<count; idx++)); do
        if [ "${found_selected[$idx]}" -eq 1 ]; then
            local ip="${found_ips[$idx]}"
            local raw_hname="${found_names[$idx]}"
            local clean_name="${raw_hname%%.*}"
            local mac="${found_macs[$idx]}"
            local st="${found_status[$idx]}"
            local r_idx="${found_real_idx[$idx]}"

            if [ "$st" == "SYNC" ] && [ "$r_idx" -ge 0 ]; then
                IFS='|' read -r c_name c_user c_host c_port c_tag c_mac c_key <<< "${all_lines[$r_idx]}"
                all_lines[$r_idx]="${c_name}|${c_user}|${c_host}|${c_port:-22}|${c_tag}|${mac}|${c_key}"
                printf "%s\n" "${all_lines[@]}" > "$CONFIG_FILE"
                echo -e "${C_YELLOW}[ SYNC ] Updated existing '${c_name}' (${ip}) with MAC: ${mac}${C_RESET}\n"
                ((synced_cnt++))
            else
                ((cur_new_num++))
                echo -e "${C_CYAN}${C_BOLD}── Configuring Node ${cur_new_num} of ${new_selected} ──────────────────────────────────────${C_RESET}"
                echo -e "  ${C_MUTED}IP Address :${C_RESET} ${C_BOLD}${ip}${C_RESET}   |   ${C_MUTED}Discovered Host :${C_RESET} ${C_GREEN}${raw_hname}${C_RESET}"
                echo -e "  ${C_MUTED}MAC Addr   :${C_RESET} ${mac:-N/A (Unreachable L2)}"
                echo -e "  ${C_MUTED}(Tip: Type [s] as Friendly Name to skip this node, or [q] to finish early)${C_RESET}\n"

                local custom_name=""
                read -erp "  Friendly Name: " -i "$clean_name" custom_name
                if [[ "$custom_name" =~ ^[Qq]$ ]]; then
                    echo -e "\n${C_MUTED}[ INFO ] Stopped remaining node setup.${C_RESET}"
                    break
                elif [[ -z "$custom_name" || "$custom_name" =~ ^[Ss]$ ]]; then
                    echo -e "  ${C_MUTED}[ SKIP ] Skipped ${ip}.${C_RESET}\n"
                    continue
                fi

                local custom_user=""
                read -erp "  SSH Username: " -i "$last_user" custom_user
                [ -z "$custom_user" ] && custom_user="$last_user"
                last_user="$custom_user"

                local custom_port=""
                read -erp "  SSH Port: " -i "22" custom_port
                [ -z "$custom_port" ] && custom_port="22"

                local custom_tag=""
                read -erp "  Tag / Category: " -i "$last_tag" custom_tag
                last_tag="$custom_tag"

                echo "${custom_name}|${custom_user}|${ip}|${custom_port}|${custom_tag}|${mac}|" >> "$CONFIG_FILE"
                echo -e "  ${C_GREEN}[  OK  ] Saved '${custom_name}' (${custom_user}@${ip}:${custom_port}) ${custom_tag:+[Tag: $custom_tag]}${C_RESET}\n"
                ((added_cnt++))
            fi
        fi
    done

    echo -ne "${C_MUTED}Done! Added ${added_cnt} new node(s), Synced ${synced_cnt} MAC(s). Press Enter to return to hub...${C_RESET}"
    read -r
}

delete_server_flow() {
    local idx="$1"
    local real_idx="${srv_real_idx[$idx]}"
    local name="${srv_names[$idx]}"

    for ((r=ROW_R_INFO_1; r<=ROW_TWIN_END; r++)); do
        render_right_cancel_pane "$r" 0
    done

    prompt_in_dialog "Delete '$name'? Click or press [y] to Delete, or [q]/[n] to Cancel: "
    enable_mouse
    local confirm=""
    local hover_row=0
    local row_yes="$ROW_R_ACT_START"
    local row_no="$(( ROW_R_ACT_START + 1 ))"

    while true; do
        if IFS= read -rsn1 -t 1 char; then
            if [[ "$char" == $'\e' ]]; then
                read -rsn2 -t 0.05 seq
                if [[ "$seq" == "[<" ]]; then
                    local mouse_event=""
                    local mchar=""
                    while IFS= read -rsn1 mchar; do
                        mouse_event+="$mchar"
                        [[ "$mchar" == "M" || "$mchar" == "m" ]] && break
                    done
                    if [[ "$mouse_event" =~ ^([0-9]+)\;([0-9]+)\;([0-9]+)([Mm])$ ]]; then
                        local btn="${BASH_REMATCH[1]}"
                        local cx="${BASH_REMATCH[2]}"
                        local cy="${BASH_REMATCH[3]}"
                        local action="${BASH_REMATCH[4]}"

                        if [ "$cx" -ge "$RIGHT_START" ] && [ "$cx" -le "$RIGHT_END" ] && { [ "$cy" -eq "$row_yes" ] || [ "$cy" -eq "$row_no" ]; }; then
                            if [ "$hover_row" -ne "$cy" ]; then
                                [ "$hover_row" -ne 0 ] && render_right_cancel_pane "$hover_row" 0
                                render_right_cancel_pane "$cy" 1
                                hover_row="$cy"
                            fi
                            if [ "$btn" -eq 0 ] && [ "$action" == "M" ]; then
                                if [ "$cy" -eq "$row_yes" ]; then
                                    confirm="y"
                                else
                                    confirm="n"
                                fi
                                break
                            fi
                        else
                            if [ "$hover_row" -ne 0 ]; then
                                render_right_cancel_pane "$hover_row" 0
                                hover_row=0
                            fi
                        fi
                    fi
                else
                    confirm="n"
                    break
                fi
            elif [[ "$char" =~ ^[YyNnQq]$ ]]; then
                confirm="$char"
                break
            fi
        fi
    done
    disable_mouse

    if [[ "$confirm" =~ ^[Yy]$ ]]; then
        unset 'all_lines[real_idx]'
        if [ "${#all_lines[@]}" -eq 0 ]; then
            > "$CONFIG_FILE"
        else
            printf "%s\n" "${all_lines[@]}" > "$CONFIG_FILE"
        fi
        temp_message "[  OK  ] Deleted '$name'."
    else
        temp_message "[ INFO ] Deletion cancelled."
    fi
}

cycle_filter_tag() {
    local count=${#unique_tags[@]}
    [ "$count" -le 1 ] && return
    local next_idx=0
    for i in "${!unique_tags[@]}"; do
        if [ "${unique_tags[$i]}" == "$FILTER_TAG" ]; then
            next_idx=$(( (i + 1) % count ))
            break
        fi
    done
    FILTER_TAG="${unique_tags[$next_idx]}"
}


theme_picker_flow() {
    repaint_theme_live() {
        draw_box "$ROW_TOP" "$((ROW_TOP + 2))" 1 "$TOTAL_W"
        draw_box "$ROW_TWIN_TOP" "$ROW_LEFT_BOTTOM" "$LEFT_START" "$LEFT_END"
        draw_box "$ROW_RIGHT_TOP" "$ROW_TWIN_BOTTOM" "$RIGHT_START" "$RIGHT_END"
        draw_box "$ROW_PROMPT_TOP" "$ROW_PROMPT_BOTTOM" 1 "$TOTAL_W"
        draw_separator "$ROW_LEGEND_SEP" "$LEFT_START" "$LEFT_END"

        local title="◆ SSH CONNECTION HUB (v${VERSION})"
        local filter_badge="[Tag: ${FILTER_TAG}]"
        local pad_title=$(( TOTAL_W - ${#title} - ${#filter_badge} - 6 ))
        [ "$pad_title" -lt 1 ] && pad_title=1
        printf "\e[%d;4H${C_HEADER}${C_BOLD}%s${C_RESET}%*s${C_YELLOW}%s${C_RESET}" \
            "$((ROW_TOP + 1))" "$title" "$pad_title" "" "$filter_badge"

        draw_pane_titles
        for ((r=ROW_TWIN_START; r<ROW_LEGEND_SEP; r++)); do
            render_left_pane "$r" 0
        done
        draw_left_legend
        for ((r=ROW_TWIN_START; r<=ROW_TWIN_END; r++)); do
            render_right_theme_pane "$r" 0
        done
        prompt_in_dialog "Theme Picker: Click or press [1-8] to preview & save border color, or [Enter/q] when done: "
    }

    for ((r=ROW_R_INFO_1; r<=ROW_TWIN_END; r++)); do
        render_right_theme_pane "$r" 0
    done
    prompt_in_dialog "Theme Picker: Click or press [1-8] to preview & save border color, or [Enter/q] when done: "
    enable_mouse

    local hover_row=0
    local row_done="$ROW_R_GLOB_START"

    while true; do
        if IFS= read -rsn1 -t 1 char; then
            if [[ "$char" == $'\e' ]]; then
                read -rsn2 -t 0.05 seq
                if [[ "$seq" == "[<" ]]; then
                    local mouse_event=""
                    local mchar=""
                    while IFS= read -rsn1 mchar; do
                        mouse_event+="$mchar"
                        [[ "$mchar" == "M" || "$mchar" == "m" ]] && break
                    done
                    if [[ "$mouse_event" =~ ^([0-9]+)\;([0-9]+)\;([0-9]+)([Mm])$ ]]; then
                        local btn="${BASH_REMATCH[1]}"
                        local cx="${BASH_REMATCH[2]}"
                        local cy="${BASH_REMATCH[3]}"
                        local action="${BASH_REMATCH[4]}"

                        if [ "$cx" -ge "$RIGHT_START" ] && [ "$cx" -le "$RIGHT_END" ] && \
                           { { [ "$cy" -ge "$ROW_R_ACT_START" ] && [ "$cy" -le "$ROW_R_ACT_END" ]; } || [ "$cy" -eq "$row_done" ]; }; then
                            if [ "$hover_row" -ne "$cy" ]; then
                                [ "$hover_row" -ne 0 ] && render_right_theme_pane "$hover_row" 0
                                render_right_theme_pane "$cy" 1
                                hover_row="$cy"
                            fi
                            if [ "$btn" -eq 0 ] && [ "$action" == "M" ]; then
                                if [ "$cy" -eq "$row_done" ]; then
                                    break
                                else
                                    local chosen=$(( cy - ROW_R_ACT_START ))
                                    save_theme "$chosen"
                                    repaint_theme_live
                                    render_right_theme_pane "$cy" 1
                                    hover_row="$cy"
                                fi
                            fi
                        else
                            if [ "$hover_row" -ne 0 ]; then
                                render_right_theme_pane "$hover_row" 0
                                hover_row=0
                            fi
                        fi
                    fi
                else
                    break
                fi
            elif [[ "$char" == "" || "$char" =~ ^[QqPp]$ ]]; then
                break
            elif [[ "$char" =~ ^[1-8]$ ]]; then
                local chosen=$(( char - 1 ))
                save_theme "$chosen"
                repaint_theme_live
                hover_row=0
            fi
        fi
    done

    disable_mouse
}
