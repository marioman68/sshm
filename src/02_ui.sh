# ==============================================================================
# MODULE 02: UI & Rendering Engine (Server-First Inspector)
# ==============================================================================

calc_geometry() {
    TERM_COLS=$(tput cols)
    TERM_LINES=$(tput lines)

    # Auto-detect Phone / Termux Portrait or Narrow Window (< 88 cols)
    if [ "$TERM_COLS" -lt 88 ] || { [ -n "${TERMUX_VERSION:-}" ] && [ "$TERM_COLS" -lt 100 ]; }; then
        IS_MOBILE=1
        [ "$TERM_COLS" -lt 38 ] && TERM_COLS=38

        TOTAL_W=$TERM_COLS
        LEFT_START=1
        LEFT_END=$TOTAL_W
        RIGHT_START=1
        RIGHT_END=$TOTAL_W

        LEFT_INNER_W=$(( LEFT_END - LEFT_START - 1 ))
        RIGHT_INNER_W=$(( RIGHT_END - RIGHT_START - 1 ))

        ROW_TOP=1
        ROW_TWIN_TOP=4
        ROW_TWIN_START=5

        # Dynamic height for server list on mobile (fits 4 to 8 rows cleanly)
        local list_rows=$(( server_count > 4 ? server_count : 4 ))
        [ "$list_rows" -gt 7 ] && list_rows=7

        ROW_LEGEND_SEP=$(( ROW_TWIN_START + list_rows ))
        ROW_LEGEND_TEXT_1=$(( ROW_LEGEND_SEP + 1 ))
        ROW_LEGEND_TEXT_2=$(( ROW_LEGEND_SEP + 1 ))
        ROW_LEFT_BOTTOM=$(( ROW_LEGEND_TEXT_1 + 1 ))

        # Stack Right Pane (Inspector) directly below Left Pane!
        ROW_RIGHT_TOP=$(( ROW_LEFT_BOTTOM + 1 ))
        ROW_R_INFO_1=$(( ROW_RIGHT_TOP + 1 ))
        ROW_R_INFO_2=$(( ROW_RIGHT_TOP + 2 ))
        ROW_R_SEP_1=$(( ROW_RIGHT_TOP + 3 ))
        ROW_R_ACT_START=$(( ROW_RIGHT_TOP + 4 ))
        ROW_R_ACT_END=$(( ROW_R_ACT_START + 7 ))
        ROW_R_SEP_2=$(( ROW_R_ACT_END + 1 ))
        ROW_R_GLOB_START=$(( ROW_R_SEP_2 + 1 ))
        ROW_R_GLOB_END=$(( ROW_R_GLOB_START + 4 ))
        ROW_TWIN_END=$ROW_R_GLOB_END
        ROW_TWIN_BOTTOM=$(( ROW_TWIN_END + 1 ))

        ROW_PROMPT_TOP=$(( ROW_TWIN_BOTTOM + 1 ))
        ROW_PROMPT_INPUT=$(( ROW_PROMPT_TOP + 1 ))
        ROW_PROMPT_BOTTOM=$(( ROW_PROMPT_INPUT + 1 ))
    else
        IS_MOBILE=0
        [ "$TERM_COLS" -lt 95 ] && TERM_COLS=95
        [ "$TERM_LINES" -lt 27 ] && TERM_LINES=27

        TOTAL_W=$(( TERM_COLS - 2 ))
        LEFT_START=1
        LEFT_END=$(( TOTAL_W / 2 ))
        RIGHT_START=$(( LEFT_END + 2 ))
        RIGHT_END=$TOTAL_W

        LEFT_INNER_W=$(( LEFT_END - LEFT_START - 1 ))
        RIGHT_INNER_W=$(( RIGHT_END - RIGHT_START - 1 ))

        CONTENT_H=$(( TERM_LINES - 9 ))
        [ "$CONTENT_H" -lt 17 ] && CONTENT_H=17

        ROW_TOP=1
        ROW_TWIN_TOP=4
        ROW_TWIN_START=5
        ROW_TWIN_END=$(( ROW_TWIN_START + CONTENT_H - 1 ))
        ROW_TWIN_BOTTOM=$(( ROW_TWIN_END + 1 ))
        ROW_LEFT_BOTTOM=$ROW_TWIN_BOTTOM
        ROW_RIGHT_TOP=$ROW_TWIN_TOP

        ROW_LEGEND_SEP=$(( ROW_TWIN_BOTTOM - 3 ))
        ROW_LEGEND_TEXT_1=$(( ROW_TWIN_BOTTOM - 2 ))
        ROW_LEGEND_TEXT_2=$(( ROW_TWIN_BOTTOM - 1 ))

        ROW_R_INFO_1=$ROW_TWIN_START
        ROW_R_INFO_2=$(( ROW_TWIN_START + 1 ))
        ROW_R_SEP_1=$(( ROW_TWIN_START + 2 ))
        ROW_R_ACT_START=$(( ROW_TWIN_START + 3 ))
        ROW_R_ACT_END=$(( ROW_R_ACT_START + 7 ))
        ROW_R_SEP_2=$(( ROW_R_ACT_END + 1 ))
        ROW_R_GLOB_START=$(( ROW_R_SEP_2 + 1 ))
        ROW_R_GLOB_END=$(( ROW_R_GLOB_START + 4 ))

        ROW_PROMPT_TOP=$(( ROW_TWIN_BOTTOM + 1 ))
        ROW_PROMPT_INPUT=$(( ROW_PROMPT_TOP + 1 ))
        ROW_PROMPT_BOTTOM=$(( ROW_PROMPT_INPUT + 1 ))
    fi
}

