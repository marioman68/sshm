# ==============================================================================
# MODULE 05: Main Event Loop, Target Selection & Mouse/Keyboard Dispatcher
# ==============================================================================

refresh_right_inspector() {
    draw_pane_titles
    for ((r=ROW_R_INFO_1; r<=ROW_TWIN_END; r++)); do
        render_right_pane "$r" 0
    done
    local target_label="None"
    [ "$server_count" -gt 0 ] && target_label="${srv_names[$selected_idx]}"
    prompt_in_dialog "Target: ${target_label}  |  [Enter/c] SSH  [n] Scan LAN  [a] Add  [q] Quit: "
}

select_target_server() {
    local new_idx="$1"
    if [ "$server_count" -eq 0 ] || [ "$new_idx" -lt 0 ] || [ "$new_idx" -ge "$server_count" ]; then
        return
    fi
    local old_idx="$selected_idx"
    selected_idx="$new_idx"
    render_left_pane "$(( ROW_TWIN_START + old_idx ))" 0
    render_left_pane "$(( ROW_TWIN_START + selected_idx ))" 0
    refresh_right_inspector
}

full_redraw() {
    load_and_ping_servers
    draw_wireframe

    local title="◆ SSH CONNECTION HUB (v${VERSION})"
    [ "$IS_MOBILE" -eq 1 ] && title="◆ SSH HUB (v${VERSION})"
    local filter_badge="[Tag: ${FILTER_TAG}]"
    local pad_title=$(( TOTAL_W - ${#title} - ${#filter_badge} - 6 ))
    [ "$pad_title" -lt 1 ] && pad_title=1

    printf "\e[%d;4H${C_HEADER}${C_BOLD}%s${C_RESET}%*s${C_YELLOW}%s${C_RESET}" \
        "$((ROW_TOP + 1))" "$title" "$pad_title" "" "$filter_badge" 

    if [ "$selected_idx" -ge "$server_count" ]; then
        selected_idx=$(( server_count > 0 ? server_count - 1 : 0 ))
    fi

    draw_pane_titles

    for ((r=ROW_TWIN_START; r<ROW_LEGEND_SEP; r++)); do
        render_left_pane "$r" 0
    done
    draw_left_legend

    for ((r=ROW_R_INFO_1; r<=ROW_TWIN_END; r++)); do
        render_right_pane "$r" 0
    done

    local target_label="None"
    [ "$server_count" -gt 0 ] && target_label="${srv_names[$selected_idx]}"
    prompt_in_dialog "Target: ${target_label}  |  [Enter/c] SSH  [n] Scan LAN  [a] Add  [q] Quit: "
}

dispatch_action() {
    local key="$1"

    # Global actions work even if 0 servers exist
    case "$key" in
        a|A) add_server_flow; full_redraw; return ;;
        n|N) scan_network_flow; full_redraw; return ;;
        p|P) theme_picker_flow; refresh_right_inspector; return ;;
        r|R) full_redraw; return ;;
        f|F) cycle_filter_tag; selected_idx=0; full_redraw; return ;;
        q|Q) cleanup_and_exit ;;
    esac

    if [ "$server_count" -eq 0 ]; then
        temp_message "[ FAIL ] No target server available. Press [a] or [n] to add one."
        refresh_right_inspector
        return
    fi

    # Target-specific actions run immediately on $selected_idx!
    case "$key" in
        c|C) connect_ssh "$selected_idx"; full_redraw ;;
        b|B) browse_gui "$selected_idx"; refresh_right_inspector ;;
        s|S) connect_sftp "$selected_idx"; full_redraw ;;
        t|T) port_tunnel_flow "$selected_idx"; full_redraw ;;
        w|W) wake_on_lan_flow "$selected_idx"; refresh_right_inspector ;;
        k|K) push_ssh_key_flow "$selected_idx"; full_redraw ;;
        e|E) edit_server_flow "$selected_idx"; full_redraw ;;
        d|D) delete_server_flow "$selected_idx"; full_redraw ;;
    esac
}

# Initial Draw
full_redraw

