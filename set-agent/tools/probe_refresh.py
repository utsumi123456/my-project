"""Exercise the semi-automatic refresh loop from inside WebView2, then quit.

  python -m tools.probe_refresh [playlist]

Cannot edit rekordbox from here, so the change is faked at the one seam the
poller reads: LIB_SIG. Checks (1) an untouched draft reloads by itself,
(2) an edited draft does not -- it lights the button instead, (3) the button
reloads and clears it, (4) a WAL-only change reloads too (the WAL is replayed).
"""
from __future__ import annotations

import sys
import time

import webview

from setagent.webui.api import Api
from setagent.webui.app import index_path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def wait_ready(window, label):
    for _ in range(60):
        time.sleep(1)
        try:
            if window.evaluate_js("!document.getElementById('app').hidden"):
                return True
        except Exception:
            pass
    print(label, "never became ready")
    return False


def fresh(window):
    # The freshness row lives in the settings sheet since 2026-09-16; on the
    # main view the only stale signal is the dot on the settings button.
    return window.evaluate_js(
        "({state: FRESH.state, btn: document.getElementById('settings').className,"
        "  loaded: LOADED_AT && LOADED_AT.getTime(), sig: LIB_SIG && LIB_SIG.db})")


def wait_reload(window, prev_loaded, label):
    """Wait until a reload finished: LOADED_AT moved on and the curtain is down.

    #app stays visible under the curtain, so wait_ready alone returns at once
    and reads values mid-reload (artwork makes a reload take several seconds).
    """
    for _ in range(60):
        time.sleep(1)
        try:
            f = fresh(window)
            if f["loaded"] and f["loaded"] != prev_loaded and                     window.evaluate_js("document.getElementById('curtain').hidden"):
                return f
        except Exception:
            pass
    print(label, "never finished reloading")
    return fresh(window)


def run(window):
    try:
        if not wait_ready(window, "boot"):
            return
        window.evaluate_js("pollLibrary()")         # don't wait for the 5s timer
        time.sleep(4)
        f0 = fresh(window)
        print("0 baseline:", f0)
        assert f0["sig"], "poller never recorded a signature"
        window.evaluate_js("window.__lc = null; (async()=>{window.__lc = await window.pywebview.api.library_changed();})()")
        time.sleep(3)
        print("  library_changed ->", window.evaluate_js("JSON.stringify(window.__lc)"))

        # (1) untouched draft + master.db changed -> auto reload
        window.evaluate_js("LIB_SIG.db = 'fake'; pollLibrary();")
        t = time.time()
        f1 = wait_reload(window, f0["loaded"], "auto-reload")
        print(f"  reload took {time.time() - t:.1f}s")
        print("1 auto-reload:", f1)
        print("   reloaded:", f1["loaded"] != f0["loaded"], "state fresh:", f1["state"] == "fresh")

        # (2) an in-app edit, then the same fake change -> stale, button lit, no reload
        window.evaluate_js("(async()=>{apply(await window.pywebview.api.set_tempo(0, 130));})()")
        time.sleep(2)
        window.evaluate_js("pollLibrary()")        # refill LIB_SIG after the reload
        time.sleep(4)
        window.evaluate_js("window.__lc = null; (async()=>{window.__lc = await window.pywebview.api.library_changed();})()")
        time.sleep(3)
        print("2 edited flag after set_tempo:", window.evaluate_js("window.__lc && window.__lc.edited"))
        window.evaluate_js("LIB_SIG.db = 'fake2'; pollLibrary();")
        time.sleep(2)
        f2 = fresh(window)
        print("  stale:", f2)
        print("   held (no reload):", f2["loaded"] == f1["loaded"], "state:", f2["state"], "btn:", f2["btn"])

        # (3) settings sheet -> reload button -> back to fresh
        window.evaluate_js("document.getElementById('settings').click()")
        time.sleep(1)
        print("  sheet:", window.evaluate_js(
            "({txt: document.getElementById('freshTxt').textContent,"
            "  btn: document.getElementById('rescan').className})"))
        window.evaluate_js("document.getElementById('rescan').click()")
        f3 = wait_reload(window, f2["loaded"], "button-reload")
        window.evaluate_js("pollLibrary()")
        time.sleep(4)
        f3 = fresh(window)
        print("3 after button:", f3)
        print("   reloaded:", f3["loaded"] != f2["loaded"], "state:", f3["state"], "btn:", f3["btn"])

        # (4) WAL-only change on an untouched draft -> auto reload as well
        window.evaluate_js("LIB_SIG.wal = 'fakewal'; pollLibrary();")
        f4 = wait_reload(window, f3["loaded"], "wal-reload")
        print("4 wal-only:", f4)
        print("   reloaded:", f4["loaded"] != f3["loaded"], "state fresh:", f4["state"] == "fresh")
    except Exception as ex:
        print("probe failed:", type(ex).__name__, ex)
    finally:
        window.destroy()


if __name__ == "__main__":
    api = Api(sys.argv[1] if len(sys.argv) > 1 else "acid")
    w = webview.create_window("Set Agent — probe", index_path(), js_api=api,
                              width=1100, height=800, background_color="#0d1014")
    api._window = w
    webview.start(run, w)
