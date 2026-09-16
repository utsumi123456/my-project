import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

raw = open("tools_rbmount.txt", "rb").read()
if raw[:2] in (b"\xff\xfe", b"\xfe\xff") or raw[1:2] == b"\x00":
    text = raw.decode("utf-16", "replace")
else:
    text = raw.decode("utf-8", "replace")
t = text.replace("\r", "").split("\n")

KEY = sys.argv[1:]
secs = [i for i, l in enumerate(t) if l.startswith("=====")]
if not KEY:
    for i in secs:
        print(t[i])
    raise SystemExit
for n, i in enumerate(secs):
    end = secs[n + 1] if n + 1 < len(secs) else len(t)
    if any(k in t[i] for k in KEY):
        print("\n".join(t[i:end]))
