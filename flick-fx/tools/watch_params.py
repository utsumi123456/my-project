"""Print the FlickFX-held parameters of a device whenever they change (MCP socket, ~4 Hz).

    python tools/watch_params.py [track] [device] [seconds]
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dev_reload import mcp  # noqa: E402

track = int(sys.argv[1]) if len(sys.argv) > 1 else 1
device = int(sys.argv[2]) if len(sys.argv) > 2 else 1
secs = float(sys.argv[3]) if len(sys.argv) > 3 else 300

last = None
t0 = time.time()
while time.time() - t0 < secs:
    r = mcp("get_device_parameters", track_index=track, device_index=device)
    ps = r["device"]["parameters"] if "device" in r else r["parameters"]
    held = {p["name"]: round(p["value"], 3) for p in ps if not p["is_enabled"]}
    if held != last:
        print(f"{time.time() - t0:6.1f}s  {held}", flush=True)
        last = held