draw_box() {
    local rs="$1"
    local re="$2"
    local cs="$3"
    local ce="$4"
    local width=$(( ce - cs - 1 ))
    local hline
    hline=$(repeat_char "─" "$width")

    printf "\e[%d;%dH${C_BORDER}╭%s╮${C_RESET}" "$rs" "$cs" "$hline"
    for ((r=rs+1; r<re; r++)); do
        printf "\e[%d;%dH${C_BORDER}│\e[%d;%dH│${C_RESET}" "$r" "$cs" "$r" "$ce"
    done
    printf "\e[%d;%dH${C_BORDER}╰%s╯${C_RESET}" "$re" "$cs" "$hline"
}

draw_separator() {
    local row="$1"
    local cs="$2"
    local ce="$3"
    local width=$(( ce - cs - 1 ))
    local hline
    hline=$(repeat_char "─" "$width")
    printf "\e[%d;%dH${C_BORDER}├%s┤${C_RESET}" "$row" "$cs" "$hline"
}

draw_pane_titles() {
    local l_title=" REMOTE NODES (${server_count}) "
    printf "\e[%d;%dH${C_HEADER}${C_BOLD}%s${C_RESET}" "$ROW_TWIN_TOP" "$(( LEFT_START + 2 ))" "$l_title"

    local r_hline
    r_hline=$(repeat_char "─" "$RIGHT_INNER_W")
    printf "\e[%d;%dH${C_BORDER}╭%s╮${C_RESET}" "$ROW_RIGHT_TOP" "$RIGHT_START" "$r_hline"

    local r_title=" NO TARGET SELECTED "
    if [ "$server_count" -gt 0 ] && [ "$selected_idx" -ge 0 ] && [ "$selected_idx" -lt "$server_count" ]; then
        local t_name="${srv_names[$selected_idx]}"
        local t_tag="${srv_tags[$selected_idx]}"
        [ -n "$t_tag" ] && t_name="${t_name} [${t_tag}]"
        local max_t=$(( RIGHT_INNER_W - 14 ))
        [ "$max_t" -lt 8 ] && max_t=8
        [ ${#t_name} -gt "$max_t" ] && t_name="${t_name:0:$((max_t - 1))}…"
        r_title=" TARGET: ${t_name} "
    fi
    printf "\e[%d;%dH${C_CYAN}${C_BOLD}%s${C_RESET}" "$ROW_RIGHT_TOP" "$(( RIGHT_START + 2 ))" "$r_title"
}

draw_wireframe() {
    clear
    calc_geometry

    draw_box "$ROW_TOP" "$((ROW_TOP + 2))" 1 "$TOTAL_W"
    draw_box "$ROW_TWIN_TOP" "$ROW_LEFT_BOTTOM" "$LEFT_START" "$LEFT_END"
    draw_box "$ROW_RIGHT_TOP" "$ROW_TWIN_BOTTOM" "$RIGHT_START" "$RIGHT_END"
    draw_box "$ROW_PROMPT_TOP" "$ROW_PROMPT_BOTTOM" 1 "$TOTAL_W"

    draw_separator "$ROW_LEGEND_SEP" "$LEFT_START" "$LEFT_END"
    draw_separator "$ROW_R_SEP_1" "$RIGHT_START" "$RIGHT_END"
    draw_separator "$ROW_R_SEP_2" "$RIGHT_START" "$RIGHT_END"
}

draw_left_legend() {
    if [ "$IS_MOBILE" -eq 1 ]; then
        printf "\e[%d;%dH ${C_GREEN}●${C_RESET}On ${C_RED}○${C_RESET}Off ${C_BLUE}◆${C_RESET}/${C_MUTED}◇${C_RESET}Mnt • Tap:Target 2x:SSH" "$ROW_LEGEND_TEXT_1" "$(( LEFT_START + 1 ))"
    else
        printf "\e[%d;%dH  ${C_GREEN}●${C_RESET} Online  ${C_RED}○${C_RESET} Offline  ${C_BLUE}◆${C_RESET} /${C_MUTED}◇${C_RESET} Click Mount" "$ROW_LEGEND_TEXT_1" "$(( LEFT_START + 1 ))"
        printf "\e[%d;%dH  Click server to target  •  2x-Click SSH  •  [f] Filter" "$ROW_LEGEND_TEXT_2" "$(( LEFT_START + 1 ))"
    fi
}

temp_message() {
    prompt_in_dialog "$1"
    ( sleep 1.4 ) &
    local pid=$!
    local garbage
    while kill -0 $pid 2>/dev/null; do
        read -t 0.1 -rsn1 garbage
    done
}

prompt_in_dialog() {
    local prompt_str="$1"
    local max_plen=$(( TOTAL_W - 5 ))
    [ "$max_plen" -lt 10 ] && max_plen=10
    if [ ${#prompt_str} -gt "$max_plen" ]; then
        prompt_str="${prompt_str:0:$((max_plen - 1))}…"
    fi
    local prompt_len=${#prompt_str}
    local input_col=$(( 3 + prompt_len ))

    printf "\e[%d;2H%*s" "$ROW_PROMPT_INPUT" "$(( TOTAL_W - 2 ))" ""
    printf "\e[%d;%dH${C_BORDER}│${C_RESET}" "$ROW_PROMPT_INPUT" "$TOTAL_W"
    printf "\e[%d;3H%s\e[%d;%dH" "$ROW_PROMPT_INPUT" "$prompt_str" "$ROW_PROMPT_INPUT" "$input_col"
}

render_left_pane() {
    local row="$1"
    local hover_mode="$2"
    local idx=$(( row - ROW_TWIN_START ))

    local bg=""
    local m_bg=""
    if [ "$idx" -ge 0 ] && [ "$idx" -lt "$server_count" ]; then
        if [ "$hover_mode" -eq 1 ]; then
            bg="${BG_HOVER}"
            m_bg="${BG_HOVER}"
        elif [ "$hover_mode" -eq 2 ]; then
            bg="${BG_HOVER}"
            m_bg="${BG_MNT_HOVER}"
        elif [ "$idx" -eq "$selected_idx" ]; then
            bg="${BG_SELECTED}"
            m_bg="${BG_SELECTED}"
        fi
    fi

    printf "\e[%d;%dH" "$row" "$(( LEFT_START + 1 ))"
    if [ "$idx" -ge 0 ] && [ "$idx" -lt "$server_count" ]; then
        local num=$(( idx + 1 ))
        local name="${srv_names[$idx]}"
        local tag="${srv_tags[$idx]}"
        local st="${srv_online[$idx]}"
        local lat="${srv_latencies[$idx]}"
        local mnt="${srv_mounted[$idx]}"

        local sel_ptr=" "
        local name_color="${C_BOLD}"
        if [ "$idx" -eq "$selected_idx" ]; then
            sel_ptr="${C_CYAN}${C_BOLD}▸${C_RESET}${bg}"
            name_color="${C_CYAN}${C_BOLD}"
        fi

        local s_icon="${C_RED}○${C_RESET}${bg}"
        local lat_str
        lat_str=$(printf "${C_MUTED}%6s${C_RESET}${bg}" "--")
        if [ "$st" == "ONLINE" ]; then
            s_icon="${C_GREEN}●${C_RESET}${bg}"
            lat_str=$(printf "${C_CYAN}%6s${C_RESET}${bg}" "$lat")
        fi

        local m_icon="${m_bg} ${C_MUTED}◇${C_RESET}${m_bg} ${C_RESET}${bg}"
        if [ "$mnt" -eq 1 ]; then
            m_icon="${m_bg} ${C_BLUE}◆${C_RESET}${m_bg} ${C_RESET}${bg}"
        fi

        local disp_name="$name"
        [ -n "$tag" ] && disp_name="$name [$tag]"

        local avail=$(( LEFT_INNER_W - 23 ))
        [ "$avail" -lt 10 ] && avail=10
        [ ${#disp_name} -gt "$avail" ] && disp_name="${disp_name:0:$((avail - 1))}…"

        local fill_w=$(( LEFT_INNER_W - 22 - ${#disp_name} ))
        [ "$fill_w" -lt 0 ] && fill_w=0

        printf "${bg} %b %b%b${C_GREEN}[%2d]${C_RESET}${bg}  %b%s${C_RESET}${bg}%*s%b ${C_RESET}" \
            "$sel_ptr" "$s_icon" "$m_icon" "$num" "$name_color" "$disp_name" "$fill_w" "" "$lat_str"
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

    # 1. Target Info Card
    if [ "$row" -eq "$ROW_R_INFO_1" ]; then
        if [ "$server_count" -gt 0 ] && [ "$selected_idx" -ge 0 ] && [ "$selected_idx" -lt "$server_count" ]; then
            local ep="${srv_users[$selected_idx]}@${srv_hosts[$selected_idx]}:${srv_ports[$selected_idx]}"
            local raw="  Endpoint : $ep"
            local pad=$(( RIGHT_INNER_W - ${#raw} ))
            [ "$pad" -lt 0 ] && pad=0
            printf "  ${C_MUTED}Endpoint :${C_RESET} ${C_BOLD}%s${C_RESET}%*s" "$ep" "$pad" ""
        else
            local raw="  No server profiles available."
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
                st_plain="ONLINE ($lat)"
                st_col="${C_GREEN}● ONLINE (${lat})${C_RESET}"
            fi

            local mnt_plain="Unmounted"
            local mnt_col="${C_MUTED}◇ Unmounted${C_RESET}"
            if [ "$mnt" -eq 1 ]; then
                mnt_plain="Mounted"
                mnt_col="${C_BLUE}◆ Mounted${C_RESET}"
            fi

            local raw="  Status   : ● $st_plain   •   ◇ $mnt_plain"
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
    fi

    # 2. Target-Specific Actions
    if [ "$row" -ge "$ROW_R_ACT_START" ] && [ "$row" -le "$ROW_R_ACT_END" ]; then
        local act_idx=$(( row - ROW_R_ACT_START ))
        local bg=""
        [ "$is_hover" -eq 1 ] && [ "$server_count" -gt 0 ] && bg="${BG_HOVER}"

        local mac_hint="No MAC saved"
        if [ "$server_count" -gt 0 ] && [ -n "${srv_macs[$selected_idx]}" ]; then
            mac_hint="${srv_macs[$selected_idx]}"
        fi

        local p1=""
        local p2=""
        local raw_text=""

        case "$act_idx" in
            0) p1="${C_GREEN}[c]${C_RESET}${bg}";  p2="   ${C_BOLD}Connect via SSH${C_RESET}${bg} (Auto-tmux)";   raw_text="  [c]   Connect via SSH (Auto-tmux)" ;;
            1) p1="${C_CYAN}[b]${C_RESET}${bg}";   p2="   Open Network Folder in File Manager";             raw_text="  [b]   Open Network Folder in File Manager" ;;
            2) p1="${C_BLUE}[s]${C_RESET}${bg}";   p2="   Interactive SFTP Shell";                          raw_text="  [s]   Interactive SFTP Shell" ;;
            3) p1="${C_PURPLE}[t]${C_RESET}${bg}"; p2="   Port Tunneling (Local Forward)";                  raw_text="  [t]   Port Tunneling (Local Forward)" ;;
            4) p1="${C_ORANGE}[w]${C_RESET}${bg}"; p2="   Wake-on-LAN (${mac_hint})";                       raw_text="  [w]   Wake-on-LAN (${mac_hint})" ;;
            5) p1="${C_YELLOW}[k]${C_RESET}${bg}"; p2="   Push SSH Public Key (ssh-copy-id)";               raw_text="  [k]   Push SSH Public Key (ssh-copy-id)" ;;
            6) p1="${C_CYAN}[e]${C_RESET}${bg}";   p2="   Edit Target Server Profile";                      raw_text="  [e]   Edit Target Server Profile" ;;
            7) p1="${C_RED}[d]${C_RESET}${bg}";    p2="   Delete Target Server Profile";                    raw_text="  [d]   Delete Target Server Profile" ;;
        esac

        if [ "$IS_MOBILE" -eq 1 ] && [ ${#raw_text} -gt "$RIGHT_INNER_W" ]; then
            local trim_len=$(( RIGHT_INNER_W - 8 ))
            [ "$trim_len" -lt 10 ] && trim_len=10
            local clean_p2="${raw_text:5:$trim_len}…"
            raw_text="  [x]${clean_p2}"
            p2="${clean_p2}"
        fi
        local pad=$(( RIGHT_INNER_W - ${#raw_text} ))
        [ "$pad" -lt 0 ] && pad=0
        printf "${bg}  %b%b%*s${C_RESET}" "$p1" "$p2" "$pad" ""
        printf "\e[%d;%dH${C_BORDER}│${C_RESET}" "$row" "$RIGHT_END"
        return
    fi

    # 3. Global Hub Actions (Includes [n] Scan & [p] Theme Picker!)
    local glob_idx=$(( row - ROW_R_GLOB_START ))
    if [ "$glob_idx" -ge 0 ] && [ "$glob_idx" -le 4 ]; then
        local bg=""
        [ "$is_hover" -eq 1 ] && bg="${BG_HOVER}"
        local p1=""
        local p2=""
        local raw_text=""
        local cur_t_short="${THEME_NAMES[$CURRENT_THEME_IDX]%% (*}"

        case "$glob_idx" in
            0) p1="${C_GREEN}[a]${C_RESET}${bg}";  p2="   Add New Server Profile";                  raw_text="  [a]   Add New Server Profile" ;;
            1) p1="${C_PURPLE}[n]${C_RESET}${bg}"; p2="   Scan Local Network (Auto-Discover SSH)";  raw_text="  [n]   Scan Local Network (Auto-Discover SSH)" ;;
            2) p1="${C_YELLOW}[p]${C_RESET}${bg}"; p2="   Border & UI Theme (${cur_t_short})";      raw_text="  [p]   Border & UI Theme (${cur_t_short})" ;;
            3)
                local ref_lbl="${AUTO_REFRESH_SEC}s"
                [ "$AUTO_REFRESH_SEC" -eq 0 ] && ref_lbl="OFF"
                p1="${C_BLUE}[r]${C_RESET}${bg}"
                p2="   Refresh Now  •  ${C_CYAN}[i]${C_RESET}${bg} Auto (${ref_lbl})"
                raw_text="  [r]   Refresh Now  •  [i] Auto (${ref_lbl})"
                ;;
            4) p1="${C_RED}[q]${C_RESET}${bg}";    p2="   Exit SSH Connection Hub";                 raw_text="  [q]   Exit SSH Connection Hub" ;;
        esac

        if [ "$IS_MOBILE" -eq 1 ] && [ ${#raw_text} -gt "$RIGHT_INNER_W" ]; then
            local trim_len=$(( RIGHT_INNER_W - 8 ))
            [ "$trim_len" -lt 10 ] && trim_len=10
            local clean_p2="${raw_text:5:$trim_len}…"
            raw_text="  [x]${clean_p2}"
            p2="${clean_p2}"
        fi
        local pad=$(( RIGHT_INNER_W - ${#raw_text} ))
        [ "$pad" -lt 0 ] && pad=0
        printf "${bg}  %b%b%*s${C_RESET}" "$p1" "$p2" "$pad" ""
        printf "\e[%d;%dH${C_BORDER}│${C_RESET}" "$row" "$RIGHT_END"
        return
    fi

    printf "%*s" "$RIGHT_INNER_W" ""
    printf "\e[%d;%dH${C_BORDER}│${C_RESET}" "$row" "$RIGHT_END"
}

render_right_cancel_pane() {
    local row="$1"
    local is_hover="$2"
    local target_name="${srv_names[$selected_idx]}"

    if [ "$row" -eq "$ROW_R_SEP_1" ]; then
        draw_separator "$row" "$RIGHT_START" "$RIGHT_END"
        return
    fi

    local col_start=$(( RIGHT_START + 1 ))
    printf "\e[%d;%dH" "$row" "$col_start"

    if [ "$row" -eq "$ROW_R_INFO_1" ]; then
        local raw="  ! CONFIRM DELETION"
        local pad=$(( RIGHT_INNER_W - ${#raw} ))
        [ "$pad" -lt 0 ] && pad=0
        printf "  ${C_RED}${C_BOLD}! CONFIRM DELETION${C_RESET}%*s" "$pad" ""
    elif [ "$row" -eq "$ROW_R_INFO_2" ]; then
        local raw="  Remove '${target_name}' from your hub?"
        local pad=$(( RIGHT_INNER_W - ${#raw} ))
        [ "$pad" -lt 0 ] && pad=0
        printf "  ${C_MUTED}Remove '${C_RESET}${C_BOLD}%s${C_RESET}${C_MUTED}' from your hub?${C_RESET}%*s" "$target_name" "$pad" ""
    elif [ "$row" -eq "$ROW_R_ACT_START" ]; then
        local bg=""
        [ "$is_hover" -eq 1 ] && bg="${BG_HOVER}"
        local p1="${C_RED}[y]${C_RESET}${bg}"
        local p2="   ${C_BOLD}Yes, Delete Target Server${C_RESET}${bg}"
        local raw_text="  [y]   Yes, Delete Target Server"
        if [ "$IS_MOBILE" -eq 1 ] && [ ${#raw_text} -gt "$RIGHT_INNER_W" ]; then
            local trim_len=$(( RIGHT_INNER_W - 8 ))
            [ "$trim_len" -lt 10 ] && trim_len=10
            local clean_p2="${raw_text:5:$trim_len}…"
            raw_text="  [x]${clean_p2}"
            p2="${clean_p2}"
        fi
        local pad=$(( RIGHT_INNER_W - ${#raw_text} ))
        [ "$pad" -lt 0 ] && pad=0
        printf "${bg}  %b%b%*s${C_RESET}" "$p1" "$p2" "$pad" ""
    elif [ "$row" -eq "$(( ROW_R_ACT_START + 1 ))" ]; then
        local bg=""
        [ "$is_hover" -eq 1 ] && bg="${BG_HOVER}"
        local p1="${C_GREEN}[q]${C_RESET}${bg}"
        local p2="   ${C_BOLD}No, Cancel & Keep Server${C_RESET}${bg}"
        local raw_text="  [q]   No, Cancel & Keep Server"
        if [ "$IS_MOBILE" -eq 1 ] && [ ${#raw_text} -gt "$RIGHT_INNER_W" ]; then
            local trim_len=$(( RIGHT_INNER_W - 8 ))
            [ "$trim_len" -lt 10 ] && trim_len=10
            local clean_p2="${raw_text:5:$trim_len}…"
            raw_text="  [x]${clean_p2}"
            p2="${clean_p2}"
        fi
        local pad=$(( RIGHT_INNER_W - ${#raw_text} ))
        [ "$pad" -lt 0 ] && pad=0
        printf "${bg}  %b%b%*s${C_RESET}" "$p1" "$p2" "$pad" ""
    else
        printf "%*s" "$RIGHT_INNER_W" ""
    fi
    printf "\e[%d;%dH${C_BORDER}│${C_RESET}" "$row" "$RIGHT_END"
}


render_right_scan_pane() {
    local row="$1"
    local is_hover="$2"
    local def_sub="$3"

    if [ "$row" -eq "$ROW_R_SEP_1" ]; then
        draw_separator "$row" "$RIGHT_START" "$RIGHT_END"
        return
    fi

    local col_start=$(( RIGHT_START + 1 ))
    printf "\e[%d;%dH" "$row" "$col_start"

    if [ "$row" -eq "$ROW_R_INFO_1" ]; then
        local raw="  ◆ LOCAL NETWORK SSH SCANNER"
        local pad=$(( RIGHT_INNER_W - ${#raw} ))
        [ "$pad" -lt 0 ] && pad=0
        printf "  ${C_PURPLE}${C_BOLD}◆ LOCAL NETWORK SSH SCANNER${C_RESET}%*s" "$pad" ""
    elif [ "$row" -eq "$ROW_R_INFO_2" ]; then
        local raw="  Active Subnet : ${def_sub}.0/24"
        local pad=$(( RIGHT_INNER_W - ${#raw} ))
        [ "$pad" -lt 0 ] && pad=0
        printf "  ${C_MUTED}Active Subnet :${C_RESET} ${C_CYAN}${C_BOLD}%s.0/24${C_RESET}%*s" "$def_sub" "$pad" ""
    elif [ "$row" -eq "$ROW_R_ACT_START" ]; then
        local bg=""
        [ "$is_hover" -eq 1 ] && bg="${BG_HOVER}"
        local p1="${C_GREEN}[Enter]${C_RESET}${bg}"
        local p2="  ${C_BOLD}Scan Active Subnet (${def_sub}.0/24)${C_RESET}${bg}"
        local raw_text="  [Enter]  Scan Active Subnet (${def_sub}.0/24)"
        if [ "$IS_MOBILE" -eq 1 ] && [ ${#raw_text} -gt "$RIGHT_INNER_W" ]; then
            local trim_len=$(( RIGHT_INNER_W - 8 ))
            [ "$trim_len" -lt 10 ] && trim_len=10
            local clean_p2="${raw_text:5:$trim_len}…"
            raw_text="  [x]${clean_p2}"
            p2="${clean_p2}"
        fi
        local pad=$(( RIGHT_INNER_W - ${#raw_text} ))
        [ "$pad" -lt 0 ] && pad=0
        printf "${bg}  %b%b%*s${C_RESET}" "$p1" "$p2" "$pad" ""
    elif [ "$row" -eq "$(( ROW_R_ACT_START + 1 ))" ]; then
        local bg=""
        [ "$is_hover" -eq 1 ] && bg="${BG_HOVER}"
        local p1="${C_CYAN}[c]${C_RESET}${bg}"
        local p2="      Enter Custom Subnet Prefix..."
        local raw_text="  [c]      Enter Custom Subnet Prefix..."
        if [ "$IS_MOBILE" -eq 1 ] && [ ${#raw_text} -gt "$RIGHT_INNER_W" ]; then
            local trim_len=$(( RIGHT_INNER_W - 8 ))
            [ "$trim_len" -lt 10 ] && trim_len=10
            local clean_p2="${raw_text:5:$trim_len}…"
            raw_text="  [x]${clean_p2}"
            p2="${clean_p2}"
        fi
        local pad=$(( RIGHT_INNER_W - ${#raw_text} ))
        [ "$pad" -lt 0 ] && pad=0
        printf "${bg}  %b%b%*s${C_RESET}" "$p1" "$p2" "$pad" ""
    elif [ "$row" -eq "$(( ROW_R_ACT_START + 2 ))" ]; then
        local bg=""
        [ "$is_hover" -eq 1 ] && bg="${BG_HOVER}"
        local p1="${C_RED}[q]${C_RESET}${bg}"
        local p2="      Cancel & Return to Hub"
        local raw_text="  [q]      Cancel & Return to Hub"
        if [ "$IS_MOBILE" -eq 1 ] && [ ${#raw_text} -gt "$RIGHT_INNER_W" ]; then
            local trim_len=$(( RIGHT_INNER_W - 8 ))
            [ "$trim_len" -lt 10 ] && trim_len=10
            local clean_p2="${raw_text:5:$trim_len}…"
            raw_text="  [x]${clean_p2}"
            p2="${clean_p2}"
        fi
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
        local raw="  ◆ BORDER & UI THEME PICKER"
        local pad=$(( RIGHT_INNER_W - ${#raw} ))
        [ "$pad" -lt 0 ] && pad=0
        printf "  ${C_HEADER}${C_BOLD}◆ BORDER & UI THEME PICKER${C_RESET}%*s" "$pad" ""
    elif [ "$row" -eq "$ROW_R_INFO_2" ]; then
        local raw="  Click or press [1-8] for live preview:"
        local pad=$(( RIGHT_INNER_W - ${#raw} ))
        [ "$pad" -lt 0 ] && pad=0
        printf "  ${C_MUTED}Click or press [1-8] for live preview:${C_RESET}%*s" "$pad" ""
    elif [ "$row" -ge "$ROW_R_ACT_START" ] && [ "$row" -le "$ROW_R_ACT_END" ]; then
        local t_idx=$(( row - ROW_R_ACT_START ))
        local bg=""
        [ "$is_hover" -eq 1 ] && bg="${BG_HOVER}"

        local t_name="${THEME_NAMES[$t_idx]}"
        local t_col="${THEME_BORDERS[$t_idx]}"
        local num=$(( t_idx + 1 ))

        local mark="   "
        local active_str=""
        if [ "$t_idx" -eq "$CURRENT_THEME_IDX" ]; then
            mark=" ${C_GREEN}${C_BOLD}✓${C_RESET}${bg} "
            active_str=" (Active)"
        fi

        local raw_text="   ✓ [${num}]  ━━  ${t_name}${active_str}"
        local pad=$(( RIGHT_INNER_W - ${#raw_text} ))
        [ "$pad" -lt 0 ] && pad=0

        printf "${bg}%b${C_CYAN}[%d]${C_RESET}${bg}  %b━━${C_RESET}${bg}  ${C_BOLD}%s${C_RESET}${bg}${C_MUTED}%s${C_RESET}${bg}%*s${C_RESET}" \
            "$mark" "$num" "$t_col" "$t_name" "$active_str" "$pad" ""
    elif [ "$row" -eq "$ROW_R_GLOB_START" ]; then
        local bg=""
        [ "$is_hover" -eq 1 ] && bg="${BG_HOVER}"
        local p1="${C_GREEN}[q/Enter]${C_RESET}${bg}"
        local p2="  ${C_BOLD}Save & Return to Inspector${C_RESET}${bg}"
        local raw_text="  [q/Enter]  Save & Return to Inspector"
        if [ "$IS_MOBILE" -eq 1 ] && [ ${#raw_text} -gt "$RIGHT_INNER_W" ]; then
            local trim_len=$(( RIGHT_INNER_W - 8 ))
            [ "$trim_len" -lt 10 ] && trim_len=10
            local clean_p2="${raw_text:5:$trim_len}…"
            raw_text="  [x]${clean_p2}"
            p2="${clean_p2}"
        fi
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
