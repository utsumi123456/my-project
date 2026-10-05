"""Serve index.html in an ordinary browser with a fake pywebview bridge.

  python -m tools.webui_harness [playlist] [port]      # default: acid (if present), 8765

Why: the real panel runs inside WebView2 and cannot be screenshotted reliably
(see tools/winshot.py), so visual review of index.html had to go through the
numeric probes. This dumps one real boot()/load()/state() into a fixture and
answers every bridge call from it, so Chrome / the Claude browser pane can render
the page at 460x940 and show what the CSS actually does. Edits to index.html are
picked up on reload (no caching). Read-only: nothing here touches master.db.
"""
from __future__ import annotations

import http.server
import json
import os
import sys
import tempfile

from setagent.webui.api import Api
from setagent.webui.app import index_path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

STUB = r"""
(async () => {
  const F = await (await fetch("/fixture.json")).json();
  const st = () => structuredClone(F.state);
  const same = async () => st();
  const api = new Proxy({
    boot: async () => structuredClone(F.boot),
    load: same, state: same, rescan: same, undo: same, redo: same,
    artwork: async (ids) => Object.fromEntries(ids.filter(i => F.artwork[i]).map(i => [i, F.artwork[i]])),
    library_changed: async () => ({ready: true, db: "1", wal: "1", edited: false, rekordbox_running: true}),
    llm_status: async () => structuredClone(F.llm),
    agent_status: async () => structuredClone(F.agent),
    select: async () => ({}),
    ask: async (t) => { const s = st(); s.agent = s.agent || {};
      s.agent.chat = [...(s.agent.chat || []), {role: "you", text: t},
        {role: "agent", text: "（ハーネス）本物のエージェントは接続されていません。"}]; return s; },
  }, {get: (o, k) => k in o ? o[k] : same});
  window.pywebview = {api};
  window.dispatchEvent(new Event("pywebviewready"));
  /* ?open=detail|agent|settings opens that surface once the set is on screen,
     so a headless screenshot can show it without clicking */
  const open = new URLSearchParams(location.search).get("open");
  if(open){
    while(document.getElementById("app").hidden) await new Promise(r => setTimeout(r, 50));
    if(open === "detail") document.querySelector("[data-view=detail]").click();
    if(open === "agent") document.getElementById("agentBtn").click();
    if(open === "settings") document.getElementById("settings").click();
  }
})();
"""


def dump_fixture(playlist: str | None) -> dict:
    api = Api()
    b = api.boot()
    if b.get("error"):
        raise SystemExit("boot failed: " + b["error"])
    pl = playlist or ("acid" if "acid" in b["playlists"] else b["playlist"])
    api.load({"playlist": pl, "preset": b.get("preset") or "one_drop", "cap32": True, "target_s": 3600})
    api.set_curve("peak_late")
    s = api.state()
    art = api.artwork([t["track_id"] for t in s["tracks"]][:40], 56)
    return {"boot": b, "state": s, "artwork": art, "llm": api.llm_status(), "agent": api.agent_status()}


def main() -> None:
    playlist = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] != "-" else None
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8765
    fixture = json.dumps(dump_fixture(playlist), ensure_ascii=False).encode("utf-8")
    index = index_path()

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def _send(self, body: bytes, ctype: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                html = open(index, encoding="utf-8").read()
                html = html.replace("<script>", '<script src="/stub.js"></script>\n<script>', 1)
                html = html.replace('window.addEventListener("pywebviewready", boot);',
                                    'window.addEventListener("pywebviewready", boot); if(window.pywebview) boot();')
                self._send(html.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/stub.js":
                self._send(STUB.encode("utf-8"), "text/javascript; charset=utf-8")
            elif path == "/fixture.json":
                self._send(fixture, "application/json; charset=utf-8")
            else:
                self.send_error(404)

    print(f"harness: http://127.0.0.1:{port}/index.html  (Ctrl+C to stop)")
    http.server.ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()


if __name__ == "__main__":
    main()
