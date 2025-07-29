CLIENT_VERSION = "0.0.35.8440"

import sys
import curses
import socket
import threading
import time
import os
import platform
import subprocess
import re
import base64
import urllib.request
import random

# --- Requirements check and auto-install ---
REQUIRED_MODULES = ["curses"]

def check_and_install_requirements():
    import importlib
    missing = []
    for mod in REQUIRED_MODULES:
        mod_name = mod.split('.')[0]
        try:
            importlib.import_module(mod_name)
        except ImportError:
            missing.append(mod_name)
    if missing:
        print(f"Missing modules: {', '.join(missing)}")
        print("Attempting to install missing modules...")
        python = sys.executable
        for mod in missing:
            try:
                subprocess.check_call([python, "-m", "pip", "install", mod])
            except Exception as e:
                print(f"Failed to install {mod}: {e}")
        print("Please restart the client after installation.")
        sys.exit(1)

check_and_install_requirements()

NICKNAME_FILE = os.path.expanduser("~/.communicator_nick")
COLOR_FILE = os.path.expanduser("~/.communicator_color")

# --- Utility functions ---
def save_nickname(nickname):
    try:
        with open(NICKNAME_FILE, "w", encoding="utf-8") as f:
            f.write(nickname.strip())
    except Exception:
        pass

