"""Drag, add and remove target-curve control points in the real UI.

  python -m tools.probe_curve [playlist]
"""
from __future__ import annotations

import json
import sys
import time

import webview

from setagent.webui.api import Api
from setagent.webui.app import index_path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

READ = """({
  curve: ST.curve, knobs: document.querySelectorAll('.knob').length,
  edited: !!ST.curve_edited, dev: (ST.deviation||[]).length,
  label: document.getElementById('curveEdited').textContent.trim(),
})"""

DRAG_KNOB = """(() => {
  const ks = document.querySelectorAll('.knob');
  const k = ks[%d];
  const r = k.getBoundingClientRect();
  const cx = r.left + r.width/2, cy = r.top + r.height/2;
  const ev = (t, x, y, el) => el.dispatchEvent(new PointerEvent(t,
      {bubbles:true, clientX:x, clientY:y, pointerId:1}));
  ev('pointerdown', cx, cy, k);
  ev('pointermove', cx, cy - %d, window);
  ev('pointerup',   cx, cy - %d, window);
  return true;
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

        print("no curve yet:", json.dumps(js(READ), ensure_ascii=False))

        js("const s=document.getElementById('curve'); s.value='peak_late';"
           "s.dispatchEvent(new Event('change',{bubbles:true}));")
        time.sleep(3.5)
        base = js(READ)
        print("\npeak_late:", json.dumps(base, ensure_ascii=False))

        # drag the 2nd control point up by 30 px
        js(DRAG_KNOB % (1, 30, 30))
        time.sleep(3.5)
        moved = js(READ)
        print("\nafter dragging knob #1 up:", json.dumps(moved, ensure_ascii=False))
        up = (base["curve"][1][1] < moved["curve"][1][1]) if len(base["curve"]) > 1 else False
        print("energy of that point went up:", up, " label:", moved["label"])

        js("""(() => {
          const svg = document.querySelector('#energy svg');
          const r = svg.getBoundingClientRect();
          svg.dispatchEvent(new MouseEvent('dblclick',
            {bubbles:true, clientX: r.left + r.width*0.4, clientY: r.top + r.height*0.4}));
        })()""")
        time.sleep(3.5)
        added = js(READ)
        print("\nafter double-click:", len(base["curve"]), "->", len(added["curve"]), "points")

        js("""(() => {
          const ks = document.querySelectorAll('.knob');
          const k = ks[Math.floor(ks.length/2)];
          k.dispatchEvent(new MouseEvent('contextmenu', {bubbles:true}));
        })()""")
        time.sleep(3.5)
        removed = js(READ)
        print("after right-click:", len(added["curve"]), "->", len(removed["curve"]), "points")
        print("knobs drawn:", removed["knobs"], " deviation segments:", removed["dev"])

        ok = (up and len(added["curve"]) == len(base["curve"]) + 1
              and len(removed["curve"]) == len(added["curve"]) - 1)
        print("\nCURVE EDITING OK" if ok else "\nCURVE EDITING LOOKS WRONG")
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
