# ==============================================================================
# MODULE 02: Responsive Geometry, Wireframe & Pane Renderers
# ==============================================================================

calc_geometry() {
    TERM_COLS=$(tput cols 2>/dev/null || echo 100)
    TERM_LINES=$(tput lines 2>/dev/null || echo 30)

    if [ -n "${TERMUX_VERSION:-}" ] || [ "$TERM_COLS" -lt 88 ]; then
        IS_MOBILE=1
        TOTAL_W=$(( TERM_COLS - 2 ))
        [ "$TOTAL_W" -lt 44 ] && TOTAL_W=44

        LEFT_START=1
        LEFT_END=$TOTAL_W
        LEFT_INNER_W=$(( TOTAL_W - 2 ))

        RIGHT_START=1
        RIGHT_END=$TOTAL_W
        RIGHT_INNER_W=$(( TOTAL_W - 2 ))

        ROW_TOP=1
        ROW_PANE_TOP=4
        ROW_TWIN_START=5

        local list_rows=6
        [ "$server_count" -gt "$list_rows" ] && list_rows="$server_count"
        [ "$list_rows" -gt 10 ] && list_rows=10

        ROW_LEGEND_SEP=$(( ROW_TWIN_START + list_rows ))
        ROW_LEFT_BOTTOM=$(( ROW_LEGEND_SEP + 3 ))

        ROW_RIGHT_TOP=$(( ROW_LEFT_BOTTOM + 1 ))
        ROW_R_INFO_1=$(( ROW_RIGHT_TOP + 1 ))
        ROW_R_INFO_2=$(( ROW_RIGHT_TOP + 2 ))
        ROW_R_INFO_3=$(( ROW_RIGHT_TOP + 3 ))
        ROW_R_SEP_1=$(( ROW_RIGHT_TOP + 4 ))
        ROW_R_ACT_START=$(( ROW_RIGHT_TOP + 5 ))
        ROW_R_ACT_END=$(( ROW_R_ACT_START + 8 ))
        ROW_R_SEP_2=$(( ROW_R_ACT_END + 1 ))
        ROW_R_GLOB_START=$(( ROW_R_SEP_2 + 1 ))
        ROW_R_GLOB_END=$(( ROW_R_GLOB_START + 4 ))
        ROW_TWIN_END=$(( ROW_R_GLOB_END ))
        ROW_BOTTOM=$(( ROW_TWIN_END + 1 ))
        ROW_DIALOG_TOP=$(( ROW_BOTTOM + 1 ))
    else
        IS_MOBILE=0
        [ "$TERM_COLS" -lt 92 ] && TERM_COLS=92
        [ "$TERM_LINES" -lt 29 ] && TERM_LINES=29

        TOTAL_W=$(( TERM_COLS - 2 ))
        LEFT_START=1
        LEFT_W=$(( (TOTAL_W * 44) / 100 ))
        [ "$LEFT_W" -lt 38 ] && LEFT_W=38
        LEFT_END=$(( LEFT_START + LEFT_W - 1 ))
        LEFT_INNER_W=$(( LEFT_W - 2 ))

        RIGHT_START=$(( LEFT_END + 2 ))
        RIGHT_END=$TOTAL_W
        RIGHT_W=$(( RIGHT_END - RIGHT_START + 1 ))
        RIGHT_INNER_W=$(( RIGHT_W - 2 ))

        ROW_TOP=1
        ROW_PANE_TOP=4
        ROW_TWIN_START=5

        CONTENT_H=$(( TERM_LINES - 9 ))
        [ "$CONTENT_H" -lt 19 ] && CONTENT_H=19

        ROW_TWIN_END=$(( ROW_TWIN_START + CONTENT_H - 1 ))
        ROW_LEGEND_SEP=$(( ROW_TWIN_END - 3 ))
        ROW_LEFT_BOTTOM=$(( ROW_TWIN_END + 1 ))
        ROW_RIGHT_TOP=$ROW_PANE_TOP

        ROW_R_INFO_1=$ROW_TWIN_START
        ROW_R_INFO_2=$(( ROW_TWIN_START + 1 ))
        ROW_R_INFO_3=$(( ROW_TWIN_START + 2 ))
        ROW_R_SEP_1=$(( ROW_TWIN_START + 3 ))
        ROW_R_ACT_START=$(( ROW_TWIN_START + 4 ))
        ROW_R_ACT_END=$(( ROW_R_ACT_START + 8 ))
        ROW_R_SEP_2=$(( ROW_R_ACT_END + 1 ))
        ROW_R_GLOB_START=$(( ROW_R_SEP_2 + 1 ))
        ROW_R_GLOB_END=$(( ROW_R_GLOB_START + 4 ))

        ROW_BOTTOM=$(( ROW_TWIN_END + 1 ))
        ROW_DIALOG_TOP=$(( ROW_BOTTOM + 1 ))
    fi
}

draw_box_top() {
    local r="$1" c1="$2" c2="$3"
    local w=$(( c2 - c1 - 1 ))
    printf "\e[%d;%dH${C_BORDER}╭%s╮${C_RESET}" "$r" "$c1" "$(repeat_char "─" "$w")"
}

draw_box_bottom() {
    local r="$1" c1="$2" c2="$3"
    local w=$(( c2 - c1 - 1 ))
    printf "\e[%d;%dH${C_BORDER}╰%s╯${C_RESET}" "$r" "$c1" "$(repeat_char "─" "$w")"
}

