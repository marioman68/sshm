#!/usr/bin/env python3
import curses
import os
import sys
import time
import json
import socket
import subprocess
import concurrent.futures
from pathlib import Path

# Set short ESC delay so pressing Esc closes modals instantaneously!
os.environ.setdefault("ESCDELAY", "25")

CONFIG_FILE = Path.home() / ".ssh_servers"
CUSTOM_CMD_FILE = Path.home() / ".ssh_custom_commands.json"
TELEM_FILE = Path("/dev/shm/sshm_telemetry.json")
MOUNT_DIR = Path.home() / "Network_Places"
REMOTEVIEW_DIR = Path.home() / ".local/share/remoteview"
PREFS_FILE = Path.home() / ".config/sshm_tui.json"

# 256-color themes: (Name, Border_256, Highlight_256, Accent_256)
THEMES = [
    ("Oceanic Blue", 33, 51, 39),
    ("Cyberpunk Neon", 198, 51, 201),
    ("Matrix Emerald", 40, 46, 82),
    ("Amber Gold", 214, 226, 208),
    ("Nordic Frost", 68, 117, 110),
]

def reset_terminal_mouse():
    """Disable all X11/SGR mouse reporting modes when leaving the TUI."""
    sys.stdout.write("\033[?1000l\033[?1002l\033[?1003l\033[?1006l\033[?1015l")
    sys.stdout.flush()

def enable_tui_mouse():
    """Enable click, double-click, and live hover motion inside curses."""
    try:
        curses.mousemask(
            curses.BUTTON1_CLICKED
            | curses.BUTTON1_DOUBLE_CLICKED
            | curses.BUTTON1_PRESSED
            | curses.REPORT_MOUSE_POSITION
        )
        curses.mouseinterval(180)
        sys.stdout.write("\033[?1003h\033[?1006h")
        sys.stdout.flush()
    except Exception:
        pass

def load_prefs():
    if PREFS_FILE.exists():
        try:
            return json.loads(PREFS_FILE.read_text())
        except Exception:
            pass
    return {"theme_idx": 0, "auto_refresh": 10}

def save_prefs(prefs):
    try:
        PREFS_FILE.parent.mkdir(parents=True, exist_ok=True)
        PREFS_FILE.write_text(json.dumps(prefs))
    except Exception:
        pass

def load_servers():
    servers = []
    if not CONFIG_FILE.exists():
        return servers
    for line in CONFIG_FILE.read_text(errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = (line.split("|") + [""] * 7)[:7]
        name, user, host, port, tag, mac, key = [p.strip() for p in parts]
        servers.append({
            "name": name,
            "user": user,
            "host": host,
            "port": port if port else "22",
            "tag": tag,
            "mac": mac,
            "key": key,
        })
    return servers

def save_servers(servers):
    lines = []
    for s in servers:
        lines.append(f"{s['name']}|{s['user']}|{s['host']}|{s['port']}|{s['tag']}|{s['mac']}|{s['key']}")
    CONFIG_FILE.write_text("\n".join(lines) + ("\n" if lines else ""))

def read_telemetry():
    if not TELEM_FILE.exists():
        return {}
    try:
        return json.loads(TELEM_FILE.read_text())
    except Exception:
        return {}

def is_mounted(srv):
    safe_name = srv["name"].replace(" ", "_").replace("/", "_")
    dfile = MOUNT_DIR / f"{safe_name}.desktop"
    rfile = REMOTEVIEW_DIR / f"{safe_name}.desktop"
    return dfile.exists() or rfile.exists()

def toggle_mount(srv):
    MOUNT_DIR.mkdir(parents=True, exist_ok=True)
    REMOTEVIEW_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = srv["name"].replace(" ", "_").replace("/", "_")
    dfile = MOUNT_DIR / f"{safe_name}.desktop"
    rfile = REMOTEVIEW_DIR / f"{safe_name}.desktop"
    if dfile.exists() or rfile.exists():
        dfile.unlink(missing_ok=True)
        rfile.unlink(missing_ok=True)
        return False, f"Unmounted '{srv['name']}' from Network Places."
    else:
        url = f"sftp://{srv['user']}@{srv['host']}:{srv['port']}/"
        content = (
            "[Desktop Entry]\n"
            "Icon=folder-remote\n"
            f"Name={srv['name']} ({srv['host']})\n"
            "Type=Link\n"
            f"URL[$e]={url}\n"
        )
        dfile.write_text(content)
        dfile.chmod(0o755)
        rfile.write_text(content)
        rfile.chmod(0o755)
        return True, f"Mounted '{srv['name']}' (/home/{srv['user']}) to Network Places!"

def measure_tcp_ms(host, port):
    t0 = time.monotonic()
    try:
        with socket.create_connection((host, int(port)), timeout=0.55):
            ms = int((time.monotonic() - t0) * 1000)
            return True, f"{ms}ms"
    except Exception:
        return False, "--"

def check_all_statuses(servers):
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
        futs = {
            ex.submit(measure_tcp_ms, s["host"], s["port"]): f"{s['host']}:{s['port']}"
            for s in servers
        }
        for fut in concurrent.futures.as_completed(futs):
            k = futs[fut]
            try:
                results[k] = fut.result()
            except Exception:
                results[k] = (False, "--")
    return results

def suspend_and_run(stdscr, cmd_list, pause=False, header_msg=None):
    reset_terminal_mouse()
    curses.def_prog_mode()
    curses.endwin()
    reset_terminal_mouse()
    os.system("clear")
    if header_msg:
        print(f"\033[1;34m=== {header_msg} ===\033[0m\n")
    try:
        subprocess.run(cmd_list)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"\033[1;31m[!] Error: {e}\033[0m")
    reset_terminal_mouse()
    if pause:
        try:
            input("\n\033[1;32mPress Enter to return to SSH Connection Hub...\033[0m")
        except KeyboardInterrupt:
            pass
    curses.reset_prog_mode()
    curses.curs_set(0)
    curses.flushinp()
    enable_tui_mouse()
    stdscr.clear()
    stdscr.refresh()

def safe_addstr(win, y, x, text, attr=0):
    h, w = win.getmaxyx()
    if 0 <= y < h and 0 <= x < w:
        max_len = w - x - 1
        if max_len > 0:
            try:
                win.addstr(y, x, text[:max_len], attr)
            except curses.error:
                pass

def draw_box(win, y, x, h, w, title, border_attr, title_attr, fill_bg=False):
    if h < 2 or w < 2:
        return
    if fill_bg:
        for r in range(y, y + h):
            safe_addstr(win, r, x, " " * (w - 1), curses.A_NORMAL)
    win.attron(border_attr)
    try:
        win.addch(y, x, curses.ACS_ULCORNER)
        win.hline(y, x + 1, curses.ACS_HLINE, w - 2)
        win.addch(y, x + w - 1, curses.ACS_URCORNER)

        for row in range(y + 1, y + h - 1):
            win.addch(row, x, curses.ACS_VLINE)
            win.addch(row, x + w - 1, curses.ACS_VLINE)

        win.addch(y + h - 1, x, curses.ACS_LLCORNER)
        win.hline(y + h - 1, x + 1, curses.ACS_HLINE, w - 2)
        win.addch(y + h - 1, x + w - 1, curses.ACS_LRCORNER)
    except curses.error:
        pass
    win.attroff(border_attr)

    if title and w > len(title) + 6:
        try:
            win.addstr(y, x + 2, f" {title} ", title_attr | curses.A_BOLD)
        except curses.error:
            pass

def draw_hsep(win, y, x, w, border_attr):
    try:
        win.attron(border_attr)
        win.addch(y, x, curses.ACS_LTEE)
        win.hline(y, x + 1, curses.ACS_HLINE, w - 2)
        win.addch(y, x + w - 1, curses.ACS_RTEE)
        win.attroff(border_attr)
    except curses.error:
        pass

def fill_hover_bar(win, y, x1, x2, attr):
    width = max(0, x2 - x1 + 1)
    if width > 0:
        safe_addstr(win, y, x1, " " * width, attr)

