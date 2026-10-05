"""Dev loop: rebuild FlickFX, drop it into Live's Current Project, swap it on a track.

    python tools/dev_reload.py [track]        # default track 1

Needs the locally patched AbletonMCP remote script (delete_device + current_project
URI lookup). Talks to it directly on 127.0.0.1:9877.
"""
import json
import shutil
import socket
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRACK = int(sys.argv[1]) if len(sys.argv) > 1 else 1


def mcp(kind, **params):
    with socket.create_connection(("127.0.0.1", 9877), timeout=15) as s:
        s.sendall(json.dumps({"type": kind, "params": params}).encode())
        buf = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
            try:
                r = json.loads(buf)
                break
            except json.JSONDecodeError:
                continue
    if r.get("status") == "error":
        raise RuntimeError(r.get("message"))
    return r.get("result", r)


def current_project() -> Path:
    db = next((Path.home() / "AppData/Local/Ableton/Live Database").glob("Live-files-*.db"))
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    fid = c.execute("select file_id from places where name='Current Project'").fetchone()[0]
    parts = []
    while fid:
        row = c.execute("select parent_id, name from files where file_id=?", (fid,)).fetchone()
        if not row:
            break
        parts.append(row[1])
        fid = row[0]
    p = "/".join(reversed(parts)).replace(":\\/", ":/")
    # the DB stores the path in the ANSI codepage on this box; prefer an existing folder match
    path = Path(p)
    if not path.exists():
        docs = Path(subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('MyDocuments')"],
            text=True).strip())
        cands = sorted((docs / "Max 9").glob("*Temp Project"), key=lambda q: q.stat().st_mtime)
        path = cands[-1]
    return path


def clear_track(track):
    """Remove FlickFX first (or it re-creates its FX), then every device it managed."""
    while True:
        devs = mcp("get_track_info", track_index=track)["devices"]
        hosts = [d for d in devs if d["name"] == "FlickFX"]
        target = hosts[0] if hosts else next((d for d in devs if d["name"].startswith("FlickFX")), None)
        if not target:
            return
        print("delete", mcp("delete_device", track_index=track, device_index=target["index"]))


def main():
    subprocess.check_call([sys.executable, str(ROOT / "m4l/build.py")])
    proj = current_project()
    shutil.copy2(ROOT / "dist/FlickFX.amxd", proj / "FlickFX.amxd")
    print("copied ->", proj)
    clear_track(TRACK)
    print(mcp("load_instrument_or_effect", track_index=TRACK, uri="query:CurrentProject#FlickFX.amxd"))
    info = mcp("get_track_info", track_index=TRACK)
    print([d["name"] for d in info["devices"]])


if __name__ == "__main__":
    main()