draw_separator() {
    local r="$1" c1="$2" c2="$3"
    local w=$(( c2 - c1 - 1 ))
    printf "\e[%d;%dH${C_BORDER}├%s┤${C_RESET}" "$r" "$c1" "$(repeat_char "─" "$w")"
}

draw_wireframe() {
    calc_geometry
    clear

    # Top Title Box
    draw_box_top "$ROW_TOP" 1 "$TOTAL_W"
    printf "\e[%d;1H${C_BORDER}│${C_RESET}%*s${C_BORDER}│${C_RESET}" "$((ROW_TOP + 1))" "$((TOTAL_W - 2))" ""
    draw_box_bottom "$((ROW_TOP + 2))" 1 "$TOTAL_W"

    if [ "$IS_MOBILE" -eq 1 ]; then
        draw_box_top "$ROW_PANE_TOP" "$LEFT_START" "$LEFT_END"
        for ((r=ROW_TWIN_START; r<ROW_LEFT_BOTTOM; r++)); do
            printf "\e[%d;%dH${C_BORDER}│${C_RESET}%*s${C_BORDER}│${C_RESET}" "$r" "$LEFT_START" "$LEFT_INNER_W" ""
        done
        draw_separator "$ROW_LEGEND_SEP" "$LEFT_START" "$LEFT_END"
        draw_box_bottom "$ROW_LEFT_BOTTOM" "$LEFT_START" "$LEFT_END"

        draw_box_top "$ROW_RIGHT_TOP" "$RIGHT_START" "$RIGHT_END"
        for ((r=ROW_R_INFO_1; r<=ROW_TWIN_END; r++)); do
            printf "\e[%d;%dH${C_BORDER}│${C_RESET}%*s${C_BORDER}│${C_RESET}" "$r" "$RIGHT_START" "$RIGHT_INNER_W" ""
        done
        draw_box_bottom "$ROW_BOTTOM" "$RIGHT_START" "$RIGHT_END"
    else
        draw_box_top "$ROW_PANE_TOP" "$LEFT_START" "$LEFT_END"
        draw_box_top "$ROW_PANE_TOP" "$RIGHT_START" "$RIGHT_END"

        for ((r=ROW_TWIN_START; r<=ROW_TWIN_END; r++)); do
            printf "\e[%d;%dH${C_BORDER}│${C_RESET}%*s${C_BORDER}│${C_RESET}" "$r" "$LEFT_START" "$LEFT_INNER_W" ""
            printf "\e[%d;%dH${C_BORDER}│${C_RESET}%*s${C_BORDER}│${C_RESET}" "$r" "$RIGHT_START" "$RIGHT_INNER_W" ""
        done

        draw_separator "$ROW_LEGEND_SEP" "$LEFT_START" "$LEFT_END"
        draw_box_bottom "$ROW_BOTTOM" "$LEFT_START" "$LEFT_END"
        draw_box_bottom "$ROW_BOTTOM" "$RIGHT_START" "$RIGHT_END"
    fi

    # Bottom Dialog Box
    draw_box_top "$ROW_DIALOG_TOP" 1 "$TOTAL_W"
    printf "\e[%d;1H${C_BORDER}│${C_RESET}%*s${C_BORDER}│${C_RESET}" "$((ROW_DIALOG_TOP + 1))" "$((TOTAL_W - 2))" ""
    draw_box_bottom "$((ROW_DIALOG_TOP + 2))" 1 "$TOTAL_W"
}

