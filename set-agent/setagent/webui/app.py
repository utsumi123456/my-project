"""Entry point for the WebView2 workbench.

  python -m setagent.webui.app [playlist]

WebView2 ships with Windows 10/11, so there is nothing extra to install on a
teammate's PC. Unlike the Canvas UI this needs no DPI call of its own: the view
reports devicePixelRatio and CSS pixels stay CSS pixels at any scaling.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import webview

from setagent.settings import Settings
from setagent.webui.api import Api

DEFAULT = dict(width=460, height=940)
MIN_SIZE = (148, 560)           # 148: the collapsed strip (dock); the view switches to it below 300px
RESTORE_MIN_W = 380


def saved_geometry(cfg: Settings, screens=None) -> dict:
    """Last position/size, but only if it still lands on a connected screen.

    A panel remembered on a monitor that is no longer plugged in must not come
    back off-screen with no way to grab it, so anything that does not overlap
    a current screen falls back to the default size at the default position.
    """
    try:
        x, y, w, h = (int(v) for v in cfg.window.split(","))
    except (ValueError, AttributeError):
        return dict(DEFAULT)
    w, h = max(w, RESTORE_MIN_W), max(h, MIN_SIZE[1])
    if screens is None:
        try:
            screens = webview.screens
        except Exception:
            screens = []
    for s in screens:
        overlap_w = min(x + w, s.x + s.width) - max(x, s.x)
        overlap_h = min(y + h, s.y + s.height) - max(y, s.y)
        if overlap_w >= 200 and overlap_h >= 120:
            return dict(x=x, y=y, width=w, height=h)
    return dict(DEFAULT)


def remember_geometry(window, cfg: Settings) -> None:
    """Persist the panel geometry on move/resize (debounced) and on close."""
    timer: list[threading.Timer | None] = [None]

    def save():
        try:
            cfg.window = f"{window.x},{window.y},{window.width},{window.height}"
            cfg.save()
        except Exception:
            pass                                # never let bookkeeping hurt the app

    def later():
        if timer[0]:
            timer[0].cancel()
        timer[0] = threading.Timer(0.8, save)
        timer[0].daemon = True
        timer[0].start()

    window.events.moved += lambda *a: later()
    window.events.resized += lambda *a: later()
    window.events.closing += lambda *a: save()


def start_dock(window, api: Api) -> None:
    """Follow rekordbox's window (webui.dock). Starts once the native window
    exists; a platform without support just leaves the panel free-floating."""
    from setagent.webui.dock import Docker, current_platform

    def undocked(msg: str) -> None:
        api.cfgfile.dock = "off"
        api.cfgfile.save()

    def go(*_a):
        if api.docker is not None:
            return
        cfg = api.cfgfile
        w = 460
        try:
            w = int(cfg.window.split(",")[2])
        except (ValueError, IndexError, AttributeError):
            pass
        d = Docker(window, current_platform(), mode=cfg.dock, panel_w=w, on_undock=undocked)
        d.collapsed = bool(cfg.dock_collapsed)
        api.docker = d
        d.start()

    window.events.shown += go


def index_path() -> str:
    """Works from source and from inside a PyInstaller one-file bundle."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent.parent))
    here = Path(__file__).resolve().parent
    for p in (here / "index.html", base / "setagent" / "webui" / "index.html"):
        if p.exists():
            return str(p)
    raise FileNotFoundError("index.html が見つからない（ビルドに同梱されていない可能性）")


def main(playlist: str | None = None) -> None:
    api = Api(playlist)
    # 2026-09-16: Set Agent is a read-only panel the DJ keeps beside rekordbox.
    # It opens as a narrow, always-on-top column (the main view is built for
    # ~400px) where the DJ last left it; the detail view is a click away and
    # the window can be widened. Going frameless is the next overlay step.
    window = webview.create_window(
        "Set Agent",
        index_path(),
        js_api=api,
        min_size=MIN_SIZE,
        background_color="#0d1014",
        on_top=True,
        **saved_geometry(api.cfgfile),
    )
    remember_geometry(window, api.cfgfile)
    start_dock(window, api)
    # Underscore-private on purpose: pywebview walks the js_api object's public
    # attributes to expose them to JS, and handing it a Window sends that walk
    # into an infinite recursion through .AccessibilityObject.Bounds.Empty.
    api._window = window         # so the XML export can raise a native save dialog
    # The Dock icon, set by the running app itself (pywebview's cocoa backend calls
    # NSApplication.setApplicationIconImage_). The bundle's .icns alone was not
    # enough on the DJ's Mac (2026-10-09): macOS keeps showing a cached icon for an
    # app replaced at the same path.
    icon = icon_path()
    webview.start(icon=icon) if icon else webview.start()


def icon_path() -> str | None:
    """SetAgent.png next to index.html (build.py bundles it), or the repo's assets/icon."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent.parent))
    for p in (Path(index_path()).with_name("SetAgent.png"),
              base / "setagent" / "webui" / "SetAgent.png",
              Path(__file__).resolve().parent.parent.parent / "assets" / "icon" / "SetAgent.png"):
        if p.exists():
            return str(p)
    return None


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
