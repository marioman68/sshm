# ==============================================================================
# MODULE 03: Backend Logic (Config, Ping/Latency, Mounts, MAC & Network Probes)
# ==============================================================================

measure_latency() {
    local host="$1"
    local port="${2:-22}"
    local ping_out

    # Verify SSH TCP port is actually open first (prevents sleeping WoL NICs from faking ONLINE)
    if ! timeout 1 bash -c "cat < /dev/null > /dev/tcp/${host}/${port}" 2>/dev/null; then
        printf -- "--|OFFLINE"
        return 1
    fi

    if ping_out=$(ping -c 1 -W 1 "$host" 2>/dev/null); then
        local ms
        ms=$(echo "$ping_out" | grep -oP 'time=\K[0-9.]+' | head -n1)
        if [ -n "$ms" ]; then
            printf "%.0fms|ONLINE" "$ms"
        else
            printf "1ms|ONLINE"
        fi
        return 0
    fi

    printf "TCP|ONLINE"
    return 0
}

# Resolves a target hostname/IP and probes ARP cache for its hardware MAC address
probe_host_mac() {
    local target="$1"
    [ -z "$target" ] && return 1

    local resolved_ip="$target"
    if [[ ! "$target" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        resolved_ip=$(getent ahostsv4 "$target" 2>/dev/null | awk '{print $1; exit}')
        [ -z "$resolved_ip" ] && resolved_ip=$(ping -c 1 -W 1 "$target" 2>/dev/null | grep -oP '\(\K[0-9.]+(?=\))' | head -n1)
    fi
    [ -z "$resolved_ip" ] && return 1

    # Wake ARP cache with a quick 1-packet ping
    ping -c 1 -W 1 "$resolved_ip" >/dev/null 2>&1

    local mac=""
    mac=$(ip neigh show "$resolved_ip" 2>/dev/null | grep -oE '([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}' | head -n1)
    if [ -z "$mac" ] && [ -f /proc/net/arp ]; then
        mac=$(awk -v ip="$resolved_ip" '$1 == ip {print $4}' /proc/net/arp | grep -oE '([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}' | head -n1)
    fi

    if [ -n "$mac" ] && [ "$mac" != "00:00:00:00:00:00" ]; then
        echo "${mac,,}"
        return 0
    fi
    return 1
}

# Resolves reverse DNS or mDNS (.local) hostname for an IP address
probe_host_name() {
    local ip="$1"
    local hname=""

    if command -v avahi-resolve-address >/dev/null 2>&1; then
        hname=$(timeout 1 avahi-resolve-address "$ip" 2>/dev/null | awk '{print $2}' | sed 's/\.$//')
    fi
    if [ -z "$hname" ]; then
        hname=$(getent hosts "$ip" 2>/dev/null | awk '{print $2; exit}')
    fi
    if [ -z "$hname" ] && command -v host >/dev/null 2>&1; then
        hname=$(timeout 1 host "$ip" 2>/dev/null | awk '/domain name pointer/ {print $5}' | sed 's/\.$//' | head -n1)
    fi

    echo "$hname"
}

# Detects primary local IPv4 /24 prefix (e.g., 192.168.4)
get_default_subnet_prefix() {
    local src_ip=""
    src_ip=$(ip route get 1.1.1.1 2>/dev/null | grep -oP 'src \K[0-9.]+')
    if [ -z "$src_ip" ]; then
        src_ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    fi
    if [[ "$src_ip" =~ ^([0-9]+\.[0-9]+\.[0-9]+)\.[0-9]+$ ]]; then
        echo "${BASH_REMATCH[1]}"
    else
        echo "192.168.1"
    fi
}

check_is_mounted() {
    local name="$1"
    local user="$2"
    local host="$3"
    local port="${4:-22}"
    local safe_name="${name// /_}"
    local desktop_file="$MOUNT_DIR/${safe_name}.desktop"

    if [ -f "$desktop_file" ]; then
        return 0
    fi

    if [ -f "$HOME/.local/share/user-places.xbel" ] && grep -q "sftp://${user}@${host}" "$HOME/.local/share/user-places.xbel" 2>/dev/null; then
        return 0
    fi

    if [ -f "$HOME/.config/gtk-3.0/bookmarks" ] && grep -q "sftp://${user}@${host}" "$HOME/.config/gtk-3.0/bookmarks" 2>/dev/null; then
        return 0
    fi

    return 1
}

toggle_mount() {
    local idx="$1"
    local name="${srv_names[$idx]}"
    local user="${srv_users[$idx]}"
    local host="${srv_hosts[$idx]}"
    local port="${srv_ports[$idx]}"
    local cur_mnt="${srv_mounted[$idx]}"

    local safe_name="${name// /_}"
    local desktop_file="$MOUNT_DIR/${safe_name}.desktop"
    local target_dir="/home/${user}"
    [ "$user" = "root" ] && target_dir="/root"
    local url="sftp://${user}@${host}:${port}${target_dir}"
    local xbel_file="$HOME/.local/share/user-places.xbel"
    local gtk_file="$HOME/.config/gtk-3.0/bookmarks"

    mkdir -p "$MOUNT_DIR"

    if [ "$cur_mnt" -eq 1 ]; then
        rm -f "$desktop_file"
        if [ -f "$gtk_file" ]; then
            sed -i "\|sftp://${user}@${host}|d" "$gtk_file"
        fi
        if [ -f "$xbel_file" ] && command -v python3 >/dev/null 2>&1; then
            python3 -c "
import os, xml.etree.ElementTree as ET
p = os.path.expanduser('$xbel_file')
try:
    tree = ET.parse(p)
    root = tree.getroot()
    for b in list(root.findall('bookmark')):
        if 'sftp://${user}@${host}' in b.attrib.get('href', ''):
            root.remove(b)
    tree.write(p, encoding='UTF-8', xml_declaration=True)
except Exception:
    pass
" 2>/dev/null
        fi
        srv_mounted[$idx]=0
        temp_message "[  OK  ] Unmounted '$name' from Network Places."
    else
        cat << DESKTOP > "$desktop_file"
[Desktop Entry]
Icon=folder-remote
Name=${name} (${user}@${host})
Type=Link
URL[$e]=${url}
DESKTOP
        chmod +x "$desktop_file"

        if [[ "${XDG_CURRENT_DESKTOP^^}" == *"KDE"* ]] && [ -f "$xbel_file" ] && command -v python3 >/dev/null 2>&1; then
            python3 -c "
import os, xml.etree.ElementTree as ET
p = os.path.expanduser('$xbel_file')
try:
    tree = ET.parse(p)
    root = tree.getroot()
    exists = any('sftp://${user}@${host}' in b.attrib.get('href', '') for b in root.findall('bookmark'))
    if not exists:
        bm = ET.SubElement(root, 'bookmark', {'href': '$url'})
        title = ET.SubElement(bm, 'title')
        title.text = 'SSH: $name'
        info = ET.SubElement(bm, 'info')
        meta = ET.SubElement(info, 'metadata', {'owner': 'http://freedesktop.org'})
        icon = ET.SubElement(meta, '{http://www.freedesktop.org/standards/shared-mime-info}icon', {'name': 'folder-remote'})
        tree.write(p, encoding='UTF-8', xml_declaration=True)
except Exception:
    pass
" 2>/dev/null
        else
            mkdir -p "$(dirname "$gtk_file")"
            touch "$gtk_file"
            if ! grep -q "sftp://${user}@${host}" "$gtk_file" 2>/dev/null; then
                echo "${url} SSH_${safe_name}" >> "$gtk_file"
            fi
        fi
        srv_mounted[$idx]=1
        temp_message "[  OK  ] Mounted '$name' (${target_dir}) to Network Places!"
    fi
}

load_and_ping_servers() {
    all_lines=()
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
    unique_tags=("ALL")
    server_count=0

    [ ! -f "$CONFIG_FILE" ] && touch "$CONFIG_FILE"

    mapfile -t raw_lines < "$CONFIG_FILE"
    local tmp_dir
    tmp_dir=$(mktemp -d)

    local real_i=0
    for line in "${raw_lines[@]}"; do
        line="${line%$'\r'}"
        [[ -z "${line// /}" || "$line" =~ ^# ]] && continue

        all_lines[$real_i]="$line"
        IFS='|' read -r name user host port tag mac key <<< "$line"
        [ -z "$port" ] && port=22

        if [ -n "$tag" ]; then
            local tag_exists=0
            for t in "${unique_tags[@]}"; do
                [ "$t" == "$tag" ] && tag_exists=1 && break
            done
            [ "$tag_exists" -eq 0 ] && unique_tags+=("$tag")
        fi

        if [ "$FILTER_TAG" == "ALL" ] || [ "$FILTER_TAG" == "$tag" ]; then
            local idx="$server_count"
            srv_real_idx[$idx]="$real_i"
            srv_names[$idx]="$name"
            srv_users[$idx]="$user"
            srv_hosts[$idx]="$host"
            srv_ports[$idx]="$port"
            srv_tags[$idx]="$tag"
            srv_macs[$idx]="$mac"
            srv_keys[$idx]="$key"

            if check_is_mounted "$name" "$user" "$host" "$port"; then
                srv_mounted[$idx]=1
            else
                srv_mounted[$idx]=0
            fi

            (
                measure_latency "$host" "$port" > "$tmp_dir/$idx"
            ) &

            ((server_count++))
        fi
        ((real_i++))
    done

    wait

    for ((i=0; i<server_count; i++)); do
        if [ -f "$tmp_dir/$i" ]; then
            IFS='|' read -r lat st < "$tmp_dir/$i"
            srv_latencies[$i]="${lat:---}"
            srv_online[$i]="${st:-OFFLINE}"
        else
            srv_latencies[$i]="--"
            srv_online[$i]="OFFLINE"
        fi
    done

    rm -rf "$tmp_dir"
}
