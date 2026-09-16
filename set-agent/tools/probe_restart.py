"""Verify the restart wiring WITHOUT killing or launching anything."""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from setagent.settings import Settings
from setagent.webui import rbrestart
from setagent.webui.api import _SERIAL, Api

print("settings has rekordbox_exe:", hasattr(Settings(), "rekordbox_exe"))
print("restart_rekordbox in _SERIAL:", "restart_rekordbox" in _SERIAL)
print("Api.restart_rekordbox exists:", hasattr(Api, "restart_rekordbox"))

print("running_exe_path():", rbrestart.running_exe_path())
print("find_exe(None):", rbrestart.find_exe(None))
print("candidates that exist:",
      [str(p) for p in rbrestart._candidates() if p.is_file()])
print("_is_running():", rbrestart._is_running())
