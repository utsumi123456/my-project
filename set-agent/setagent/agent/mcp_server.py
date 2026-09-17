"""A tiny MCP server that hands AgentTools to a `claude -p` child process.

Why this exists (docs/llm_backend_2026-09-17.md): on an enterprise account the
DJ may not be able to obtain an API key, but Claude Code is signed in with the
company seat. `claude -p` can drive our tools if they are reachable as an MCP
server, so this module speaks just enough of MCP's streamable-HTTP transport
(JSON-RPC over POST, one response per request) for that one client.

Standard library only, so the PyInstaller bundle stays small.

Threading. The decrypted master.db lives on the api worker thread, and that is
the thread blocked in `ask()` while the child runs. So tool bodies are NOT run
on the HTTP thread: the handler queues the call and waits, and the blocked
worker drains the queue through `pump()` while it waits for the child to exit.
`direct=True` runs tools on the HTTP thread instead (tests, or tools with no
thread affinity).
"""
from __future__ import annotations

import json
import queue
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from setagent.agent.tools import TOOL_SCHEMA, AgentTools

SERVER_NAME = "setagent"
PROTOCOL_DEFAULT = "2025-03-26"


def mcp_name(tool: str) -> str:
    """MCP tool names are [A-Za-z0-9_-]; ours use dots ("analysis.get_sections")."""
    return tool.replace(".", "_")


MCP_TOOLS: list[dict] = [
    {"name": mcp_name(t["name"]), "description": t["description"], "inputSchema": t["input_schema"]}
    for t in TOOL_SCHEMA
]
_BACK: dict[str, str] = {mcp_name(t["name"]): t["name"] for t in TOOL_SCHEMA}


class _Job:
    __slots__ = ("name", "args", "done", "result")

    def __init__(self, name: str, args: dict):
        self.name, self.args = name, args
        self.done = threading.Event()
        self.result: Any = None


class ToolServer:
    """One instance per process. `tools` may be swapped when a new set is loaded."""

    def __init__(self, tools: AgentTools | None = None, *, direct: bool = False,
                 call_timeout_s: float = 55.0):
        self.tools = tools
        self.direct = direct
        self.call_timeout_s = call_timeout_s
        self._q: "queue.Queue[_Job]" = queue.Queue()
        self._srv: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.calls: list[str] = []            # tool names in the order the child asked
        self.transcript: list[dict] = []      # {name, args, text} -- what the model was shown
        self.log: Callable[[str], None] | None = None

    # ------------------------------------------------------------ lifecycle
    @property
    def url(self) -> str:
        if not self._srv:
            raise RuntimeError("ToolServer is not running")
        return f"http://127.0.0.1:{self._srv.server_address[1]}/mcp"

    def start(self) -> str:
        if self._srv:
            return self.url
        srv = _QuietServer(("127.0.0.1", 0), _handler_for(self))
        srv.daemon_threads = True
        self._srv = srv
        self._thread = threading.Thread(target=srv.serve_forever, name="setagent-mcp", daemon=True)
        self._thread.start()
        return self.url

    def stop(self) -> None:
        if self._srv:
            self._srv.shutdown()
            self._srv.server_close()
            self._srv = None

    def mcp_config(self) -> dict:
        return {"mcpServers": {SERVER_NAME: {"type": "http", "url": self.url}}}

    # --------------------------------------------------------------- tools
    def _execute(self, name: str, args: dict) -> Any:
        if self.tools is None:
            return {"error": "セットが読み込まれていません"}
        return self.tools.call(_BACK.get(name, name), args)

    def call_tool(self, name: str, args: dict) -> Any:
        """Called on the HTTP thread. Runs now (direct) or hands off to pump()."""
        self.calls.append(_BACK.get(name, name))
        if self.direct:
            return self._execute(name, args)
        job = _Job(name, args)
        self._q.put(job)
        if not job.done.wait(self.call_timeout_s):
            return {"error": "ツールの実行が時間内に終わりませんでした"}
        return job.result

    def pump(self, wait_s: float = 0.0) -> int:
        """Run queued tool calls on the calling thread. Returns how many ran.
        With wait_s > 0 it blocks up to that long for the first job."""
        ran = 0
        deadline = time.monotonic() + wait_s
        while True:
            try:
                remaining = deadline - time.monotonic()
                job = self._q.get(timeout=remaining) if (ran == 0 and remaining > 0) else self._q.get_nowait()
            except queue.Empty:
                return ran
            try:
                job.result = self._execute(job.name, job.args)
            except Exception as ex:                    # tools.call already guards; belt and braces
                job.result = {"error": f"{job.name} failed: {ex}"}
            finally:
                job.done.set()
            ran += 1

    def pump_until(self, alive: Callable[[], bool], timeout_s: float, tick_s: float = 0.05) -> bool:
        """Drain the queue while `alive()` holds. Returns False on timeout."""
        deadline = time.monotonic() + timeout_s
        while alive():
            if time.monotonic() > deadline:
                return False
            self.pump(tick_s)
        self.pump(0)                                    # anything that landed at the very end
        return True

    # ------------------------------------------------------------ protocol
    def handle(self, req: dict) -> dict | None:
        """One JSON-RPC message in, one out (None for notifications)."""
        m, id_ = req.get("method"), req.get("id")
        if self.log:
            self.log(f"mcp <- {m}")
        if m == "initialize":
            params = req.get("params") or {}
            return _ok(id_, {"protocolVersion": params.get("protocolVersion", PROTOCOL_DEFAULT),
                             "capabilities": {"tools": {}},
                             "serverInfo": {"name": SERVER_NAME, "version": "1"}})
        if m == "ping":
            return _ok(id_, {})
        if m == "tools/list":
            return _ok(id_, {"tools": MCP_TOOLS})
        if m == "tools/call":
            params = req.get("params") or {}
            name = params.get("name", "")
            if name not in _BACK:
                return _ok(id_, _tool_text({"error": f"unknown tool '{name}'"}, is_error=True))
            args = params.get("arguments") or {}
            out = self.call_tool(name, args)
            is_err = isinstance(out, dict) and "error" in out and len(out) == 1
            r = _tool_text(out, is_error=is_err)
            self.transcript.append({"name": _BACK.get(name, name), "args": args,
                                    "text": r["content"][0]["text"]})
            return _ok(id_, r)
        if id_ is None:
            return None                                 # notifications/initialized etc.
        return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32601, "message": f"unknown method {m}"}}


