SERVER_VERSION = "0.0.2.2"

import http.server
import socketserver
import socket
import threading
import http.server
import socketserver
from collections import defaultdict
import time
import base64
import os

HOST = '0.0.0.0'
PORT = 3256

clients = []
nicknames = {}
blocked_nicknames = set()
banned_ips = set()
ADMINS = {"username"}
ADMIN_PASSWORD = "password"
admin_clients = set()
vote_kick_votes = defaultdict(set)
reports = defaultdict(set)
reputation = defaultdict(int)
user_rep_votes = defaultdict(set)  # {target_nick: set(voter_nick)}
client_versions = {}  # Add at the top with other globals
user_status = defaultdict(lambda: "online")  # New: user status
user_rooms = defaultdict(lambda: "main")     # New: user chat room
chat_rooms = defaultdict(set)                # room_name: set of client sockets
last_messages = {}                           # client_socket: (timestamp, msg)
typing_users = defaultdict(set)              # room_name: set of nicknames typing

STICKERS = {
    "shrug": r"¯\_(ツ)_/¯",
    "tableflip": r"(╯°□°）╯︵ ┻━┻",
    "lenny": r"( ͡° ͜ʖ ͡°)",
}

def timestamp():
    return time.strftime("[%H:%M:%S]", time.localtime())

def broadcast(message, sender_socket=None, include_sender=True, room=None):
    # Only send to users in the same room
    targets = clients if not room else chat_rooms[room]
    for client in list(targets):
        if include_sender or client != sender_socket:
            try:
                client.sendall(message)
            except:
                pass

def broadcast_system(msg, room=None):
    broadcast(f"{timestamp()} SERVER> {msg}\n".encode('utf-8'), room=room)

