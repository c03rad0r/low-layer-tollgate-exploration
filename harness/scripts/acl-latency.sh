#!/usr/bin/env bash
# Measure how long a peer ACL change takes to reach the running daemon.
#
# Usage:
#   acl-latency.sh <host> [runs] [via-host]
#
# Appends a throwaway npub (nobody holds the key) to peers.allow, polls
# `fipsctl acl show` until it appears in the *effective* allow set, restores
# the file, and polls until it disappears. Uses passwordless sudo on the
# remote and always restores from a backup.
#
# Read-only with respect to peers: the npub is random and unused. The only
# writes are the temporary ACL edit and its restore.
set -euo pipefail

HOST=${1:?usage: acl-latency.sh <host> [runs] [via-host]}
RUNS=${2:-3}
VIA=${3:-}
HERE=$(cd "$(dirname "$0")" && pwd)
NPUB=$("$HERE/gen-npub.py")

remote() {
  if [ -n "$VIA" ]; then
    ssh -o BatchMode=yes -o ConnectTimeout=8 "$VIA" \
      "ssh -o BatchMode=yes -o ConnectTimeout=8 $HOST 'NPUB=$NPUB bash -s'"
  else
    ssh -o BatchMode=yes -o ConnectTimeout=8 "$HOST" "NPUB=$NPUB bash -s"
  fi
}

echo "host=$HOST runs=$RUNS throwaway_npub=$NPUB"
remote <<'REMOTE'
set -u
F=/etc/fips/peers.allow
sudo cp "$F" /tmp/allow.bak
python3 - "$NPUB" "$F" "$RUNS" <<'PY'
import json, subprocess, sys, time
npub, path, runs = sys.argv[1], sys.argv[2], int(sys.argv[3])

def effective():
    d = json.loads(subprocess.check_output(["fipsctl", "acl", "show"]))
    return npub in d.get("allow_entries", [])

def wait_for(state, timeout=10.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if effective() == state:
            return (time.monotonic() - t0) * 1000.0
        time.sleep(0.02)
    return -1.0

for run in range(1, runs + 1):
    if effective():
        raise SystemExit("npub unexpectedly present before run")
    subprocess.run(["sudo", "tee", "-a", path], input=(npub + "\n").encode(),
                   stdout=subprocess.DEVNULL, check=True)
    added = wait_for(True)
    subprocess.run(["sudo", "cp", "/tmp/allow.bak", path], check=True)
    removed = wait_for(False)
    print(f"run {run}: add_ms={added:.0f} remove_ms={removed:.0f}")
PY
sudo rm -f /tmp/allow.bak
REMOTE
