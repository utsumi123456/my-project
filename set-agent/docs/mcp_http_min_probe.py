# -*- coding: utf-8 -*-
"""Smallest streamable-HTTP MCP server, stdlib only. Runs inside the same process
that owns the Draft, so no IPC is needed between Set Agent and its tools."""
import json, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOOLS = [{
    "name": "set_total",
    "description": "セットの予測総尺と目標を返します（analysis.timing の値）",
    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
}]
CALLS = []

def handle(req):
    m, id_ = req.get("method"), req.get("id")
    if m == "initialize":
        return {"jsonrpc": "2.0", "id": id_, "result": {
            "protocolVersion": req["params"].get("protocolVersion", "2025-03-26"),
            "capabilities": {"tools": {}}, "serverInfo": {"name": "setagent", "version": "0.1"}}}
    if m == "tools/list":
        return {"jsonrpc": "2.0", "id": id_, "result": {"tools": TOOLS}}
    if m == "tools/call":
        CALLS.append(req["params"]["name"])
        out = {"total_s": 8238, "total": "137:18", "target_s": 3600, "target": "60:00",
               "over_s": 4638, "over": "77:18", "tracks": 96}
        return {"jsonrpc": "2.0", "id": id_, "result": {
            "content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}]}}
    if id_ is None:
        return None                     # notification
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32601, "message": f"unknown {m}"}}

class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        sys.stderr.write("HTTP " + (fmt % a) + "\n")
    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        reqs = body if isinstance(body, list) else [body]
        outs = [r for r in (handle(q) for q in reqs) if r is not None]
        if not outs:
            self.send_response(202); self.send_header("content-length", "0"); self.end_headers(); return
        data = json.dumps(outs[0] if len(outs) == 1 else outs, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("mcp-session-id", "setagent-1")
        self.send_header("content-length", str(len(data)))
        self.end_headers(); self.wfile.write(data)
    def do_GET(self):                    # no server-initiated stream
        self.send_response(405); self.send_header("content-length", "0"); self.end_headers()
    def do_DELETE(self):
        self.send_response(200); self.send_header("content-length", "0"); self.end_headers()

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 47831
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"listening on http://127.0.0.1:{port}/mcp", flush=True)
    import time
    t0 = time.time()
    while time.time() - t0 < float(sys.argv[2] if len(sys.argv) > 2 else 90):
        time.sleep(0.5)
    print("calls seen:", CALLS, flush=True)
