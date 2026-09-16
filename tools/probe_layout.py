"""Boot the workbench, measure the real layout from inside WebView2, print, quit.

  python -m tools.probe_layout [playlist]

Screenshots are a poor way to check a UI you cannot bring to the front. This asks
the view itself: how tall is each lane, is it inside the viewport, did the energy
SVG actually render, how many track blocks are on screen. Numbers, not pixels.
"""
from __future__ import annotations

import json
import sys
import time

import webview

from setagent.webui.api import Api
from setagent.webui.app import index_path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROBE = """
(() => {
  const box = sel => {
    const e = document.querySelector(sel);
    if (!e) return null;
    const b = e.getBoundingClientRect();
    return {top: Math.round(b.top), bottom: Math.round(b.bottom),
            h: Math.round(b.height),
            onscreen: b.top < innerHeight && b.bottom > 0 && b.height > 0};
  };
  return {
    viewport: [innerWidth, innerHeight],
    dpr: devicePixelRatio,
    bar:       box('.bar'),
    hero:      box('.hero-block'),
    transport: box('.transport'),
    scroll:    box('#scroll'),
    tracks:    box('#tracks'),
    energy:    box('#energy'),
    sections:  box('#sections'),
    legend:    box('.legend'),
    foot:      box('.foot'),
    energySvg:  !!document.querySelector('#energy svg'),
    energyPaths: document.querySelectorAll('#energy path').length,
    sectionRows: document.querySelectorAll('.sec').length,
    trackBlocks: document.querySelectorAll('.trk').length,
    phraseBlocks: document.querySelectorAll('.trk .ph').length,
    noAnalysis:  document.querySelectorAll('.trk .none').length,
    hero: (document.getElementById('hero')||{}).textContent,
    canvasWidth: Math.round((document.getElementById('canvas')||{}).clientWidth || 0),
    controls: ['settings','tPreset','tTempo','tMile','reco','list'].filter(
      id => !document.getElementById(id)),
  };
})()
"""


def run(window):
    try:
        for i in range(60):            # loading 96 tracks of phrase data takes a while
            time.sleep(1)
            try:
                if window.evaluate_js("!document.getElementById('app').hidden"):
                    print(f"ready after {i + 1}s")
                    break
            except Exception:
                pass
        else:
            print("never became ready — still on the boot curtain")
        time.sleep(1)
        r = window.evaluate_js(PROBE)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        lanes = {k: r[k] for k in ("tracks", "energy", "sections")}
        bad = [k for k, v in lanes.items() if not (v and v["onscreen"])]
        print("\nTier 1 lanes off screen:", bad or "none")
        print("missing controls:", r["controls"] or "none")
    except Exception as ex:
        print("probe failed:", type(ex).__name__, ex)
    finally:
        window.destroy()


if __name__ == "__main__":
    api = Api(sys.argv[1] if len(sys.argv) > 1 else "acid")
    w = webview.create_window("Set Agent — Workbench", index_path(), js_api=api,
                              width=1280, height=820, background_color="#0d1014",
                              maximized=True)
    api._window = w
    webview.start(run, w)
