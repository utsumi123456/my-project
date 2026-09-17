# -*- coding: utf-8 -*-
"""Stand-in for `claude` in tests: same flags, no network.

Speaks to the MCP server named in --mcp-config exactly as the real CLI does
(initialize, tools/list, tools/call) and prints one `--output-format json`
result object. Behaviour is steered by environment variables so tests can hit
every branch of CliBackend without a sign-in:

  FAKE_CLAUDE_MODE        ok (default) | propose | error | slow
  FAKE_CLAUDE_LOGGED_IN   1 (default) | 0            -> `auth status`
  FAKE_CLAUDE_RESUME_FAILS 1 -> a --resume call fails "No conversation found"
  FAKE_CLAUDE_REMOVE_REF  track_ref removed by the "propose" mode
  FAKE_CLAUDE_ARGS        file that receives argv as JSON, one line per call
"""
import json
import os
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")


def rpc(url, method, params=None, id_=None):
    body = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        body["params"] = params
    if id_ is not None:
        body["id"] = id_
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"content-type": "application/json",
                                          "accept": "application/json, text/event-stream"})
    with urllib.request.urlopen(req, timeout=10) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def result(text, is_error=False, subtype="success", session_id=""):
    print(json.dumps({"type": "result", "subtype": subtype, "is_error": is_error,
                      "duration_ms": 1, "duration_api_ms": 1, "num_turns": 1,
                      "result": text, "session_id": session_id, "total_cost_usd": 0},
                     ensure_ascii=False))


def main(argv):
    rec = os.environ.get("FAKE_CLAUDE_ARGS")
    if rec:
        with open(rec, "a", encoding="utf-8") as f:
            f.write(json.dumps(argv, ensure_ascii=False) + "\n")

    if argv[:2] == ["auth", "status"]:
        print(json.dumps({"loggedIn": os.environ.get("FAKE_CLAUDE_LOGGED_IN", "1") == "1",
                          "authMethod": "claude.ai", "subscriptionType": "enterprise",
                          "orgName": "Fake Org"}))
        return 0
    if argv[:1] == ["--version"]:
        print("9.9.9 (Claude Code)")
        return 0
    if "-p" not in argv:
        print("fake claude: unsupported invocation", file=sys.stderr)
        return 2

    def opt(name):
        return argv[argv.index(name) + 1] if name in argv else None

    prompt = argv[-1]
    session = opt("--session-id") or opt("--resume") or ""
    mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")

    if "--resume" in argv and os.environ.get("FAKE_CLAUDE_RESUME_FAILS") == "1":
        result(f"No conversation found with session ID: {session}", is_error=True, session_id=session)
        return 1
    if mode == "error":
        result("Not logged in · Please run /login", is_error=True, session_id=session)
        return 1
    if mode == "slow":
        time.sleep(float(os.environ.get("FAKE_CLAUDE_SLEEP", "5")))

    cfg = json.load(open(opt("--mcp-config"), encoding="utf-8"))
    url = cfg["mcpServers"]["setagent"]["url"]
    rpc(url, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                            "clientInfo": {"name": "fake-claude", "version": "0"}}, 0)
    rpc(url, "notifications/initialized")
    tools = rpc(url, "tools/list", {}, 1)["result"]["tools"]
    names = [t["name"] for t in tools]
    got = rpc(url, "tools/call", {"name": "analysis_get_set_summary", "arguments": {}}, 2)
    summary = got["result"]["content"][0]["text"]
    text = f"[{len(names)} tools] {prompt[:40]} → {summary}"
    if mode == "propose":
        ref = os.environ.get("FAKE_CLAUDE_REMOVE_REF", "")
        got = rpc(url, "tools/call", {"name": "set_propose_changes",
                                      "arguments": {"reason": "テストの提案です",
                                                    "operations": [{"op": "remove", "track_ref": ref}]}}, 3)
        text += " | proposed: " + got["result"]["content"][0]["text"][:80]
    result(text, session_id=session)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
