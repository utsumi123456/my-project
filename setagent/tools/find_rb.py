import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
roots = []
for v in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
    p = os.environ.get(v)
    if p:
        roots.append(p)
hits = []
for r in roots:
    for dirpath, dirnames, filenames in os.walk(r):
        # bound depth to ~4 under each root
        depth = dirpath[len(r):].count(os.sep)
        if depth > 4:
            dirnames[:] = []
            continue
        for f in filenames:
            if f.lower() == "rekordbox.exe":
                hits.append(os.path.join(dirpath, f))
        if len(hits) > 20:
            break
for h in hits:
    print(h)
print("total:", len(hits))
