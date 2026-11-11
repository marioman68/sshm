# ==============================================================================
# MODULE 02: UI & Rendering Engine
# ==============================================================================

calc_geometry() {
    TERM_COLS=$(tput cols)
    TERM_LINES=$(tput lines)

    [ "$TERM_COLS" -lt 95 ] && TERM_COLS=95
    [ "$TERM_LINES" -lt 24 ] && TERM_LINES=24

    TOTAL_W=$(( TERM_COLS - 2 ))
    LEFT_START=1
    LEFT_END=$(( TOTAL_W / 2 ))
    RIGHT_START=$(( LEFT_END + 2 ))
    RIGHT_END=$TOTAL_W

    LEFT_INNER_W=$(( LEFT_END - LEFT_START - 1 ))
    RIGHT_INNER_W=$(( RIGHT_END - RIGHT_START - 1 ))

    CONTENT_H=$(( TERM_LINES - 9 ))
    [ "$CONTENT_H" -lt 11 ] && CONTENT_H=11

    ROW_TOP=1
    ROW_TWIN_TOP=4
    ROW_TWIN_START=5
    ROW_TWIN_END=$(( ROW_TWIN_START + CONTENT_H - 1 ))
    ROW_TWIN_BOTTOM=$(( ROW_TWIN_END + 1 ))

    ROW_LEGEND_SEP=$(( ROW_TWIN_BOTTOM - 3 ))
    ROW_LEGEND_TEXT_1=$(( ROW_TWIN_BOTTOM - 2 ))
    ROW_LEGEND_TEXT_2=$(( ROW_TWIN_BOTTOM - 1 ))

    ROW_PROMPT_TOP=$(( ROW_TWIN_BOTTOM + 1 ))
    ROW_PROMPT_INPUT=$(( ROW_PROMPT_TOP + 1 ))
    ROW_PROMPT_BOTTOM=$(( ROW_PROMPT_INPUT + 1 ))
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

draw_wireframe() {
    clear
    calc_geometry

    draw_box "$ROW_TOP" "$((ROW_TOP + 2))" 1 "$TOTAL_W"
    draw_box "$ROW_TWIN_TOP" "$ROW_TWIN_BOTTOM" "$LEFT_START" "$LEFT_END"
    draw_box "$ROW_TWIN_TOP" "$ROW_TWIN_BOTTOM" "$RIGHT_START" "$RIGHT_END"
    draw_box "$ROW_PROMPT_TOP" "$ROW_PROMPT_BOTTOM" 1 "$TOTAL_W"

    draw_separator "$ROW_LEGEND_SEP" "$LEFT_START" "$LEFT_END"
}

draw_left_legend() {
    printf "\e[%d;%dH   ${C_GREEN}●${C_RESET} Online   ${C_RED}○${C_RESET} Offline   ${C_BLUE}◆${C_RESET} Mounted   ${C_MUTED}◇${C_RESET} Unmounted" "$ROW_LEGEND_TEXT_1" "$(( LEFT_START + 1 ))"
    printf "\e[%d;%dH   Click ${C_BLUE}◆${C_RESET}  /  ${C_MUTED}◇${C_RESET}  to toggle mount   Press [f] to filter tags" "$ROW_LEGEND_TEXT_2" "$(( LEFT_START + 1 ))"
}

temp_message() {
    prompt_in_dialog "$1"
    ( sleep 1.5 ) &
    local pid=$!
    local garbage
    while kill -0 $pid 2>/dev/null; do
        read -t 0.1 -rsn1 garbage
    done
}

prompt_in_dialog() {
    local prompt_str="$1"
    local prompt_len=${#prompt_str}
    local input_col=$(( 3 + prompt_len ))

    printf "\e[%d;2H%*s" "$ROW_PROMPT_INPUT" "$(( TOTAL_W - 2 ))" ""
    printf "\e[%d;%dH${C_BORDER}│${C_RESET}" "$ROW_PROMPT_INPUT" "$TOTAL_W"
    printf "\e[%d;3H%s\e[%d;%dH" "$ROW_PROMPT_INPUT" "$prompt_str" "$ROW_PROMPT_INPUT" "$input_col"
}

# hover_mode: 0 = none, 1 = standard row hover, 2 = mount icon hover
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

        # Status dot on the left (keeps row bg intact)
        local s_icon="${C_RED}○${C_RESET}${bg}"
        local lat_str
        lat_str=$(printf "${C_MUTED}%6s${C_RESET}${bg}" "--")
        if [ "$st" == "ONLINE" ]; then
            s_icon="${C_GREEN}●${C_RESET}${bg}"
            lat_str=$(printf "${C_CYAN}%6s${C_RESET}${bg}" "$lat")
        fi

        # Mount diamond after status dot (gets distinct m_bg when hovered directly)
        local m_icon="${m_bg} ${C_MUTED}◇${C_RESET}${m_bg} ${C_RESET}${bg}"
        if [ "$mnt" -eq 1 ]; then
            m_icon="${m_bg} ${C_BLUE}◆${C_RESET}${m_bg} ${C_RESET}${bg}"
        fi

        local disp_name="$name"
        [ -n "$tag" ] && disp_name="$name [$tag]"

        local avail=$(( LEFT_INNER_W - 22 ))
        [ "$avail" -lt 10 ] && avail=10
        [ ${#disp_name} -gt "$avail" ] && disp_name="${disp_name:0:$((avail - 1))}…"

        local fill_w=$(( LEFT_INNER_W - 21 - ${#disp_name} ))
        [ "$fill_w" -lt 0 ] && fill_w=0

        printf "${bg}  %b%b${C_GREEN}[%2d]${C_RESET}${bg}  ${C_BOLD}%s${C_RESET}${bg}%*s%b ${C_RESET}" \
            "$s_icon" "$m_icon" "$num" "$disp_name" "$fill_w" "" "$lat_str"
    else
        printf "${bg}%*s${C_RESET}" "$LEFT_INNER_W" ""
    fi
    printf "\e[%d;%dH${C_BORDER}│${C_RESET}" "$row" "$LEFT_END"
}

render_right_pane() {
    local row="$1"
    local is_hover="$2"
    local act_idx=$(( row - ROW_TWIN_START ))

    local bg=""
    [ "$is_hover" -eq 1 ] && [ "$act_idx" -ge 0 ] && [ "$act_idx" -le 10 ] && bg="${BG_HOVER}"

    local col_start=$(( RIGHT_START + 1 ))
    printf "\e[%d;%dH" "$row" "$col_start"

    if [ "$act_idx" -ge 0 ] && [ "$act_idx" -le 10 ]; then
        local p1=""
        local p2=""
        local raw_text=""

        case "$act_idx" in
            0)  p1="${C_GREEN}[c]${C_RESET}${bg}";  p2="   Connect via SSH (Auto-tmux)"; raw_text="  [c]   Connect via SSH (Auto-tmux)" ;;
            1)  p1="${C_CYAN}[b]${C_RESET}${bg}";   p2="   Browse files in GUI File Manager"; raw_text="  [b]   Browse files in GUI File Manager" ;;
            2)  p1="${C_BLUE}[s]${C_RESET}${bg}";   p2="   Interactive SFTP shell"; raw_text="  [s]   Interactive SFTP shell" ;;
            3)  p1="${C_PURPLE}[t]${C_RESET}${bg}"; p2="   Port Tunneling (Local forward)"; raw_text="  [t]   Port Tunneling (Local forward)" ;;
            4)  p1="${C_ORANGE}[w]${C_RESET}${bg}"; p2="   Wake-on-LAN (Magic Packet)"; raw_text="  [w]   Wake-on-LAN (Magic Packet)" ;;
            5)  p1="${C_YELLOW}[k]${C_RESET}${bg}"; p2="   Push SSH Key (ssh-copy-id)"; raw_text="  [k]   Push SSH Key (ssh-copy-id)" ;;
            6)  p1="${C_GREEN}[a]${C_RESET}${bg}";  p2="   Add new server profile"; raw_text="  [a]   Add new server profile" ;;
            7)  p1="${C_CYAN}[e]${C_RESET}${bg}";   p2="   Edit server profile"; raw_text="  [e]   Edit server profile" ;;
            8)  p1="${C_RED}[d]${C_RESET}${bg}";    p2="   Delete server profile"; raw_text="  [d]   Delete server profile" ;;
            9)  p1="${C_BLUE}[r]${C_RESET}${bg}";   p2="   Refresh status & latencies"; raw_text="  [r]   Refresh status & latencies" ;;
            10) p1="${C_RED}[q]${C_RESET}${bg}";    p2="   Exit Console"; raw_text="  [q]   Exit Console" ;;
        esac

        local text_len=${#raw_text}
        local pad=$(( RIGHT_INNER_W - text_len ))
        [ "$pad" -lt 0 ] && pad=0

        printf "${bg}  %b%b${bg}%*s${C_RESET}" "$p1" "$p2" "$pad" ""
    else
        printf "${bg}%*s${C_RESET}" "$RIGHT_INNER_W" ""
    fi
    printf "\e[%d;%dH${C_BORDER}│${C_RESET}" "$row" "$RIGHT_END"
}
