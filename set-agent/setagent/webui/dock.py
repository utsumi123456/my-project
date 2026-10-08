"""Dock the panel to rekordbox's window, so it reads as part of rekordbox (B).

rekordbox has no plugin API, and drawing into its process (the old S6 overlay
spike: DLL injection + D3D12 Present hooks) breaks on every update. Instead the
panel follows rekordbox's main window from the outside:

  side    beside rekordbox (right edge), same top and height. Falls back to
          `inside` when the screen has no room beside it.
  inside  over rekordbox's right edge, inside its frame.
  split   resize rekordbox so both fit side by side on its screen. Moves
          another app's window, so macOS asks for Accessibility permission once.
  off     a free-floating panel, as before.

While docked the panel stays above rekordbox only while rekordbox (or the panel
itself) is the frontmost app, so it never floats over the DJ's other apps.
Dragging the panel away undocks it, the way a DJ would expect.

Window discovery reads only geometry: Quartz CGWindowList on macOS (no
permission needed) and EnumWindows/DWM on Windows. Nothing is injected.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable

MODES = ("off", "side", "inside", "split")
MIN_PANEL_W = 380
MIN_RB_W = 900                    # rekordbox below this is unusable; split refuses to go narrower
DRAG_UNDOCK_PX = 40


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def overlap(self, o: "Rect") -> int:
        ow = min(self.right, o.right) - max(self.x, o.x)
        oh = min(self.bottom, o.bottom) - max(self.y, o.y)
        return max(ow, 0) * max(oh, 0)

    def close_to(self, o: "Rect", tol: int = 2) -> bool:
        return all(abs(a - b) <= tol for a, b in ((self.x, o.x), (self.y, o.y), (self.w, o.w), (self.h, o.h)))


@dataclass(frozen=True)
class Placement:
    panel: Rect
    mode: str                       # the mode actually used (side may become inside)
    rekordbox: Rect | None = None   # split: where rekordbox should go


def screen_of(r: Rect, screens: list[Rect]) -> Rect | None:
    best = max(screens, key=lambda s: s.overlap(r), default=None)
    return best if best is not None and best.overlap(r) > 0 else (screens[0] if screens else None)


def plan(rb: Rect, panel_w: int, screens: list[Rect], mode: str) -> Placement | None:
    """Where the panel (and, for split, rekordbox) should be. Pure geometry.

    `screens` are work areas (menu bar / taskbar excluded) in the same top-left
    origin coordinates as `rb`."""
    if mode == "off" or rb.w <= 0 or rb.h <= 0:
        return None
    scr = screen_of(rb, screens) or rb
    pw = max(MIN_PANEL_W, int(panel_w))
    top = max(rb.y, scr.y)
    height = min(rb.bottom, scr.bottom) - top
    if mode == "split":
        # rekordbox keeps the left part of its screen, the panel takes the right
        pw = min(pw, scr.w - MIN_RB_W)
        if pw < MIN_PANEL_W:
            mode = "inside"
        else:
            rb_new = Rect(scr.x, scr.y, scr.w - pw, scr.h)
            return Placement(Rect(rb_new.right, scr.y, pw, scr.h), "split", rb_new)
    if mode == "side":
        if rb.right + pw <= scr.right:
            return Placement(Rect(rb.right, top, pw, height), "side")
        if rb.x - pw >= scr.x:                      # no room right, room left
            return Placement(Rect(rb.x - pw, top, pw, height), "side")
        mode = "inside"
    # inside: over rekordbox's own right edge
    pw = min(pw, rb.w)
    return Placement(Rect(rb.right - pw, top, pw, height), "inside")


# ---------------------------------------------------------------- platform

class Platform:
    """What the docker needs from the OS. Subclassed per platform; tests fake it."""

    def rekordbox_window(self) -> Rect | None: ...
    def screens(self) -> list[Rect]: return []
    def frontmost_is_ours(self) -> bool: return True          # rekordbox or this panel
    def place_panel(self, window, r: Rect) -> None: ...
    def panel_rect(self, window) -> Rect | None: ...
    def set_on_top(self, window, on: bool) -> None:
        try:
            window.on_top = on
        except Exception:
            pass
    def move_rekordbox(self, r: Rect) -> str: return "unsupported"   # "ok" | "denied" | "unsupported"


class MacPlatform(Platform):
    def __init__(self):
        import AppKit
        import Quartz
        self.AppKit, self.Quartz = AppKit, Quartz
        self.pid = os.getpid()

    def _primary_h(self) -> float:
        return self.AppKit.NSScreen.screens()[0].frame().size.height

    def _rb_pids(self) -> set[int]:
        apps = self.AppKit.NSWorkspace.sharedWorkspace().runningApplications()
        return {int(a.processIdentifier()) for a in apps if (a.localizedName() or "") == "rekordbox"}

    def rekordbox_window(self) -> Rect | None:
        Q = self.Quartz
        pids = self._rb_pids()
        if not pids:
            return None
        info = Q.CGWindowListCopyWindowInfo(
            Q.kCGWindowListOptionOnScreenOnly | Q.kCGWindowListExcludeDesktopElements, Q.kCGNullWindowID)
        best = None
        for w in info or []:
            if int(w.get("kCGWindowOwnerPID", -1)) not in pids or int(w.get("kCGWindowLayer", 1)) != 0:
                continue
            b = w.get("kCGWindowBounds") or {}
            r = Rect(int(b.get("X", 0)), int(b.get("Y", 0)), int(b.get("Width", 0)), int(b.get("Height", 0)))
            if r.w < 400 or r.h < 300 or float(w.get("kCGWindowAlpha", 1)) <= 0:
                continue                                    # tooltips, popovers, splash
            if best is None or r.w * r.h > best.w * best.h:
                best = r
        return best

    def screens(self) -> list[Rect]:
        H = self._primary_h()
        out = []
        for s in self.AppKit.NSScreen.screens():
            f = s.visibleFrame()
            out.append(Rect(int(f.origin.x), int(H - (f.origin.y + f.size.height)),
                            int(f.size.width), int(f.size.height)))
        return out

    def frontmost_is_ours(self) -> bool:
        app = self.AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return False
        return int(app.processIdentifier()) == self.pid or (app.localizedName() or "") == "rekordbox"

    def _nswindow(self, window):
        from webview.platforms.cocoa import BrowserView
        inst = BrowserView.instances.get(window.uid)
        return inst.window if inst else None

    def place_panel(self, window, r: Rect) -> None:
        from PyObjCTools import AppHelper
        H = self._primary_h()

        def go():
            w = self._nswindow(window)
            if w is not None:
                frame = self.AppKit.NSMakeRect(r.x, H - (r.y + r.h), r.w, r.h)
                w.setFrame_display_(frame, True)
        AppHelper.callAfter(go)

    def panel_rect(self, window) -> Rect | None:
        w = self._nswindow(window)
        if w is None:
            return None
        f = w.frame()
        H = self._primary_h()
        return Rect(int(f.origin.x), int(H - (f.origin.y + f.size.height)), int(f.size.width), int(f.size.height))

    def set_on_top(self, window, on: bool) -> None:
        from PyObjCTools import AppHelper

        def go():
            w = self._nswindow(window)
            if w is not None:
                # floating, not pywebview's status-bar level: above rekordbox,
                # below menus and system UI
                w.setLevel_(self.AppKit.NSFloatingWindowLevel if on else self.AppKit.NSNormalWindowLevel)
        AppHelper.callAfter(go)

    def move_rekordbox(self, r: Rect) -> str:
        try:
            import ApplicationServices as AS
        except Exception:
            return "unsupported"
        if not AS.AXIsProcessTrustedWithOptions({AS.kAXTrustedCheckOptionPrompt: True}):
            return "denied"
        for pid in self._rb_pids():
            app = AS.AXUIElementCreateApplication(pid)
            err, wins = AS.AXUIElementCopyAttributeValue(app, AS.kAXWindowsAttribute, None)
            if err or not wins:
                continue
            target, area = None, 0
            for w in wins:
                e1, size = AS.AXUIElementCopyAttributeValue(w, AS.kAXSizeAttribute, None)
                if e1:
                    continue
                ok, sz = AS.AXValueGetValue(size, AS.kAXValueCGSizeType, None)
                if ok and sz.width * sz.height > area:
                    target, area = w, sz.width * sz.height
            if target is None:
                continue
            pos = AS.AXValueCreate(AS.kAXValueCGPointType, self.Quartz.CGPointMake(r.x, r.y))
            size = AS.AXValueCreate(AS.kAXValueCGSizeType, self.Quartz.CGSizeMake(r.w, r.h))
            AS.AXUIElementSetAttributeValue(target, AS.kAXPositionAttribute, pos)
            AS.AXUIElementSetAttributeValue(target, AS.kAXSizeAttribute, size)
            return "ok"
        return "unsupported"


class WinPlatform(Platform):
    def __init__(self):
        import ctypes
        import ctypes.wintypes as wt
        self.ct, self.wt = ctypes, wt
        self.user32 = ctypes.windll.user32
        self.pid = os.getpid()
        self._rb_hwnd = None

    def _proc_name(self, pid: int) -> str:
        ct, wt = self.ct, self.wt
        k32 = ct.windll.kernel32
        h = k32.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ""
        try:
            buf = ct.create_unicode_buffer(520)
            n = wt.DWORD(520)
            if k32.QueryFullProcessImageNameW(h, 0, buf, ct.byref(n)):
                return os.path.basename(buf.value).lower()
            return ""
        finally:
            k32.CloseHandle(h)

    def _pid_of(self, hwnd) -> int:
        pid = self.wt.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, self.ct.byref(pid))
        return pid.value

    def _rect(self, hwnd) -> Rect | None:
        ct, wt = self.ct, self.wt
        r = wt.RECT()
        try:   # DWMWA_EXTENDED_FRAME_BOUNDS: the visible frame, without the invisible resize border
            if ct.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ct.byref(r), ct.sizeof(r)) != 0:
                raise OSError
        except Exception:
            if not self.user32.GetWindowRect(hwnd, ct.byref(r)):
                return None
        return Rect(r.left, r.top, r.right - r.left, r.bottom - r.top)

    def rekordbox_window(self) -> Rect | None:
        ct, wt = self.ct, self.wt
        found: list[tuple[int, Rect, int]] = []
        names: dict[int, str] = {}

        @ct.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        def each(hwnd, _):
            if not self.user32.IsWindowVisible(hwnd) or self.user32.IsIconic(hwnd):
                return True
            if self.user32.GetWindow(hwnd, 4):                # GW_OWNER: dialogs and popups
                return True
            pid = self._pid_of(hwnd)
            if pid not in names:
                names[pid] = self._proc_name(pid)
            if names[pid] != "rekordbox.exe":
                return True
            r = self._rect(hwnd)
            if r and r.w >= 400 and r.h >= 300:
                found.append((r.w * r.h, r, hwnd))
            return True

        self.user32.EnumWindows(each, 0)
        if not found:
            self._rb_hwnd = None
            return None
        found.sort(key=lambda t: -t[0])
        self._rb_hwnd = found[0][2]
        return found[0][1]

    def screens(self) -> list[Rect]:
        ct, wt = self.ct, self.wt
        out: list[Rect] = []

        class MONITORINFO(ct.Structure):
            _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]

        @ct.WINFUNCTYPE(wt.BOOL, wt.HMONITOR, wt.HDC, ct.POINTER(wt.RECT), wt.LPARAM)
        def each(hmon, hdc, rc, _):
            mi = MONITORINFO()
            mi.cbSize = ct.sizeof(MONITORINFO)
            if self.user32.GetMonitorInfoW(hmon, ct.byref(mi)):
                w = mi.rcWork
                out.append(Rect(w.left, w.top, w.right - w.left, w.bottom - w.top))
            return True

        self.user32.EnumDisplayMonitors(None, None, each, 0)
        return out

    def frontmost_is_ours(self) -> bool:
        hwnd = self.user32.GetForegroundWindow()
        if not hwnd:
            return False
        pid = self._pid_of(hwnd)
        return pid == self.pid or self._proc_name(pid) == "rekordbox.exe"

    def place_panel(self, window, r: Rect) -> None:
        window.move(r.x, r.y)
        window.resize(r.w, r.h)

    def panel_rect(self, window) -> Rect | None:
        try:
            return Rect(int(window.x), int(window.y), int(window.width), int(window.height))
        except Exception:
            return None

    def move_rekordbox(self, r: Rect) -> str:
        if not self._rb_hwnd:
            return "unsupported"
        if self.user32.IsZoomed(self._rb_hwnd):
            self.user32.ShowWindow(self._rb_hwnd, 9)          # SW_RESTORE: a maximised window ignores moves
        ok = self.user32.SetWindowPos(self._rb_hwnd, None, r.x, r.y, r.w, r.h, 0x0014)  # NOZORDER|NOACTIVATE
        return "ok" if ok else "denied"


def current_platform() -> Platform | None:
    try:
        if sys.platform == "darwin":
            return MacPlatform()
        if sys.platform.startswith("win"):
            return WinPlatform()
    except Exception:
        return None
    return None


# ------------------------------------------------------------------ docker

class Docker:
    """Background follower. Thread-safe enough for its job: the view changes
    `mode` and `panel_w`; the loop reads them each tick."""

    def __init__(self, window, platform: Platform | None, mode: str = "off", panel_w: int = 460,
                 on_undock: Callable[[str], None] | None = None, tick_s: float = 0.25):
        self.window = window
        self.p = platform
        self.mode = mode if mode in MODES else "off"
        self.panel_w = max(MIN_PANEL_W, int(panel_w))
        self.on_undock = on_undock
        self.tick_s = tick_s
        self.collapsed = False
        self.collapsed_w = 64
        self.effective = "off"           # what the last placement actually did
        self.note = ""
        self._target: Rect | None = None     # what we last asked for
        self._seen: Rect | None = None       # where it actually settled
        self._settle = 0
        self._last_rb: Rect | None = None
        self._split_applied = False
        self._on_top: bool | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------ control
    def start(self) -> None:
        if self.p is None or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="setagent-dock", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def set_mode(self, mode: str) -> dict:
        if mode not in MODES:
            return {"error": f"不明なドッキング: {mode}"}
        with self._lock:
            if self.mode == "off" and mode != "off":
                cur = self.p.panel_rect(self.window) if self.p else None
                if cur and not self.collapsed:
                    self.panel_w = max(MIN_PANEL_W, cur.w)
            self.mode = mode
            self._target = self._seen = None
            self._split_applied = False
            self.note = ""
        if mode == "off" and self.p:
            self._set_top(True)          # back to the old always-on-top panel
            self.effective = "off"
        return self.status()

    def set_collapsed(self, on: bool) -> dict:
        with self._lock:
            self.collapsed = bool(on)
            self._target = None
        if self.mode == "off" and self.p:      # undocked: shrink/grow in place
            cur = self.p.panel_rect(self.window)
            if cur:
                w = self.collapsed_w if on else self.panel_w
                x = cur.right - w if on else max(cur.right - w, 0)
                self.p.place_panel(self.window, Rect(x, cur.y, w, cur.h))
        return self.status()

    def status(self) -> dict:
        return {"mode": self.mode, "effective": self.effective, "collapsed": self.collapsed,
                "available": self.p is not None, "note": self.note, "modes": list(MODES)}

    # ------------------------------------------------------------- loop
    def _set_top(self, on: bool) -> None:
        if self._on_top is on:
            return
        self._on_top = on
        self.p.set_on_top(self.window, on)

    def tick(self) -> None:
        """One step: find rekordbox, place the panel, mind the stacking."""
        with self._lock:
            mode, pw, collapsed = self.mode, self.panel_w, self.collapsed
        if mode == "off":
            return
        rb = self.p.rekordbox_window()
        if rb is None:
            self.effective = "waiting"
            self._split_applied = False         # re-split when rekordbox comes back
            self._set_top(False)                # rekordbox closed or hidden: an ordinary window
            return
        cur = self.p.panel_rect(self.window)
        if self._settle > 0:
            # the OS may nudge a placement (menu bar, screen edge): what it
            # settled to is the baseline for noticing the DJ's own drag
            self._settle -= 1
            if cur is not None:
                self._seen = cur
        elif self._seen is not None and cur is not None and self._last_rb is not None:
            moved = abs(cur.x - self._seen.x) > DRAG_UNDOCK_PX or abs(cur.y - self._seen.y) > DRAG_UNDOCK_PX
            if moved and rb.close_to(self._last_rb):
                with self._lock:
                    self.mode = "off"
                self.effective = "off"
                self._target = self._seen = None
                self._set_top(True)
                if self.on_undock:
                    self.on_undock("パネルを動かしたのでドッキングを解除しました")
                return
            if not collapsed and not moved and abs(cur.w - self._seen.w) > 8:
                with self._lock:                # the DJ resized the docked panel: keep that width
                    self.panel_w = pw = max(MIN_PANEL_W, cur.w)
                self._seen = cur
        screens = self.p.screens()
        if mode == "split" and not self._split_applied:
            self._split_applied = True          # one attempt per rekordbox window; never fight the DJ
            sp = plan(rb, pw, screens, "split")
            if sp is not None and sp.rekordbox is not None:
                r = self.p.move_rekordbox(sp.rekordbox)
                if r == "ok":
                    rb = sp.rekordbox
                    self.note = ""
                elif r == "denied":
                    self.note = ("rekordbox のウィンドウを動かす許可がありません。macOS は システム設定 → "
                                 "プライバシーとセキュリティ → アクセシビリティ で Set Agent を許可してください")
                else:
                    self.note = "この環境では rekordbox を縮められません。横か内側に付けます"
            else:
                self.note = "画面が狭く rekordbox を縮められません。内側に付けます"
        pl = plan(rb, pw, screens, "side" if mode == "split" else mode)
        if pl is None:
            return
        target = pl.panel
        if collapsed:
            # the strip hugs rekordbox: beside its right edge keep our left edge, otherwise our right
            x = target.x if (pl.mode == "side" and target.x >= rb.right - 1) else target.right - self.collapsed_w
            target = Rect(x, target.y, self.collapsed_w, target.h)
        self.effective = "split" if (mode == "split" and pl.mode == "side") else pl.mode
        if self._target is None or not self._target.close_to(target):
            self.p.place_panel(self.window, target)
            self._target = target
            self._settle = 2
        self._last_rb = rb
        self._set_top(self.p.frontmost_is_ours())

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as ex:            # a flaky OS call must not kill the follower
                self.note = f"{type(ex).__name__}: {ex}"
            self._stop.wait(self.tick_s)