def load_nickname():
    try:
        with open(NICKNAME_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""

def save_color(color_name):
    try:
        with open(COLOR_FILE, "w", encoding="utf-8") as f:
            f.write(color_name.strip())
    except Exception:
        pass

def load_color():
    try:
        with open(COLOR_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return "green"

def play_notification_sound():
    try:
        system = platform.system()
        if system == "Windows":
            import winsound
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            # Windows 10+ notification (optional, best effort)
            try:
                import ctypes
                ctypes.windll.user32.MessageBeep(0xFFFFFFFF)
            except Exception:
                pass
        elif system == "Darwin":
            os.system('afplay /System/Library/Sounds/Glass.aiff &')
        elif system == "Linux":
            # Try notify-send for visible notification
            try:
                os.system('notify-send "Communicator" "You were mentioned!"')
            except Exception:
                pass
            # Try termux-notification for Android/Termux
            if "ANDROID_ROOT" in os.environ or "TERMUX_VERSION" in os.environ:
                try:
                    os.system('termux-notification --title "Communicator" --content "You were mentioned!"')
                except Exception:
                    pass
            print('\a', end='', flush=True)
        else:
            print('\a', end='', flush=True)
    except Exception:
        pass

# --- Main Communicator ---
def main(stdscr):
    # --- Call state ---
    dm_state = {
        'active': False,      # True if in DM mode
        'peer': None,         # Username of the DM peer
    }
    curses.curs_set(1)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN, -1)
    curses.init_pair(2, curses.COLOR_WHITE, -1)
    curses.init_pair(3, curses.COLOR_CYAN, -1)
    curses.init_pair(4, curses.COLOR_YELLOW, -1)
    curses.init_pair(5, curses.COLOR_MAGENTA, -1)
    curses.init_pair(6, curses.COLOR_RED, -1)
    # Pink: use color 13 if available, else fallback to magenta
    try:
        curses.init_pair(7, 13, -1)
        pink_color = curses.color_pair(7)
    except Exception:
        pink_color = curses.color_pair(5)
    color_map = {
        "green": curses.color_pair(1),
        "white": curses.color_pair(2),
        "cyan": curses.color_pair(3),
        "yellow": curses.color_pair(4),
        "magenta": curses.color_pair(5),
        "red": curses.color_pair(6),
        "pink": pink_color,
    }

    def create_windows():
        max_y, max_x = stdscr.getmaxyx()
        chat_win = curses.newwin(max_y - 3, max_x, 0, 0)
        chat_win.scrollok(True)
        input_win = curses.newwin(1, max_x, max_y - 2, 0)
        status_win = curses.newwin(1, max_x, max_y - 1, 0)
        return chat_win, input_win, status_win, max_y, max_x

    chat_win, input_win, status_win, max_y, max_x = create_windows()
    lock = threading.Lock()
    stop_event = threading.Event()

    # --- Get server and nickname ---
    stdscr.addstr(max_y - 3, 0, "-" * (max_x - 1))
    stdscr.refresh()
    server_prompt = "Server IP (default 172.22.90.1, or type 'scan' to search): "
    stdscr.addstr(max_y - 2, 0, server_prompt[:max_x-1])
    stdscr.refresh()
    curses.echo()
    server_ip = stdscr.getstr(max_y - 2, len(server_prompt)).decode().strip() or "172.22.90.1"
    if server_ip.lower() == 'scan':
        scan_msg = "Scanning for servers..."
        input_win.clear(); input_win.addstr(scan_msg[:input_win.getmaxyx()[1]-1]); input_win.refresh()
        def scan_for_servers(port=3256, timeout=0.2, already_scanned=None, already_found=None):
            import socket
            import ipaddress
            found = already_found or []
            scanned = already_scanned or set()
            # Try to get all local IPv4 addresses
            try:
                import netifaces
                interfaces = netifaces.interfaces()
                local_ips = []
                for iface in interfaces:
                    addrs = netifaces.ifaddresses(iface)
                    if netifaces.AF_INET in addrs:
                        for addr in addrs[netifaces.AF_INET]:
                            local_ips.append(addr['addr'])
            except Exception:
                # Fallback: try to get local IP from socket
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.connect(("8.8.8.8", 80))
                    local_ips = [s.getsockname()[0]]
                    s.close()
                except Exception:
                    local_ips = ["127.0.0.1"]
            # Scan all /24 subnets for all interfaces
            for local_ip in local_ips:
                try:
                    net = ipaddress.IPv4Interface(local_ip + "/24").network
                except Exception:
                    continue
                for ip in net.hosts():
                    ipstr = str(ip)
                    if ipstr in scanned or ipstr == local_ip:
                        continue
                    scanned.add(ipstr)
                    # Show currently scanned IP
                    input_win.clear(); input_win.addstr(f"Scanning: {ipstr}"[:input_win.getmaxyx()[1]-1]); input_win.refresh()
                    try:
                        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        s.settimeout(timeout)
                        s.connect((ipstr, port))
                        s.sendall(b"\n")
                        banner = s.recv(1024).decode(errors='ignore')
                        if "nickname" in banner.lower() or "welcome" in banner.lower():
                            found.append((ipstr, banner.strip()))
                            s.close()
                            return found, scanned, True  # Stop scan, found server
                        s.close()
                    except Exception:
                        pass
            return found, scanned, False  # No new server found
        servers = []
        scanned = set()
        keep_scanning = True
        while keep_scanning:
            new_servers, scanned, found_flag = scan_for_servers(already_scanned=scanned, already_found=servers)
            servers = new_servers
            input_win.clear(); input_win.refresh()
            if not servers:
                stdscr.addstr(max_y - 2, 0, "No Communicator servers found on local network. Press any key.")
                stdscr.refresh()
                stdscr.getch()
                return
            # Print server list line by line, paginated to fit window
            stdscr.clear()
            stdscr.addstr(0, 0, "Servers found:", curses.color_pair(3))
            max_list_lines = max_y - 6  # Leave space for prompt and input
            for idx, (ip, banner) in enumerate(servers[:max_list_lines]):
                line = f"{idx+1}. {ip} - {banner}"
                stdscr.addstr(idx + 1, 0, line[:max_x-1])
            prompt_line = min(len(servers), max_list_lines) + 2
            stdscr.addstr(prompt_line, 0, "Enter server number to connect, or press Enter to scan more: ")
            stdscr.refresh()
            curses.echo()
            user_input = stdscr.getstr(prompt_line, len("Enter server number to connect, or press Enter to scan more: ")).decode().strip()
            if user_input.isdigit():
                sel = int(user_input)
                if 1 <= sel <= len(servers):
                    server_ip = servers[sel-1][0]
                    keep_scanning = False
                else:
                    stdscr.addstr(prompt_line + 1, 0, "Invalid selection. Press any key.")
                    stdscr.refresh()
                    stdscr.getch()
                    keep_scanning = False
                    return
            elif user_input == "":
                # Continue scanning for more servers
                continue
            else:
                stdscr.addstr(prompt_line + 1, 0, "Invalid input. Press any key.")
                stdscr.refresh()
                stdscr.getch()
                keep_scanning = False
                return
    input_win.clear(); input_win.refresh()
    nickname = load_nickname()
    if not nickname:
        nickname_prompt = "Nickname: "
        stdscr.addstr(max_y - 2, 0, nickname_prompt[:max_x-1])
        stdscr.refresh()
        nickname = stdscr.getstr(max_y - 2, len(nickname_prompt)).decode().strip()
        save_nickname(nickname)
    input_win.clear(); input_win.refresh()
    user_color_name = load_color()
    user_color = color_map.get(user_color_name, curses.color_pair(1))

    # --- Handle terminal resize ---
    def handle_resize():
        nonlocal chat_win, input_win, status_win, max_y, max_x
        chat_win, input_win, status_win, max_y, max_x = create_windows()
        stdscr.clear()
        stdscr.addstr(max_y - 3, 0, "-" * (max_x - 1))
        stdscr.refresh()
        chat_win.refresh()
        input_win.refresh()
        status_win.refresh()

    # --- Connect ---
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((server_ip, 3256))
    except Exception as e:
        stdscr.addstr(max_y - 2, 0, f"Connection failed: {e}"[:max_x-1])
        stdscr.refresh()
        stdscr.getch()
        return
    prompt = sock.recv(1024).decode('utf-8')
    sock.sendall(nickname.encode('utf-8'))
    chat_win.addstr(prompt + nickname + '\n', user_color)
    chat_win.refresh()

    # --- Admin password prompt and status ---
    is_admin = False
    admin_status_lock = threading.Lock()
    prompt = sock.recv(1024).decode('utf-8')
    if prompt.strip().lower().startswith("enter admin password"):
        input_win.clear(); input_win.addstr(prompt); input_win.refresh(); curses.echo()
        password = input_win.getstr(0, len(prompt)).decode().strip()
        sock.sendall(password.encode('utf-8'))
        response = sock.recv(1024).decode('utf-8')
        chat_win.addstr(response + '\n', user_color)
        chat_win.refresh()
        # Server will send a special message if admin access is granted
        if "Admin access granted" in response:
            with admin_status_lock:
                is_admin = True
    elif prompt.strip():
        chat_win.addstr(prompt + '\n', user_color)
        chat_win.refresh()

    # Listen for admin status from server
    def set_admin_status(msg):
        nonlocal is_admin
        with admin_status_lock:
            if msg.strip() == "SERVER> ADMIN_GRANTED":
                is_admin = True
            elif msg.strip() == "SERVER> ADMIN_REVOKED":
                is_admin = False

    # --- Receive thread ---
    pending_files = {}  # id: (filename, sender, filedata)
    def animated_addstr(win, y, x, text, color, delay=0.025):
        for i, ch in enumerate(text):
            win.addstr(y, x + i, ch, color)
            win.refresh()
            time.sleep(delay)

    def receive(sock, chat_win, lock, stop_event):
        nonlocal pending_files
        nonlocal dm_state
        buffer = b""
        def print_animated(msg, color):
            with lock:
                y, x = chat_win.getyx()
                animated_addstr(chat_win, y, 0, msg, color)
                chat_win.addstr('\n')
                chat_win.refresh()
        while not stop_event.is_set():
            try:
                data = sock.recv(4096)
                if not data:
                    break
                buffer += data
                while True:
                    # Check for file transfer message
                    if buffer.startswith(b"/sendfile "):
                        delim = buffer.find(b":::")
                        if delim == -1:
                            break
                        header = buffer[:delim].decode('utf-8', errors='replace')
                        header_parts = header.split(" ", 4)
                        if len(header_parts) < 4:
                            with lock:
                                chat_win.addstr("Malformed file transfer header.\n", curses.color_pair(6))
                                chat_win.refresh()
                            buffer = buffer[delim+3:]
                            continue
                        sender = header_parts[1]
                        filename = header_parts[2]
                        try:
                            b64len = int(header_parts[3])
                        except Exception:
                            with lock:
                                chat_win.addstr("Malformed file transfer length.\n", curses.color_pair(6))
                                chat_win.refresh()
                            buffer = buffer[delim+3:]
                            continue
                        if len(buffer) < delim+3+b64len:
                            break
                        b64 = buffer[delim+3:delim+3+b64len]
                        try:
                            filedata = base64.b64decode(b64)
                            file_id = str(random.randint(10000, 99999))
                            pending_files[file_id] = (filename, sender, filedata)
                            with lock:
                                chat_win.addstr(f"Received file '{filename}' from {sender}. Use /rcvfile [{file_id}] /path/to/save\n", curses.color_pair(4) | curses.A_BOLD)
                                chat_win.refresh()
                        except Exception as e:
                            with lock:
                                chat_win.addstr(f"Failed to receive file: {e}\n", curses.color_pair(6))
                                chat_win.refresh()
                        buffer = buffer[delim+3+b64len:]
                        continue
                    # Otherwise, try to decode as utf-8 message
                    msg_end = buffer.find(b'\n')
                    if msg_end == -1:
                        break
                    try:
                        msg = buffer[:msg_end].decode('utf-8', errors='replace').strip()
                    except Exception:
                        buffer = buffer[msg_end+1:]
                        continue
                    buffer = buffer[msg_end+1:]
                    # Listen for admin status from server
                    if msg == "SERVER> ADMIN_GRANTED":
                        set_admin_status(msg)
                        continue
                    if msg == "SERVER> ADMIN_REVOKED":
                        set_admin_status(msg)
                        continue
                    if msg.startswith("SERVER> LIST:"):
                        userlist = msg[len("SERVER> LIST:"):].strip()
                        with lock:
                            chat_win.addstr("Connected users (from server):\n", curses.color_pair(3))
                            for user in userlist.split(','):
                                if user.strip():
                                    chat_win.addstr(f"- {user.strip()}\n", curses.color_pair(2))
                            chat_win.refresh()
                        continue
                    if msg.startswith("SERVER> LISTIP:"):
                        iplist = msg[len("SERVER> LISTIP:"):].strip()
                        with lock:
                            chat_win.addstr("Connected users + IPs (from server):\n", curses.color_pair(3))
                            for line in iplist.split(';'):
                                if line.strip():
                                    chat_win.addstr(f"- {line.strip()}\n", curses.color_pair(2))
                            chat_win.refresh()
                        continue
                    if msg == "SERVER> CLEARALL":
                        with lock:
                            chat_win.clear(); chat_win.refresh()
                        continue
                    # --- Mention notification ---
                    mention_pattern = re.compile(r'@' + re.escape(nickname) + r'\b', re.IGNORECASE)
                    if mention_pattern.search(msg):
                        play_notification_sound()
                        print_animated(f"[MENTION] {msg}", curses.color_pair(4) | curses.A_BOLD)
                        continue
                    # Animate all other messages
                    print_animated(msg, user_color)
            except Exception as e:
                with lock:
                    chat_win.addstr(f"Receive error: {e}\n", curses.color_pair(6))
                    chat_win.refresh()
                break

    recv_thread = threading.Thread(target=receive, args=(sock, chat_win, lock, stop_event), daemon=True)
    recv_thread.start()

    # --- Main input loop ---
    COMMANDS = ["/help", "/list", "/listip", "/clear", "/clearall", "/color", "/rename", "/ver", "/quit"]
    input_history = []
    input_history_idx = 0
    while True:
        # Check for terminal resize
        if curses.is_term_resized(max_y, max_x):
            handle_resize()

        input_win.clear(); input_win.addstr(f"{nickname}> ", user_color); input_win.refresh(); curses.echo()
        msg = input_win.getstr().decode().strip()
        if msg:
            input_history.append(msg)
            input_history_idx = len(input_history)
        if msg.lower() in ("/quit", "/exit"):
            break
        # --- DM commands ---
        if msg.startswith("/dm "):
            peer = msg.split(" ",1)[1].strip()
            if not peer:
                with lock:
                    chat_win.addstr("Usage: /dm [username]\n", curses.color_pair(2))
                    chat_win.refresh()
                continue
            if peer == nickname:
                with lock:
                    chat_win.addstr("You cannot DM yourself.\n", curses.color_pair(6))
                    chat_win.refresh()
                continue
            dm_state['active'] = True
            dm_state['peer'] = peer
            with lock:
                chat_win.addstr(f"Now in direct message mode with {peer}. Type /edm to return to main chat.\n", curses.color_pair(5) | curses.A_BOLD)
                chat_win.refresh()
            continue
        if msg == "/edm":
            if dm_state['active']:
                with lock:
                    chat_win.addstr(f"Exited DM mode with {dm_state['peer']}.\n", curses.color_pair(2))
                    chat_win.refresh()
                dm_state['active'] = False
                dm_state['peer'] = None
            else:
                with lock:
                    chat_win.addstr("You are not in DM mode.\n", curses.color_pair(2))
                    chat_win.refresh()
            continue
        if msg == "/help":
            with lock:
                chat_win.addstr("Available commands:\n", curses.color_pair(3))
                commands = [
                    "/help    -    Show this help message",
                    "/list    -    List connected users",
                    "/dm [USER]    -    Enter direct message mode with a user",
                    "/edm      -    Exit direct message mode (return to main chat)",
                    "/clear    -    Clear chat window",
                    "/color COLOR    -    Change chat color (green, white, cyan, yellow, magenta, red, pink)",
                    "/rename NEWNICK    -    Change your nickname",
                    "/ver    -    Show client version",
                    "/update    -    Update client if available",
                    "/sendfile [USER] [PATH/filename]    -    Send a file to a user",
                    "/rcvfile [ID] [PATH/filename]    -    Receive a file by ID and save to PATH",
                    "/quit    -    Exit the client"
                ]
                with admin_status_lock:
                    if is_admin:
                        admin_cmds = [
                            "/listip    -    List users with IPs (admin only)",
                            "/clearall    -    Clear chat for all users (admin only)"
                        ]
                        commands.insert(2, admin_cmds[0])
                        commands.insert(4, admin_cmds[1])
                for cmd in commands:
                    chat_win.addstr(cmd + "\n", curses.color_pair(2))
                chat_win.refresh()
            continue
        elif msg == "/clear":
            with lock:
                chat_win.clear(); chat_win.refresh()
            continue
        elif msg == "/list":
            try:
                sock.sendall(b"/list")
            except:
                break
            continue
        elif msg == "/listip":
            with admin_status_lock:
                if is_admin:
                    try:
                        sock.sendall(b"/listip")
                    except:
                        break
                else:
                    with lock:
                        chat_win.addstr("You are not admin.\n", curses.color_pair(6))
                        chat_win.refresh()
            continue
        elif msg == "/clearall":
            with admin_status_lock:
                if is_admin:
                    try:
                        sock.sendall(b"/clearall")
                    except:
                        break
                else:
                    with lock:
                        chat_win.addstr("You are not admin.\n", curses.color_pair(6))
                        chat_win.refresh()
            continue
        elif msg == "/update":
            # --- Update logic for .exe and .py ---
            try:
                import shutil
                is_frozen = getattr(sys, 'frozen', False)
                if is_frozen:
                    # Running as exe
                    exe_path = sys.executable
                    update_url = f"http://{server_ip}:8080/UPDATE/Client.exe"
                    with lock:
                        chat_win.addstr(f"\nChecking for updates at {update_url}...\n", curses.A_BOLD)
                        chat_win.refresh()
                    # Download new exe to temp file
                    import tempfile
                    tmp_fd, tmp_path = tempfile.mkstemp(suffix='.exe')
                    os.close(tmp_fd)
                    try:
                        with urllib.request.urlopen(update_url) as response, open(tmp_path, 'wb') as out_file:
                            shutil.copyfileobj(response, out_file)
                        # Optionally, check version string in exe (skip for now)
                        # Replace current exe
                        bak_path = exe_path + ".bak"
                        if os.path.exists(bak_path):
                            os.remove(bak_path)
                        os.rename(exe_path, bak_path)
                        shutil.move(tmp_path, exe_path)
                        with lock:
                            chat_win.addstr("Update complete. Restarting...\n", curses.A_BOLD)
                            chat_win.refresh()
                        stop_event.set()
                        sock.close()
                        # Relaunch exe
                        if platform.system() == "Windows":
                            os.startfile(exe_path)
                        else:
                            subprocess.Popen([exe_path])
                        os._exit(0)
                    except Exception as e:
                        with lock:
                            chat_win.addstr(f"Update failed: {e}\n", curses.A_BOLD)
                            chat_win.refresh()
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)
                    continue
                else:
                    # Running as .py
                    update_url = f"http://{server_ip}:8080/UPDATE/Client.py"
                    with lock:
                        chat_win.addstr(f"\nChecking for updates at {update_url}...\n", curses.A_BOLD)
                        chat_win.refresh()
                    response = urllib.request.urlopen(update_url)
                    new_code = response.read()
                    first_lines = new_code.decode(errors="ignore").splitlines()[:5]
                    new_version = None
                    for line in first_lines:
                        if "CLIENT_VERSION" in line:
                            parts = line.split("=")
                            if len(parts) > 1:
                                new_version = parts[1].strip().strip('"').strip("'")
                            break
                    if new_version and new_version != CLIENT_VERSION:
                        script_path = os.path.realpath(__file__)
                        bak_path = script_path + ".bak"
                        if os.path.exists(bak_path):
                            os.remove(bak_path)
                        os.rename(script_path, bak_path)
                        with open(script_path, "wb") as f:
                            f.write(new_code)
                        with lock:
                            chat_win.addstr(f"Updated to version {new_version}. Launching new client...\n", curses.A_BOLD)
                            chat_win.refresh()
                        stop_event.set()
                        sock.close()
                        restart_client()
                        break
                    elif new_version == CLIENT_VERSION:
                        with lock:
                            chat_win.addstr("You already have the latest version.\n", curses.A_BOLD)
                            chat_win.refresh()
                    else:
                        with lock:
                            chat_win.addstr("Could not determine version of downloaded file.\n", curses.A_BOLD)
                            chat_win.refresh()
            except Exception as e:
                with lock:
                    chat_win.addstr(f"Update failed: {e}\n", curses.A_BOLD)
                    chat_win.refresh()
            continue
        elif msg.startswith("/color"):
            color_name = msg[6:].strip().lower()
            if color_name in color_map:
                save_color(color_name)
                user_color = color_map[color_name]
                with lock:
                    chat_win.addstr(f"Chat color changed to {color_name}.\n", user_color)
                    chat_win.refresh()
            else:
                with lock:
                    chat_win.addstr("Available colors: green, white, cyan, yellow, magenta, red, pink\n", curses.color_pair(2))
                    chat_win.refresh()
            continue
        elif msg == "/gui":
            import subprocess
            # Relaunch self with --gui
            script_path = os.path.realpath(__file__)
            python = sys.executable
            try:
                subprocess.Popen([python, script_path, "--gui"])
            except Exception as e:
                with lock:
                    chat_win.addstr(f"Failed to launch GUI: {e}\n", curses.color_pair(6))
                    chat_win.refresh()
            break
        elif msg.startswith("/rename"):
            newnick = msg[7:].strip()
            if newnick:
                nickname = newnick
                save_nickname(nickname)
                try:
                    sock.sendall(f"/rename {nickname}".encode('utf-8'))
                except:
                    break
                with lock:
                    chat_win.addstr(f"Nickname changed to: {nickname}\n", user_color)
                    chat_win.refresh()
            else:
                with lock:
                    chat_win.addstr("Usage: /rename NEWNICK\n", curses.color_pair(2))
                    chat_win.refresh()
            continue
        elif msg == "/ver":
            with lock:
                chat_win.addstr(f"Client version: {CLIENT_VERSION}\n", curses.color_pair(2))
                chat_win.refresh()
            continue
        elif msg.startswith("/sendfile "):
            try:
                # Allow spaces in target and filepath, and support any file extension
                parts = msg.split(" ", 2)
                if len(parts) != 3:
                    with lock:
                        chat_win.addstr("Usage: /sendfile USER FILEPATH\n", curses.color_pair(2))
                        chat_win.refresh()
                    continue
                target, filepath = parts[1], parts[2]
                if not os.path.isfile(filepath):
                    with lock:
                        chat_win.addstr(f"File not found: {filepath}\n", curses.color_pair(6))
                        chat_win.refresh()
                    continue
                filename = os.path.basename(filepath)
                try:
                    with open(filepath, "rb") as f:
                        file_bytes = f.read()
                    b64 = base64.b64encode(file_bytes)
                    b64len = len(b64)
                except Exception as e:
                    with lock:
                        chat_win.addstr(f"Failed to read file: {e}\n", curses.color_pair(6))
                        chat_win.refresh()
                    continue
                # Send as bytes, not as utf-8 string, to support all binary files
                # Format: /sendfile <target> <filename> <b64len>:::<b64data>
                header = f"/sendfile {target} {filename} {b64len}:::".encode('utf-8')
                filemsg = header + b64
                try:
                    sock.sendall(filemsg)
                except Exception as e:
                    with lock:
                        chat_win.addstr(f"Socket error: {e}\n", curses.color_pair(6))
                        chat_win.refresh()
                    break
                with lock:
                    chat_win.addstr(f"Sent file '{filename}' to {target}.\n", curses.color_pair(2))
                    chat_win.refresh()
            except Exception as e:
                with lock:
                    chat_win.addstr(f"Failed to send file: {e}\n", curses.color_pair(6))
                    chat_win.refresh()
            continue
        elif msg.startswith("/rcvfile "):
            try:
                parts = msg.split()
                if len(parts) < 3:
                    with lock:
                        chat_win.addstr("Usage: /rcvfile [ID] [PATH]\n", curses.color_pair(2))
                        chat_win.refresh()
                    continue
                file_id = parts[1].strip('[]')
                save_path = " ".join(parts[2:])
                if file_id not in pending_files:
                    with lock:
                        chat_win.addstr(f"No file with ID {file_id} pending.\n", curses.color_pair(6))
                        chat_win.refresh()
                    continue
                filename, sender, filedata = pending_files[file_id]
                try:
                    with open(save_path, "wb") as f:
                        f.write(filedata)
                    with lock:
                        chat_win.addstr(f"Saved file '{filename}' from {sender} to {save_path}\n", curses.color_pair(4) | curses.A_BOLD)
                        chat_win.refresh()
                    del pending_files[file_id]
                except Exception as e:
                    with lock:
                        chat_win.addstr(f"Failed to save file: {e}\n", curses.color_pair(6))
                        chat_win.refresh()
            except Exception as e:
                with lock:
                    chat_win.addstr(f"Error: {e}\n", curses.color_pair(6))
                    chat_win.refresh()
            continue
        # --- Send to server if not a local command ---
        # If in a call, make chat private: both users DM each other (via /msg) while in call
        # If in DM mode, send all messages as /msg to peer
        if dm_state['active'] and dm_state['peer'] and not msg.startswith("/msg "):
            try:
                sock.sendall(f"/msg {dm_state['peer']} {msg}".encode('utf-8'))
            except:
                break
        else:
            try:
                sock.sendall(msg.encode('utf-8'))
            except:
                break
    stop_event.set()
    sock.close()

