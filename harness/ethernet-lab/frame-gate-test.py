#!/usr/bin/env python3
"""nft netdev frame-gate correctness test.

Builds a veth pair inside the container and exercises a netdev ingress chain
that matches EtherType 0x2121 against an authorised-MAC set.

Two observation points are used, because AF_PACKET is *not* one:

* AF_PACKET taps run before the netdev ingress hook, so a packet socket still
  sees frames that nft drops. Counting there gives a false pass.
* nft counters are authoritative for rule matching.
* For a control case, a real IPv4/UDP packet is sent and received through the
  same chain. If an `ether type 0x0800 drop` rule blocks delivery to a UDP
  socket, the ingress hook is on the real receive path.

Cases:

  1. no table                     UDP passes
  2. `0x0800 drop`                UDP delivery blocked (control)
  3. `0x2121` gate, empty set     UDP passes; 0x2121 drop counter rises
  4. sender MAC authorised        0x2121 accept counter rises, drop does not
  5. sender MAC removed           0x2121 drop counter rises again
  6. unauthorised source MAC      0x2121 drop counter rises

This is a correctness test, not a throughput test. It says nothing about the
captive-portal (ndsctl) case, which needs a real AP. MACs are spoofable: this is
rate/abuse control, not authorisation.
"""

import re
import socket
import struct
import subprocess
import sys
import time

ETH_P_ALL = 0x0003
ETH_P_IPV4 = 0x0800
ETH_P_FIPS = 0x2121
ETH_P_OTHER = 0x88B5

SENDER = "02:00:00:00:00:01"
OTHER = "02:00:00:00:00:03"
RECEIVER = "02:00:00:00:00:02"
IF_TX = "v0"
IF_RX = "v1"
SRC_IP = "10.0.0.3"   # not assigned locally: avoids the martian-source check
DST_IP = "10.0.0.2"
UDP_PORT = 9999


def mac(text):
    return bytes.fromhex(text.replace(":", ""))


def run(*cmd, check=True):
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def setup_links():
    run("ip", "link", "add", IF_TX, "type", "veth", "peer", "name", IF_RX)
    run("ip", "link", "set", IF_TX, "address", SENDER)
    run("ip", "link", "set", IF_RX, "address", RECEIVER)
    run("ip", "link", "set", IF_TX, "up")
    run("ip", "link", "set", IF_RX, "up")
    # Only the receive side needs an address. Assigning SRC_IP locally would
    # make the packet a martian source on IF_RX and rp_filter=2 would drop it.
    run("ip", "addr", "add", f"{DST_IP}/24", "dev", IF_RX)


def drop_table():
    run("nft", "delete", "table", "netdev", "tollgate", check=False)


def add_chain():
    run("nft", "add", "table", "netdev", "tollgate")
    run(
        "nft", "add", "chain", "netdev", "tollgate", "ingress",
        "{", "type", "filter", "hook", "ingress", "device", IF_RX,
        "priority", "0;", "}",
    )


def add_mac_set():
    run(
        "nft", "add", "set", "netdev", "tollgate", "authorised_macs",
        "{", "type", "ether_addr;", "}",
    )


def add_fips_gate():
    add_chain()
    add_mac_set()
    run(
        "nft", "add", "rule", "netdev", "tollgate", "ingress",
        "ether", "type", hex(ETH_P_FIPS),
        "ether", "saddr", "@authorised_macs", "counter", "accept",
    )
    run(
        "nft", "add", "rule", "netdev", "tollgate", "ingress",
        "ether", "type", hex(ETH_P_FIPS), "counter", "drop",
    )


def set_add(addr):
    run("nft", "add", "element", "netdev", "tollgate", "authorised_macs",
        "{", addr, "}")


def set_del(addr):
    run("nft", "delete", "element", "netdev", "tollgate", "authorised_macs",
        "{", addr, "}")


def counters():
    """Return {'accept': n, 'drop': n} from the chain's anonymous counters."""
    text = run("nft", "list", "chain", "netdev", "tollgate", "ingress").stdout
    out = {"accept": 0, "drop": 0}
    for packets, verdict in re.findall(
            r"counter packets (\d+) bytes \d+ (accept|drop)", text):
        out[verdict] = int(packets)
    return out