# Main Interactive Event Loop
while true; do
    enable_mouse

    if [ "$RESIZE_TRIGGERED" -eq 1 ]; then
        RESIZE_TRIGGERED=0
        active_hover_side=""
        active_hover_row=0
        active_hover_mode=0
        full_redraw
        continue
    fi

    if IFS= read -rsn1 -t 1 key; then
        if [[ "$key" == $'\e' ]]; then
            read -rsn2 -t 0.05 rest
            if [[ "$rest" == "[<" ]]; then
                mouse_event=""
                while IFS= read -rsn1 char; do
                    mouse_event+="$char"
                    [[ "$char" == "M" || "$char" == "m" ]] && break
                done

                if [[ "$mouse_event" =~ ^([0-9]+)\;([0-9]+)\;([0-9]+)([Mm])$ ]]; then
                    btn="${BASH_REMATCH[1]}"
                    cx="${BASH_REMATCH[2]}"
                    cy="${BASH_REMATCH[3]}"
                    action="${BASH_REMATCH[4]}"

                    new_side=""
                    new_mode=1
                    if [ "$cy" -ge "$ROW_TWIN_START" ] && [ "$cy" -le "$ROW_TWIN_END" ]; then
                        if [ "$cx" -ge 2 ] && [ "$cx" -le "$LEFT_END" ] && [ "$cy" -lt "$ROW_LEGEND_SEP" ]; then
                            new_side="L"
                            if [ "$cx" -ge 7 ] && [ "$cx" -le 9 ]; then
                                new_mode=2
                            fi
                        elif [ "$cx" -ge "$RIGHT_START" ] && [ "$cx" -le "$RIGHT_END" ]; then
                            if { [ "$cy" -ge "$ROW_R_ACT_START" ] && [ "$cy" -le "$ROW_R_ACT_END" ]; } || \
                               { [ "$cy" -ge "$ROW_R_GLOB_START" ] && [ "$cy" -le "$ROW_R_GLOB_END" ]; }; then
                                new_side="R"
                            fi
                        fi
                    fi

                    if [ -n "$new_side" ]; then
                        if [ "$new_side" != "$active_hover_side" ] || [ "$cy" -ne "$active_hover_row" ] || [ "$new_mode" -ne "$active_hover_mode" ]; then
                            [ "$active_hover_side" == "L" ] && [ "$active_hover_row" -ge "$ROW_TWIN_START" ] && render_left_pane "$active_hover_row" 0
                            [ "$active_hover_side" == "R" ] && [ "$active_hover_row" -ge "$ROW_TWIN_START" ] && render_right_pane "$active_hover_row" 0

                            [ "$new_side" == "L" ] && render_left_pane "$cy" "$new_mode"
                            [ "$new_side" == "R" ] && render_right_pane "$cy" 1

                            active_hover_side="$new_side"
                            active_hover_row="$cy"
                            active_hover_mode="$new_mode"
                        fi
                    else
                        if [ -n "$active_hover_side" ]; then
                            [ "$active_hover_side" == "L" ] && [ "$active_hover_row" -ge "$ROW_TWIN_START" ] && render_left_pane "$active_hover_row" 0
                            [ "$active_hover_side" == "R" ] && [ "$active_hover_row" -ge "$ROW_TWIN_START" ] && render_right_pane "$active_hover_row" 0
                            active_hover_side=""
                            active_hover_row=0
                            active_hover_mode=0
                        fi
                    fi

                    if [ "$btn" -eq 0 ] && [ "$action" == "M" ]; then
                        if [ "$new_side" == "L" ]; then
                            clicked_idx=$(( cy - ROW_TWIN_START ))
                            if [ "$clicked_idx" -ge 0 ] && [ "$clicked_idx" -lt "$server_count" ]; then
                                if [ "$new_mode" -eq 2 ]; then
                                    toggle_mount "$clicked_idx"
                                    render_left_pane "$cy" 2
                                    [ "$clicked_idx" -eq "$selected_idx" ] && refresh_right_inspector
                                else
                                    if [ "$clicked_idx" -eq "$selected_idx" ]; then
                                        connect_ssh "$selected_idx"
                                        full_redraw
                                    else
                                        select_target_server "$clicked_idx"
                                        render_left_pane "$cy" 1
                                    fi
                                fi
                            fi
                        elif [ "$new_side" == "R" ]; then
                            if [ "$cy" -ge "$ROW_R_ACT_START" ] && [ "$cy" -le "$ROW_R_ACT_END" ]; then
                                act_idx=$(( cy - ROW_R_ACT_START ))
                                case "$act_idx" in
                                    0) dispatch_action "c" ;;
                                    1) dispatch_action "b" ;;
                                    2) dispatch_action "s" ;;
                                    3) dispatch_action "t" ;;
                                    4) dispatch_action "w" ;;
                                    5) dispatch_action "k" ;;
                                    6) dispatch_action "e" ;;
                                    7) dispatch_action "d" ;;
                                esac
                            elif [ "$cy" -ge "$ROW_R_GLOB_START" ] && [ "$cy" -le "$ROW_R_GLOB_END" ]; then
                                glob_idx=$(( cy - ROW_R_GLOB_START ))
                                case "$glob_idx" in
                                    0) dispatch_action "a" ;;
                                    1) dispatch_action "n" ;;
                                    2) dispatch_action "p" ;;
                                    3) dispatch_action "r" ;;
                                    4) dispatch_action "q" ;;
                                esac
                            fi
                        fi
                    fi
                fi
            elif [[ "$rest" == "[A" ]]; then
                [ "$selected_idx" -gt 0 ] && select_target_server "$(( selected_idx - 1 ))"
            elif [[ "$rest" == "[B" ]]; then
                [ "$selected_idx" -lt "$(( server_count - 1 ))" ] && select_target_server "$(( selected_idx + 1 ))"
            fi
        elif [[ "$key" == "" ]]; then
            [ "$server_count" -gt 0 ] && dispatch_action "c"
        elif [[ "$key" =~ ^[1-9]$ ]]; then
            num_idx=$(( key - 1 ))
            if [ "$num_idx" -lt "$server_count" ]; then
                select_target_server "$num_idx"
            fi
        else
            dispatch_action "$key"
        fi
    fi
done
