"""Drag a track's right edge in the real UI and check the play range actually moved.

  python -m tools.probe_trim [playlist]

The edge drag converts set-time pixels back to source-time milliseconds through
the tempo scaling, so this is the step most likely to be quietly wrong. It reads
play_out_ms and play_s before and after.
"""
from __future__ import annotations

import json
import sys
import time

import webview

from setagent.webui.api import Api
from setagent.webui.app import index_path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

READ = """(() => {
  const t = ST.tracks[3];
  return {i: t.i, title: t.title, preset: t.preset, bpm: t.bpm, set_tempo: t.set_tempo,
          play_in_ms: t.play_in_ms, play_out_ms: t.play_out_ms,
          play_s: t.play_s, phrases: t.phrases.length};
})()"""

DRAG_RIGHT_EDGE = """(() => {
  const n = document.querySelectorAll('.trk')[3];
  const r = n.getBoundingClientRect();
  const host = document.getElementById('tracks');
  const ev = (type, x, el) => el.dispatchEvent(new PointerEvent(type,
      {bubbles: true, clientX: x, clientY: r.top + 30, pointerId: 1}));
  ev('pointerdown', r.right - 3, n);          // inside the 7px grab zone
  ev('pointermove', r.right - 3 - %d, host);  // pull the OUT edge left
  ev('pointerup',   r.right - 3 - %d, host);
  return {width: Math.round(r.width)};
})()"""


def run(window):
    def js(c):
        return window.evaluate_js(c)

    try:
        for i in range(60):
            time.sleep(1)
            if js("!document.getElementById('app').hidden"):
                print(f"ready after {i + 1}s\n")
                break
        time.sleep(1)

        before = js(READ)
        total_before = js("ST.total_s")
        # keep the cut well inside the block: the api refuses a range under 4 s
        pull = max(6, min(12, geom0 := int(js("document.querySelectorAll('.trk')[3]"
                                             ".getBoundingClientRect().width")) // 3))
        geom = js(DRAG_RIGHT_EDGE % (pull, pull))
        time.sleep(3.5)
        after = js(READ)
        total_after = js("ST.total_s")

        density = js("document.getElementById('density').textContent")
        print("density:", density, " block width px:", geom["width"])
        print("before:", json.dumps(before, ensure_ascii=False))
        print("after :", json.dumps(after, ensure_ascii=False))

        pps = 36 / 60.0                            # 'section' zoom
        scale = (before["set_tempo"] / before["bpm"]) if before["bpm"] else 1
        expect_ms = pull / pps * 1000 * scale
        moved_ms = (before["play_out_ms"] or 0) - (after["play_out_ms"] or 0)
        print(f"\nexpected OUT to move ~{expect_ms:.0f} ms, actually moved {moved_ms:.0f} ms")
        print(f"play_s {before['play_s']} -> {after['play_s']}")
        print(f"total  {total_before} -> {total_after}")
        print("preset became:", after["preset"])
        print("phrase blocks:", before["phrases"], "->", after["phrases"])
        ok = (abs(moved_ms - expect_ms) < 1500 and after["play_s"] < before["play_s"]
              and after["preset"] == "custom")
        print("\nTRIM OK" if ok else "\nTRIM LOOKS WRONG")

        js("document.getElementById('undo').click()")
        time.sleep(3.0)
        print("after undo, play_s:", js(READ)["play_s"], "total:", js("ST.total_s"))
    except Exception as ex:
        import traceback
        print("probe failed:", type(ex).__name__, ex)
        traceback.print_exc()
    finally:
        window.destroy()


if __name__ == "__main__":
    api = Api(sys.argv[1] if len(sys.argv) > 1 else "acid")
    w = webview.create_window("Set Agent — Workbench", index_path(), js_api=api,
                              width=1280, height=820, background_color="#0d1014",
                              maximized=True)
    api._window = w
    webview.start(run, w)
