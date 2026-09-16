import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
for l in open("tools_rbmount.txt", encoding="utf-8", errors="replace"):
    if l.startswith("====="):
        print(l.rstrip())