def handle_client(client_socket, address):
    ip = address[0]
    print(f"[INFO] New connection from {address}")
    try:
        # Ban IP check
        if ip in banned_ips:
            print(f"[INFO] Blocked connection attempt from banned IP {ip}")
            client_socket.sendall(b"Your IP is banned from this server.\n")
            client_socket.close()
            return
        # Ask for nickname
        client_socket.sendall(b"Enter your nickname: ")
        nickname = client_socket.recv(1024).decode('utf-8').strip()
        if not nickname:
            nickname = f"User{address[1]}"
        # Blocked nickname check
        if nickname in blocked_nicknames:
            print(f"[INFO] Blocked connection attempt from blocked nickname {nickname} ({address})")
            client_socket.sendall(b"You are blocked from this server.\n")
            client_socket.close()
            return
        nicknames[client_socket] = nickname
        user_status[nickname] = "online"
        user_rooms[nickname] = "main"
        chat_rooms["main"].add(client_socket)
        if nickname in ADMINS:
            client_socket.sendall(b"Enter admin password: ")
            password = client_socket.recv(1024).decode('utf-8').strip()
            if password == ADMIN_PASSWORD:
                admin_clients.add(client_socket)
                client_socket.sendall(b"Admin access granted.\n")
                print(f"[INFO] {nickname} ({address}) logged in as admin.")
            else:
                client_socket.sendall(b"Wrong password. Connection closed.\n")
                client_socket.close()
                print(f"[INFO] {nickname} ({address}) failed admin login.")
                return
        else:
            client_socket.sendall(b"Welcome.\n")
        welcome_msg = f"{nickname} has joined the chat."
        print(f"[INFO] {welcome_msg}")
        broadcast((f"{timestamp()} {welcome_msg}\n").encode('utf-8'), room="main")
        # Send user count after join
        user_count_msg = f"{timestamp()} SERVER> Users connected: {len(nicknames)}\n"
        broadcast(user_count_msg.encode('utf-8'), room="main")
        print(f"[INFO] Users connected: {len(nicknames)}")

        while True:
            data = client_socket.recv(4096)
            if not data:
                break
            msg = data.decode('utf-8').strip()
            nickname = nicknames.get(client_socket, "")
            room = user_rooms[nickname]


            # --- Call signaling ---
            # /call_request <target>
            if msg.startswith("/call_request "):
                target = msg.split(" ", 1)[1].strip()
                # Check if target exists
                found = False
                for client, nick in nicknames.items():
                    if nick == target:
                        # Optionally: check if target is already in a call (not implemented, simple relay)
                        client.sendall(f"/call_request {nickname}\n".encode('utf-8'))
                        found = True
                        break
                if not found:
                    client_socket.sendall(f"/call_busy {target}\n".encode('utf-8'))
                continue
            # /call_accept <from_user>
            if msg.startswith("/call_accept "):
                from_user = msg.split(" ", 1)[1].strip()
                found = False
                for client, nick in nicknames.items():
                    if nick == from_user:
                        client.sendall(f"/call_accepted {nickname}\n".encode('utf-8'))
                        found = True
                        break
                continue
            # /call_reject <from_user>
            if msg.startswith("/call_reject "):
                from_user = msg.split(" ", 1)[1].strip()
                found = False
                for client, nick in nicknames.items():
                    if nick == from_user:
                        client.sendall(f"/call_rejected {nickname}\n".encode('utf-8'))
                        found = True
                        break
                continue
            # /call_end
            if msg.startswith("/call_end"):
                # End call for both parties (broadcast to all, or track call state for more advanced logic)
                # For now, just notify all users in the room
                for client, nick in nicknames.items():
                    if client != client_socket:
                        client.sendall(f"/call_ended {nickname}\n".encode('utf-8'))
                continue
            # /call_busy <target>
            if msg.startswith("/call_busy "):
                target = msg.split(" ", 1)[1].strip()
                for client, nick in nicknames.items():
                    if nick == target:
                        client.sendall(f"/call_busy {nickname}\n".encode('utf-8'))
                        break
                continue
            # --- Typing indicator ---
            if msg == "/typing":
                typing_users[room].add(nickname)
                broadcast_system(f"{nickname} is typing...", room=room)
                continue
            if msg == "/notyping":
                typing_users[room].discard(nickname)
                continue

            # --- Private message ---
            if msg.startswith("/msg "):
                try:
                    _, target, pm = msg.split(" ", 2)
                    found = False
                    for client, nick in nicknames.items():
                        if nick == target:
                            client.sendall(f"{timestamp()} [PM] {nickname}> {pm}\n".encode('utf-8'))
                            client_socket.sendall(f"{timestamp()} [PM to {target}]> {pm}\n".encode('utf-8'))
                            found = True
                            break
                    if not found:
                        client_socket.sendall(f"{timestamp()} SERVER> User {target} not found.\n".encode('utf-8'))
                except Exception:
                    client_socket.sendall(f"{timestamp()} SERVER> Usage: /msg <user> <message>\n".encode('utf-8'))
                continue

            # --- Status ---
            if msg.startswith("/status "):
                status = msg[8:].strip()
                user_status[nickname] = status
                broadcast_system(f"{nickname} is now '{status}'", room=room)
                continue

            # --- Edit last message ---
            if msg.startswith("/edit "):
                new_msg = msg[6:].strip()
                if client_socket in last_messages:
                    t, old = last_messages[client_socket]
                    edit_msg = f"{timestamp()} {nickname} (edited): {new_msg}"
                    broadcast(edit_msg.encode('utf-8'), room=room)
                    last_messages[client_socket] = (time.time(), new_msg)
                else:
                    client_socket.sendall(f"{timestamp()} SERVER> No message to edit.\n".encode('utf-8'))
                continue

            # --- Delete last message ---
            if msg == "/delete":
                if client_socket in last_messages:
                    t, old = last_messages[client_socket]
                    broadcast_system(f"{nickname} deleted their last message.", room=room)
                    last_messages.pop(client_socket, None)
                else:
                    client_socket.sendall(f"{timestamp()} SERVER> No message to delete.\n".encode('utf-8'))
                continue

            # --- Stickers ---
            if msg.startswith("/sticker "):
                sticker = msg[9:].strip()
                if sticker in STICKERS:
                    sticker_msg = f"{timestamp()} {nickname}> {STICKERS[sticker]}"
                    broadcast(sticker_msg.encode('utf-8'), room=room)
                else:
                    client_socket.sendall(f"{timestamp()} SERVER> Sticker not found. Available: {', '.join(STICKERS)}\n".encode('utf-8'))
                continue

            # --- File transfer (base64, small files only) ---
            if msg.startswith("/sendfile "):
                try:
                    # Accept: /sendfile <user> <filename>:::<base64>
                    parts = msg.split(" ", 2)
                    if len(parts) != 3 or ":::" not in parts[2]:
                        client_socket.sendall(f"{timestamp()} SERVER> Usage: /sendfile <user> <filename>:::<base64data>\n".encode('utf-8'))
                        continue
                    target = parts[1]
                    filename, b64 = parts[2].split(":::", 1)
                    filename = filename.strip()
                    b64 = b64.strip()
                    # Forward to target user using the same protocol as client expects
                    found = False
                    for client, nick in nicknames.items():
                        if nick == target:
                            # Forward as: /sendfile <sender> <filename>:::<base64>
                            client.sendall(f"/sendfile {nickname} {filename}:::{b64}\n".encode('utf-8'))
                            client_socket.sendall(f"{timestamp()} SERVER> File sent to {target}.\n".encode('utf-8'))
                            found = True
                            break
                    if not found:
                        client_socket.sendall(f"{timestamp()} SERVER> User {target} not found.\n".encode('utf-8'))
                except Exception as e:
                    client_socket.sendall(f"{timestamp()} SERVER> Error: {e}\n".encode('utf-8'))
                continue

            # --- Join room ---
            if msg.startswith("/join "):
                new_room = msg[6:].strip()
                old_room = user_rooms[nickname]
                chat_rooms[old_room].discard(client_socket)
                user_rooms[nickname] = new_room
                chat_rooms[new_room].add(client_socket)
                client_socket.sendall(f"{timestamp()} SERVER> Joined room '{new_room}'.\n".encode('utf-8'))
                broadcast_system(f"{nickname} joined this room.", room=new_room)
                continue

            # --- Search (not needed on server, client-side only) ---

            # --- /list: show users with status ---
            if msg == "/list":
                userlist = ",".join(f"{nick} [{reputation[nick]}] ({user_status[nick]})" for nick in nicknames.values())
                client_socket.sendall(f"{timestamp()} SERVER> LIST: {userlist}\n".encode('utf-8'))
                continue
            if msg == "/listip":
                if client_socket in admin_clients:
                    iplist = ";".join(f"{nick} ({client.getpeername()[0]})" for client, nick in nicknames.items())
                    client_socket.sendall(f"SERVER> LISTIP: {iplist}\n".encode('utf-8'))
                else:
                    client_socket.sendall(b"SERVER> LISTIP: Permission denied.\n")
                continue
            if msg == "/clearall":
                if client_socket in admin_clients:
                    print(f"[INFO] CLEARALL issued by admin {nickname}")
                    broadcast(b"SERVER> CLEARALL\n")
                else:
                    client_socket.sendall(b"SERVER> CLEARALL: Permission denied.\n")
                continue
            # --- End command handling ---
            # Broadcast message to all clients in the same room, with timestamp
            outmsg = f"{timestamp()} {nickname}> {msg}\n"
            broadcast(outmsg.encode('utf-8'), sender_socket=client_socket, room=room)
            last_messages[client_socket] = (time.time(), msg)
    except Exception as e:
        print(f"[ERROR] Exception in handle_client: {e}")
    finally:
        if client_socket in clients:
            clients.remove(client_socket)
        if client_socket in nicknames:
            left_msg = f"{nicknames[client_socket]} has left the chat."
            room = user_rooms[nicknames[client_socket]]
            broadcast((f"{timestamp()} {left_msg}\n").encode('utf-8'), room=room)
            chat_rooms[room].discard(client_socket)
            del nicknames[client_socket]
            # Send user count after leave
            user_count_msg = f"SERVER> Users connected: {len(nicknames)}\n"
            broadcast(user_count_msg.encode('utf-8'))
            print(f"[INFO] Users connected: {len(nicknames)}")
        if client_socket in admin_clients:
            admin_clients.remove(client_socket)
        client_socket.close()

