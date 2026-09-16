"""TAD-5: read rekordboxAgent's asar bundle and list the HTTP routes it defines.

  python -m tools.probe_rbagent

Read-only. It opens the packaged app, pulls out the JS, and greps for route
definitions. Nothing is requested over the network here -- that is a separate,
deliberate step.
"""
from __future__ import annotations

import json
import re
import struct
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ASAR = Path(r"C:\Program Files\rekordbox\rekordbox 7.2.14"
            r"\rekordboxAgent-win32-x64\resources\app.asar")


def read_asar(path: Path):
    """Yield (name, bytes) for every file in an asar archive."""
    data = path.read_bytes()
    # pickle: uint32 header-size-field-size, uint32 header size,
    #         uint32 payload size, uint32 json length
    (_, _, _, json_len) = struct.unpack("<IIII", data[:16])
    header = json.loads(data[16:16 + json_len].decode("utf-8"))
    base = 16 + json_len
    base += (4 - base % 4) % 4                      # align to 4 bytes

    out = []

    def walk(node, prefix=""):
        for name, meta in (node.get("files") or {}).items():
            p = f"{prefix}/{name}" if prefix else name
            if "files" in meta:
                walk(meta, p)
            elif "offset" in meta:
                off = base + int(meta["offset"])
                out.append((p, data[off:off + int(meta["size"])]))

    walk(header)
    return out


ROUTE_PATTERNS = [
    re.compile(rb"""\.(get|post|put|patch|delete|use|all)\s*\(\s*["'`]([^"'`]{2,120})["'`]""", re.I),
    re.compile(rb"""(?:route|path|endpoint)\s*[:=]\s*["'`](/[^"'`]{1,120})["'`]""", re.I),
]


def main() -> int:
    if not ASAR.exists():
        print("not found:", ASAR)
        return 1
    files = read_asar(ASAR)
    print(f"asar: {ASAR.stat().st_size/1e6:.1f} MB, {len(files)} entries\n")

    # the app's own code, not its 6000 vendored files
    js = [(n, b) for n, b in files
          if n.endswith((".js", ".mjs", ".cjs"))
          and "node_modules" not in n]
    print("app js entries (node_modules excluded):", len(js))
    for n, b in sorted(js, key=lambda t: -len(t[1]))[:25]:
        print(f"  {len(b):>9,}  {n}")

    hits: dict[str, set[str]] = {}
    for name, blob in js:
        for pat in ROUTE_PATTERNS:
            for m in pat.finditer(blob):
                g = m.groups()
                verb = (g[0].decode("ascii", "replace").lower() if len(g) > 1 else "path")
                route = g[-1].decode("utf-8", "replace")
                if not route.startswith("/"):
                    continue
                if len(route) > 100 or " " in route:
                    continue
                hits.setdefault(route, set()).add(f"{verb}:{name.split('/')[-1]}")

    print(f"\nroute-like strings: {len(hits)}")
    for route in sorted(hits):
        who = ", ".join(sorted(hits[route]))[:110]
        print(f"  {route:<46} {who}")

    for n, b in js:
        if len(b) < 4000:
            print(f"\n===== {n} =====")
            print(b.decode("utf-8", "replace"))

    print("\n--- non-js app files (what else is packaged) ---")
    others = [(n, len(b)) for n, b in files
              if "node_modules" not in n and not n.endswith((".js", ".mjs", ".cjs"))]
    for n, sz in sorted(others, key=lambda t: -t[1])[:40]:
        print(f"  {sz:>10,}  {n}")
    print(f"  ({len(others)} non-js app entries)")

    # The logic is bytenode-compiled (.jsc = V8 bytecode); the source is not in
    # the bundle. But the file tree still names the routes, and the constant pool
    # inside each .jsc still holds its string literals.
    print("\n--- jsc/routes and jsc/server tree ---")
    tree = sorted(n for n, _ in files
                  if n.startswith("jsc/") and (".jsc" in n))
    for n in tree:
        print("  ", n)

    print("\n--- printable strings inside the route/server bytecode ---")
    want = [n for n, _ in files
            if n.startswith(("jsc/routes/", "jsc/server/", "jsc/controllers/"))]
    blobs = {n: b for n, b in files if n in want}
    strs = re.compile(rb"[ -~]{4,90}")
    for n in sorted(blobs):
        found = []
        for m in strs.finditer(blobs[n]):
            s = m.group(0).decode("ascii", "replace")
            if re.fullmatch(r"[A-Za-z0-9_/:\-.{}? ]+", s) and (
                    s.startswith("/") or re.search(
                        r"(?i)xml|import|reload|refresh|playlist|library|collection|"
                        r"bridge|master|db|sync|route|api|port|localhost", s)):
                found.append(s)
        found = sorted(set(found))
        if found:
            print(f"\n  == {n}")
            for s in found[:60]:
                print("     ", s)

    print("\n--- strings mentioning xml / import / library / playlist ---")
    kw = re.compile(rb"""["'`]([^"'`\n]{0,80}(?:xml|import|reload|refresh|playlist|library|"""
                    rb"""collection)[^"'`\n]{0,80})["'`]""", re.I)
    seen = set()
    for name, blob in js:
        for m in kw.finditer(blob):
            s = m.group(1).decode("utf-8", "replace").strip()
            if len(s) < 4 or s in seen or " " in s and len(s) > 60:
                continue
            seen.add(s)
    for s in sorted(seen)[:120]:
        print("  ", s)
    print(f"  ... {len(seen)} unique")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