def restart_client():
    # After update, auto-relaunch the client script in a new process, then exit
    try:
        curses.endwin()
    except Exception:
        pass
    script_path = os.path.realpath(__file__)
    system = platform.system()
    try:
        if system == "Windows":
            # Use PowerShell to start a new window and run the script, then exit the old one
            cmd = [
                "powershell",
                "-NoProfile",
                "-Command",
                f"Start-Process -WindowStyle Normal -FilePath '{sys.executable}' -ArgumentList '{script_path}'"
            ]
            subprocess.Popen(cmd, shell=False)
        elif system == "Darwin":
            subprocess.Popen(['open', '-a', 'Terminal', script_path])
        else:
            # Linux/Unix/Termux
            term = os.environ.get("TERMUX_VERSION")
            if term:
                # Termux:am for Android
                try:
                    subprocess.Popen(["am", "start", "-n", "com.termux/.app.TermuxActivity", "-d", f"file://{script_path}"])
                except Exception:
                    subprocess.Popen([sys.executable, script_path])
            else:
                # Try gnome-terminal, xterm, or fallback
                try:
                    subprocess.Popen(['gnome-terminal', '--', sys.executable, script_path])
                except Exception:
                    try:
                        subprocess.Popen(['xterm', '-e', sys.executable, script_path])
                    except Exception:
                        subprocess.Popen([sys.executable, script_path])
        print("Update complete. The new client should open in a new window.")
    except Exception as e:
        print(f"Update complete, but failed to auto-relaunch: {e}\nPlease start the client manually.")
    os._exit(0)

if __name__ == "__main__":
    curses.wrapper(main)