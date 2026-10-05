"""Report FlickFX activity per side: launches (wet peaks) and Decay L/R changes.

    python tools/watch_tails.py [track] [seconds]
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dev_reload import mcp  # noqa: E402

track = int(sys.argv[1]) if len(sys.argv) > 1 else 1
secs = float(sys.argv[2]) if len(sys.argv) > 2 else 600


def params(i):
    return {p["name"]: p for p in mcp("get_device_parameters", track_index=track, device_index=i)["device"]["parameters"]}


devs = mcp("get_track_info", track_index=track)["devices"]
ff = next(d["index"] for d in devs if d["name"] == "FlickFX")
sides = {d["name"][8]: d["index"] for d in devs if d["name"].startswith("FlickFX ") and "·" in d["name"]}
last_decay, peak, t0 = {}, {k: 0.0 for k in sides}, time.time()
while time.time() - t0 < secs:
    fp = params(ff)
    for k in ("Decay L", "Decay R"):
        v = round(fp[k]["value"])
        if last_decay.get(k) not in (None, v):
            print(f"{time.time() - t0:6.1f}s  {k} {last_decay[k]} -> {v} ms", flush=True)
        last_decay[k] = v
    for side, idx in sides.items():
        ps = params(idx)
        wet = next(p["value"] for n, p in ps.items() if "dry" in n.lower() and "wet" in n.lower())
        tail_name = next((n for n in ("Decay Time", "Feedback", "Resonance") if n in ps), None)
        if tail_name and wet < 0.01:      # idle: the held value is the tail base
            tv = round(ps[tail_name]["value"], 3)
            key = side + tail_name
            if last_decay.get(key) not in (None, tv):
                print(f"{time.time() - t0:6.1f}s  {side} {tail_name} {last_decay[key]} -> {tv}", flush=True)
            last_decay[key] = tv
        if wet > peak[side] + 0.05:
            peak[side] = wet
        elif wet < 0.02 and peak[side] > 0.2:
            print(f"{time.time() - t0:6.1f}s  {side} launch peak ~{peak[side]:.2f}", flush=True)
            peak[side] = 0.0
        elif wet < 0.02:
            peak[side] = 0.0