# ==============================================================================
# RICH INTERACTIVE OVERLAY MODALS (Multi-Field Form & Choice Dialogs)
# ==============================================================================
def show_form_modal(stdscr, title, subtitle, fields, submit_label="✔ Save Changes", cancel_label="✖ Cancel (Esc)"):
    """
    Render a rich multi-field overlay modal with mouse support, live in-place editing,
    Save / Cancel buttons, and instant Esc cancellation.
    `fields`: list of (key, label, initial_value, placeholder_hint)
    Returns: dict of {key: value} on Save, or None on Cancel/Esc.
    """
    h, w = stdscr.getmaxyx()
    num_f = len(fields)
    box_w = min(w - 4, 72)
    box_h = min(h - 2, num_f * 2 + 8)
    by = max(1, (h - box_h) // 2)
    bx = max(2, (w - box_w) // 2)

    values = [str(f[2] or "") for f in fields]
    cursors = [len(v) for v in values]
    # focus_idx: 0..num_f-1 are text fields, num_f = Submit button, num_f+1 = Cancel button
    focus_idx = 0
    hov_item = None  # ("field", i) or ("btn", 0/1)

    c_border = curses.color_pair(1) | curses.A_BOLD
    c_cyan   = curses.color_pair(2) | curses.A_BOLD
    c_green  = curses.color_pair(3) | curses.A_BOLD
    c_yellow = curses.color_pair(4) | curses.A_BOLD
    c_red    = curses.color_pair(5) | curses.A_BOLD
    c_gray   = curses.color_pair(7)
    c_white  = curses.color_pair(9)
    c_hov    = curses.color_pair(10) | curses.A_BOLD
    c_btn_ok = curses.color_pair(14) | curses.A_BOLD
    c_btn_no = curses.color_pair(15) | curses.A_BOLD

    stdscr.timeout(80)

    while True:
        # Draw shadow & modal frame directly onto stdscr (preserving background dashboard!)
        for r in range(by + 1, min(h - 1, by + box_h + 1)):
            safe_addstr(stdscr, r, bx + 2, " " * min(w - bx - 3, box_w), curses.A_DIM)

        draw_box(stdscr, by, bx, box_h, box_w, f"◆ {title}", c_border, c_cyan, fill_bg=True)
        safe_addstr(stdscr, by + 1, bx + 3, subtitle[:box_w - 6], c_yellow)
        draw_hsep(stdscr, by + 2, bx, box_w, c_border)

        label_w = 18
        inp_x = bx + label_w + 3
        inp_w = box_w - label_w - 6

        field_rows = {}
        for i, (_, lbl, _, hint) in enumerate(fields):
            fy = by + 3 + i * 2
            if fy >= by + box_h - 3:
                break
            field_rows[fy] = i
            is_focused = (focus_idx == i)
            is_hovered = (hov_item == ("field", i))

            # Field label
            ptr = "▸ " if is_focused else "  "
            safe_addstr(stdscr, fy, bx + 2, ptr, c_cyan if is_focused else c_gray)
            safe_addstr(stdscr, fy, bx + 4, f"{lbl:<15}:", c_cyan if (is_focused or is_hovered) else c_white)

            # Input box background
            val_str = values[i]
            bg_attr = c_hov if (is_focused or is_hovered) else curses.A_UNDERLINE
            safe_addstr(stdscr, fy, inp_x, " " * inp_w, bg_attr)

            if val_str:
                disp = val_str[-inp_w + 2:] if len(val_str) >= inp_w - 1 else val_str
                safe_addstr(stdscr, fy, inp_x + 1, disp, bg_attr | curses.A_BOLD)
            elif hint and not is_focused:
                safe_addstr(stdscr, fy, inp_x + 1, f"({hint})"[:inp_w - 2], c_gray)

            # Draw active block cursor inside focused text field
            if is_focused:
                cur_pos = min(cursors[i], inp_w - 2)
                ch_under = val_str[cursors[i]] if cursors[i] < len(val_str) else " "
                safe_addstr(stdscr, fy, inp_x + 1 + cur_pos, ch_under, curses.A_REVERSE | curses.A_BOLD)

        # Bottom divider + Buttons + Help Footer
        btn_sep_y = by + box_h - 3
        draw_hsep(stdscr, btn_sep_y, bx, box_w, c_border)

        btn_y = by + box_h - 2
        b1_str = f"  {submit_label}  "
        b2_str = f"  {cancel_label}  "
        b1_x = bx + 4
        b2_x = bx + 6 + len(b1_str)

        b1_active = (focus_idx == num_f) or (hov_item == ("btn", 0))
        b2_active = (focus_idx == num_f + 1) or (hov_item == ("btn", 1))

        safe_addstr(stdscr, btn_y, b1_x, b1_str, c_btn_ok if b1_active else c_green)
        safe_addstr(stdscr, btn_y, b2_x, b2_str, c_btn_no if b2_active else c_red)

        hint_right = "↑/↓/Tab: Field • Enter: Save • Esc: Cancel"
        if box_w > len(b1_str) + len(b2_str) + len(hint_right) + 10:
            safe_addstr(stdscr, btn_y, bx + box_w - len(hint_right) - 2, hint_right, c_gray)

        stdscr.refresh()

        ch = stdscr.getch()
        if ch == -1:
            continue

        if ch == 27:  # ESC key pressed!
            return None

        if ch == curses.KEY_MOUSE:
            try:
                _, mx, my, _, bstate = curses.getmouse()
                hov_item = None
                if my in field_rows and (bx + 2) <= mx <= (bx + box_w - 3):
                    hov_item = ("field", field_rows[my])
                elif my == btn_y:
                    if b1_x <= mx <= b1_x + len(b1_str):
                        hov_item = ("btn", 0)
                    elif b2_x <= mx <= b2_x + len(b2_str):
                        hov_item = ("btn", 1)

                is_click = bool(bstate & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED | curses.BUTTON1_DOUBLE_CLICKED))
                if is_click:
                    # Clicking outside modal box does nothing (or clicking Cancel closes)
                    if hov_item and hov_item[0] == "field":
                        focus_idx = hov_item[1]
                        cursors[focus_idx] = len(values[focus_idx])
                    elif hov_item == ("btn", 0):
                        return {fields[i][0]: values[i].strip() for i in range(num_f)}
                    elif hov_item == ("btn", 1):
                        return None
            except Exception:
                pass
            continue

        if ch in (curses.KEY_DOWN, 9):  # Down or Tab
            focus_idx = (focus_idx + 1) % (num_f + 2)
        elif ch in (curses.KEY_UP, curses.KEY_BTAB):  # Up or Shift-Tab
            focus_idx = (focus_idx - 1) % (num_f + 2)
        elif ch in (curses.KEY_ENTER, 10, 13):
            if focus_idx == num_f + 1:
                return None
            else:
                return {fields[i][0]: values[i].strip() for i in range(num_f)}
        elif 0 <= focus_idx < num_f:
            # Handle text editing in active field
            cur = cursors[focus_idx]
            val = values[focus_idx]
            if ch in (curses.KEY_BACKSPACE, 127, 8):
                if cur > 0:
                    values[focus_idx] = val[:cur - 1] + val[cur:]
                    cursors[focus_idx] -= 1
            elif ch == curses.KEY_DC:
                if cur < len(val):
                    values[focus_idx] = val[:cur] + val[cur + 1:]
            elif ch == curses.KEY_LEFT:
                cursors[focus_idx] = max(0, cur - 1)
            elif ch == curses.KEY_RIGHT:
                cursors[focus_idx] = min(len(val), cur + 1)
            elif ch == curses.KEY_HOME or ch == 1:  # Ctrl+A
                cursors[focus_idx] = 0
            elif ch == curses.KEY_END or ch == 5:   # Ctrl+E
                cursors[focus_idx] = len(val)
            elif ch == 21:  # Ctrl+U clears field
                values[focus_idx] = ""
                cursors[focus_idx] = 0
            elif 32 <= ch <= 126:
                ch_str = chr(ch)
                values[focus_idx] = val[:cur] + ch_str + val[cur:]
                cursors[focus_idx] += 1
        elif focus_idx >= num_f:
            if ch in (curses.KEY_LEFT, curses.KEY_RIGHT):
                focus_idx = num_f if focus_idx == num_f + 1 else num_f + 1


def show_choice_modal(stdscr, title, subtitle, options):
    """
    Render a rich interactive menu modal with hoverable options and a Cancel button.
    `options`: list of (code, key_badge, label_text, desc_text, color_pair)
    Returns selected `code` or None on Cancel/Esc.
    """
    h, w = stdscr.getmaxyx()
    box_w = min(w - 4, 68)
    box_h = len(options) * 2 + 7
    by = max(2, (h - box_h) // 2)
    bx = max(2, (w - box_w) // 2)

    sel_idx = 0
    hov_idx = -1

    c_border = curses.color_pair(1) | curses.A_BOLD
    c_cyan   = curses.color_pair(2) | curses.A_BOLD
    c_yellow = curses.color_pair(4) | curses.A_BOLD
    c_red    = curses.color_pair(5) | curses.A_BOLD
    c_gray   = curses.color_pair(7)
    c_white  = curses.color_pair(9)
    c_hov    = curses.color_pair(10) | curses.A_BOLD
    c_btn_no = curses.color_pair(15) | curses.A_BOLD

    stdscr.timeout(80)

    while True:
        for r in range(by + 1, min(h - 1, by + box_h + 1)):
            safe_addstr(stdscr, r, bx + 2, " " * min(w - bx - 3, box_w), curses.A_DIM)

        draw_box(stdscr, by, bx, box_h, box_w, f"◆ {title}", c_border, c_cyan, fill_bg=True)
        safe_addstr(stdscr, by + 1, bx + 3, subtitle[:box_w - 6], c_yellow)
        draw_hsep(stdscr, by + 2, bx, box_w, c_border)

        opt_rows = {}
        for i, (code, kbadge, lbl, desc, col) in enumerate(options):
            ry = by + 3 + i * 2
            opt_rows[ry] = i
            active = (i == sel_idx) or (i == hov_idx)
            if active:
                fill_hover_bar(stdscr, ry, bx + 1, bx + box_w - 2, c_hov)
                safe_addstr(stdscr, ry, bx + 2, "▸", c_hov)
                safe_addstr(stdscr, ry, bx + 4, kbadge, curses.color_pair(11) | curses.A_BOLD)
                safe_addstr(stdscr, ry, bx + 10, f"{lbl} ", c_hov)
                if desc:
                    safe_addstr(stdscr, ry, bx + 11 + len(lbl), f"— {desc}", c_hov)
            else:
                safe_addstr(stdscr, ry, bx + 4, kbadge, col | curses.A_BOLD)
                safe_addstr(stdscr, ry, bx + 10, lbl, c_white | curses.A_BOLD)
                if desc:
                    safe_addstr(stdscr, ry, bx + 11 + len(lbl), f"— {desc}", c_gray)

        sep_y = by + box_h - 3
        draw_hsep(stdscr, sep_y, bx, box_w, c_border)

        btn_y = by + box_h - 2
        cancel_str = "  ✖ Cancel / Close (Esc)  "
        cx = bx + 3
        is_cancel_hov = (hov_idx == 99) or (sel_idx == len(options))
        safe_addstr(stdscr, btn_y, cx, cancel_str, c_btn_no if is_cancel_hov else c_red)
        safe_addstr(stdscr, btn_y, bx + box_w - 28, "↑/↓/Click • Esc to Cancel", c_gray)

        stdscr.refresh()

        ch = stdscr.getch()
        if ch == -1:
            continue
        if ch in (27, ord('q'), ord('Q')):
            return None

        if ch == curses.KEY_MOUSE:
            try:
                _, mx, my, _, bstate = curses.getmouse()
                hov_idx = -1
                if my in opt_rows and (bx + 1) <= mx <= (bx + box_w - 2):
                    hov_idx = opt_rows[my]
                    sel_idx = hov_idx
                elif my == btn_y and cx <= mx <= cx + len(cancel_str):
                    hov_idx = 99

                if bool(bstate & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED | curses.BUTTON1_DOUBLE_CLICKED)):
                    if hov_idx == 99:
                        return None
                    elif 0 <= hov_idx < len(options):
                        return options[hov_idx][0]
            except Exception:
                pass
            continue

        if ch == curses.KEY_UP:
            sel_idx = (sel_idx - 1) % (len(options) + 1)
        elif ch == curses.KEY_DOWN:
            sel_idx = (sel_idx + 1) % (len(options) + 1)
        elif ch in (curses.KEY_ENTER, 10, 13):
            if sel_idx == len(options):
                return None
            return options[sel_idx][0]
        elif 32 <= ch <= 126:
            kch = chr(ch).lower()
            for code, _, _, _, _ in options:
                if kch == str(code).lower():
                    return code


def send_wol(mac_str):
    mac = mac_str.replace(":", "").replace("-", "").strip()
    if len(mac) != 12:
        return False, "Invalid or missing MAC address!"
    try:
        data = bytes.fromhex("FF" * 6 + mac * 16)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.sendto(data, ("255.255.255.255", 9))
        return True, f"Sent Wake-on-LAN magic packet to {mac_str}!"
    except Exception as e:
        return False, f"WoL Error: {e}"

def get_ssh_base(srv):
    cmd = ["ssh", "-p", str(srv["port"])]
    if srv["key"]:
        kp = os.path.expanduser(srv["key"])
        if os.path.exists(kp):
            cmd += ["-i", kp]
    return cmd

def deploy_or_remove_agent(stdscr, srv):
    opts = [
        ("1", "[1]", "Deploy / Update Agent", "Install systemd service & start live stats", curses.color_pair(3)),
        ("2", "[2]", "Check Agent Status", "View remote systemctl status output", curses.color_pair(2)),
        ("3", "[3]", "Remove Telemetry Agent", "Stop & uninstall agent from remote node", curses.color_pair(5)),
    ]
    choice = show_choice_modal(
        stdscr,
        f"TELEMETRY AGENT MANAGER — {srv['name']}",
        f"Target Endpoint: {srv['user']}@{srv['host']}:{srv['port']}",
        opts,
    )
    if not choice:
        return "Telemetry Agent action cancelled."

    ssh_base = get_ssh_base(srv)
    target = f"{srv['user']}@{srv['host']}"
    if choice == "1":
        remote_script = (
            "mkdir -p ~/.config/systemd/user ~/.local/share/sshm && "
            "cat << 'AEOF' > ~/.local/share/sshm/sshm-agent.py\n"
            "import time, json, socket, os\n"
            "def get_stats():\n"
            "    try:\n"
            "        with open('/proc/stat') as f: v1 = [float(x) for x in f.readline().split()[1:]]\n"
            "        time.sleep(0.4)\n"
            "        with open('/proc/stat') as f: v2 = [float(x) for x in f.readline().split()[1:]]\n"
            "        cpu = int(round((1.0 - (v2[3]-v1[3])/(sum(v2)-sum(v1)))*100))\n"
            "    except: cpu = 0\n"
            "    try:\n"
            "        with open('/proc/meminfo') as f:\n"
            "            m = {l.split(':')[0]: int(l.split(':')[1].split()[0]) for l in f if ':' in l}\n"
            "        tot = m.get('MemTotal', 1)/1048576.0\n"
            "        used = (m.get('MemTotal', 1) - m.get('MemAvailable', m.get('MemFree', 0)))/1048576.0\n"
            "        ram_str = f'{used:.1f}/{tot:.0f}G'\n"
            "    except: ram_str = '--'\n"
            "    try:\n"
            "        with open('/proc/uptime') as f: sec = int(float(f.readline().split()[0]))\n"
            "        d, r = divmod(sec, 86400); h, r = divmod(r, 3600); mn = r // 60\n"
            "        up_str = f'{d}d {h}h' if d else f'{h}h {mn}m'\n"
            "    except: up_str = '--'\n"
            "    return {'cpu': cpu, 'ram_str': ram_str, 'up_str': up_str}\n"
            "sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\n"
            "sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)\n"
            "while True:\n"
            "    try:\n"
            "        payload = json.dumps(get_stats()).encode()\n"
            "        sock.sendto(payload, ('255.255.255.255', 55888))\n"
            "    except: pass\n"
            "    time.sleep(3)\n"
            "AEOF\n"
            "chmod +x ~/.local/share/sshm/sshm-agent.py && "
            "cat << 'SEOF' > ~/.config/systemd/user/sshm-agent.service\n"
            "[Unit]\nDescription=SSHM Telemetry Heartbeat Agent\nAfter=network.target\n"
            "[Service]\nExecStart=/usr/bin/python3 %h/.local/share/sshm/sshm-agent.py\nRestart=always\nRestartSec=3\n"
            "[Install]\nWantedBy=default.target\nSEOF\n"
            "loginctl enable-linger $USER 2>/dev/null || true && "
            "systemctl --user daemon-reload && "
            "systemctl --user enable --now sshm-agent.service && "
            "echo '[  OK  ] Telemetry Agent deployed & enabled for boot!'"
        )
        suspend_and_run(stdscr, ssh_base + [target, remote_script], pause=True, header_msg=f"Deploying Agent to {srv['name']}")
        return f"Deployed Telemetry Agent to '{srv['name']}'!"
    elif choice == "2":
        suspend_and_run(stdscr, ssh_base + [target, "systemctl --user status sshm-agent.service"], pause=True, header_msg=f"Agent Status on {srv['name']}")
        return f"Checked Agent status on '{srv['name']}'."
    elif choice == "3":
        rm_script = (
            "systemctl --user disable --now sshm-agent.service 2>/dev/null || true && "
            "rm -f ~/.config/systemd/user/sshm-agent.service ~/.local/share/sshm/sshm-agent.py && "
            "systemctl --user daemon-reload && "
            "echo '[  OK  ] Telemetry Agent removed.'"
        )
        suspend_and_run(stdscr, ssh_base + [target, rm_script], pause=True, header_msg=f"Removing Agent from {srv['name']}")
        return f"Removed Telemetry Agent from '{srv['name']}'."
    return ""

def run_lan_scan(stdscr, servers):
    res = show_form_modal(
        stdscr,
        "SCAN LOCAL NETWORK (AUTO-DISCOVER SSH)",
        "Probes all 254 hosts in parallel for active SSH servers",
        [
            ("subnet", "Subnet Prefix", "192.168.4", "e.g. 192.168.4 or 10.0.0"),
            ("port",   "SSH Port",      "22",        "Default: 22"),
        ],
        submit_label="🔍 Start Scan",
    )
    if not res or not res.get("subnet"):
        return "LAN Scan cancelled."

    subnet = res["subnet"].rstrip(".")
    scan_port = int(res["port"]) if res.get("port", "").isdigit() else 22

    # Show a sleek scanning splash box
    h, w = stdscr.getmaxyx()
    draw_box(stdscr, h // 2 - 2, w // 2 - 26, 5, 52, "◆ SCANNING LAN...", curses.color_pair(1), curses.color_pair(2), fill_bg=True)
    safe_addstr(stdscr, h // 2, w // 2 - 22, f"Probing {subnet}.1 - .254 on port {scan_port}...", curses.color_pair(4) | curses.A_BOLD)
    stdscr.refresh()

    found = []
    def probe(ip):
        try:
            with socket.create_connection((ip, scan_port), timeout=0.35):
                return ip
        except Exception:
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=64) as ex:
        futs = [ex.submit(probe, f"{subnet}.{i}") for i in range(1, 255)]
        for f in concurrent.futures.as_completed(futs):
            ip = f.result()
            if ip:
                found.append(ip)

    found.sort(key=lambda x: int(x.split(".")[-1]))
    if not found:
        return f"No active SSH hosts found on {subnet}.0/24 (port {scan_port})."

    existing_ips = {s["host"] for s in servers}
    opts = []
    for idx, ip in enumerate(found[:8], 1):
        status_tag = "Already Saved" if ip in existing_ips else "Click to Quick-Add Profile"
        col = curses.color_pair(7) if ip in existing_ips else curses.color_pair(3)
        opts.append((ip, f"[{idx}]", f"{ip}:{scan_port}", status_tag, col))

    picked_ip = show_choice_modal(
        stdscr,
        f"DISCOVERED SSH HOSTS ({len(found)} FOUND)",
        "Select a discovered host to add it to your Server Hub, or press Esc:",
        opts,
    )
    if not picked_ip:
        return f"LAN Scan complete ({len(found)} active hosts found)."

    # Open the Add Server modal pre-filled with the discovered IP!
    new_data = show_form_modal(
        stdscr,
        "ADD DISCOVERED SERVER PROFILE",
        f"Configuring discovered endpoint {picked_ip}:{scan_port}",
        [
            ("name", "Server Name",  f"Node-{picked_ip.split('.')[-1]}", "Friendly display name"),
            ("user", "SSH Username", os.environ.get("USER", "root"),     "e.g. lucas, root, ubuntu"),
            ("host", "Host / IP",    picked_ip,                          "IP or hostname"),
            ("port", "SSH Port",     str(scan_port),                     "Default: 22"),
            ("tag",  "Group Tag",    "LAN",                              "e.g. Main Server, Homelab"),
            ("mac",  "MAC Address",  "",                                 "Optional for Wake-on-LAN"),
        ],
        submit_label="✔ Add Server",
    )
    if new_data and new_data.get("name") and new_data.get("host"):
        servers.append({
            "name": new_data["name"],
            "user": new_data["user"] or os.environ.get("USER", "root"),
            "host": new_data["host"],
            "port": new_data["port"] or "22",
            "tag":  new_data["tag"],
            "mac":  new_data["mac"],
            "key":  "",
        })
        save_servers(servers)
        return f"Added discovered server '{new_data['name']}' ({new_data['host']})!"
    return "Discovered host addition cancelled."

def tui_main(stdscr):
    curses.curs_set(0)
    curses.noecho()
    curses.cbreak()
    stdscr.keypad(True)
    enable_tui_mouse()

    curses.start_color()
    curses.use_default_colors()

    prefs = load_prefs()
    theme_idx = prefs.get("theme_idx", 0) % len(THEMES)
    auto_refresh = prefs.get("auto_refresh", 10)

    def setup_colors(idx):
        _, c_border, c_hi, c_acc = THEMES[idx]
        if curses.COLORS >= 256:
            curses.init_pair(1, c_border, -1)  # Royal Blue Box Borders (33)
            curses.init_pair(2, c_hi, -1)      # Bright Cyan Highlight/Titles (51)
            curses.init_pair(3, 46, -1)        # Vibrant Green (Online / [c] / [g] / [a])
            curses.init_pair(4, 226, -1)       # Vibrant Yellow (Auto / Tag / RAM / [k] / [p])
            curses.init_pair(5, 196, -1)       # Bright Red (Offline / [d] / [q])
            curses.init_pair(6, 141, -1)       # Vibrant Purple (CPU dot / [t] / [n])
            curses.init_pair(7, 244, -1)       # Muted Gray (Labels, Unmounted, Hints)
            curses.init_pair(8, c_acc, -1)     # Endpoint / Up / Connect text (39)
            curses.init_pair(9, 255, -1)       # Crisp White ([w] / standard text)
            curses.init_pair(10, 255, 24)      # Standard Row Hover (Crisp White on Deep Navy)
            curses.init_pair(11, 51, 24)       # Cyan Accent on Deep Navy Hover
            curses.init_pair(12, 46, 24)       # Green Accent on Deep Navy Hover
            curses.init_pair(13, 226, 127)     # Diamond Hover (Bright Gold on Magenta Pill)
            curses.init_pair(14, 16, 46)       # Modal Save Button Active (Black on Bright Green)
            curses.init_pair(15, 255, 160)     # Modal Cancel Button Active (White on Crimson Red)
        else:
            curses.init_pair(1, curses.COLOR_BLUE, -1)
            curses.init_pair(2, curses.COLOR_CYAN, -1)
            curses.init_pair(3, curses.COLOR_GREEN, -1)
            curses.init_pair(4, curses.COLOR_YELLOW, -1)
            curses.init_pair(5, curses.COLOR_RED, -1)
            curses.init_pair(6, curses.COLOR_MAGENTA, -1)
            curses.init_pair(7, curses.COLOR_WHITE, -1)
            curses.init_pair(8, curses.COLOR_CYAN, -1)
            curses.init_pair(9, curses.COLOR_WHITE, -1)
            curses.init_pair(10, curses.COLOR_WHITE, curses.COLOR_BLUE)
            curses.init_pair(11, curses.COLOR_CYAN, curses.COLOR_BLUE)
            curses.init_pair(12, curses.COLOR_GREEN, curses.COLOR_BLUE)
            curses.init_pair(13, curses.COLOR_YELLOW, curses.COLOR_MAGENTA)
            curses.init_pair(14, curses.COLOR_BLACK, curses.COLOR_GREEN)
            curses.init_pair(15, curses.COLOR_WHITE, curses.COLOR_RED)

    setup_colors(theme_idx)

    servers = load_servers()
    selected_idx = 0
    tag_filter = "ALL"
    status_banner = ""
    status_banner_time = 0

    mouse_x, mouse_y = -1, -1

    ping_cache = check_all_statuses(servers)
    last_refresh = time.monotonic()

    stdscr.timeout(100)
    click_zones = []

    def get_hovered_zone(my, mx):
        for zy, zx1, zx2, act, arg in click_zones:
            if my == zy and zx1 <= mx <= zx2:
                return (act, arg, zy, zx1, zx2)
        return (None, None, -1, -1, -1)

    HOVER_HELP = {
        "c": "Launch an interactive SSH session (automatically attaches/creates tmux)",
        "b": "Mount & open this server's remote filesystem in your desktop File Manager",
        "s": "Open an interactive command-line SFTP file transfer shell",
        "t": "Configure local SSH port forwarding (tunnel remote service to localhost)",
        "w": "Broadcast a Wake-on-LAN magic packet to power on this machine",
        "k": "Copy your local SSH public key to this server for passwordless login",
        "g": "Deploy, check, or remove the background CPU/RAM Telemetry Heartbeat Agent",
        "e": "Open the interactive Server Profile Editor modal (Esc to cancel anytime)",
        "d": "Delete this server profile from your hub (with confirmation modal)",
        "a": "Open the New Server Profile form modal (Esc to cancel anytime)",
        "n": "Scan your local subnet in parallel for open SSH endpoints",
        "p": "Cycle through vibrant 256-color border & UI themes",
        "r": "Immediately re-probe TCP latency & telemetry across all servers",
        "i": "Cycle automatic background refresh timer (10s / 30s / 60s / OFF)",
        "f": "Cycle group tag filter to view specific server categories",
        "q": "Cleanly exit SSH Connection Hub back to your terminal shell",
    }

    def trigger_action(act, arg=None):
        nonlocal selected_idx, theme_idx, auto_refresh, tag_filter, servers, ping_cache, last_refresh, status_banner, status_banner_time

        visible = [s for s in servers if tag_filter == "ALL" or s["tag"].lower() == tag_filter.lower()]
        if not visible:
            visible = servers

        if act == "select_srv":
            if 0 <= arg < len(visible):
                selected_idx = arg
        elif act == "ssh_srv":
            if 0 <= arg < len(visible):
                selected_idx = arg
                srv = visible[selected_idx]
                ssh_cmd = get_ssh_base(srv) + ["-t", f"{srv['user']}@{srv['host']}", "tmux attach || tmux new || $SHELL"]
                suspend_and_run(stdscr, ssh_cmd, pause=False, header_msg=f"Connecting to {srv['name']} ({srv['host']})")
                ping_cache = check_all_statuses(servers)
        elif act == "mount_srv":
            if 0 <= arg < len(visible):
                selected_idx = arg
                _, msg = toggle_mount(visible[arg])
                status_banner = msg
                status_banner_time = time.monotonic()
        elif act == "p":
            theme_idx = (theme_idx + 1) % len(THEMES)
            setup_colors(theme_idx)
            prefs["theme_idx"] = theme_idx
            save_prefs(prefs)
            status_banner = f"Switched theme to {THEMES[theme_idx][0]}!"
            status_banner_time = time.monotonic()
        elif act == "i":
            cycles = [10, 30, 60, 0]
            cur = cycles.index(auto_refresh) if auto_refresh in cycles else 0
            auto_refresh = cycles[(cur + 1) % len(cycles)]
            prefs["auto_refresh"] = auto_refresh
            save_prefs(prefs)
            status_banner = f"Auto-refresh set to {auto_refresh}s" if auto_refresh else "Auto-refresh disabled"
            status_banner_time = time.monotonic()
        elif act == "r":
            servers = load_servers()
            ping_cache = check_all_statuses(servers)
            last_refresh = time.monotonic()
            status_banner = "Refreshed all server statuses!"
            status_banner_time = time.monotonic()
        elif act == "f":
            tags = ["ALL"] + sorted({s["tag"] for s in servers if s["tag"]})
            cur_t = tags.index(tag_filter) if tag_filter in tags else 0
            tag_filter = tags[(cur_t + 1) % len(tags)]
            selected_idx = 0
            status_banner = f"Tag Filter: {tag_filter}"
            status_banner_time = time.monotonic()
        elif act == "a":
            res = show_form_modal(
                stdscr,
                "ADD NEW SERVER PROFILE",
                "Fill in the server details below (Press Esc or click Cancel anytime)",
                [
                    ("name", "Server Name",  "",                             "e.g. Homelab Node"),
                    ("user", "SSH Username", os.environ.get("USER", "root"), "e.g. lucas, root"),
                    ("host", "Host / IP",    "",                             "e.g. 192.168.4.100"),
                    ("port", "SSH Port",     "22",                           "Default: 22"),
                    ("tag",  "Group Tag",    "",                             "e.g. Main Server, Gaming"),
                    ("mac",  "MAC Address",  "",                             "AA:BB:CC:DD:EE:FF (optional)"),
                    ("key",  "SSH Key Path", "",                             "~/.ssh/id_ed25519 (optional)"),
                ],
                submit_label="✔ Create Server",
            )
            if res and res.get("name") and res.get("host"):
                servers.append({
                    "name": res["name"],
                    "user": res["user"] or os.environ.get("USER", "root"),
                    "host": res["host"],
                    "port": res["port"] or "22",
                    "tag":  res["tag"],
                    "mac":  res["mac"],
                    "key":  res["key"],
                })
                save_servers(servers)
                ping_cache = check_all_statuses(servers)
                status_banner = f"Added server '{res['name']}'!"
            else:
                status_banner = "Add server cancelled."
            status_banner_time = time.monotonic()
        elif act == "n":
            msg = run_lan_scan(stdscr, servers)
            servers = load_servers()
            ping_cache = check_all_statuses(servers)
            status_banner = msg
            status_banner_time = time.monotonic()
        elif act in ("c", "b", "s", "t", "w", "k", "g", "e", "d"):
            if not visible:
                return
            srv = visible[selected_idx]
            if act == "c":
                ssh_cmd = get_ssh_base(srv) + ["-t", f"{srv['user']}@{srv['host']}", "tmux attach || tmux new || $SHELL"]
                suspend_and_run(stdscr, ssh_cmd, pause=False, header_msg=f"Connecting to {srv['name']} ({srv['host']})")
                ping_cache = check_all_statuses(servers)
            elif act == "b":
                if not is_mounted(srv):
                    toggle_mount(srv)
                url = f"sftp://{srv['user']}@{srv['host']}:{srv['port']}/"
                subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                status_banner = f"Mounted & opened '{srv['name']}' in File Manager!"
                status_banner_time = time.monotonic()
            elif act == "s":
                sftp_cmd = ["sftp", "-P", str(srv["port"])]
                if srv["key"] and os.path.exists(os.path.expanduser(srv["key"])):
                    sftp_cmd += ["-i", os.path.expanduser(srv["key"])]
                sftp_cmd.append(f"{srv['user']}@{srv['host']}")
                suspend_and_run(stdscr, sftp_cmd, pause=False, header_msg=f"SFTP Shell: {srv['name']}")
            elif act == "t":
                res = show_form_modal(
                    stdscr,
                    f"PORT TUNNELING — {srv['name']}",
                    f"Forward a local desktop port through {srv['user']}@{srv['host']}:{srv['port']}",
                    [
                        ("lport", "Local Port",  "8080",      "Port on this PC (localhost)"),
                        ("rhost", "Target Host", "127.0.0.1", "Remote target IP/host"),
                        ("rport", "Target Port", "8080",      "Port on remote server"),
                    ],
                    submit_label="🚀 Open Tunnel",
                )
                if res and res.get("lport") and res.get("rport"):
                    lport, rhost, rport = res["lport"], res["rhost"] or "127.0.0.1", res["rport"]
                    tun_cmd = get_ssh_base(srv) + [
                        "-L", f"{lport}:{rhost}:{rport}",
                        f"{srv['user']}@{srv['host']}",
                        f"echo '=== Tunnel Active: localhost:{lport} -> {rhost}:{rport} ==='; echo 'Press Enter to close tunnel...'; read"
                    ]
                    suspend_and_run(stdscr, tun_cmd, pause=False, header_msg=f"Port Tunnel: {srv['name']}")
                else:
                    status_banner = "Port tunnel cancelled."
                    status_banner_time = time.monotonic()
            elif act == "w":
                _, msg = send_wol(srv["mac"])
                status_banner = msg
                status_banner_time = time.monotonic()
            elif act == "k":
                k_cmd = ["ssh-copy-id", "-p", str(srv["port"]), f"{srv['user']}@{srv['host']}"]
                suspend_and_run(stdscr, k_cmd, pause=True, header_msg=f"Pushing SSH Key to {srv['name']}")
            elif act == "g":
                msg = deploy_or_remove_agent(stdscr, srv)
                if msg:
                    status_banner = msg
                    status_banner_time = time.monotonic()
            elif act == "e":
                res = show_form_modal(
                    stdscr,
                    f"EDIT SERVER PROFILE — {srv['name']}",
                    "Use ↑/↓/Tab to switch fields, type to edit, or press Esc to cancel",
                    [
                        ("name", "Server Name",  srv["name"], "Display name"),
                        ("user", "SSH Username", srv["user"], "SSH user"),
                        ("host", "Host / IP",    srv["host"], "Hostname or IP"),
                        ("port", "SSH Port",     srv["port"], "Default: 22"),
                        ("tag",  "Group Tag",    srv["tag"],  "Optional group tag"),
                        ("mac",  "MAC Address",  srv["mac"],  "AA:BB:CC:DD:EE:FF"),
                        ("key",  "SSH Key Path", srv["key"],  "Optional identity file"),
                    ],
                    submit_label="✔ Save Profile",
                )
                if res is not None and res.get("name") and res.get("host"):
                    srv["name"] = res["name"]
                    srv["user"] = res["user"] or srv["user"]
                    srv["host"] = res["host"]
                    srv["port"] = res["port"] or "22"
                    srv["tag"]  = res["tag"]
                    srv["mac"]  = res["mac"]
                    srv["key"]  = res["key"]
                    save_servers(servers)
                    ping_cache = check_all_statuses(servers)
                    status_banner = f"Saved changes to '{srv['name']}'!"
                else:
                    status_banner = "Edit cancelled — no changes made."
                status_banner_time = time.monotonic()
            elif act == "d":
                ans = show_choice_modal(
                    stdscr,
                    f"CONFIRM DELETE — {srv['name']}",
                    f"Are you sure you want to remove '{srv['name']}' ({srv['host']})?",
                    [
                        ("no",  "[n]", "No, Keep Server Profile",   "Return safely without deleting", curses.color_pair(3)),
                        ("yes", "[y]", f"Yes, Delete '{srv['name']}'", "Permanently remove from ~/.ssh_servers", curses.color_pair(5)),
                    ],
                )
                if ans == "yes":
                    old_name = srv["name"]
                    servers = [s for s in servers if s is not srv]
                    save_servers(servers)
                    status_banner = f"Deleted server '{old_name}'."
                else:
                    status_banner = "Delete cancelled."
                status_banner_time = time.monotonic()

    while True:
        now = time.monotonic()
        if auto_refresh > 0 and (now - last_refresh) >= auto_refresh:
            servers = load_servers()
            ping_cache = check_all_statuses(servers)
            last_refresh = now

        if tag_filter == "ALL":
            visible_servers = servers
        else:
            visible_servers = [s for s in servers if s["tag"].lower() == tag_filter.lower()]

        if not visible_servers and tag_filter != "ALL":
            tag_filter = "ALL"
            visible_servers = servers

        if selected_idx >= len(visible_servers):
            selected_idx = max(0, len(visible_servers) - 1)

        telem = read_telemetry()
        stdscr.erase()
        click_zones.clear()
        h, w = stdscr.getmaxyx()

        if h < 20 or w < 76:
            safe_addstr(stdscr, 1, 2, "Terminal too small! Resize to at least 80x22.", curses.color_pair(5) | curses.A_BOLD)
            stdscr.refresh()
            ch = stdscr.getch()
            if ch in (ord('q'), ord('Q')):
                break
            continue

        c_border  = curses.color_pair(1)
        c_cyan    = curses.color_pair(2)
        c_green   = curses.color_pair(3)
        c_yellow  = curses.color_pair(4)
        c_red     = curses.color_pair(5)
        c_purple  = curses.color_pair(6)
        c_gray    = curses.color_pair(7)
        c_blue    = curses.color_pair(8)
        c_white   = curses.color_pair(9)
        c_hov     = curses.color_pair(10) | curses.A_BOLD
        c_hov_cy  = curses.color_pair(11) | curses.A_BOLD
        c_hov_gr  = curses.color_pair(12) | curses.A_BOLD
        c_hov_mnt = curses.color_pair(13) | curses.A_BOLD

        left_w = max(36, int(w * 0.41))
        right_w = w - left_w - 1
        right_x = left_w + 1
        main_h = h - 6

        auto_str = f"{auto_refresh}s" if auto_refresh > 0 else "OFF"
        auto_lbl = f"[Auto: {auto_str}]"
        tag_lbl  = f"[Tag: {tag_filter}]"
        ax = w - len(auto_lbl) - len(tag_lbl) - 4
        tx = w - len(tag_lbl) - 3
        click_zones.append((1, ax, ax + len(auto_lbl) - 1, "i", None))
        click_zones.append((1, tx, tx + len(tag_lbl) - 1, "f", None))

        for i in range(len(visible_servers)):
            row_y = 4 + i
            if row_y >= 3 + main_h - 4:
                break
            click_zones.append((row_y, 5, 7, "mount_srv", i))
            click_zones.append((row_y, 1, left_w - 2, "row_srv", i))

        leg_sep_y = 3 + main_h - 4
        ly2 = leg_sep_y + 2
        click_zones.append((ly2, 39, 51, "f", None))

        if visible_servers:
            srv = visible_servers[selected_idx]
            k = f"{srv['host']}:{srv['port']}"
            t_info = telem.get(k) or telem.get(srv["host"]) or {}
            p_online, p_ms = ping_cache.get(k, (False, "--"))
            is_on = bool(t_info) or p_online
            st_str = f"● ONLINE ({p_ms})" if is_on else "○ OFFLINE"
            mx_stat = right_x + 13 + len(st_str) + 3
            click_zones.append((5, mx_stat + 3, mx_stat + 16, "mount_status", selected_idx))

            act_codes = ["c", "b", "s", "t", "w", "k", "g", "e", "d"]
            ay = 8
            for code in act_codes:
                if ay < 3 + main_h - 6:
                    click_zones.append((ay, right_x + 1, right_x + right_w - 2, code, None))
                    ay += 1

            sep2_y = 17
            sy = (sep2_y + 1) if sep2_y < 3 + main_h - 5 else (ay + 1)
            for gcode in ("a", "n", "p"):
                if sy < 3 + main_h - 1:
                    click_zones.append((sy, right_x + 1, right_x + right_w - 2, gcode, None))
                    sy += 1
            if sy < 3 + main_h - 1:
                ix = right_x + 24
                click_zones.append((sy, right_x + 1, ix - 2, "r", None))
                click_zones.append((sy, ix - 1, right_x + right_w - 2, "i", None))
                sy += 1
            if sy < 3 + main_h - 1:
                click_zones.append((sy, right_x + 1, right_x + right_w - 2, "q", None))

        hov_act, hov_arg, hov_y, hov_x1, hov_x2 = get_hovered_zone(mouse_y, mouse_x)

        # 1. TOP HEADER BAR
        draw_box(stdscr, 0, 0, 3, w, "", c_border, c_cyan)
        safe_addstr(stdscr, 1, 2, "◆", c_blue | curses.A_BOLD)
        safe_addstr(stdscr, 1, 4, "SSH CONNECTION HUB (v2.1.0)", c_cyan | curses.A_BOLD)

        safe_addstr(stdscr, 1, ax, auto_lbl, c_hov if (hov_act == "i" and hov_y == 1) else (c_yellow | curses.A_BOLD))
        safe_addstr(stdscr, 1, tx, tag_lbl, c_hov if (hov_act == "f" and hov_y == 1) else (c_yellow | curses.A_BOLD))

        # 2. LEFT PANE: REMOTE NODES
        draw_box(stdscr, 3, 0, main_h, left_w, f"REMOTE NODES ({len(visible_servers)})", c_border, c_cyan)

        for i, srv in enumerate(visible_servers):
            row_y = 4 + i
            if row_y >= 3 + main_h - 4:
                break
            k = f"{srv['host']}:{srv['port']}"
            t_info = telem.get(k) or telem.get(srv["host"])
            p_online, p_ms = ping_cache.get(k, (False, "--"))
            is_on = bool(t_info) or p_online
            mounted = is_mounted(srv)
            is_sel = (i == selected_idx)

            row_hovered = (hov_act == "row_srv" and hov_arg == i)
            mnt_hovered = (hov_act == "mount_srv" and hov_arg == i)

            if row_hovered:
                fill_hover_bar(stdscr, row_y, 1, left_w - 2, c_hov)

            if is_sel or row_hovered:
                safe_addstr(stdscr, row_y, 2, "▸", c_hov_cy if row_hovered else (c_cyan | curses.A_BOLD))

            if is_on:
                safe_addstr(stdscr, row_y, 4, "●", c_hov_gr if row_hovered else (c_green | curses.A_BOLD))
            else:
                safe_addstr(stdscr, row_y, 4, "○", c_hov if row_hovered else c_red)

            if mnt_hovered:
                safe_addstr(stdscr, row_y, 5, f" {'◆' if mounted else '◇'} ", c_hov_mnt)
            else:
                if mounted:
                    safe_addstr(stdscr, row_y, 6, "◆", c_hov_cy if row_hovered else (c_blue | curses.A_BOLD))
                else:
                    safe_addstr(stdscr, row_y, 6, "◇", c_hov if row_hovered else c_gray)

            idx_lbl = f"[{i+1:2d}]"
            safe_addstr(stdscr, row_y, 8, idx_lbl, c_hov_gr if row_hovered else (c_green | (curses.A_BOLD if is_sel else 0)))

            tag_suffix = f" [{srv['tag']}]" if srv["tag"] else ""
            full_name = f"{srv['name']}{tag_suffix}"
            max_name_w = left_w - 20
            if row_hovered:
                name_attr = c_hov_cy
            elif is_sel:
                name_attr = c_cyan | curses.A_BOLD
            else:
                name_attr = c_white
            safe_addstr(stdscr, row_y, 13, full_name[:max_name_w], name_attr)

            ms_str = p_ms if is_on else "--"
            if row_hovered:
                ms_attr = c_hov_cy if is_on else c_hov
            else:
                ms_attr = c_cyan if is_on else c_gray
            safe_addstr(stdscr, row_y, left_w - len(ms_str) - 2, ms_str, ms_attr)

        draw_hsep(stdscr, leg_sep_y, 0, left_w, c_border)
        ly1 = leg_sep_y + 1
        safe_addstr(stdscr, ly1, 2, "●", c_green | curses.A_BOLD)
        safe_addstr(stdscr, ly1, 4, "Online", c_white)
        safe_addstr(stdscr, ly1, 13, "○", c_red)
        safe_addstr(stdscr, ly1, 15, "Offline", c_white)
        safe_addstr(stdscr, ly1, 25, "◆", c_blue | curses.A_BOLD)
        safe_addstr(stdscr, ly1, 27, "/", c_gray)
        safe_addstr(stdscr, ly1, 29, "◇", c_gray)
        safe_addstr(stdscr, ly1, 31, "Click Mount", c_white)

        safe_addstr(stdscr, ly2, 2, "Click server to target • 2x-Click SSH • ", c_gray)
        safe_addstr(stdscr, ly2, 42, "[f] Filter", c_hov if (hov_act == "f" and hov_y == ly2) else c_gray)

        # 3. RIGHT PANE: TARGET SERVER & ACTIONS
        if visible_servers:
            srv = visible_servers[selected_idx]
            k = f"{srv['host']}:{srv['port']}"
            t_info = telem.get(k) or telem.get(srv["host"]) or {}
            p_online, p_ms = ping_cache.get(k, (False, "--"))
            is_on = bool(t_info) or p_online
            mounted = is_mounted(srv)

            tag_title = f" [{srv['tag']}]" if srv["tag"] else ""
            draw_box(stdscr, 3, right_x, main_h, right_w, f"TARGET: {srv['name']}{tag_title}", c_border, c_cyan)

            safe_addstr(stdscr, 4, right_x + 2, "Endpoint : ", c_gray)
            safe_addstr(stdscr, 4, right_x + 13, f"{srv['user']}@{srv['host']}:{srv['port']}", c_blue | curses.A_BOLD)

            safe_addstr(stdscr, 5, right_x + 2, "Status   : ", c_gray)
            if is_on:
                st_str = f"● ONLINE ({p_ms})"
                safe_addstr(stdscr, 5, right_x + 13, st_str, c_green | curses.A_BOLD)
            else:
                st_str = "○ OFFLINE"
                safe_addstr(stdscr, 5, right_x + 13, st_str, c_red | curses.A_BOLD)

            mx = right_x + 13 + len(st_str) + 3
            safe_addstr(stdscr, 5, mx, "•", c_gray)
            mnt_badge = " ◆ Mounted " if mounted else " ◇ Unmounted "
            if hov_act == "mount_status":
                safe_addstr(stdscr, 5, mx + 3, mnt_badge, c_hov_mnt)
            else:
                safe_addstr(stdscr, 5, mx + 4, mnt_badge.strip(), (c_blue | curses.A_BOLD) if mounted else c_gray)

            safe_addstr(stdscr, 6, right_x + 2, "Metrics  : ", c_gray)
            if t_info:
                cpu_v = f"{t_info.get('cpu', 0)}%"
                ram_v = t_info.get("ram_str") or f"{t_info.get('ram', '--')}%"
                up_v = t_info.get("up_str", "--")

                cx = right_x + 13
                safe_addstr(stdscr, 6, cx, "●", c_purple | curses.A_BOLD)
                safe_addstr(stdscr, 6, cx + 2, "CPU ", c_white)
                safe_addstr(stdscr, 6, cx + 6, cpu_v, c_cyan | curses.A_BOLD)

                rx = cx + 6 + len(cpu_v) + 4
                safe_addstr(stdscr, 6, rx, "•", c_gray)
                safe_addstr(stdscr, 6, rx + 4, "RAM ", c_white)
                safe_addstr(stdscr, 6, rx + 8, ram_v, c_yellow | curses.A_BOLD)

                ux = rx + 8 + len(ram_v) + 4
                safe_addstr(stdscr, 6, ux, "•", c_gray)
                safe_addstr(stdscr, 6, ux + 4, "Up ", c_white)
                safe_addstr(stdscr, 6, ux + 7, up_v, c_blue | curses.A_BOLD)
            else:
                safe_addstr(stdscr, 6, right_x + 13, "○ Agent not reporting ([g] to deploy live stats)", c_gray)

            draw_hsep(stdscr, 7, right_x, right_w, c_border)

            agent_state = "● Active" if t_info else "Deploy / Status"
            wol_mac = srv["mac"] if srv["mac"] else "No MAC configured"

            srv_actions = [
                ("c", "[c]", c_green,  "Connect via SSH", c_blue | curses.A_BOLD, " (Auto-tmux)", c_white),
                ("b", "[b]", c_cyan,   "Open Network Folder in File Manager", c_white, "", 0),
                ("s", "[s]", c_blue,   "Interactive SFTP Shell", c_white, "", 0),
                ("t", "[t]", c_purple, "Port Tunneling (Local Forward)", c_white, "", 0),
                ("w", "[w]", c_white,  f"Wake-on-LAN ({wol_mac})", c_white, "", 0),
                ("k", "[k]", c_yellow, "Push SSH Public Key (ssh-copy-id)", c_white, "", 0),
                ("g", "[g]", c_green,  f"Manage Telemetry Agent ({agent_state})", c_white, "", 0),
                ("e", "[e]", c_cyan,   "Edit Target Server Profile", c_white, "", 0),
                ("d", "[d]", c_red,    "Delete Target Server Profile", c_white, "", 0),
            ]

            ay = 8
            for act_code, key_str, key_col, text1, col1, text2, col2 in srv_actions:
                if ay < 3 + main_h - 6:
                    is_row_hov = (hov_act == act_code and hov_y == ay)
                    if is_row_hov:
                        fill_hover_bar(stdscr, ay, right_x + 1, right_x + right_w - 2, c_hov)
                        safe_addstr(stdscr, ay, right_x + 2, key_str, c_hov_cy)
                        safe_addstr(stdscr, ay, right_x + 8, text1 + text2, c_hov)
                    else:
                        safe_addstr(stdscr, ay, right_x + 2, key_str, key_col | curses.A_BOLD)
                        safe_addstr(stdscr, ay, right_x + 8, text1, col1)
                        if text2:
                            safe_addstr(stdscr, ay, right_x + 8 + len(text1), text2, col2)
                    ay += 1

            sep2_y = 17
            if sep2_y < 3 + main_h - 5:
                draw_hsep(stdscr, sep2_y, right_x, right_w, c_border)
                sy = sep2_y + 1
            else:
                sy = ay + 1

            theme_name = THEMES[theme_idx][0]
            global_rows = [
                ("a", "[a]", c_green,  "Add New Server Profile"),
                ("n", "[n]", c_purple, "Scan Local Network (Auto-Discover SSH)"),
                ("p", "[p]", c_yellow, f"Border & UI Theme ({theme_name})"),
            ]
            for gcode, kstr, kcol, gdesc in global_rows:
                if sy < 3 + main_h - 1:
                    if hov_act == gcode and hov_y == sy:
                        fill_hover_bar(stdscr, sy, right_x + 1, right_x + right_w - 2, c_hov)
                        safe_addstr(stdscr, sy, right_x + 2, kstr, c_hov_cy)
                        safe_addstr(stdscr, sy, right_x + 8, gdesc, c_hov)
                    else:
                        safe_addstr(stdscr, sy, right_x + 2, kstr, kcol | curses.A_BOLD)
                        safe_addstr(stdscr, sy, right_x + 8, gdesc, c_white)
                    sy += 1

            if sy < 3 + main_h - 1:
                ix = right_x + 24
                if hov_act == "r" and hov_y == sy:
                    fill_hover_bar(stdscr, sy, right_x + 1, ix - 2, c_hov)
                    safe_addstr(stdscr, sy, right_x + 2, "[r]", c_hov_cy)
                    safe_addstr(stdscr, sy, right_x + 8, "Refresh Now", c_hov)
                else:
                    safe_addstr(stdscr, sy, right_x + 2, "[r]", c_cyan | curses.A_BOLD)
                    safe_addstr(stdscr, sy, right_x + 8, "Refresh Now  •  ", c_white)

                if hov_act == "i" and hov_y == sy:
                    fill_hover_bar(stdscr, sy, ix - 1, right_x + right_w - 2, c_hov)
                    safe_addstr(stdscr, sy, ix, "[i]", c_hov_cy)
                    safe_addstr(stdscr, sy, ix + 4, f"Auto ({auto_str})", c_hov)
                else:
                    safe_addstr(stdscr, sy, ix, "[i]", c_cyan | curses.A_BOLD)
                    safe_addstr(stdscr, sy, ix + 4, f"Auto ({auto_str})", c_white)
                sy += 1

            if sy < 3 + main_h - 1:
                if hov_act == "q" and hov_y == sy:
                    fill_hover_bar(stdscr, sy, right_x + 1, right_x + right_w - 2, c_hov)
                    safe_addstr(stdscr, sy, right_x + 2, "[q]", c_hov_cy)
                    safe_addstr(stdscr, sy, right_x + 8, "Exit SSH Connection Hub", c_hov)
                else:
                    safe_addstr(stdscr, sy, right_x + 2, "[q]", c_red | curses.A_BOLD)
                    safe_addstr(stdscr, sy, right_x + 8, "Exit SSH Connection Hub", c_white)
        else:
            draw_box(stdscr, 3, right_x, main_h, right_w, "NO SERVERS CONFIGURED", c_border, c_cyan)
            safe_addstr(stdscr, 6, right_x + 4, "Press [a] to add a server or [n] to scan your LAN.", c_yellow | curses.A_BOLD)

        # 4. BOTTOM STATUS BAR (With Dynamic Hover Explanations!)
        bot_y = h - 3
        draw_box(stdscr, bot_y, 0, 3, w, "", c_border, c_cyan)
        if status_banner and (now - status_banner_time) < 4.0:
            safe_addstr(stdscr, bot_y + 1, 2, f"[  OK  ] {status_banner}", c_cyan | curses.A_BOLD)
        elif hov_act in ("mount_srv", "mount_status"):
            m_srv = visible_servers[hov_arg] if (hov_arg is not None and hov_arg < len(visible_servers)) else None
            if m_srv:
                act_word = "UNMOUNT" if is_mounted(m_srv) else "MOUNT"
                safe_addstr(stdscr, bot_y + 1, 2, f"◆ Click to {act_word} '{m_srv['name']}' in Network Places (Dolphin)", c_hov_mnt)
        elif hov_act == "row_srv" and hov_arg is not None and hov_arg < len(visible_servers):
            h_srv = visible_servers[hov_arg]
            safe_addstr(stdscr, bot_y + 1, 2, f"▸ Click to target '{h_srv['name']}' ({h_srv['host']})  •  Double-Click to connect via SSH", c_cyan | curses.A_BOLD)
        elif hov_act in HOVER_HELP:
            safe_addstr(stdscr, bot_y + 1, 2, f"▸ [{hov_act.upper()}] {HOVER_HELP[hov_act]}", c_yellow | curses.A_BOLD)
        else:
            target_name = visible_servers[selected_idx]["name"] if visible_servers else "None"
            prompt_str = f"Target: {target_name}  │  [Enter/c] SSH  [b] Browse  [n] Scan  [i] Timer  [q] Quit:"
            safe_addstr(stdscr, bot_y + 1, 2, prompt_str, c_cyan | curses.A_BOLD)

        stdscr.refresh()

        ch = stdscr.getch()
        if ch == -1:
            continue

        if ch == curses.KEY_MOUSE:
            try:
                _, mx, my, _, bstate = curses.getmouse()
                mouse_x, mouse_y = mx, my
                is_double = bool(bstate & curses.BUTTON1_DOUBLE_CLICKED)
                is_click = bool(bstate & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED | curses.BUTTON1_DOUBLE_CLICKED))
                if is_click:
                    act, arg, _, _, _ = get_hovered_zone(my, mx)
                    if act == "q":
                        return
                    elif act == "row_srv":
                        if is_double:
                            trigger_action("ssh_srv", arg)
                        else:
                            trigger_action("select_srv", arg)
                    elif act in ("mount_srv", "mount_status"):
                        trigger_action("mount_srv", arg)
                    elif act:
                        trigger_action(act, arg)
            except Exception:
                pass
            continue

        if ch in (ord('q'), ord('Q')):
            break
        elif ch == curses.KEY_UP:
            if visible_servers:
                selected_idx = (selected_idx - 1) % len(visible_servers)
        elif ch == curses.KEY_DOWN:
            if visible_servers:
                selected_idx = (selected_idx + 1) % len(visible_servers)
        elif ord('1') <= ch <= ord('9'):
            idx = ch - ord('1')
            if idx < len(visible_servers):
                selected_idx = idx
        elif ch in (curses.KEY_ENTER, 10, 13):
            trigger_action("c")
        elif ch in (ord('m'), ord('M')):
            trigger_action("mount_srv", selected_idx)
        elif 32 <= ch <= 126:
            key_char = chr(ch).lower()
            if key_char in ("c", "b", "s", "t", "w", "k", "g", "e", "d", "a", "n", "p", "r", "i", "f"):
                trigger_action(key_char)

def main():
    reset_terminal_mouse()
    try:
        curses.wrapper(tui_main)
    except KeyboardInterrupt:
        pass
    finally:
        reset_terminal_mouse()

if __name__ == "__main__":
    main()