def server_console():
    while True:
        cmd = input()
        if cmd.startswith("/autoupdate"):
            update_url = f"https://github.com/sirpatch/Lan-Communicator/blob/main/Client.py"
            print(f"[INFO] Sent auto-update command with URL: {update_url}")
            broadcast(f"SERVER> AUTOUPDATE: {update_url}\n".encode('utf-8'))
        elif cmd.startswith("/msg "):
            msg = cmd[5:].strip()
            print(f"[INFO] SERVER> {msg}")
            broadcast(f"SERVER> {msg}\n".encode('utf-8'))
        elif cmd.startswith("/block "):
            to_block = cmd[7:].strip()
            blocked_nicknames.add(to_block)
            print(f"[INFO] Blocked nickname: {to_block}")
            # Disconnect blocked users immediately
            for client, nick in list(nicknames.items()):
                if nick == to_block:
                    try:
                        client.sendall(b"You have been blocked by the server.\n")
                        client.close()
                    except:
                        pass
        elif cmd.startswith("/banip "):
            ip_to_ban = cmd[7:].strip()
            banned_ips.add(ip_to_ban)
            print(f"[INFO] Banned IP: {ip_to_ban}")
            # Disconnect all clients from this IP
            for client, nick in list(nicknames.items()):
                try:
                    if client.getpeername()[0] == ip_to_ban:
                        client.sendall(b"Your IP has been banned by the server.\n")
                        client.close()
                except:
                    pass
        elif cmd.startswith("/unblock "):
            to_unblock = cmd[9:].strip()
            if to_unblock in blocked_nicknames:
                blocked_nicknames.remove(to_unblock)
                print(f"[INFO] Unblocked nickname: {to_unblock}")
        elif cmd.startswith("/unbanip "):
            ip_to_unban = cmd[9:].strip()
            if ip_to_unban in banned_ips:
                banned_ips.remove(ip_to_unban)
                print(f"[INFO] Unbanned IP: {ip_to_unban}")
        elif cmd == "/list":
            print("[INFO] Connected users:", ", ".join(nicknames.values()))
        elif cmd == "/blocked":
            print("[INFO] Blocked nicknames:", ", ".join(blocked_nicknames))
        elif cmd == "/banned":
            print("[INFO] Banned IPs:", ", ".join(banned_ips))
        elif cmd in ("/quit", "/exit"):
            print("[INFO] Shutting down server from console.")
            broadcast(b"SERVER> Server is shutting down.\n")
            break
        elif cmd == "/restart":
            print("[INFO] Restarting server by command.")
            broadcast(b"SERVER> Server is restarting...\n")
            import os, sys
            os.execv(sys.executable, [sys.executable] + sys.argv)
        else:
            print("[INFO] Commands: /msg <text>, /block <nickname>, /banip <ip>, /unblock <nickname>, /unbanip <ip>, /list, /blocked, /banned, /quit, /restart")

if __name__ == "__main__":
    print(f"[INFO] Communicator Server v{SERVER_VERSION} starting on {HOST}:{PORT}")
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((HOST, PORT))
    server_socket.listen(100)
    threading.Thread(target=server_console, daemon=True).start()
    try:
        while True:
            client_socket, address = server_socket.accept()
            clients.append(client_socket)
            threading.Thread(target=handle_client, args=(client_socket, address), daemon=True).start()
    except KeyboardInterrupt:
        print("[INFO] Server shutting down.")
    finally:
        server_socket.close()