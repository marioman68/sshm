# ==============================================================================
# MODULE 05: Main Interactive Loop & Event Dispatcher
# ==============================================================================

while true; do
    load_servers
    enable_mouse
    RESIZE_TRIGGERED=0

    draw_wireframe

    printf "\e[2;3H${C_HEADER}${C_BOLD}◆ SSH CONNECTION HUB (v${VERSION})${C_RESET}"
    printf "\e[2;%dH${C_MUTED}Filter: [${C_CYAN}%s${C_MUTED}]${C_RESET}" "$(( TOTAL_W - ${#FILTER_TAG} - 12 ))" "$FILTER_TAG"
    printf "\e[2;%dH${C_BORDER}│${C_RESET}" "$TOTAL_W"

    printf "\e[%d;4H${C_CYAN}${C_BOLD} REMOTE NODES (${server_count}) ${C_RESET}" "$ROW_TWIN_TOP"
    printf "\e[%d;%dH${C_HEADER}${C_BOLD} ACTION CENTER ${C_RESET}" "$ROW_TWIN_TOP" "$(( RIGHT_START + 3 ))"

    printf "\e[%d;4H${C_YELLOW}${C_BOLD} STATUS & QUICK LAUNCH ${C_RESET}" "$ROW_PROMPT_TOP"
    printf "\e[%d;3HType node [1-%d], action key, [f]ilter, or [q] to exit: \e[%d;%dH${C_BORDER}│${C_RESET}" \
        "$ROW_PROMPT_INPUT" "$server_count" "$ROW_PROMPT_INPUT" "$TOTAL_W"

    for ((r=ROW_TWIN_START; r<=ROW_TWIN_END; r++)); do
        if [ "$r" -lt "$ROW_LEGEND_SEP" ]; then
            render_left_pane "$r" 0
        fi
        render_right_pane "$r" 0
    done

    draw_left_legend

    active_hover_side=""
    active_hover_row=0
    active_hover_mode=0
    choice=""
    clicked_mount_idx=-1

    printf "\e[%d;60H" "$ROW_PROMPT_INPUT"

    while true; do
        if [ "$RESIZE_TRIGGERED" -eq 1 ]; then
            choice="r"
            break
        fi

        char=""
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
                        action="${BASH_REMATCH[4]}"

                        side=""
                        new_hover_mode=1
                        if [ "$cy" -ge "$ROW_TWIN_START" ] && [ "$cy" -le "$ROW_TWIN_END" ]; then
                            if [ "$cx" -ge 2 ] && [ "$cx" -le "$LEFT_END" ]; then
                                if [ "$cy" -lt "$ROW_LEGEND_SEP" ]; then
                                    side="L"
                                    # Columns 5 to 7 correspond to the mount diamond area
                                    if [ "$cx" -ge 5 ] && [ "$cx" -le 7 ]; then
                                        new_hover_mode=2
                                    fi
                                fi
                            elif [ "$cx" -ge "$RIGHT_START" ] && [ "$cx" -le "$RIGHT_END" ]; then
                                side="R"
                            fi
                        fi

                        if [ -n "$side" ]; then
                            redraw=0
                            if [ "$side" != "$active_hover_side" ] || [ "$cy" -ne "$active_hover_row" ] || [ "$new_hover_mode" -ne "$active_hover_mode" ]; then
                                redraw=1
                            fi

                            if [ "$redraw" -eq 1 ]; then
                                if [ "$active_hover_side" == "L" ] && [ "$active_hover_row" -ge "$ROW_TWIN_START" ] && [ "$active_hover_row" -ne "$cy" ]; then
                                    render_left_pane "$active_hover_row" 0
                                fi
                                if [ "$active_hover_side" == "R" ] && [ "$active_hover_row" -ge "$ROW_TWIN_START" ] && [ "$active_hover_row" -ne "$cy" ]; then
                                    render_right_pane "$active_hover_row" 0
                                fi
                                if [ "$active_hover_side" != "$side" ]; then
                                    [ "$active_hover_side" == "L" ] && [ "$active_hover_row" -ge "$ROW_TWIN_START" ] && render_left_pane "$active_hover_row" 0
                                    [ "$active_hover_side" == "R" ] && [ "$active_hover_row" -ge "$ROW_TWIN_START" ] && render_right_pane "$active_hover_row" 0
                                fi

                                [ "$side" == "L" ] && render_left_pane "$cy" "$new_hover_mode"
                                [ "$side" == "R" ] && render_right_pane "$cy" 1

                                active_hover_side="$side"
                                active_hover_row="$cy"
                                active_hover_mode="$new_hover_mode"
                                printf "\e[%d;60H" "$ROW_PROMPT_INPUT"
                            fi
                        else
                            if [ -n "$active_hover_side" ]; then
                                [ "$active_hover_side" == "L" ] && [ "$active_hover_row" -ge "$ROW_TWIN_START" ] && render_left_pane "$active_hover_row" 0
                                [ "$active_hover_side" == "R" ] && [ "$active_hover_row" -ge "$ROW_TWIN_START" ] && render_right_pane "$active_hover_row" 0
                                active_hover_side=""
                                active_hover_row=0
                                active_hover_mode=0
                                printf "\e[%d;60H" "$ROW_PROMPT_INPUT"
                            fi
                        fi

                        if [ "$btn" -eq 0 ] && [ "$action" == "M" ]; then
                            if [ "$side" == "L" ]; then
                                clicked_idx=$(( cy - ROW_TWIN_START ))
                                if [ "$clicked_idx" -ge 0 ] && [ "$clicked_idx" -lt "$server_count" ]; then
                                    # Click on mount diamond (cols 5-7) toggles mount
                                    if [ "$cx" -ge 5 ] && [ "$cx" -le 7 ]; then
                                        clicked_mount_idx=$clicked_idx
                                        choice="MOUNT_TOGGLE"
                                        break
                                    else
                                        choice="$(( clicked_idx + 1 ))"
                                        break
                                    fi
                                fi
                            elif [ "$side" == "R" ]; then
                                case $(( cy - ROW_TWIN_START )) in
                                    0)  choice="c"; break ;;
                                    1)  choice="b"; break ;;
                                    2)  choice="s"; break ;;
                                    3)  choice="t"; break ;;
                                    4)  choice="w"; break ;;
                                    5)  choice="k"; break ;;
                                    6)  choice="a"; break ;;
                                    7)  choice="e"; break ;;
                                    8)  choice="d"; break ;;
                                    9)  choice="r"; break ;;
                                    10) choice="q"; break ;;
                                esac
                            fi
                        fi
                    fi
                fi
            elif [[ "$char" =~ ^[0-9a-zA-Z]$ ]]; then
                choice="$char"
                break
            fi
        fi
    done

    disable_mouse

    case "$choice" in
        [Qq])
            clear
            exit 0
            ;;
        [Rr])
            continue
            ;;
        [Ff])
            cycle_filter_tag
            ;;
        MOUNT_TOGGLE)
            [ "$clicked_mount_idx" -ge 0 ] && toggle_mount "$clicked_mount_idx"
            ;;
        [Cc])
            prompt_server_index "Enter server number to connect"
            idx=$?
            [ "$idx" -ne 255 ] && connect_ssh "$idx"
            ;;
        [Bb])
            prompt_server_index "Enter server number to browse"
            idx=$?
            [ "$idx" -ne 255 ] && browse_gui "$idx"
            ;;
        [Ss])
            prompt_server_index "Enter server number for SFTP"
            idx=$?
            [ "$idx" -ne 255 ] && connect_sftp "$idx"
            ;;
        [Tt])
            prompt_server_index "Enter server number for Port Tunnel"
            idx=$?
            [ "$idx" -ne 255 ] && port_tunnel_flow "$idx"
            ;;
        [Ww])
            prompt_server_index "Enter server number to Wake-on-LAN"
            idx=$?
            [ "$idx" -ne 255 ] && wake_on_lan_flow "$idx"
            ;;
        [Kk])
            prompt_server_index "Enter server number to push SSH key"
            idx=$?
            [ "$idx" -ne 255 ] && push_ssh_key_flow "$idx"
            ;;
        [Aa])
            add_server_flow
            ;;
        [Ee])
            prompt_server_index "Enter server number to edit"
            idx=$?
            [ "$idx" -ne 255 ] && edit_server_flow "$idx"
            ;;
        [Dd])
            prompt_server_index "Enter server number to delete"
            idx=$?
            [ "$idx" -ne 255 ] && delete_server_flow "$idx"
            ;;
        *)
            if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "$server_count" ]; then
                connect_ssh $(( choice - 1 ))
            fi
            ;;
    esac
done
