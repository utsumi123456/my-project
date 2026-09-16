"""Entry point for the WebView2 workbench.

  python -m setagent.webui.app [playlist]

WebView2 ships with Windows 10/11, so there is nothing extra to install on a
teammate's PC. Unlike the Canvas UI this needs no DPI call of its own: the view
reports devicePixelRatio and CSS pixels stay CSS pixels at any scaling.
"""
from __future__ import annotations

import sys
from pathlib import Path

import webview

from setagent.webui.api import Api


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
    window = webview.create_window(
        "Set Agent — Workbench",
        index_path(),
        js_api=api,
        width=1280, height=820, min_size=(940, 620),
        background_color="#0d1014",
        maximized=True,          # a 137-minute set wants every pixel of the display
    )
    # Underscore-private on purpose: pywebview walks the js_api object's public
    # attributes to expose them to JS, and handing it a Window sends that walk
    # into an infinite recursion through .AccessibilityObject.Bounds.Empty.
    api._window = window         # so the XML export can raise a native save dialog
    webview.start()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
