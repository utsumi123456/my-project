"""Boot the two-view workbench, measure both views from inside WebView2, quit.

  python -m tools.probe_views [playlist] [width height]

Read-only redesign (2026-09-16): the main view must carry the predicted length
as its hero and hold at a narrow width; the detail view must still show all the
lanes. This asks the view itself for numbers instead of a screenshot.
"""
from __future__ import annotations

import json
import sys
import time

import webview

from setagent.webui.api import Api
from setagent.webui.app import index_path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BOX = """
const box = sel => {
  const e = document.querySelector(sel);
  if (!e) return null;
  const b = e.getBoundingClientRect();
  return {top: Math.round(b.top), bottom: Math.round(b.bottom), h: Math.round(b.height),
          w: Math.round(b.width),
          onscreen: b.top < innerHeight && b.bottom > 0 && b.height > 0};
};
"""

MAIN = "(() => {" + BOX + """
  const txt = id => (document.getElementById(id)||{}).textContent || "";
  return {
    view: 'main',
    viewport: [innerWidth, innerHeight],
    hero: txt('hero').trim(),
    heroClass: (document.getElementById('hero')||{}).className,
    heroSub: txt('heroSub').replace(/\\s+/g,' ').trim(),
    heroFontPx: parseFloat(getComputedStyle(document.getElementById('hero')).fontSize),
    reco: {hidden: document.getElementById('reco').hidden,
           cls: document.getElementById('reco').className,
           q: document.getElementById('reco').dataset.q,
           text: txt('reco').replace(/\\s+/g,' ').trim()},
    rows: document.querySelectorAll('.row').length,
    pastRows: document.querySelectorAll('.row.past').length,
    firstRow: (document.querySelector('.row')||{}).textContent?.replace(/\\s+/g,' ').trim(),
    lastRow: [...document.querySelectorAll('.row')].pop()?.textContent.replace(/\\s+/g,' ').trim(),
    fresh: txt('freshTxt').trim(),
    plName: txt('plName'),
    boxes: {bar: box('.bar'), main: box('#main'), hero: box('.hero-block'),
            reco: box('#reco'), conds: box('.cond-row'), list: box('#list'), fresh: box('.fresh')},
    detailHidden: document.getElementById('detail').hidden,
    horizontalOverflow: document.documentElement.scrollWidth > innerWidth,
    mainOverflowX: document.getElementById('main').scrollWidth > document.getElementById('main').clientWidth,
    gone: ['export','verdict'].filter(id => document.getElementById(id)),
  };
})()"""

DETAIL = "(() => {" + BOX + """
  return {
    view: 'detail',
    mainHidden: document.getElementById('main').hidden,
    transport: box('.transport'), scroll: box('#scroll'), tracks: box('#tracks'),
    energy: box('#energy'), sections: box('#sections'), legend: box('.legend'),
    reality: box('#reality'), foot: box('.foot'),
    energySvg: !!document.querySelector('#energy svg'),
    energyPaths: document.querySelectorAll('#energy path').length,
    trackBlocks: document.querySelectorAll('.trk').length,
    phraseBlocks: document.querySelectorAll('.trk .ph').length,
    sectionRows: document.querySelectorAll('.sec').length,
    canvasWidth: Math.round(document.getElementById('canvas').clientWidth),
    minimapChildren: document.getElementById('minimap').children.length,
    realityHead: (document.querySelector('#reality h3')||{}).textContent,
    warns: document.querySelectorAll('#warns li').length,
  };
})()"""


def run(window):
    try:
        for i in range(60):
            time.sleep(1)
            try:
                if window.evaluate_js("!document.getElementById('app').hidden"):
                    print(f"ready after {i + 1}s")
                    break
            except Exception:
                pass
        else:
            print("never became ready")
        time.sleep(1)
        m = window.evaluate_js(MAIN)
        print(json.dumps(m, ensure_ascii=False, indent=2))

        # select a row from the list, then switch to the detail view
        window.evaluate_js("document.querySelectorAll('.row')[2].click()")
        time.sleep(0.5)
        sel = window.evaluate_js(
            "[...document.querySelectorAll('.row')].findIndex(r => r.dataset.sel === '1')")
        print("selected row after click:", sel)

        window.evaluate_js("document.querySelector('[data-view=detail]').click()")
        time.sleep(1)
        d = window.evaluate_js(DETAIL)
        print(json.dumps(d, ensure_ascii=False, indent=2))
        selTitle = window.evaluate_js("document.getElementById('selTitle').textContent")
        print("inspector shows:", selTitle)
        lanes = {k: d[k] for k in ("tracks", "energy", "sections")}
        bad = [k for k, v in lanes.items() if not (v and v["onscreen"])]
        print("\nTier lanes off screen in detail:", bad or "none")

        window.evaluate_js("document.querySelector('[data-view=main]').click()")
        time.sleep(0.3)
        print("back to main, detail hidden:",
              window.evaluate_js("document.getElementById('detail').hidden"))
    except Exception as ex:
        print("probe failed:", type(ex).__name__, ex)
    finally:
        window.destroy()


if __name__ == "__main__":
    pl = sys.argv[1] if len(sys.argv) > 1 else "acid"
    w_, h_ = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) > 3 else (1280, 820)
    api = Api(pl)
    w = webview.create_window("Set Agent — probe", index_path(), js_api=api,
                              width=w_, height=h_, background_color="#0d1014",
                              maximized=(len(sys.argv) <= 3))
    api._window = w
    webview.start(run, w)
