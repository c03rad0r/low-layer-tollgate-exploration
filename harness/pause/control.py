#!/usr/bin/env python3
"""Send one mutating command to the local FIPS control socket."""
import json
import socket
import sys

npub = sys.argv[1]
allow = sys.argv[2].lower() in ("1", "true", "allow", "yes")
path = sys.argv[3] if len(sys.argv) > 3 else "/run/fips/control.sock"

sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.connect(path)
request = {"command": "set_forwarding",
           "params": {"npub": npub, "allow": allow}}
sock.sendall((json.dumps(request) + "\n").encode())
data = b""
while not data.endswith(b"\n"):
    chunk = sock.recv(4096)
    if not chunk:
        break
    data += chunk
sock.close()
print(data.decode().strip())
