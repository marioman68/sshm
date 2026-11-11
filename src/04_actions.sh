# ==============================================================================
# MODULE 04: User Actions & Workflows
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
    echo -e "${C_HEADER}${C_BOLD}◆ CONNECTING TO: ${name} (${user}@${host}:${port})${C_RESET}\n"

    local ssh_opts=("-p" "$port")
    if [ -n "$key" ]; then
        local exp_key
        exp_key=$(expand_path "$key")
        [ -f "$exp_key" ] && ssh_opts+=("-i" "$exp_key")
    fi

    echo -ne "${C_YELLOW}[INPUT] Auto-attach to remote tmux session if available? (y/N): ${C_RESET}"
    read -r use_tmux
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
    local url="sftp://${user}@${host}:${port}/"

    if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$url" &>/dev/null &
        temp_message "[  OK  ] Opening '$name' in GUI file manager..."
    elif command -v dolphin >/dev/null 2>&1; then
        dolphin "$url" &>/dev/null &
        temp_message "[  OK  ] Opening '$name' in Dolphin..."
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
    echo -e "${C_HEADER}${C_BOLD}◆ SFTP SESSION: ${name}${C_RESET}\n"

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
    echo -e "${C_HEADER}${C_BOLD}◆ BACKGROUND PORT TUNNELING: ${name}${C_RESET}\n"
    echo -ne "${C_YELLOW}[INPUT] Local port to bind (e.g. 8080): ${C_RESET}"
    read -erp "" lport
    echo -ne "${C_YELLOW}[INPUT] Remote target port (e.g. 80): ${C_RESET}"
    read -erp "" rport

    if [[ -z "$lport" || -z "$rport" ]]; then
        echo -e "\n${C_RED}[ FAIL ] Ports cannot be empty.${C_RESET}"
        sleep 1.5
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
        temp_message "[ FAIL ] No MAC address saved for '$name'. Edit profile first."
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
    echo -e "${C_HEADER}${C_BOLD}◆ PUSH SSH KEY TO: ${name}${C_RESET}\n"
    echo -e "${C_MUTED}(Tip: Press [Tab] to auto-complete file paths)${C_RESET}"
    echo -ne "${C_YELLOW}[INPUT] SSH Public Key path [Default: ${key:-~/.ssh/id_ed25519.pub}]: ${C_RESET}"
    read -erp "" custom_key

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
    echo -e "${C_HEADER}${C_BOLD}◆ ADD NEW SERVER PROFILE${C_RESET}\n"

    echo -ne "${C_YELLOW}Friendly Name: ${C_RESET}"
    read -erp "" name
    [ -z "$name" ] && return

    echo -ne "${C_YELLOW}Username: ${C_RESET}"
    read -erp "" user
    [ -z "$user" ] && return

    echo -ne "${C_YELLOW}Host / IP Address: ${C_RESET}"
    read -erp "" host
    [ -z "$host" ] && return

    echo -ne "${C_YELLOW}SSH Port [Default: 22]: ${C_RESET}"
    read -erp "" port
    [ -z "$port" ] && port=22

    echo -ne "${C_YELLOW}Tag / Category (optional, e.g. Homelab): ${C_RESET}"
    read -erp "" tag

    echo -ne "${C_YELLOW}MAC Address for WoL (optional, XX:XX:XX:XX:XX:XX): ${C_RESET}"
    read -erp "" mac

    echo -e "${C_MUTED}(Tip: Press [Tab] to auto-complete key path)${C_RESET}"
    echo -ne "${C_YELLOW}SSH Private Key Path (optional): ${C_RESET}"
    read -erp "" key

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
    echo -e "${C_HEADER}${C_BOLD}◆ EDIT SERVER PROFILE: ${c_name}${C_RESET}\n"
    echo -e "${C_MUTED}(Edit values below or press Enter to accept current value)${C_RESET}\n"

    read -erp "Friendly Name: " -i "$c_name" name
    read -erp "Username: " -i "$c_user" user
    read -erp "Host / IP: " -i "$c_host" host
    read -erp "SSH Port: " -i "$c_port" port
    read -erp "Tag / Category: " -i "$c_tag" tag
    read -erp "MAC Address: " -i "$c_mac" mac
    echo -e "${C_MUTED}(Tip: Press [Tab] to auto-complete key path)${C_RESET}"
    read -erp "SSH Key Path: " -i "$c_key" key

    all_lines[$real_idx]="${name}|${user}|${host}|${port:-22}|${tag}|${mac}|${key}"
    printf "%s\n" "${all_lines[@]}" > "$CONFIG_FILE"

    echo -e "\n${C_GREEN}[  OK  ] Profile updated!${C_RESET}"
    sleep 1
}

delete_server_flow() {
    local idx="$1"
    local real_idx="${srv_real_idx[$idx]}"
    local name="${srv_names[$idx]}"

    prompt_in_dialog "Delete '$name'? Type [y] to confirm: "
    read -r confirm
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

prompt_server_index() {
    local prompt_msg="$1"
    if [ "$server_count" -eq 0 ]; then
        temp_message "[ FAIL ] No servers available in current view."
        return 255
    fi
    prompt_in_dialog "$prompt_msg [1-$server_count]: "
    local num
    read -r num
    if [[ "$num" =~ ^[0-9]+$ ]] && [ "$num" -ge 1 ] && [ "$num" -le "$server_count" ]; then
        return $(( num - 1 ))
    else
        temp_message "[ FAIL ] Invalid server selection."
        return 255
    fi
}
