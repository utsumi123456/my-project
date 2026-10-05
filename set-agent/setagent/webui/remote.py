"""Open the panel on a phone on the same Wi-Fi (2026-10-05).

The PC keeps running the one Api; this serves the very same index.html over
HTTP on the LAN and turns each `pywebview.api.<name>(...)` call into a POST to
/api/<name>. The phone is a second view of the same set, not a copy: an edit
on either side shows up on the other through Api.sync_rev().

How a phone gets in: the PC shows a QR code for http://<lan-ip>:<port>/?k=<key>.
The key is random per server start and is checked on every request, so another
device on the same Wi-Fi that did not scan the code gets a 403. Only private
(LAN) addresses are answered at all. The server starts when the DJ asks for the
QR code, not with the app, so nothing listens on the network by default.

stdlib only (http.server); the QR image comes from segno (pure Python).
"""
from __future__ import annotations

import hmac
import ipaddress
import json
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORTS = range(8760, 8780)
MAX_BODY = 1 << 20      # the largest call (ask / artwork ids) is a few KB

# What a phone may call. Everything else -- the API key, the Claude login
# console, restarting rekordbox, the native save dialog -- acts on the PC itself
# and stays on the PC.
ALLOWED = frozenset({
    "boot", "load", "state", "select", "set_curve", "set_milestone", "set_preset",
    "set_range", "set_tempo", "set_lock", "move", "set_target", "undo", "redo",
    "rescan", "set_set_bpm", "set_bpm_change", "move_curve_point", "add_curve_point",
    "remove_curve_point", "export_preview", "llm_status", "agent_status", "set_level",
    "ask", "insert_candidate", "set_item_approved", "apply_pending", "reject_pending",
    "artwork", "library_changed", "sync_rev",
})
PC_ONLY = "この操作は PC の Set Agent で行ってください"

# Injected ahead of the page's own script. It stands in for pywebview's bridge:
# same names, same promise-returning calls, and the same "pywebviewready" event.
SHIM = """<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<script>
(function(){
  const q = new URLSearchParams(location.search);
  const key = q.get("k") || "";
  let me = "";
  try { me = sessionStorage.getItem("setagent.client") || ""; } catch(e){}
  if(!me){
    me = "phone-" + Math.random().toString(36).slice(2, 10);
    try { sessionStorage.setItem("setagent.client", me); } catch(e){}
  }
  window.SETAGENT_REMOTE = true;
  window.SETAGENT_CLIENT = me;
  const call = name => async (...args) => {
    const r = await fetch("/api/" + name, {
      method: "POST",
      headers: {"Content-Type": "application/json", "X-SetAgent-Key": key,
                "X-SetAgent-Client": me},
      body: JSON.stringify(args),
    });
    if(r.status === 403)
      return {error: "接続キーが無効です。PC の QR コードを読み直してください", fatal: true};
    if(!r.ok) return {error: "PC との通信に失敗しました（" + r.status + "）"};
    return r.json();
  };
  window.pywebview = {api: new Proxy({}, {get: (_, name) => call(String(name))})};
  window.addEventListener("load", () => window.dispatchEvent(new Event("pywebviewready")));
})();
</script>
"""

FORBIDDEN_PAGE = """<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Set Agent</title></head>
<body style="background:#0d1014;color:#e6e6e6;font-family:Arial,sans-serif;padding:24px">
<p>接続キーが無効です。</p>
<p>PC の Set Agent で「設定 → iPhone で表示」を開き、表示された QR コードをカメラで読み取ってください。</p>
</body></html>"""


def _route_ip() -> str | None:
    """The address the OS would send LAN traffic from. A UDP connect sends
    nothing; it only asks which interface would route there."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def _rank(ip: str) -> int:
    """Which address a phone on the same Wi-Fi is most likely to reach.

    Home routers hand out 192.168.x.x and an iPhone hotspot 172.20.10.x, while
    a corporate VPN client (CatoNetworks on this PC, 2026-10-05) sits on 10.x
    and also wins the routing table -- so the route alone pointed the QR code
    at an address the phone could never reach. Prefer the Wi-Fi-looking ones."""
    a = ipaddress.ip_address(ip)
    if a in ipaddress.ip_network("192.168.0.0/16"):
        return 0
    if a in ipaddress.ip_network("172.16.0.0/12"):
        return 1
    if a in ipaddress.ip_network("10.0.0.0/8"):
        return 2
    return 3


def lan_ips() -> list[str]:
    """Every IPv4 address a phone could use to reach this PC, best guess first.
    Loopback and link-local (169.254, an unconfigured adapter) are left out."""
    found: list[str] = []
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
        found += [i[4][0] for i in infos]
    except OSError:
        pass
    r = _route_ip()
    if r:
        found.append(r)
    out = []
    for ip in found:
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if a.is_loopback or a.is_link_local or not a.is_private or ip in out:
            continue
        out.append(ip)
    return sorted(out, key=_rank) or ["127.0.0.1"]


def lan_ip() -> str:
    return lan_ips()[0]


def qr_svg(text: str) -> str:
    """The QR code as an inline SVG, dark modules on white with a quiet zone so
    phone cameras read it off a dark panel."""
    import segno
    return segno.make(text, error="m").svg_inline(scale=6, border=3, dark="#000",
                                                  light="#fff")


def inject(html: str) -> str:
    """Put the shim right after <head ...>, before any of the page's scripts."""
    i = html.find("<head")
    j = html.find(">", i) if i >= 0 else -1
    if j < 0:
        return SHIM + html
    return html[:j + 1] + SHIM + html[j + 1:]


