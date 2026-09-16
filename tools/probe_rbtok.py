"""TAD-5d: unfiltered strings from the token/auth bytecode."""
from __future__ import annotations

import re
import sys

from tools.probe_rbagent import read_asar, ASAR

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

STR = re.compile(rb"[ -~]{4,200}")
NOISE = re.compile(r"^[\x20-\x2f\x3a-\x40\x5b-\x60\x7b-\x7e]+$")

WANT = [
    "jsc/routes/api/agent/token/generate_token.jsc",
    "jsc/routes/api/agent/token/index.jsc",
    "jsc/libs/apiutil.jsc",
    "jsc/routes/api/agent/login.jsc",
    "jsc/server/index.jsc",
]


def main() -> int:
    files = dict(read_asar(ASAR))
    for name in WANT:
        blob = files.get(name)
        if blob is None:
            print(f"\n===== {name}  (NOT IN BUNDLE)")
            continue
        seen, out = set(), []
        for m in STR.finditer(blob):
            s = m.group(0).decode("ascii", "replace").strip()
            if len(s) < 4 or NOISE.match(s) or s in seen:
                continue
            seen.add(s)
            out.append(s)
        print(f"\n===== {name}  ({len(blob):,} bytes, {len(out)} strings)")
        for s in out:
            print("   ", s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
