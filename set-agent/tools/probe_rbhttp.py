"""TAD-5: knock on rekordboxAgent's local HTTP server. READ-ONLY.

  python -m tools.probe_rbhttp

Only GET, and only on routes whose name says they read something. Nothing here
creates, updates, moves or deletes anything in the DJ's library -- those routes
exist (create_item / update_item / delete_item / move_item) and are deliberately
NOT touched.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OPTIONS = Path.home() / "AppData/Roaming/Pioneer/rekordboxAgent/storage/options.json"

# read-only by name; the write verbs in the bundle are intentionally excluded
GETS = [
    "/",
    "/api",
    "/api/agent",
    "/api/agent/mode/get_mode",
    "/api/agent/env/get_env",
    "/api/agent/messages/get_list",
    "/api/agent/syncCondition/get_syncCondition",
    "/api/agent/sharedPlaylists/mode/get_mode",
    "/api/data",
    "/api/data/djmdPlaylists",
    "/api/data/djmdContents/get_list",
    "/api/localSync/get_localSyncState",
]


def port() -> int:
    try:
        raw = json.loads(OPTIONS.read_text(encoding="utf-8"))
    except Exception as e:
        print("could not read options.json:", e)
        return 30001
    # stored as a list of [key, value] pairs
    try:
        for k, v in raw:
            if k == "port":
                return int(v)
    except Exception:
        pass
    return 30001


def get(url: str, timeout=4):
    req = urllib.request.Request(url, method="GET",
                                 headers={"accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(1200).decode("utf-8", "replace")
            return r.status, dict(r.headers), body
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read(600).decode("utf-8", "replace")
    except Exception as e:
        return None, {}, f"{type(e).__name__}: {e}"


def main() -> int:
    p = port()
    print(f"port from options.json: {p}\n")
    for path in GETS:
        code, hdrs, body = get(f"http://127.0.0.1:{p}{path}")
        one = " ".join(body.split())[:160]
        ct = hdrs.get("Content-Type", "")
        print(f"  {str(code):<5} {path:<46} {ct[:28]:<28} {one}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
