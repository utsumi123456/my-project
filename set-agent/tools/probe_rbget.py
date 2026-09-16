"""TAD-5c: GET-only probes against the recovered mount path. No write verbs."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:30001"
PATHS = [
    "/api/v1/hello",
    "/api/v1/agent/mode",
    "/api/v1/agent/env",
    "/api/v1/agent/messages",
    "/api/v1/agent/syncCondition",
    "/api/v1/data/djmdContents",
    "/api/v1/data/djmdPlaylists",
    "/api/v1/data/djmdProperties",
    "/api/v1/localSync/syncState",
]


def probe(path: str) -> None:
    req = urllib.request.Request(BASE + path, method="GET",
                                 headers={"User-Agent": "rekordbox"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            body = r.read(400).decode("utf-8", "replace")
            print(f"{r.status:>3}  {path}\n     {body[:300]}")
    except urllib.error.HTTPError as e:
        body = e.read(400).decode("utf-8", "replace").replace("\n", " ")
        print(f"{e.code:>3}  {path}\n     {body[:300]}")
    except Exception as e:                       # noqa: BLE001
        print(f"ERR  {path}\n     {type(e).__name__}: {e}")


if __name__ == "__main__":
    for p in PATHS:
        probe(p)
