"""Log every change to master.db / -wal / -shm while the DJ edits in rekordbox.

  python -m tools.watch_masterdb [--out log.jsonl] [--minutes 20] [--stop stopfile]

Read-only: it only stats the three files and reads the 32-byte WAL header.
Nothing here opens the database.

Why the WAL header: SQLCipher encrypts page content, not the WAL framing.
The header carries a checkpoint sequence number that rekordbox's SQLite bumps
every time it checkpoints (writes WAL frames back into master.db), and the
file size gives the frame count. Together with master.db's mtime that answers
the question §5-1 left open: when does an edit become readable to us?
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from setagent.rekordbox.library import find_master_db

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WAL_HDR = 32
FRAME_HDR = 24


def stat(p: Path) -> dict | None:
    try:
        s = p.stat()
    except OSError:
        return None
    return {"size": s.st_size, "mtime": round(s.st_mtime, 3)}


def wal_header(p: Path) -> dict | None:
    try:
        with open(p, "rb") as fh:
            h = fh.read(WAL_HDR)
    except OSError as ex:
        return {"err": type(ex).__name__}
    if len(h) < WAL_HDR:
        return {"empty": True}
    magic, ver, page, ckpt, salt1, salt2 = struct.unpack(">IIIIII", h[:24])
    size = p.stat().st_size
    frames = max(0, (size - WAL_HDR) // (FRAME_HDR + page)) if page else None
    return {"magic": hex(magic), "page": page, "ckpt_seq": ckpt,
            "salt1": salt1, "salt2": salt2, "frames": frames}


def rb_running() -> bool:
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True,
                             text=True, timeout=10, errors="replace").stdout
        return "rekordbox.exe" in out.lower()
    except Exception:
        return False


def snapshot(db: Path) -> dict:
    wal = db.with_name(db.name + "-wal")
    shm = db.with_name(db.name + "-shm")
    return {"db": stat(db), "wal": stat(wal), "shm": stat(shm),
            "walhdr": wal_header(wal) if wal.exists() else None}


def diff(a: dict, b: dict) -> list[str]:
    out = []
    for k in ("db", "wal", "shm"):
        x, y = a.get(k), b.get(k)
        if x != y:
            if x is None or y is None:
                out.append(f"{k}: {'appeared' if x is None else 'vanished'}")
                continue
            parts = []
            if x["size"] != y["size"]:
                parts.append(f"size {x['size']}→{y['size']} ({y['size']-x['size']:+d})")
            if x["mtime"] != y["mtime"]:
                parts.append("mtime " + datetime.fromtimestamp(y["mtime"]).strftime("%H:%M:%S.%f")[:-3])
            out.append(f"{k}: " + ", ".join(parts))
    x, y = a.get("walhdr") or {}, b.get("walhdr") or {}
    for f in ("ckpt_seq", "frames", "salt1"):
        if x.get(f) != y.get(f):
            out.append(f"wal.{f} {x.get(f)}→{y.get(f)}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db")
    ap.add_argument("--out", default="output/wal_watch.jsonl")
    ap.add_argument("--minutes", type=float, default=20)
    ap.add_argument("--interval", type=float, default=0.5)
    ap.add_argument("--stop", default="output/wal_watch.stop")
    a = ap.parse_args()

    db = find_master_db(a.db)
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    stop = Path(a.stop)
    if stop.exists():
        stop.unlink()

    def log(kind: str, **kw):
        rec = {"t": datetime.now().isoformat(timespec="milliseconds"), "kind": kind, **kw}
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        line = rec["t"][11:] + f"  {kind:8s} " + " | ".join(kw.get("changes", [])) \
            if kind == "change" else rec["t"][11:] + f"  {kind:8s} " + json.dumps(kw, ensure_ascii=False)
        print(line, flush=True)

    prev = snapshot(db)
    running = rb_running()
    log("start", db=str(db), rekordbox_running=running, snap=prev)
    deadline = time.time() + a.minutes * 60
    last_rb = time.time()
    while time.time() < deadline and not stop.exists():
        time.sleep(a.interval)
        cur = snapshot(db)
        ch = diff(prev, cur)
        if ch:
            log("change", changes=ch, snap=cur)
            prev = cur
        if time.time() - last_rb > 5:
            last_rb = time.time()
            r = rb_running()
            if r != running:
                running = r
                log("rekordbox", running=r)
    log("end", reason="stopfile" if stop.exists() else "timeout", snap=snapshot(db),
        rekordbox_running=rb_running())


if __name__ == "__main__":
    main()