def _ok(id_, result) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


TEXT_CAP = 24000                                        # ~8k tokens; compact outputs stay well under


def _tool_text(out: Any, *, is_error: bool = False) -> dict:
    text = json.dumps(out, ensure_ascii=False, default=str)
    if len(text) > TEXT_CAP:
        # Cut the long list, not the JSON: the model must never see a broken object.
        if isinstance(out, dict):
            key = next((k for k, v in out.items() if isinstance(v, list) and len(v) > 8), None)
            if key:
                keep = list(out[key])
                while keep and len(json.dumps({**out, key: keep}, ensure_ascii=False, default=str)) > TEXT_CAP - 120:
                    keep = keep[: max(1, len(keep) * 3 // 4)]
                out = {**out, key: keep,
                       "truncated": f"{key}: {len(out[key])} 件のうち先頭 {len(keep)} 件だけを返しました"}
        elif isinstance(out, list):
            keep = list(out)
            while keep and len(json.dumps(keep, ensure_ascii=False, default=str)) > TEXT_CAP - 120:
                keep = keep[: max(1, len(keep) * 3 // 4)]
            out = keep + [{"truncated": f"{len(out)} 件のうち先頭 {len(keep)} 件だけを返しました"}]
        text = json.dumps(out, ensure_ascii=False, default=str)
        if len(text) > TEXT_CAP:
            text = text[:TEXT_CAP] + "…"
    r = {"content": [{"type": "text", "text": text}]}
    if is_error:
        r["isError"] = True
    return r


class _QuietServer(ThreadingHTTPServer):
    """The CLI drops idle keep-alive connections when it exits; that is not an
    error worth a traceback on the console."""
    daemon_threads = True

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


def _handler_for(server: ToolServer):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *a):                 # keep the console quiet
            if server.log:
                server.log("http " + (fmt % a))

        def _send(self, code: int, body: bytes = b"", ctype: str = "application/json"):
            self.send_response(code)
            if body:
                self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(body)))
            self.send_header("mcp-session-id", "setagent")
            self.end_headers()
            if body:
                self.wfile.write(body)

        def do_POST(self):
            n = int(self.headers.get("content-length") or 0)
            raw = self.rfile.read(n) if n else b""
            try:
                body = json.loads(raw or b"{}")
            except ValueError:
                self._send(400, json.dumps({"jsonrpc": "2.0", "id": None,
                                            "error": {"code": -32700, "message": "parse error"}}).encode())
                return
            reqs = body if isinstance(body, list) else [body]
            outs = [r for r in (server.handle(q) for q in reqs if isinstance(q, dict)) if r is not None]
            if not outs:
                self._send(202)
                return
            payload = outs[0] if (len(outs) == 1 and not isinstance(body, list)) else outs
            self._send(200, json.dumps(payload, ensure_ascii=False).encode("utf-8"))

        def do_GET(self):                               # we never push server-initiated messages
            self._send(405)

        def do_DELETE(self):                            # session close: nothing to release
            self._send(200)

    return Handler


if __name__ == "__main__":                              # manual smoke: python -m setagent.agent.mcp_server
    s = ToolServer(None, direct=True)
    print(s.start(), file=sys.stderr)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        s.stop()
