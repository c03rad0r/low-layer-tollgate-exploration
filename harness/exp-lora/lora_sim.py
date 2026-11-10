#!/usr/bin/env python3
"""E-LORA: how long does a Cashu payment take over 255-byte LoRa frames?

No radio. A stop-and-wait fragment model with independent loss in each
direction; the numbers are airtime plus expected retransmissions, not measured
RF. Token sizes are real P2PK tokens minted in the local Nutshell lab.
"""

from __future__ import annotations

import json
import random
import statistics

FRAME = 255
FRAMES = {
    "1 proof (541 B)": 541,
    "3 proofs (1013 B)": 1013,
    "5 proofs (1487 B)": 1487,
}
BPS = [1000, 5000, 22000]
LOSS = 0.30
RUNS = 1000
SEED = 20261109


def one_run(size: int, bps: float, rng: random.Random) -> dict:
    payload_frames = (size + FRAME - 1) // FRAME
    # One ACK per fragment in this conservative model; the ACK is small.
    sent = 0
    airtime = 0.0
    for _ in range(payload_frames):
        while True:
            sent += 1
            airtime += FRAME * 8 / bps
            if rng.random() >= LOSS:          # fragment arrives
                airtime += 8 * 8 / bps        # tiny ACK
                if rng.random() >= LOSS:      # ACK arrives
                    break
                # ACK lost: resend the fragment
    return {"frames_sent": sent, "airtime_s": airtime}


def main() -> int:
    rng = random.Random(SEED)
    out = {"frame_bytes": FRAME, "loss": LOSS, "runs": RUNS, "seed": SEED,
           "results": []}
    for label, size in FRAMES.items():
        for bps in BPS:
            runs = [one_run(size, bps, rng) for _ in range(RUNS)]
            times = sorted(r["airtime_s"] for r in runs)
            frames = [r["frames_sent"] for r in runs]
            row = {
                "token": label,
                "bytes": size,
                "payload_frames": (size + FRAME - 1) // FRAME,
                "bps": bps,
                "time_s_median": round(statistics.median(times), 2),
                "time_s_p95": round(times[int(0.95 * RUNS) - 1], 2),
                "time_s_max": round(times[-1], 2),
                "frames_sent_median": statistics.median(frames),
                "overhead_x": round(statistics.median(frames) /
                                    ((size + FRAME - 1) // FRAME), 2),
            }
            out["results"].append(row)
            print(json.dumps(row))
    out["contact_windows"] = []
    for window_min in (1, 5, 30):
        for row in out["results"]:
            if row["bps"] == 1000:
                out["contact_windows"].append({
                    "window_min": window_min,
                    "token": row["token"],
                    "used_pct_p95": round(
                        100 * row["time_s_p95"] / (window_min * 60), 1),
                })
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
