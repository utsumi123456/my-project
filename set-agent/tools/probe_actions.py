"""Drive the real UI from inside WebView2 and report what each control did.

  python -m tools.probe_actions [playlist]

This is the wiring test: a handler can be syntactically fine and still call the
wrong bridge method. Each step fires a real DOM event and then reads the state
back out of the view, so a silent mis-wire shows up as an unchanged value.
"""
from __future__ import annotations

import json
import sys
import time

import webview

from setagent.webui.api import Api
from setagent.webui.app import index_path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SNAP = """({
  title: (document.getElementById('selTitle')||{}).textContent,
  preset: (ST && ST.tracks.find(t => t.i === ST.selected) || {}).preset,
  tempo: (ST && ST.tracks.find(t => t.i === ST.selected) || {}).set_tempo,
  mile: (ST && ST.tracks.find(t => t.i === ST.selected) || {}).milestone_s != null,
  locks: (ST && ST.tracks.find(t => t.i === ST.selected) || {locks: []}).locks,
  setBpm: ST && ST.set_bpm,
  hero: document.getElementById('hero').textContent,
  mileMarks: document.querySelectorAll('.mile').length,
  selected: document.querySelectorAll('.trk[data-sel="1"]').length,
  firstTitle: (document.querySelector('.trk .trk-t')||{}).textContent,
  modalOpen: !document.getElementById('modal').hidden,
  modalTitle: (document.getElementById('mTitle')||{}).textContent,
  toast: document.getElementById('toast').hidden ? null
         : document.getElementById('toast').textContent,
})"""

CLICK_TRACK = """(() => {
  const n = document.querySelectorAll('.trk')[%d];
  const r = n.getBoundingClientRect();
  const o = {bubbles:true, clientX: r.left + 4, clientY: r.top + 10, pointerId: 1};
  n.dispatchEvent(new PointerEvent('pointerdown', o));
  n.dispatchEvent(new PointerEvent('pointerup', o));
  return n.dataset.i;
})()"""

FIRE = "(() => { const e = document.getElementById('%s'); %s; " \
       "e.dispatchEvent(new Event('change', {bubbles:true})); return true; })()"


def run(window):
    def js(code):
        return window.evaluate_js(code)

    def settle(s=1.6):
        time.sleep(s)

    try:
        for i in range(60):
            time.sleep(1)
            try:
                if js("!document.getElementById('app').hidden"):
                    print(f"ready after {i + 1}s\n")
                    break
            except Exception:
                pass
        settle()

        steps = []

        idx = js(CLICK_TRACK % 5)
        settle()
        steps.append(("6曲目をクリックして選択", js(SNAP)))

        # the per-track edit controls left the panel (2026-09-16); the commands
        # still exist on the bridge, which is what the agent's Change Sets use
        js("(async()=>apply(await window.pywebview.api.set_preset(ST.selected, 'short')))()")
        settle(2.5)
        steps.append(("プリセットを short に（bridge）", js(SNAP)))

        js("(async()=>apply(await window.pywebview.api.set_milestone(ST.selected, 600)))()")
        settle(2.5)
        steps.append(("マイルストーンをオン（bridge）", js(SNAP)))

        js("(async()=>apply(await window.pywebview.api.set_lock(ST.selected, 'position', true)))()")
        settle(2.5)
        steps.append(("位置をロック（bridge）", js(SNAP)))

        js(FIRE % ("setBpm", "e.value='160'"))
        settle(2.5)
        steps.append(("Set BPM を 160 に", js(SNAP)))

        js("document.getElementById('undo').click()")
        settle(2.5)
        steps.append(("元に戻す", js(SNAP)))

        js("document.getElementById('settings').click()")
        settle(2.0)
        steps.append(("設定を開く", js(SNAP)))
        js("document.querySelector('#mActions button').click()")   # やめる
        settle(0.8)

        js("setView('detail')")            # the lanes live in the detail view now
        settle(1.0)
        js("document.querySelectorAll('[data-zoom]')[1].click()")
        settle(2.0)
        steps.append(("詳細ズーム", js(
            "Object.assign(" + SNAP + ", {"
            "density: document.getElementById('density').textContent,"
            "canvasW: document.getElementById('canvas').clientWidth,"
            "energyH: Math.round(document.getElementById('energy').clientHeight)})")))

        js("document.querySelectorAll('[data-zoom]')[1].click()")
        settle(1.5)
        before = js("[...document.querySelectorAll('.trk .trk-t')].slice(0,4)"
                    ".map(n => n.textContent)")
        js("""(() => {
          const ns = document.querySelectorAll('.trk');
          const a = ns[0], b = ns[3];
          const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
          const host = document.getElementById('tracks');
          const ev = (t, x, el) => el.dispatchEvent(new PointerEvent(t,
              {bubbles: true, clientX: x, clientY: ra.top + 12, pointerId: 1}));
          ev('pointerdown', ra.left + ra.width / 2, a);   // mid-block: the 7px edge zone would trim, not move
          ev('pointermove', rb.left + rb.width - 3, host);
          ev('pointerup',  rb.left + rb.width - 3, host);
          return true;
        })()""")
        settle(3.0)
        after = js("[...document.querySelectorAll('.trk .trk-t')].slice(0,4)"
                   ".map(n => n.textContent)")
        steps.append(("1曲目を4曲目の後ろへドラッグ",
                      {"before": before, "after": after,
                       "reordered": before != after,
                       "hero": js("document.getElementById('hero').textContent")}))

        for label, snap in steps:
            print(f"--- {label}")
            print(json.dumps(snap, ensure_ascii=False))
            print()
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
