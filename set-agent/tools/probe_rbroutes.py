"""TAD-5: pull the literal strings out of the routing/server bytecode.

  python -m tools.probe_rbroutes

Bytenode strips the source but the V8 constant pool keeps string literals, so
the mount path and the HTTP verbs are still readable.
"""
from __future__ import annotations

import re
import sys

from tools.probe_rbagent import read_asar, ASAR

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WANT = (
    "jsc/express_loader.jsc",
    "jsc/server/index.jsc",
    "jsc/app.jsc",
    "jsc/main_core.jsc",
    "jsc/routes/api/index.jsc",
    "jsc/routes/api/handler_helpers/handler.jsc",
    "jsc/routes/api/data/index.jsc",
    "jsc/routes/api/data/djmdPlaylists/index.jsc",
    "jsc/routes/api/data/djmdPlaylists/create_item.jsc",
    "jsc/routes/api/agent/mode/get_mode.jsc",
    "jsc/libs/apiutil.jsc",
)

STR = re.compile(rb"[ -~]{3,120}")
NOISE = re.compile(r"^[\x20-\x2f\x3a-\x40\x5b-\x60\x7b-\x7e]+$")


def main() -> int:
    files = dict(read_asar(ASAR))
    for name in WANT:
        blob = files.get(name)
        if blob is None:
            print(f"\n===== {name}  (NOT IN BUNDLE)")
            continue
        out = []
        for m in STR.finditer(blob):
            s = m.group(0).decode("ascii", "replace").strip()
            if len(s) < 3 or NOISE.match(s):
                continue
            out.append(s)
        seen, uniq = set(), []
        for s in out:
            if s not in seen:
                seen.add(s)
                uniq.append(s)
        print(f"\n===== {name}  ({len(blob):,} bytes, {len(uniq)} strings)")
        for s in uniq[:110]:
            print("   ", s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
