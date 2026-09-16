"""TAD-5b: find the express mount path + HTTP verbs in the routing bytecode."""
from __future__ import annotations

import re
import sys

from tools.probe_rbagent import read_asar, ASAR

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

STR = re.compile(rb"[ -~]{3,160}")
NOISE = re.compile(r"^[\x20-\x2f\x3a-\x40\x5b-\x60\x7b-\x7e]+$")

# any literal that looks like a URL path, a verb, or a mount call
HINT = re.compile(
    r"(^/|/api|router|Router|\bget\b|\bpost\b|\bput\b|\bpatch\b|\bdelete\b|"
    r"\buse\b|listen|localhost|127\.0\.0\.1|30001|token|Bearer|authoriz|"
    r"Cannot |middleware|\.jsc$)",
    re.I,
)


def strings(blob: bytes) -> list[str]:
    seen, out = set(), []
    for m in STR.finditer(blob):
        s = m.group(0).decode("ascii", "replace").strip()
        if len(s) < 3 or NOISE.match(s) or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def main() -> int:
    files = dict(read_asar(ASAR))
    targets = [n for n in files
               if n.startswith("jsc/")
               and ("server" in n or "route" in n or "express" in n
                    or n in ("jsc/app.jsc", "jsc/main_core.jsc")
                    or "apiutil" in n or "auth" in n or "token" in n)]
    print(f"# {len(targets)} candidate files")
    for name in sorted(targets):
        hits = [s for s in strings(files[name]) if HINT.search(s)]
        if not hits:
            continue
        print(f"\n===== {name}")
        for s in hits[:60]:
            print("   ", s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