def _private(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


class _Server(ThreadingHTTPServer):
    # http.server turns on SO_REUSEADDR, which on Windows lets a second process
    # bind the very same port and silently split the traffic. Ask for the port
    # exclusively instead, so a busy port is skipped and the QR code always
    # points at this process.
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class RemoteServer:
    def __init__(self, api, index_html: Path, host: str = "0.0.0.0"):
        self.api = api
        self.index_html = Path(index_html)
        self.host = host
        self.key = secrets.token_urlsafe(16)
        self.httpd: _Server | None = None
        self.port: int | None = None
        self._thread: threading.Thread | None = None

    # -------------------------------------------------------------- control
    @property
    def running(self) -> bool:
        return self.httpd is not None

    def url(self, ip: str | None = None) -> str:
        return f"http://{ip or lan_ip()}:{self.port}/?k={self.key}"

    def start(self) -> None:
        if self.httpd:
            return
        last: OSError | None = None
        for port in PORTS:
            try:
                httpd = _Server((self.host, port), self._handler())
                break
            except OSError as e:
                last = e
        else:
            raise OSError(f"空いているポートがありません（{PORTS.start}〜{PORTS.stop - 1}）: {last}")
        self.httpd, self.port = httpd, httpd.server_address[1]
        self._thread = threading.Thread(target=httpd.serve_forever, name="setagent-remote",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self.httpd:
            return
        self.httpd.shutdown()
        self.httpd.server_close()
        self.httpd = self.port = self._thread = None

    # -------------------------------------------------------------- request
    def _ok_key(self, given: str | None) -> bool:
        return bool(given) and hmac.compare_digest(given, self.key)

    def page(self) -> bytes:
        return inject(self.index_html.read_text(encoding="utf-8")).encode("utf-8")

    def call(self, name: str, args, client: str) -> dict:
        if name not in ALLOWED:
            return {"error": PC_ONLY}
        if not isinstance(args, list):
            args = []
        if name == "boot":
            # a phone joins the set the PC already has open; it never reopens it
            return self.api.boot(True)
        fn = getattr(self.api, name, None)
        if fn is None:
            return {"error": PC_ONLY}
        token = self.api.origin.set(client or "phone")
        try:
            return fn(*args)
        except TypeError as e:
            return {"error": f"呼び出しの引数が不正です: {e}"}
        finally:
            self.api.origin.reset(token)

    def _handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "SetAgent"

            def log_message(self, *a):            # the panel has no console to log to
                pass

            def _send(self, code: int, body: bytes, ctype: str):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                self.wfile.write(body)

            def _json(self, code: int, obj) -> None:
                self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                           "application/json; charset=utf-8")

            def _lan_only(self) -> bool:
                if _private(self.client_address[0]):
                    return True
                self._send(403, b"forbidden", "text/plain")
                return False

            def do_GET(self):
                if not self._lan_only():
                    return
                path, _, query = self.path.partition("?")
                if path != "/":
                    self._send(404, b"not found", "text/plain")
                    return
                from urllib.parse import parse_qs
                k = (parse_qs(query).get("k") or [None])[0]
                if not server._ok_key(k):
                    self._send(403, FORBIDDEN_PAGE.encode("utf-8"), "text/html; charset=utf-8")
                    return
                self._send(200, server.page(), "text/html; charset=utf-8")

            def do_POST(self):
                if not self._lan_only():
                    return
                if not self.path.startswith("/api/"):
                    self._send(404, b"not found", "text/plain")
                    return
                # read the body before any refusal: closing a socket with unread
                # data makes Windows reset it, and the phone then sees a network
                # error instead of the 403 that tells it to rescan the QR code
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    n = -1
                if not 0 <= n <= MAX_BODY:
                    self.close_connection = True
                    self._json(400, {"error": "bad request"})
                    return
                body = self.rfile.read(n) if n else b""
                if not server._ok_key(self.headers.get("X-SetAgent-Key")):
                    self._json(403, {"error": "forbidden"})
                    return
                try:
                    args = json.loads(body or b"[]")
                except (ValueError, json.JSONDecodeError):
                    self._json(400, {"error": "bad request"})
                    return
                name = self.path[len("/api/"):]
                client = (self.headers.get("X-SetAgent-Client") or "phone")[:40]
                try:
                    self._json(200, server.call(name, args, client))
                except Exception as e:             # never drop the phone's promise
                    self._json(200, {"error": f"{type(e).__name__}: {e}"})

        return Handler
