"""Simulate one flick through FlickFX and sample the target Dry/Wet in Live.

Runs the real FlickEnvelope at ~500 Hz, sends /wet over UDP like flick_fx.py,
and reads the parameter back through the AbletonMCP socket (port 9877).

    python tools/probe_flick.py [track] [device] [param]
"""
import json
import socket
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import flick_fx as f  # noqa: E402

track, device, param = (int(a) for a in (sys.argv[1:4] if len(sys.argv) > 3 else (2, 0, 32)))


def read_param() -> float:
    with socket.create_connection(("127.0.0.1", 9877), timeout=5) as s:
        s.sendall(json.dumps({"type": "get_device_parameters",
                              "params": {"track_index": track, "device_index": device}}).encode())
        buf = b""
        while True:
            buf += s.recv(65536)
            try:
                r = json.loads(buf)
                break
            except json.JSONDecodeError:
                continue
    r = r.get("result", r)
    params = r["device"]["parameters"] if "device" in r else r["parameters"]
    return params[param]["value"]


def drive(env, osc, stop):
    prev = time.perf_counter()
    t0 = prev
    while not stop.is_set():
        now = time.perf_counter()
        dt, prev = now - prev, now
        y = 0.9 if now - t0 < 0.04 else 0.0      # 40 ms flick to 90 %
        osc.send("/wet", env.step(0.0, y, dt))
        time.sleep(0.002)


env = f.FlickEnvelope(decay_s=0.8)
osc = f.OscOut(9031)
stop = threading.Event()
osc.send("/wet", 0.0)
time.sleep(0.1)
th = threading.Thread(target=drive, args=(env, osc, stop))
t0 = time.perf_counter()
th.start()
samples = []
while time.perf_counter() - t0 < 1.2:
    samples.append((time.perf_counter() - t0, read_param()))
stop.set()
th.join()
for t, v in samples:
    print(f"{t * 1000:6.0f} ms  {v:5.3f}  {'#' * round(v * 40)}")
peak = max(v for _, v in samples)
print(f"peak {peak:.3f}  end {samples[-1][1]:.3f}")
