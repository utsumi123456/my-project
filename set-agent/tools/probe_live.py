"""Open the real panel and log what the DJ's rekordbox edits do to it, live.

  python -m tools.probe_live [playlist] [--minutes 10] [--stop output/live.stop]

No screenshots: every second it asks the view for the hero, row count, first
rows and freshness state, and prints a line whenever any of them change. Edit
the playlist in rekordbox while this runs; the WAL replay should make the
change show up within one poll interval (5 s) without touching the app.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import webview

from setagent.webui.api import Api
from setagent.webui.app import index_path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROBE = """(() => {
  const txt = id => (document.getElementById(id)||{}).textContent || "";
  const rows = [...document.querySelectorAll('.row')];
  return {
    ready: !document.getElementById('app').hidden && document.getElementById('curtain').hidden,
    hero: txt('hero').trim(),
    sub: txt('heroSub').replace(/\\s+/g,' ').trim(),
    rows: rows.length,
    titles: rows.slice(0, 4).map(r => (r.querySelector('.t')||r).textContent.replace(/\\s+/g,' ').trim().slice(0, 28)),
    fresh: FRESH.state, freshTxt: txt('freshTxt').trim(),
    loaded: LOADED_AT && LOADED_AT.toLocaleTimeString('ja-JP'),
  };
})()"""


def run(window, minutes: float, stop: Path):
    prev = None
    deadline = time.time() + minutes * 60
    try:
        while time.time() < deadline and not stop.exists():
            time.sleep(1)
            try:
                cur = window.evaluate_js(PROBE)
            except Exception:
                continue
            if cur != prev:
                t = datetime.now().strftime("%H:%M:%S")
                if prev is None or not cur.get("ready"):
                    print(t, "state:", cur, flush=True)
                else:
                    diff = {k: (prev.get(k), v) for k, v in cur.items() if prev.get(k) != v}
                    print(t, "changed:", diff, flush=True)
                prev = cur
        print(datetime.now().strftime("%H:%M:%S"), "end:", "stopfile" if stop.exists() else "timeout")
    finally:
        window.destroy()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("playlist", nargs="?", default=None)
    ap.add_argument("--minutes", type=float, default=10)
    ap.add_argument("--stop", default="output/live.stop")
    a = ap.parse_args()
    stop = Path(a.stop)
    stop.parent.mkdir(parents=True, exist_ok=True)
    stop.unlink(missing_ok=True)
    api = Api(a.playlist)
    w = webview.create_window("Set Agent — live probe", index_path(), js_api=api,
                              width=460, height=940, background_color="#0d1014", on_top=True)
    api._window = w
    webview.start(run, (w, a.minutes, stop))
