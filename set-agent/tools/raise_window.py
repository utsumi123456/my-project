"""Pin (or release) the Set Agent window on top so a screenshot can see it.

  python -m tools.raise_window          pin topmost + focus
  python -m tools.raise_window release  put it back in the normal z-order

Windows refuses SetForegroundWindow from a process that is not already in front,
so TOPMOST is the only reliable way to photograph the window from a script.
Always release it afterwards -- leaving someone's tool pinned over their work is
rude.
"""
from __future__ import annotations

import ctypes
import sys

u = ctypes.windll.user32
HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
SWP_NOSIZE_NOMOVE = 0x0003
SW_RESTORE = 9


def find(title_prefix: str = "Set Agent") -> int:
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(h, _l):
        buf = ctypes.create_unicode_buffer(300)
        u.GetWindowTextW(h, buf, 300)
        if buf.value.startswith(title_prefix) and u.IsWindowVisible(h):
            found.append(h)
        return True

    u.EnumWindows(cb, 0)
    return found[0] if found else 0


if __name__ == "__main__":
    h = find()
    if not h:
        print("window not found")
        raise SystemExit(1)
    if "release" in sys.argv:
        u.SetWindowPos(h, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOSIZE_NOMOVE)
        print("released")
    else:
        u.ShowWindow(h, SW_RESTORE)
        u.SetWindowPos(h, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOSIZE_NOMOVE)
        u.SetForegroundWindow(h)
        print("pinned", hex(h))
