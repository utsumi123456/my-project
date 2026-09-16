import re, subprocess, sys, tempfile, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
html = open("setagent/webui/index.html", encoding="utf-8").read()
blocks = re.findall(r"<script>(.*?)</script>", html, re.S)
print("script blocks:", len(blocks))
js = "\n;\n".join(blocks)
fd, path = tempfile.mkstemp(suffix=".js")
os.write(fd, js.encode("utf-8")); os.close(fd)
try:
    r = subprocess.run(["node", "--check", path], capture_output=True, text=True)
    print("node --check exit:", r.returncode)
    if r.returncode != 0:
        print(r.stderr[:2000])
    else:
        print("OK — no syntax errors")
finally:
    os.unlink(path)
# also count that doRestart / doExport appear once each
for name in ("function doExport", "function doRestart", "restart_rekordbox"):
    print(f"  {name}: {html.count(name)}")
