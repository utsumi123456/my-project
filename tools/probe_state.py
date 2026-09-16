"""Exercise the webui state builder without opening a window.

  python -m tools.probe_state [playlist]
"""
from __future__ import annotations

import json
import sys

from setagent.webui.api import Api

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

api = Api()
b = api.boot()
if b.get("error"):
    print("BOOT FAILED:", b["error"]); print(b.get("detail", "")); raise SystemExit(1)
print("playlists:", len(b["playlists"]), "->", b["playlist"])

name = sys.argv[1] if len(sys.argv) > 1 else b["playlist"]
s = api.load({"playlist": name, "preset": "one_drop", "cap32": True, "target_s": 3600})
if s.get("error") and not s.get("tracks"):
    print("LOAD FAILED:", s["error"]); print(s.get("detail", "")); raise SystemExit(1)

print("total", s["total_s"], "target", s["target_s"], "delta", s["delta_s"])
print("tracks", len(s["tracks"]), "energy pts", len(s["energy"]),
      "sections", len(s["sections"]), "trims", len(s["trims"]),
      "trim_total", s["trim_total_s"])
print("analysis", s["analysis"])
print("warnings:")
for w in s["warnings"][:6]:
    print("  ", w["level"], w["text"])

with_ph = [t for t in s["tracks"] if t["phrases"]]
print("tracks with phrase strip:", len(with_ph), "/", len(s["tracks"]))
if with_ph:
    t = with_ph[0]
    print("sample track:", json.dumps({k: t[k] for k in
          ("i", "title", "bpm", "start_s", "end_s", "play_s", "preset")},
          ensure_ascii=False))
    print("  phrases:")
    for p in t["phrases"]:
        print("   %-8s %-7s %8.2f -> %8.2f" % (p["label"], p["group"], p["start_s"], p["end_s"]))
    span = t["phrases"][-1]["end_s"] - t["phrases"][0]["start_s"]
    print("  phrase span %.2fs vs play_s %.2fs" % (span, t["play_s"]))

api.set_curve("peak_late")
s2 = api.state()
print("curve points", len(s2["curve"]), "deviation segs", len(s2["deviation"]))
print("OK")
