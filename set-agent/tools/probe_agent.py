"""Drive the agent drawer from inside WebView2 and report what it did.

  python -m tools.probe_agent [playlist]

Checks the B-8 boundary end to end: ask -> reply -> candidates -> a Change Set
that is only applied for the ticked items, with the ghost timeline moving when
an item is unticked.
"""
from __future__ import annotations

import json
import sys
import time

import webview

import os
os.environ.setdefault("SETAGENT_LLM_BACKEND", "api")   # deterministic: Advisor unless a key is set

from setagent.webui.api import Api
from setagent.webui.app import index_path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SNAP = """({
  drawerOpen: !document.getElementById('drawer').hidden,
  status: document.getElementById('agentStatus').textContent.slice(0, 40),
  level: document.getElementById('level').value,
  msgs: document.querySelectorAll('#chat .msg').length,
  lastMsg: (document.querySelector('#chat .msg:last-child')||{}).textContent,
  cands: document.querySelectorAll('.cand').length,
  hasCard: !!document.querySelector('#pending .card'),
  ops: [...document.querySelectorAll('#pending .op')].map(c => c.checked),
  opText: [...document.querySelectorAll('#pending .card label span')].map(s => s.textContent),
  diff: [...document.querySelectorAll('#pending .diff span')].map(s => s.textContent),
  ghosts: document.querySelectorAll('.ghost').length,
  hero: document.getElementById('hero').textContent,
  plog: document.getElementById('plog').textContent,
})"""


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

        out = []
        js("document.getElementById('agentBtn').click()")
        time.sleep(1.2)
        out.append(("ドロワーを開く", js(SNAP)))

        for q in ("今のセット何分？", "バランスどう？", "候補を出して"):
            js(f"document.getElementById('askText').value = {json.dumps(q)};"
               "document.getElementById('askSend').click()")
            time.sleep(4.0)
            out.append((f"「{q}」", js(SNAP)))

        if js("document.querySelectorAll('.cand').length > 0"):
            js("document.querySelector('.cand').click()")
            time.sleep(4.0)
            out.append(("候補をクリックして挿入案", js(SNAP)))

            if js("document.querySelectorAll('#pending .op').length > 0"):
                before = js("document.querySelectorAll('.ghost').length")
                js("const c = document.querySelector('#pending .op'); c.checked = false;"
                   "c.dispatchEvent(new Event('change', {bubbles:true}));")
                time.sleep(3.0)
                after = js("document.querySelectorAll('.ghost').length")
                out.append(("1件のチェックを外す",
                            {**js(SNAP), "ghostsBefore": before, "ghostsAfter": after}))
                js("const c = document.querySelector('#pending .op'); c.checked = true;"
                   "c.dispatchEvent(new Event('change', {bubbles:true}));")
                time.sleep(3.0)
                js("document.getElementById('applyPending').click()")
                time.sleep(4.0)
                out.append(("適用", js(SNAP)))

        for label, snap in out:
            print(f"--- {label}")
            print(json.dumps(snap, ensure_ascii=False)[:900])
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