def ip_checksum(header):
    total = sum(struct.unpack("!10H", header))
    total = (total & 0xFFFF) + (total >> 16)
    total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF


def udp_frame():
    payload = b"tollgate-frame-gate"
    udp = struct.pack("!HHHH", UDP_PORT, UDP_PORT, 8 + len(payload), 0) + payload
    src = socket.inet_aton(SRC_IP)
    dst = socket.inet_aton(DST_IP)
    ip = struct.pack("!BBHHHBBH4s4s",
                     0x45, 0, 20 + len(udp), 1, 0, 64, 17, 0, src, dst)
    ip = ip[:10] + struct.pack("!H", ip_checksum(ip)) + ip[12:]
    return mac(RECEIVER) + mac(SENDER) + struct.pack("!H", ETH_P_IPV4) + ip + udp


def fips_frame(src=SENDER):
    return mac(RECEIVER) + mac(src) + struct.pack("!H", ETH_P_FIPS) + b"\x00" * 32


def send_raw(frames):
    sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW)
    sock.bind((IF_TX, 0))
    for frame in frames:
        sock.send(frame)
    sock.close()


def udp_roundtrip(count):
    """Send `count` IPv4/UDP frames and count how many are delivered."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", UDP_PORT))
    sock.settimeout(0.1)
    send_raw([udp_frame() for _ in range(count)])
    got = 0
    deadline = time.monotonic() + 1.0
    while got < count and time.monotonic() < deadline:
        try:
            sock.recvfrom(2048)
            got += 1
        except socket.timeout:
            continue
    sock.close()
    return got


def main():
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    setup_links()
    results = []

    got = udp_roundtrip(count)
    results.append(("baseline: no table, IPv4/UDP delivered", got, count))

    drop_table()
    add_chain()
    run("nft", "add", "rule", "netdev", "tollgate", "ingress",
        "ether", "type", hex(ETH_P_IPV4), "counter", "drop")
    got = udp_roundtrip(count)
    results.append(("control: 0x0800 drop, IPv4/UDP delivered", got, 0))
    results.append(("control: 0x0800 drop counter", counters()["drop"], count))

    drop_table()
    add_fips_gate()

    got = udp_roundtrip(count)
    results.append(("0x2121 gate does not affect IPv4/UDP", got, count))

    before = counters()
    send_raw([fips_frame() for _ in range(count)])
    after = counters()
    results.append(("empty MAC set: 0x2121 accepted", after["accept"] - before["accept"], 0))
    results.append(("empty MAC set: 0x2121 dropped", after["drop"] - before["drop"], count))

    set_add(SENDER)
    before = counters()
    send_raw([fips_frame() for _ in range(count)])
    after = counters()
    results.append(("sender authorised: 0x2121 accepted", after["accept"] - before["accept"], count))
    results.append(("sender authorised: 0x2121 dropped", after["drop"] - before["drop"], 0))

    set_del(SENDER)
    before = counters()
    send_raw([fips_frame() for _ in range(count)])
    after = counters()
    results.append(("sender removed: 0x2121 dropped", after["drop"] - before["drop"], count))

    before = counters()
    send_raw([fips_frame(src=OTHER) for _ in range(count)])
    after = counters()
    results.append(("unauthorised MAC: 0x2121 dropped", after["drop"] - before["drop"], count))

    print(f"frames per case: {count}")
    print(f"links: {IF_TX} <-> {IF_RX}")
    print()
    ok = True
    for name, got, want in results:
        status = "PASS" if got == want else "FAIL"
        if got != want:
            ok = False
        print(f"{status}  {name:46s} got={got:4d} want={want:4d}")

    print()
    print(run("nft", "list", "table", "netdev", "tollgate").stdout)
    print("Note: MACs are spoofable. This gate is rate/abuse control, not")
    print("authorisation. Authorisation is the FMP link gate keyed on npub.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
