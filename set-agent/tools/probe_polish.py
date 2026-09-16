"""Measure the craft floor from inside WebView2 (2026-09-16 polish pass).

  python -m tools.probe_polish [playlist] [width height]

Exit criteria for the polish pass, read off the live DOM rather than the CSS:
  - no rendered text below 11px
  - every text colour on its own background clears WCAG AA (4.5:1; 3:1 at 24px+)
  - every control that reacts to a click can take keyboard focus
  - inputs are wide enough for their placeholder
  - no horizontal overflow at the panel's narrow width
"""
from __future__ import annotations

import json
import sys
import time

import webview

from setagent.webui.api import Api
from setagent.webui.app import index_path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

AUDIT = r"""(() => {
  const lum = c => {
    const m = c.match(/\d+(\.\d+)?/g).map(Number);
    if (m.length > 3 && m[3] === 0) return null;                 // transparent
    const f = v => { v /= 255; return v <= 0.03928 ? v/12.92 : ((v+0.055)/1.055)**2.4; };
    return 0.2126*f(m[0]) + 0.7152*f(m[1]) + 0.0722*f(m[2]);
  };
  const bgOf = el => {
    for (let n = el; n; n = n.parentElement) {
      const c = getComputedStyle(n).backgroundColor;
      if (lum(c) !== null) return c;
    }
    return "rgb(13,16,20)";
  };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); const hi = Math.max(x,y), lo = Math.min(x,y); return (hi+0.05)/(lo+0.05); };
  const visible = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== "hidden"; };

  const small = [], lowContrast = [];
  const seen = new Set();
  for (const el of document.querySelectorAll('#app *')) {
    if (!visible(el)) continue;
    const own = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    if (!own) continue;
    const cs = getComputedStyle(el);
    const px = parseFloat(cs.fontSize);
    const key = el.className + '|' + px + '|' + cs.color;
    if (px < 11) small.push({sel: el.className || el.tagName, px, text: el.textContent.trim().slice(0, 24)});
    if (seen.has(key)) continue; seen.add(key);
    const r = ratio(cs.color, bgOf(el));
    const need = px >= 24 ? 3 : 4.5;
    if (r < need) lowContrast.push({sel: el.className || el.tagName, px, ratio: +r.toFixed(2), color: cs.color, bg: bgOf(el), text: el.textContent.trim().slice(0, 24)});
  }
  const clickable = [...document.querySelectorAll('#app button, #app select, #app input, #app .row, #app .trk, #app .reco, #app .hintq, #app .cand')].filter(visible);
  const unfocusable = clickable.filter(el => el.tabIndex < 0).map(el => el.className || el.tagName);
  const inputs = [...document.querySelectorAll('#app input[type=text]')].filter(visible).map(el => {
    const probe = document.createElement('span');
    probe.style.cssText = `position:absolute;visibility:hidden;white-space:nowrap;font:${getComputedStyle(el).font}`;
    probe.textContent = el.placeholder || el.value; document.body.appendChild(probe);
    const need = probe.getBoundingClientRect().width + 16; probe.remove();
    return {id: el.id, width: Math.round(el.clientWidth), need: Math.round(need), fits: el.clientWidth >= need};
  });
  const fontSizes = [...new Set([...document.querySelectorAll('#app *')].filter(visible).map(el => parseFloat(getComputedStyle(el).fontSize)))].sort((a,b)=>a-b);
  return {
    viewport: [innerWidth, innerHeight],
    fontSizes, small, lowContrast, unfocusable: [...new Set(unfocusable)],
    inputs,
    overflow: document.documentElement.scrollWidth > innerWidth || document.getElementById('main').scrollWidth > document.getElementById('main').clientWidth,
    focusRule: [...document.styleSheets[0].cssRules].some(r => r.selectorText && r.selectorText.includes(':focus-visible') && r.selectorText.includes('select')),
  };
})()"""


def run(window):
    try:
        for i in range(60):
            time.sleep(1)
            try:
                if window.evaluate_js("!document.getElementById('app').hidden && document.getElementById('curtain').hidden"):
                    break
            except Exception:
                pass
        time.sleep(1.5)
        for view in ("main", "detail"):
            window.evaluate_js(f"setView('{view}')")
            time.sleep(1)
            a = window.evaluate_js(AUDIT)
            a["view"] = view
            print(json.dumps(a, ensure_ascii=False, indent=1))
            ok = not a["small"] and not a["lowContrast"] and not a["unfocusable"] and all(i["fits"] for i in a["inputs"]) and not a["overflow"]
            print(f"== {view}: {'PASS' if ok else 'FAIL'}\n")
    except Exception as ex:
        print("probe failed:", type(ex).__name__, ex)
    finally:
        window.destroy()


if __name__ == "__main__":
    pl = sys.argv[1] if len(sys.argv) > 1 else "acid"
    w_, h_ = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) > 3 else (460, 940)
    api = Api(pl)
    w = webview.create_window("Set Agent — probe", index_path(), js_api=api,
                              width=w_, height=h_, background_color="#0d1014")
    api._window = w
    webview.start(run, w)