draw_pane_titles() {
    local l_title=" REMOTE NODES (${server_count}) "
    local l_rem=$(( LEFT_END - LEFT_START - 2 - ${#l_title} ))
    [ "$l_rem" -lt 1 ] && l_rem=1
    printf "\e[%d;%dH${C_BORDER}╭─${C_HEADER}${C_BOLD}%s${C_RESET}${C_BORDER}%s╮${C_RESET}" \
        "$ROW_PANE_TOP" "$LEFT_START" "$l_title" "$(repeat_char "─" "$l_rem")"

    local r_title=" TARGET: None "
    if [ "$server_count" -gt 0 ] && [ "$selected_idx" -ge 0 ] && [ "$selected_idx" -lt "$server_count" ]; then
        local t_name="${srv_names[$selected_idx]}"
        local t_tag="${srv_tags[$selected_idx]}"
        if [ -n "$t_tag" ]; then
            r_title=" TARGET: ${t_name} [${t_tag}] "
        else
            r_title=" TARGET: ${t_name} "
        fi
    fi

    local max_rt=$(( RIGHT_INNER_W - 4 ))
    if [ "${#r_title}" -gt "$max_rt" ]; then
        r_title="${r_title:0:$max_rt} "
    fi

    local r_rem=$(( RIGHT_END - RIGHT_START - 2 - ${#r_title} ))
    [ "$r_rem" -lt 1 ] && r_rem=1
    printf "\e[%d;%dH${C_BORDER}╭─${C_CYAN}${C_BOLD}%s${C_RESET}${C_BORDER}%s╮${C_RESET}" \
        "$ROW_RIGHT_TOP" "$RIGHT_START" "$r_title" "$(repeat_char "─" "$r_rem")"
}

draw_left_legend() {
    local r1=$(( ROW_LEGEND_SEP + 1 ))
    local r2=$(( ROW_LEGEND_SEP + 2 ))
    local col=$(( LEFT_START + 1 ))

    local raw1="  ● Online  ○ Offline  ◆ / ◇ Click Mount"
    local pad1=$(( LEFT_INNER_W - ${#raw1} ))
    [ "$pad1" -lt 0 ] && pad1=0
    printf "\e[%d;%dH  ${C_GREEN}●${C_RESET} Online  ${C_RED}○${C_RESET} Offline  ${C_BLUE}◆${C_RESET} / ${C_MUTED}◇${C_RESET} Click Mount%*s${C_BORDER}│${C_RESET}" \
        "$r1" "$col" "$pad1" ""

    local raw2="  Click server to target • 2x-Click SSH • [f] Filter"
    if [ "${#raw2}" -gt "$LEFT_INNER_W" ]; then
        raw2="  Click to target • 2x-Click SSH"
        local pad2=$(( LEFT_INNER_W - ${#raw2} ))
        [ "$pad2" -lt 0 ] && pad2=0
        printf "\e[%d;%dH${C_MUTED}%s%*s${C_RESET}${C_BORDER}│${C_RESET}" "$r2" "$col" "$raw2" "$pad2" ""
    else
        local pad2=$(( LEFT_INNER_W - ${#raw2} ))
        [ "$pad2" -lt 0 ] && pad2=0
        printf "\e[%d;%dH${C_MUTED}  Click server to target • 2x-Click SSH • [f] Filter%*s${C_RESET}${C_BORDER}│${C_RESET}" \
            "$r2" "$col" "$pad2" ""
    fi
}

render_left_pane() {
    local row="$1"
    local hover_mode="${2:-0}"
    local idx=$(( row - ROW_TWIN_START ))
    local col_start=$(( LEFT_START + 1 ))

    printf "\e[%d;%dH" "$row" "$col_start"

    if [ "$idx" -ge 0 ] && [ "$idx" -lt "$server_count" ]; then
        local is_sel=0
        [ "$idx" -eq "$selected_idx" ] && is_sel=1

        local bg=""
        [ "$is_sel" -eq 1 ] && bg="${BG_SELECT}"
        [ "$hover_mode" -ge 1 ] && bg="${BG_HOVER}"

        local ptr="  "
        [ "$is_sel" -eq 1 ] && ptr=" ${C_CYAN}${C_BOLD}▸${C_RESET}${bg}"

        local dot="${C_RED}○${C_RESET}${bg}"
        [ "${srv_online[$idx]}" == "ONLINE" ] && dot="${C_GREEN}●${C_RESET}${bg}"

        local mnt="${C_MUTED}◇${C_RESET}${bg}"
        if [ "${srv_mounted[$idx]}" -eq 1 ]; then
            mnt="${C_BLUE}◆${C_RESET}${bg}"
        fi
        if [ "$hover_mode" -eq 2 ]; then
            mnt="${C_YELLOW}${C_BOLD}◈${C_RESET}${bg}"
        fi

        local num_str
        printf -v num_str "[%2d]" "$((idx + 1))"

        local name="${srv_names[$idx]}"
        local tag="${srv_tags[$idx]}"
        local disp_name="$name"
        [ -n "$tag" ] && disp_name="${name} [${tag}]"

        local lat="${srv_latencies[$idx]}"
        local max_name_w=$(( LEFT_INNER_W - 19 ))
        [ "$max_name_w" -lt 10 ] && max_name_w=10
        if [ "${#disp_name}" -gt "$max_name_w" ]; then
            disp_name="${disp_name:0:$((max_name_w - 1))}…"
        fi

        local name_pad=$(( max_name_w - ${#disp_name} ))
        [ "$name_pad" -lt 0 ] && name_pad=0

        local n_col="${C_RESET}${bg}"
        [ "$is_sel" -eq 1 ] && n_col="${C_CYAN}${C_BOLD}${bg}"

        local lat_col="${C_MUTED}${bg}"
        [ "${srv_online[$idx]}" == "ONLINE" ] && lat_col="${C_CYAN}${bg}"

        local raw_len=$(( 2 + 2 + 2 + 4 + 2 + max_name_w + 1 + 5 ))
        local trail_pad=$(( LEFT_INNER_W - raw_len ))
        [ "$trail_pad" -lt 0 ] && trail_pad=0

        printf "${bg}%b %b %b ${C_GREEN}%s${C_RESET}${bg}  %b%s%*s${C_RESET}${bg} %b%5s${C_RESET}${bg}%*s${C_RESET}" \
            "$ptr" "$dot" "$mnt" "$num_str" "$n_col" "$disp_name" "$name_pad" "" "$lat_col" "$lat" "$trail_pad" ""
    else
        printf "%*s" "$LEFT_INNER_W" ""
    fi

    printf "\e[%d;%dH${C_BORDER}│${C_RESET}" "$row" "$LEFT_END"
}

render_right_pane() {
    local row="$1"
    local is_hover="$2"

    if [ "$row" -eq "$ROW_R_SEP_1" ] || [ "$row" -eq "$ROW_R_SEP_2" ]; then
        draw_separator "$row" "$RIGHT_START" "$RIGHT_END"
        return
    fi

    local col_start=$(( RIGHT_START + 1 ))
    printf "\e[%d;%dH" "$row" "$col_start"

    if [ "$row" -eq "$ROW_R_INFO_1" ]; then
        if [ "$server_count" -gt 0 ] && [ "$selected_idx" -ge 0 ] && [ "$selected_idx" -lt "$server_count" ]; then
            local ep="${srv_users[$selected_idx]}@${srv_hosts[$selected_idx]}:${srv_ports[$selected_idx]}"
            local raw="  Endpoint : ${ep}"
            local pad=$(( RIGHT_INNER_W - ${#raw} ))
            [ "$pad" -lt 0 ] && pad=0
            printf "  ${C_MUTED}Endpoint :${C_RESET} ${C_BLUE}${C_BOLD}%s${C_RESET}%*s" "$ep" "$pad" ""
        else
            local raw="  No server profiles configured yet."
            local pad=$(( RIGHT_INNER_W - ${#raw} ))
            [ "$pad" -lt 0 ] && pad=0
            printf "${C_MUTED}%s%*s${C_RESET}" "$raw" "$pad" ""
        fi
        printf "\e[%d;%dH${C_BORDER}│${C_RESET}" "$row" "$RIGHT_END"
        return
    elif [ "$row" -eq "$ROW_R_INFO_2" ]; then
        if [ "$server_count" -gt 0 ] && [ "$selected_idx" -ge 0 ] && [ "$selected_idx" -lt "$server_count" ]; then
            local st="${srv_online[$selected_idx]}"
            local lat="${srv_latencies[$selected_idx]}"
            local mnt="${srv_mounted[$selected_idx]}"

            local st_plain="OFFLINE"
            local st_col="${C_RED}○ OFFLINE${C_RESET}"
            if [ "$st" == "ONLINE" ]; then
                st_plain="ONLINE (${lat})"
                st_col="${C_GREEN}● ONLINE (${lat})${C_RESET}"
            fi

            local mnt_plain="Unmounted"
            local mnt_col="${C_MUTED}◇ Unmounted${C_RESET}"
            if [ "$mnt" -eq 1 ]; then
                mnt_plain="Mounted"
                mnt_col="${C_BLUE}◆ Mounted${C_RESET}"
            fi

            local raw="  Status   : ● ${st_plain}   •   ◇ ${mnt_plain}"
            local pad=$(( RIGHT_INNER_W - ${#raw} ))
            [ "$pad" -lt 0 ] && pad=0
            printf "  ${C_MUTED}Status   :${C_RESET} %b   ${C_MUTED}•${C_RESET}   %b%*s" "$st_col" "$mnt_col" "$pad" ""
        else
            local raw="  Press [a] or [n] below to add servers."
            local pad=$(( RIGHT_INNER_W - ${#raw} ))
            [ "$pad" -lt 0 ] && pad=0
            printf "${C_MUTED}%s%*s${C_RESET}" "$raw" "$pad" ""
        fi
        printf "\e[%d;%dH${C_BORDER}│${C_RESET}" "$row" "$RIGHT_END"
        return
    elif [ "$row" -eq "$ROW_R_INFO_3" ]; then
        if [ "$server_count" -gt 0 ] && [ "$selected_idx" -ge 0 ] && [ "$selected_idx" -lt "$server_count" ]; then
            if [ "${srv_has_agent[$selected_idx]:-0}" -eq 1 ]; then
                local cpu="${srv_cpu[$selected_idx]}"
                local ram="${srv_ram[$selected_idx]}"
                local up="${srv_uptime[$selected_idx]}"
                local raw="  Metrics  : ● CPU ${cpu}%   •   RAM ${ram}   •   Up ${up}"
                local pad=$(( RIGHT_INNER_W - ${#raw} ))
                [ "$pad" -lt 0 ] && pad=0
                printf "  ${C_MUTED}Metrics  :${C_RESET} ${C_PURPLE}●${C_RESET} CPU ${C_CYAN}${C_BOLD}%s%%${C_RESET}   ${C_MUTED}•${C_RESET}   RAM ${C_YELLOW}${C_BOLD}%s${C_RESET}   ${C_MUTED}•${C_RESET}   Up ${C_BOLD}%s${C_RESET}%*s" "$cpu" "$ram" "$up" "$pad" ""
            else
                local raw="  Metrics  : ○ Agent not installed ([g] for live stats)"
                local pad=$(( RIGHT_INNER_W - ${#raw} ))
                [ "$pad" -lt 0 ] && pad=0
                printf "  ${C_MUTED}Metrics  : ○ Agent not installed (${C_CYAN}[g]${C_MUTED} for live stats)%*s${C_RESET}" "$pad" ""
            fi
        else
            printf "%*s" "$RIGHT_INNER_W" ""
        fi
        printf "\e[%d;%dH${C_BORDER}│${C_RESET}" "$row" "$RIGHT_END"
        return
    fi

    local act_idx=$(( row - ROW_R_ACT_START ))
    if [ "$act_idx" -ge 0 ] && [ "$act_idx" -le 8 ]; then
        local bg=""
        [ "$is_hover" -eq 1 ] && bg="${BG_HOVER}"

        local p1=""
        local p2=""
        local raw_text=""
        local mac_lbl="Not Configured"
        if [ "$server_count" -gt 0 ] && [ -n "${srv_macs[$selected_idx]:-}" ]; then
            mac_lbl="${srv_macs[$selected_idx]}"
        fi

        case "$act_idx" in
            0) p1="${C_GREEN}[c]${C_RESET}${bg}";  p2="   ${C_BLUE}${C_BOLD}Connect via SSH${C_RESET}${bg} (Auto-tmux)"; raw_text="  [c]   Connect via SSH (Auto-tmux)" ;;
            1) p1="${C_CYAN}[b]${C_RESET}${bg}";   p2="   Open Network Folder in File Manager";         raw_text="  [b]   Open Network Folder in File Manager" ;;
            2) p1="${C_BLUE}[s]${C_RESET}${bg}";   p2="   Interactive SFTP Shell";                      raw_text="  [s]   Interactive SFTP Shell" ;;
            3) p1="${C_PURPLE}[t]${C_RESET}${bg}"; p2="   Port Tunneling (Local Forward)";              raw_text="  [t]   Port Tunneling (Local Forward)" ;;
            4) p1="${C_RESET}${bg}[w]";            p2="   Wake-on-LAN (${mac_lbl})";                    raw_text="  [w]   Wake-on-LAN (${mac_lbl})" ;;
            5) p1="${C_YELLOW}[k]${C_RESET}${bg}"; p2="   Push SSH Public Key (ssh-copy-id)";           raw_text="  [k]   Push SSH Public Key (ssh-copy-id)" ;;
            6)
                local ag_lbl="Deploy Live Telemetry Agent (Instant Status)"
                [ "${srv_has_agent[$selected_idx]:-0}" -eq 1 ] && ag_lbl="Manage Telemetry Agent (● Active)"
                p1="${C_GREEN}[g]${C_RESET}${bg}"
                p2="   ${ag_lbl}"
                raw_text="  [g]   ${ag_lbl}"
                ;;
            7) p1="${C_CYAN}[e]${C_RESET}${bg}";   p2="   Edit Target Server Profile";                  raw_text="  [e]   Edit Target Server Profile" ;;
            8) p1="${C_RED}[d]${C_RESET}${bg}";    p2="   Delete Target Server Profile";                raw_text="  [d]   Delete Target Server Profile" ;;
        esac

        if [ "$server_count" -eq 0 ]; then
            local pad=$(( RIGHT_INNER_W - ${#raw_text} ))
            [ "$pad" -lt 0 ] && pad=0
            printf "${C_MUTED}%s%*s${C_RESET}" "$raw_text" "$pad" ""
        else
            local pad=$(( RIGHT_INNER_W - ${#raw_text} ))
            [ "$pad" -lt 0 ] && pad=0
            printf "${bg}  %b%b%*s${C_RESET}" "$p1" "$p2" "$pad" ""
        fi
        printf "\e[%d;%dH${C_BORDER}│${C_RESET}" "$row" "$RIGHT_END"
        return
    fi

    local glob_idx=$(( row - ROW_R_GLOB_START ))
    if [ "$glob_idx" -ge 0 ] && [ "$glob_idx" -le 4 ]; then
        local bg=""
        [ "$is_hover" -eq 1 ] && bg="${BG_HOVER}"

        local p1=""
        local p2=""
        local raw_text=""
        local th_short="${THEME_NAMES[$CURRENT_THEME_IDX]%% (*}"

        case "$glob_idx" in
            0) p1="${C_GREEN}[a]${C_RESET}${bg}";  p2="   Add New Server Profile";                      raw_text="  [a]   Add New Server Profile" ;;
            1) p1="${C_PURPLE}[n]${C_RESET}${bg}"; p2="   Scan Local Network (Auto-Discover SSH)";      raw_text="  [n]   Scan Local Network (Auto-Discover SSH)" ;;
            2) p1="${C_YELLOW}[p]${C_RESET}${bg}"; p2="   Border & UI Theme (${th_short})";             raw_text="  [p]   Border & UI Theme (${th_short})" ;;
            3)
                local ref_lbl="${AUTO_REFRESH_SEC}s"
                [ "$AUTO_REFRESH_SEC" -eq 0 ] && ref_lbl="OFF"
                p1="${C_BLUE}[r]${C_RESET}${bg}"
                p2="   Refresh Now  •  ${C_CYAN}[i]${C_RESET}${bg} Auto (${ref_lbl})"
                raw_text="  [r]   Refresh Now  •  [i] Auto (${ref_lbl})"
                ;;
            4) p1="${C_RED}[q]${C_RESET}${bg}";    p2="   Exit SSH Connection Hub";                     raw_text="  [q]   Exit SSH Connection Hub" ;;
        esac

        local pad=$(( RIGHT_INNER_W - ${#raw_text} ))
        [ "$pad" -lt 0 ] && pad=0
        printf "${bg}  %b%b%*s${C_RESET}" "$p1" "$p2" "$pad" ""
        printf "\e[%d;%dH${C_BORDER}│${C_RESET}" "$row" "$RIGHT_END"
        return
    fi

    printf "%*s" "$RIGHT_INNER_W" ""
    printf "\e[%d;%dH${C_BORDER}│${C_RESET}" "$row" "$RIGHT_END"
}

render_right_delete_pane() {
    local row="$1"
    local is_hover="$2"
    local name="$3"
    local ep="$4"

    if [ "$row" -eq "$ROW_R_SEP_1" ]; then
        draw_separator "$row" "$RIGHT_START" "$RIGHT_END"
        return
    fi

    local col_start=$(( RIGHT_START + 1 ))
    printf "\e[%d;%dH" "$row" "$col_start"

    if [ "$row" -eq "$ROW_R_INFO_1" ]; then
        local raw="  ⚠ CONFIRM DELETE: ${name}"
        local pad=$(( RIGHT_INNER_W - ${#raw} ))
        [ "$pad" -lt 0 ] && pad=0
        printf "  ${C_RED}${C_BOLD}⚠ CONFIRM DELETE:${C_RESET} ${C_BOLD}%s${C_RESET}%*s" "$name" "$pad" ""
    elif [ "$row" -eq "$ROW_R_INFO_2" ]; then
        local raw="  Endpoint : ${ep}"
        local pad=$(( RIGHT_INNER_W - ${#raw} ))
        [ "$pad" -lt 0 ] && pad=0
        printf "  ${C_MUTED}Endpoint :${C_RESET} %s%*s" "$ep" "$pad" ""
    elif [ "$row" -eq "$ROW_R_ACT_START" ]; then
        local bg=""
        [ "$is_hover" -eq 1 ] && bg="${BG_HOVER}"
        local p1="${C_RED}[y]${C_RESET}${bg}"
        local p2="   ${C_RED}${C_BOLD}Yes, Permanently Delete Profile${C_RESET}${bg}"
        local raw_text="  [y]   Yes, Permanently Delete Profile"
        local pad=$(( RIGHT_INNER_W - ${#raw_text} ))
        [ "$pad" -lt 0 ] && pad=0
        printf "${bg}  %b%b%*s${C_RESET}" "$p1" "$p2" "$pad" ""
    elif [ "$row" -eq "$(( ROW_R_ACT_START + 1 ))" ]; then
        local bg=""
        [ "$is_hover" -eq 1 ] && bg="${BG_HOVER}"
        local p1="${C_GREEN}[n]${C_RESET}${bg}"
        local p2="   ${C_BOLD}No, Cancel & Keep Server${C_RESET}${bg}"
        local raw_text="  [n]   No, Cancel & Keep Server"
        local pad=$(( RIGHT_INNER_W - ${#raw_text} ))
        [ "$pad" -lt 0 ] && pad=0
        printf "${bg}  %b%b%*s${C_RESET}" "$p1" "$p2" "$pad" ""
    else
        printf "%*s" "$RIGHT_INNER_W" ""
    fi
    printf "\e[%d;%dH${C_BORDER}│${C_RESET}" "$row" "$RIGHT_END"
}

render_right_theme_pane() {
    local row="$1"
    local is_hover="$2"

    if [ "$row" -eq "$ROW_R_SEP_1" ] || [ "$row" -eq "$ROW_R_SEP_2" ]; then
        draw_separator "$row" "$RIGHT_START" "$RIGHT_END"
        return
    fi

    local col_start=$(( RIGHT_START + 1 ))
    printf "\e[%d;%dH" "$row" "$col_start"

    if [ "$row" -eq "$ROW_R_INFO_1" ]; then
        local raw="  ◆ SELECT BORDER & UI COLOR THEME"
        local pad=$(( RIGHT_INNER_W - ${#raw} ))
        [ "$pad" -lt 0 ] && pad=0
        printf "  ${C_HEADER}${C_BOLD}◆ SELECT BORDER & UI COLOR THEME${C_RESET}%*s" "$pad" ""
    elif [ "$row" -eq "$ROW_R_INFO_2" ]; then
        local raw="  Active : ${THEME_NAMES[$CURRENT_THEME_IDX]}"
        local pad=$(( RIGHT_INNER_W - ${#raw} ))
        [ "$pad" -lt 0 ] && pad=0
        printf "  ${C_MUTED}Active :${C_RESET} ${C_BOLD}%s${C_RESET}%*s" "${THEME_NAMES[$CURRENT_THEME_IDX]}" "$pad" ""
    elif [ "$row" -ge "$ROW_R_ACT_START" ] && [ "$row" -le "$(( ROW_R_ACT_START + 7 ))" ]; then
        local t_idx=$(( row - ROW_R_ACT_START ))
        local bg=""
        [ "$is_hover" -eq 1 ] && bg="${BG_HOVER}"

        local t_name="${THEME_NAMES[$t_idx]}"
        local t_col="${THEME_BORDERS[$t_idx]}"
        local mark="   "
        [ "$t_idx" -eq "$CURRENT_THEME_IDX" ] && mark=" ${C_GREEN}${C_BOLD}✓${C_RESET}${bg} "

        local raw_text="   ✓ [${t_idx}]  ● ${t_name}"
        local pad=$(( RIGHT_INNER_W - ${#raw_text} ))
        [ "$pad" -lt 0 ] && pad=0

        printf "${bg}%b${C_CYAN}[%d]${C_RESET}${bg}  %b●${C_RESET}${bg} ${C_BOLD}%s${C_RESET}${bg}%*s${C_RESET}" \
            "$mark" "$((t_idx + 1))" "$t_col" "$t_name" "$pad" ""
    elif [ "$row" -eq "$ROW_R_GLOB_START" ]; then
        local bg=""
        [ "$is_hover" -eq 1 ] && bg="${BG_HOVER}"
        local p1="${C_GREEN}[q/Enter]${C_RESET}${bg}"
        local p2="  ${C_BOLD}Save & Return to Inspector${C_RESET}${bg}"
        local raw_text="  [q/Enter]  Save & Return to Inspector"
        local pad=$(( RIGHT_INNER_W - ${#raw_text} ))
        [ "$pad" -lt 0 ] && pad=0
        printf "${bg}  %b%b%*s${C_RESET}" "$p1" "$p2" "$pad" ""
    else
        printf "%*s" "$RIGHT_INNER_W" ""
    fi
    printf "\e[%d;%dH${C_BORDER}│${C_RESET}" "$row" "$RIGHT_END"
}

render_right_refresh_pane() {
    local row="$1"
    local is_hover="$2"

    if [ "$row" -eq "$ROW_R_SEP_1" ] || [ "$row" -eq "$ROW_R_SEP_2" ]; then
        draw_separator "$row" "$RIGHT_START" "$RIGHT_END"
        return
    fi

    local col_start=$(( RIGHT_START + 1 ))
    printf "\e[%d;%dH" "$row" "$col_start"

    local cur_lbl="${AUTO_REFRESH_SEC} Seconds"
    [ "$AUTO_REFRESH_SEC" -eq 0 ] && cur_lbl="OFF (Manual Only)"

    if [ "$row" -eq "$ROW_R_INFO_1" ]; then
        local raw="  ◆ AUTO-REFRESH TIMER SETTINGS"
        local pad=$(( RIGHT_INNER_W - ${#raw} ))
        [ "$pad" -lt 0 ] && pad=0
        printf "  ${C_HEADER}${C_BOLD}◆ AUTO-REFRESH TIMER SETTINGS${C_RESET}%*s" "$pad" ""
    elif [ "$row" -eq "$ROW_R_INFO_2" ]; then
        local raw="  Current Interval : ${cur_lbl}"
        local pad=$(( RIGHT_INNER_W - ${#raw} ))
        [ "$pad" -lt 0 ] && pad=0
        printf "  ${C_MUTED}Current Interval :${C_RESET} ${C_CYAN}${C_BOLD}%s${C_RESET}%*s" "$cur_lbl" "$pad" ""
    elif [ "$row" -ge "$ROW_R_ACT_START" ] && [ "$row" -le "$(( ROW_R_ACT_START + 5 ))" ]; then
        local opt_idx=$(( row - ROW_R_ACT_START ))
        local bg=""
        [ "$is_hover" -eq 1 ] && bg="${BG_HOVER}"

        local key_lbl=""
        local desc_lbl=""
        local match_val=-1

        case "$opt_idx" in
            0) key_lbl="[1]"; desc_lbl="Every 5 Seconds (Fast)";         match_val=5 ;;
            1) key_lbl="[2]"; desc_lbl="Every 10 Seconds (Default)";     match_val=10 ;;
            2) key_lbl="[3]"; desc_lbl="Every 30 Seconds (Relaxed)";     match_val=30 ;;
            3) key_lbl="[4]"; desc_lbl="Every 60 Seconds (1 Minute)";    match_val=60 ;;
            4) key_lbl="[5]"; desc_lbl="Enter Custom Interval (Sec)..."; match_val=-2 ;;
            5) key_lbl="[0]"; desc_lbl="Turn OFF Auto-Refresh";          match_val=0 ;;
        esac

        local mark="   "
        local act_tag=""
        if [ "$AUTO_REFRESH_SEC" -eq "$match_val" ]; then
            mark=" ${C_GREEN}${C_BOLD}✓${C_RESET}${bg} "
            act_tag=" (Active)"
        elif [ "$opt_idx" -eq 4 ] && [ "$AUTO_REFRESH_SEC" -ne 0 ] && [ "$AUTO_REFRESH_SEC" -ne 5 ] && [ "$AUTO_REFRESH_SEC" -ne 10 ] && [ "$AUTO_REFRESH_SEC" -ne 30 ] && [ "$AUTO_REFRESH_SEC" -ne 60 ]; then
            mark=" ${C_GREEN}${C_BOLD}✓${C_RESET}${bg} "
            act_tag=" (${AUTO_REFRESH_SEC}s Active)"
        fi

        local raw_text="   ✓ ${key_lbl}  ${desc_lbl}${act_tag}"
        local pad=$(( RIGHT_INNER_W - ${#raw_text} ))
        [ "$pad" -lt 0 ] && pad=0

        local k_col="${C_CYAN}"
        [ "$opt_idx" -eq 5 ] && k_col="${C_RED}"

        printf "${bg}%b%b%s${C_RESET}${bg}  ${C_BOLD}%s${C_RESET}${bg}${C_MUTED}%s${C_RESET}${bg}%*s${C_RESET}" \
            "$mark" "$k_col" "$key_lbl" "$desc_lbl" "$act_tag" "$pad" ""
    elif [ "$row" -eq "$ROW_R_GLOB_START" ]; then
        local bg=""
        [ "$is_hover" -eq 1 ] && bg="${BG_HOVER}"
        local p1="${C_GREEN}[q/Enter]${C_RESET}${bg}"
        local p2="  ${C_BOLD}Save & Return to Inspector${C_RESET}${bg}"
        local raw_text="  [q/Enter]  Save & Return to Inspector"
        local pad=$(( RIGHT_INNER_W - ${#raw_text} ))
        [ "$pad" -lt 0 ] && pad=0
        printf "${bg}  %b%b%*s${C_RESET}" "$p1" "$p2" "$pad" ""
    else
        printf "%*s" "$RIGHT_INNER_W" ""
    fi
    printf "\e[%d;%dH${C_BORDER}│${C_RESET}" "$row" "$RIGHT_END"
}

render_right_agent_pane() {
    local row="$1"
    local is_hover="$2"
    local my_ip="$3"
    local has_ag="${srv_has_agent[$selected_idx]:-0}"

    if [ "$row" -eq "$ROW_R_SEP_1" ]; then
        draw_separator "$row" "$RIGHT_START" "$RIGHT_END"
        return
    fi

    local col_start=$(( RIGHT_START + 1 ))
    printf "\e[%d;%dH" "$row" "$col_start"

    if [ "$row" -eq "$ROW_R_INFO_1" ]; then
        local st_txt="Not Installed"
        local st_col="${C_MUTED}"
        if [ "$has_ag" -eq 1 ]; then
            st_txt="● Active"
            st_col="${C_PURPLE}"
        fi
        local raw="  ◆ TELEMETRY AGENT (${st_txt})"
        local pad=$(( RIGHT_INNER_W - ${#raw} ))
        [ "$pad" -lt 0 ] && pad=0
        printf "  ${C_HEADER}${C_BOLD}◆ TELEMETRY AGENT${C_RESET} (%b%s${C_RESET})%*s" "$st_col" "$st_txt" "$pad" ""
    elif [ "$row" -eq "$ROW_R_INFO_2" ]; then
        local raw="  Hub Receiver : ${my_ip}:${TELEM_PORT} (UDP)"
        local pad=$(( RIGHT_INNER_W - ${#raw} ))
        [ "$pad" -lt 0 ] && pad=0
        printf "  ${C_MUTED}Hub Receiver :${C_RESET} ${C_CYAN}${C_BOLD}%s:%s${C_RESET} ${C_MUTED}(UDP)${C_RESET}%*s" "$my_ip" "$TELEM_PORT" "$pad" ""
    elif [ "$row" -eq "$ROW_R_INFO_3" ]; then
        local raw="  Pushes live CPU, RAM, Uptime & instant status"
        local pad=$(( RIGHT_INNER_W - ${#raw} ))
        [ "$pad" -lt 0 ] && pad=0
        printf "  ${C_MUTED}Pushes live CPU, RAM, Uptime & instant status%*s${C_RESET}" "$pad" ""
    elif [ "$row" -eq "$ROW_R_ACT_START" ]; then
        local bg=""
        [ "$is_hover" -eq 1 ] && bg="${BG_HOVER}"
        local p1="${C_GREEN}[1/Enter]${C_RESET}${bg}"
        local p2="  ${C_BOLD}Deploy / Update Agent via SSH${C_RESET}${bg}"
        local raw_text="  [1/Enter]  Deploy / Update Agent via SSH"
        local pad=$(( RIGHT_INNER_W - ${#raw_text} ))
        [ "$pad" -lt 0 ] && pad=0
        printf "${bg}  %b%b%*s${C_RESET}" "$p1" "$p2" "$pad" ""
    elif [ "$row" -eq "$(( ROW_R_ACT_START + 1 ))" ]; then
        local bg=""
        [ "$is_hover" -eq 1 ] && bg="${BG_HOVER}"
        local p1="${C_YELLOW}[c]${C_RESET}${bg}"
        local p2="        Deploy with Custom Receiver IP..."
        local raw_text="  [c]        Deploy with Custom Receiver IP..."
        local pad=$(( RIGHT_INNER_W - ${#raw_text} ))
        [ "$pad" -lt 0 ] && pad=0
        printf "${bg}  %b%b%*s${C_RESET}" "$p1" "$p2" "$pad" ""
    elif [ "$row" -eq "$(( ROW_R_ACT_START + 2 ))" ]; then
        local bg=""
        [ "$is_hover" -eq 1 ] && bg="${BG_HOVER}"
        local p1="${C_RED}[2/x]${C_RESET}${bg}"
        local p2="      Remove Agent from Target Server"
        local raw_text="  [2/x]      Remove Agent from Target Server"
        local pad=$(( RIGHT_INNER_W - ${#raw_text} ))
        [ "$pad" -lt 0 ] && pad=0
        printf "${bg}  %b%b%*s${C_RESET}" "$p1" "$p2" "$pad" ""
    elif [ "$row" -eq "$(( ROW_R_ACT_START + 3 ))" ]; then
        local bg=""
        [ "$is_hover" -eq 1 ] && bg="${BG_HOVER}"
        local p1="${C_MUTED}[q]${C_RESET}${bg}"
        local p2="        Cancel & Return to Inspector"
        local raw_text="  [q]        Cancel & Return to Inspector"
        local pad=$(( RIGHT_INNER_W - ${#raw_text} ))
        [ "$pad" -lt 0 ] && pad=0
        printf "${bg}  %b%b%*s${C_RESET}" "$p1" "$p2" "$pad" ""
    else
        printf "%*s" "$RIGHT_INNER_W" ""
    fi
    printf "\e[%d;%dH${C_BORDER}│${C_RESET}" "$row" "$RIGHT_END"
}

prompt_in_dialog() {
    local msg="$1"
    local r=$(( ROW_DIALOG_TOP + 1 ))
    local inner=$(( TOTAL_W - 4 ))
    printf "\e[%d;3H%*s" "$r" "$inner" ""
    printf "\e[%d;3H${C_CYAN}${C_BOLD}%s${C_RESET}" "$r" "${msg:0:$inner}"
}

temp_message() {
    local msg="$1"
    prompt_in_dialog "$msg"
    sleep 1.2
}
