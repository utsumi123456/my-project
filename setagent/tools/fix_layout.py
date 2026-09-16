"""One-off: apply the flex-layout fix to webui/index.html in place.

The lanes were being pushed off-screen because .scroll had no min-height, so the
fixed-height blocks above and below it ate the whole column.
"""
from pathlib import Path

P = Path(__file__).resolve().parent.parent / "setagent" / "webui" / "index.html"
s = P.read_text(encoding="utf-8")

PAIRS = [
    (".bar{display:flex;flex-wrap:wrap;align-items:center;gap:var(--s3);\n",
     ".bar{display:flex;flex-wrap:wrap;align-items:center;gap:var(--s3);flex:none;\n"),
    ("  gap:var(--s5);padding:var(--s4);border-bottom:1px solid var(--line);background:var(--surface)}",
     "  gap:var(--s5);padding:var(--s3) var(--s4);border-bottom:1px solid var(--line);\n"
     "  background:var(--surface);flex:none}"),
    (".hero{font-family:var(--mono);font-size:50px;",
     ".hero{font-family:var(--mono);font-size:42px;"),
    ("padding:var(--s3) var(--s4);overflow:auto;max-height:190px}",
     "padding:var(--s3) var(--s4);overflow:auto;max-height:148px}"),
    (".transport{display:flex;align-items:center;gap:var(--s3);padding:var(--s2) var(--s4);\n",
     ".transport{display:flex;align-items:center;gap:var(--s3);padding:var(--s2) var(--s4);flex:none;\n"),
    (".scroll{flex:1;overflow:auto;background:var(--surface)}",
     "/* min-height:0 is what lets a flex child scroll instead of pushing the rest of\n"
     "   the column off-screen; the floor keeps ENERGY and SECTIONS -- both Tier 1 --\n"
     "   on screen at the shortest window we support. */\n"
     ".scroll{flex:1 1 auto;min-height:330px;overflow:auto;background:var(--surface)}"),
    (".legend{display:flex;flex-wrap:wrap;gap:6px var(--s4);padding:6px var(--s4);\n",
     ".legend{display:flex;flex-wrap:wrap;gap:6px var(--s4);padding:6px var(--s4);flex:none;\n"),
    ("  max-height:210px;overflow:auto}",
     "  flex:none;max-height:152px;overflow:auto}"),
]

missing = []
for old, new in PAIRS:
    if old not in s:
        missing.append(old[:50])
        continue
    s = s.replace(old, new, 1)

P.write_text(s, encoding="utf-8")
print("bytes now", len(s.encode("utf-8")))
print("min-height:330px present:", "min-height:330px" in s)
if missing:
    print("NOT FOUND (already applied or drifted):")
    for m in missing:
        print("  ", m)
