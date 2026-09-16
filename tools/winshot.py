"""Capture a tkinter window by its own hwnd (PrintWindow), in-process.

Desktop screenshots on this machine sometimes hand back a stale frame, which once
cost an afternoon of chasing a bug that was not there. This asks the window to
paint itself, so what lands in the PNG is what the app just drew.
Windows only.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes


class _BMIH(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


def settle(app, rounds: int = 6) -> None:
    app.update_idletasks()
    for _ in range(rounds):
        app.update()


def shoot(app, out: str) -> tuple[int, int]:
    settle(app)
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    top = int(app.winfo_id())
    while True:
        parent = user32.GetParent(top)
        if not parent:
            break
        top = parent

    rect = wintypes.RECT()
    user32.GetWindowRect(top, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top

    hdc = user32.GetWindowDC(top)
    memdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(memdc, bmp)
    user32.PrintWindow(top, memdc, 2)          # PW_RENDERFULLCONTENT

    bi = _BMIH()
    bi.biSize = ctypes.sizeof(_BMIH); bi.biWidth = w; bi.biHeight = -h
    bi.biPlanes = 1; bi.biBitCount = 32; bi.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(memdc, bmp, 0, h, buf, ctypes.byref(bi), 0)

    from PIL import Image
    Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB").save(out)
    gdi32.DeleteObject(bmp); gdi32.DeleteDC(memdc); user32.ReleaseDC(top, hdc)
    return w, h
