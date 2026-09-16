"""Smoke-probe the pywebview/WebView2 host before committing the UI to it.

Answers three questions and shows the answers in the window itself:
  1. does a WebView2 window open at all on this machine
  2. does the JS -> Python bridge (js_api) round-trip real data
  3. does it render at the monitor's real pixel density (the whole point of B)

  python -m tools.probe_webview
"""
from __future__ import annotations

import sys

import webview

HTML = """
<!doctype html><meta charset="utf-8">
<style>
  :root{color-scheme:dark}
  body{margin:0;background:#14171c;color:#f0f3f6;
       font:14px/1.6 "IBM Plex Sans","Segoe UI",system-ui,sans-serif;padding:24px}
  h1{font-size:17px;margin:0 0 16px}
  dl{display:grid;grid-template-columns:auto 1fr;gap:6px 16px;margin:0}
  dt{color:#7d8794}
  dd{margin:0;font-family:"IBM Plex Mono",Consolas,monospace}
  .ok{color:#1fb013}.ng{color:#d03b3b}
  canvas{margin-top:20px;border:1px solid #2d333b;border-radius:3px;display:block}
  p{color:#b9c2cc;font-size:13px;margin:14px 0 0}
</style>
<h1>Set Agent — WebView2 probe</h1>
<dl>
  <dt>bridge</dt><dd id="bridge">…</dd>
  <dt>python</dt><dd id="py">…</dd>
  <dt>devicePixelRatio</dt><dd id="dpr">…</dd>
  <dt>CSS viewport</dt><dd id="css">…</dd>
  <dt>backing pixels</dt><dd id="real">…</dd>
  <dt>user agent</dt><dd id="ua" style="font-size:11px">…</dd>
</dl>
<canvas id="c" width="560" height="60"></canvas>
<p>The diagonal below is the actual test: on the old tkinter Canvas it is a staircase.
Here it should be a clean antialiased line, and the 1px hairlines should stay 1px.</p>
<script>
  const $ = id => document.getElementById(id);
  $('dpr').textContent = window.devicePixelRatio;
  $('css').textContent = innerWidth + ' x ' + innerHeight + ' css px';
  $('real').textContent = Math.round(innerWidth*devicePixelRatio) + ' x ' +
                          Math.round(innerHeight*devicePixelRatio) + ' device px';
  $('ua').textContent = navigator.userAgent;

  const c = $('c'), ctx = c.getContext('2d');
  const s = window.devicePixelRatio || 1;
  c.width = 560*s; c.height = 60*s; c.style.width='560px'; c.style.height='60px';
  ctx.scale(s,s);
  ctx.strokeStyle = '#4a9be8'; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(8,52); ctx.lineTo(552,8); ctx.stroke();
  ctx.strokeStyle = '#2d333b'; ctx.lineWidth = 1;
  for (let x = 8.5; x < 552; x += 24){ ctx.beginPath(); ctx.moveTo(x,6); ctx.lineTo(x,54); ctx.stroke(); }
  ctx.fillStyle = '#f0f3f6'; ctx.font = '11px "IBM Plex Mono", monospace';
  ctx.fillText('1分 = 36px の目盛り — 11px の文字が読めるか', 14, 26);

  window.addEventListener('pywebviewready', async () => {
    try {
      const r = await window.pywebview.api.probe({from: 'js'});
      $('bridge').innerHTML = '<span class="ok">round-trip OK</span>';
      $('py').textContent = r.python + '  ·  tracks=' + r.tracks + '  ·  ' + r.playlist;
    } catch (e) {
      $('bridge').innerHTML = '<span class="ng">FAILED: ' + e + '</span>';
    }
  });
</script>
"""


class Api:
    def probe(self, payload):
        """Called from JS. Touches the real library so the bridge is proven end to end."""
        out = {"python": sys.version.split()[0], "echo": payload,
               "tracks": "n/a", "playlist": "library not opened"}
        try:
            from setagent.rekordbox.library import Library
            lib = Library.open()
            names = lib.playlists()
            out["playlist"] = f"{len(names)} playlists"
            if names:
                out["tracks"] = len(lib.playlist_tracks(names[0]))
        except Exception as e:                      # never let a probe crash the window
            out["playlist"] = f"library error: {type(e).__name__}: {e}"
        return out


if __name__ == "__main__":
    webview.create_window("Set Agent — WebView2 probe", html=HTML,
                          width=760, height=520, js_api=Api())
    webview.start()
