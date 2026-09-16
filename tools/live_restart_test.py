"""One live pass of the restart path, then leave rekordbox closed again.

Safe because rekordbox starts CLOSED here: step 1 is a pure launch (no kill),
step 2 exercises graceful-kill+relaunch on an app with no unsaved work, step 3
restores the original closed state.
"""
import sys, time
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from setagent.webui import rbrestart

print("[0] running at start:", rbrestart._is_running())

print("[1] launch (was closed) ...")
r1 = rbrestart.restart(None, force=False)
print("    ->", r1)
time.sleep(12)
print("    running now:", rbrestart._is_running())

print("[2] restart (now running) — graceful kill + relaunch ...")
r2 = rbrestart.restart(r1.get("exe"), force=False)
print("    ->", r2)
time.sleep(12)
print("    running now:", rbrestart._is_running())

print("[3] cleanup — force close to restore the original closed state ...")
import subprocess
subprocess.run(["taskkill", "/IM", "rekordbox.exe", "/F"],
               capture_output=True, text=True)
time.sleep(3)
print("    running now:", rbrestart._is_running())
