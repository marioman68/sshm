# ==============================================================================
# MODULE 03: Backend Logic (Mounts, Ping/TCP Latency & Config Loading)
# ==============================================================================

# Universal Desktop Environment Mount Check
is_mounted() {
    local name="$1"
    local user="$2"
    local host="$3"
    local port="$4"
    local safe_name="${name// /_}"

    if [[ "$XDG_CURRENT_DESKTOP" == *"KDE"* ]] || [ -d "$REMOTEVIEW_DIR" ]; then
        [ -f "$REMOTEVIEW_DIR/${safe_name}.desktop" ] && return 0
    fi
    if [ -f "$GTK_BOOKMARKS" ]; then
        grep -q "sftp://${user}@${host}:${port}" "$GTK_BOOKMARKS" 2>/dev/null && return 0
    fi
    return 1
}

toggle_mount() {
    local idx="$1"
    local name="${srv_names[$idx]}"
    local user="${srv_users[$idx]}"
    local host="${srv_hosts[$idx]}"
    local port="${srv_ports[$idx]}"
    local safe_name="${name// /_}"

    if is_mounted "$name" "$user" "$host" "$port"; then
        rm -f "$REMOTEVIEW_DIR/${safe_name}.desktop" 2>/dev/null
        if [ -f "$GTK_BOOKMARKS" ]; then
            sed -i "\|sftp://${user}@${host}:${port}|d" "$GTK_BOOKMARKS" 2>/dev/null
        fi
        temp_message "[  OK  ] Unmounted '$name' from Network Folders."
    else
        if [[ "$XDG_CURRENT_DESKTOP" == *"KDE"* ]] || command -v dolphin >/dev/null 2>&1; then
            mkdir -p "$REMOTEVIEW_DIR"
            cat <<EOF2 > "$REMOTEVIEW_DIR/${safe_name}.desktop"
[Desktop Entry]
Icon=folder-remote
Name=$name
Type=Link
URL=sftp://${user}@${host}:${port}/
EOF2
        else
            mkdir -p "$(dirname "$GTK_BOOKMARKS")"
            echo "sftp://${user}@${host}:${port}/ $name" >> "$GTK_BOOKMARKS"
        fi
        temp_message "[  OK  ] Mounted '$name' to Network Folders!"
    fi
}

measure_latency() {
    local host="$1"
    local port="$2"
    local rtt=""

    rtt=$(ping -c 1 -W 1 "$host" 2>/dev/null | awk -F'time=' '/time=/ {split($2, a, " "); print int(a[1]+0.5)"ms"}')
    if [ -n "$rtt" ]; then
        echo "ONLINE|$rtt"
        return
    fi

    if timeout 1 bash -c "</dev/tcp/$host/$port" 2>/dev/null; then
        echo "ONLINE|TCP"
    else
        echo "OFFLINE|--"
    fi
}

load_servers() {
    touch "$CONFIG_FILE"
    all_lines=()
    unique_tags=("ALL")

    while IFS= read -r line || [ -n "$line" ]; do
        [[ -z "$line" || "$line" =~ ^# ]] && continue
        all_lines+=("$line")
        IFS='|' read -r _ _ _ _ tag _ _ <<< "$line"
        if [ -n "$tag" ]; then
            local found=0
            for t in "${unique_tags[@]}"; do
                [ "$t" == "$tag" ] && found=1 && break
            done
            [ "$found" -eq 0 ] && unique_tags+=("$tag")
        fi
    done < "$CONFIG_FILE"

    srv_real_idx=()
    srv_names=()
    srv_users=()
    srv_hosts=()
    srv_ports=()
    srv_tags=()
    srv_macs=()
    srv_keys=()
    srv_online=()
    srv_latencies=()
    srv_mounted=()

    local tmp_dir
    tmp_dir=$(mktemp -d)

    local disp_i=0
    for i in "${!all_lines[@]}"; do
        IFS='|' read -r name user host port tag mac key <<< "${all_lines[$i]}"
        [ -z "$port" ] && port=22

        if [ "$FILTER_TAG" != "ALL" ] && [ "$tag" != "$FILTER_TAG" ]; then
            continue
        fi

        srv_real_idx+=("$i")
        srv_names+=("$name")
        srv_users+=("$user")
        srv_hosts+=("$host")
        srv_ports+=("$port")
        srv_tags+=("$tag")
        srv_macs+=("$mac")
        srv_keys+=("$key")

        if is_mounted "$name" "$user" "$host" "$port"; then
            srv_mounted+=("1")
        else
            srv_mounted+=("0")
        fi

        (
            measure_latency "$host" "$port" > "$tmp_dir/$disp_i"
        ) &

        disp_i=$(( disp_i + 1 ))
    done

    wait

    server_count=$disp_i
    for ((j=0; j<server_count; j++)); do
        if [ -f "$tmp_dir/$j" ]; then
            IFS='|' read -r st lat < "$tmp_dir/$j"
            srv_online+=("$st")
            srv_latencies+=("$lat")
        else
            srv_online+=("OFFLINE")
            srv_latencies+=("--")
        fi
    done

    rm -rf "$tmp_dir"
}
