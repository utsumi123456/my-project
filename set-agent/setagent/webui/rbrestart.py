"""Quit and relaunch rekordbox on the DJ's behalf (Windows and macOS).

Two callers:
  * the playlist write-back (rekordbox.writeback): rekordbox must be closed while
    master.db is written, so "quit -> write -> relaunch" is one button;
  * the old XML flow, which needed a relaunch so rekordbox re-read the XML.

The destructive part -- force-terminating a rekordbox that is showing an
unsaved-changes prompt -- is NEVER done on our own initiative: quit() and
restart() refuse and return 'still_running' unless the caller passes
force=True, which the UI only does after a second, explicit confirm.
"""
from __future__ import annotations

import glob
import os
import subprocess
import sys
import time
from pathlib import Path

_WIN_PROC = "rekordbox.exe"
_MAC_PROC = "rekordbox"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_WIN = sys.platform.startswith("win")
_MAC = sys.platform == "darwin"


def _run(args, timeout=15):
    return subprocess.run(args, capture_output=True, text=True, errors="replace",
                          timeout=timeout, creationflags=_NO_WINDOW)


def _is_running() -> bool:
    try:
        if _WIN:
            out = _run(["tasklist", "/FI", f"IMAGENAME eq {_WIN_PROC}", "/NH"]).stdout
            return _WIN_PROC.lower() in (out or "").lower()
        if _MAC:
            return bool(_run(["pgrep", "-x", _MAC_PROC]).stdout.strip())
    except Exception:
        return False
    return False


is_running = _is_running


def _mac_app_of(binary: str) -> str | None:
    """'/Applications/rekordbox 7/rekordbox.app/Contents/MacOS/rekordbox' -> the .app."""
    p = Path(binary)
    for parent in [p, *p.parents]:
        if parent.suffix == ".app":
            return str(parent)
    return None


def running_exe_path() -> str | None:
    """Where the live rekordbox lives: rekordbox.exe on Windows, the .app on macOS."""
    try:
        if _WIN:
            ps = ("Get-CimInstance Win32_Process -Filter \"name='rekordbox.exe'\" "
                  "| Select-Object -ExpandProperty ExecutablePath")
            out = _run(["powershell", "-NoProfile", "-Command", ps]).stdout
            paths = sorted((ln.strip() for ln in (out or "").splitlines() if ln.strip()), key=len)
            return paths[0] if paths else None
        if _MAC:
            pids = _run(["pgrep", "-x", _MAC_PROC]).stdout.split()
            for pid in pids:
                comm = _run(["ps", "-o", "comm=", "-p", pid]).stdout.strip()
                app = _mac_app_of(comm) if comm else None
                if app:
                    return app
    except Exception:
        return None
    return None


def _candidates() -> list[Path]:
    """Every plausible rekordbox install, newest first.

    Windows nests a version folder (Program Files\\rekordbox\\rekordbox 7.2.14\\
    rekordbox.exe), so glob one and two levels deep. macOS installs
    /Applications/rekordbox 7/rekordbox.app."""
    found: list[Path] = []
    seen: set[str] = set()

    def add(p: Path) -> None:
        key = str(p).lower()
        if p.exists() and key not in seen:
            seen.add(key)
            found.append(p)

    if _WIN:
        for base in (os.environ.get("ProgramW6432"), os.environ.get("ProgramFiles"),
                     os.environ.get("ProgramFiles(x86)"), os.environ.get("LOCALAPPDATA")):
            if not base:
                continue
            b = Path(base)
            for pat in ("rekordbox*/rekordbox.exe", "rekordbox*/rekordbox*/rekordbox.exe"):
                try:
                    for p in b.glob(pat):
                        if p.is_file():
                            add(p)
                except OSError:
                    continue
    elif _MAC:
        for root in ("/Applications", str(Path.home() / "Applications")):
            for pat in ("rekordbox*/rekordbox.app", "rekordbox.app"):
                for p in glob.glob(os.path.join(root, pat)):
                    add(Path(p))
    found.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    return found


def find_exe(remembered: str | None) -> str | None:
    if remembered and Path(remembered).exists():
        return remembered
    live = running_exe_path()
    if live and Path(live).exists():
        return live
    for p in _candidates():
        return str(p)
    return None


def _launch(exe: str) -> None:
    if _MAC:
        subprocess.Popen(["open", "-a", exe], close_fds=True)
        return
    flags = (getattr(subprocess, "DETACHED_PROCESS", 0)
             | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    subprocess.Popen([exe], close_fds=True, creationflags=flags, cwd=str(Path(exe).parent))


def _ask_to_quit() -> None:
    """The polite quit: rekordbox saves and may show its own prompt."""
    if _WIN:
        _run(["taskkill", "/IM", _WIN_PROC])
    elif _MAC:
        _run(["osascript", "-e", f'tell application "{_MAC_PROC}" to quit'], timeout=20)


def _force_quit() -> None:
    if _WIN:
        _run(["taskkill", "/IM", _WIN_PROC, "/F"])
    elif _MAC:
        _run(["pkill", "-x", _MAC_PROC])


def _wait_gone(seconds: float, step: float = 0.5) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if not _is_running():
            return True
        time.sleep(step)
    return not _is_running()


def quit_app(force: bool = False, wait_s: float = 12.0) -> dict:
    """Close rekordbox. Returns {ok, action, exe, error?}.

    action: 'not_running' | 'quit' | 'still_running' | 'unsupported'
    'exe' is captured before quitting so the caller can relaunch the same one."""
    if not (_WIN or _MAC):
        return {"ok": False, "action": "unsupported", "error": "この OS では rekordbox を操作できません"}
    exe = running_exe_path()
    if not _is_running():
        return {"ok": True, "action": "not_running", "exe": exe}
    try:
        _ask_to_quit()
    except Exception:
        pass
    if _wait_gone(wait_s):
        time.sleep(1.0)                        # let rekordbox's file handles go
        return {"ok": True, "action": "quit", "exe": exe}
    if not force:
        # Probably an unsaved-changes prompt. Do NOT force here -- that is the
        # data-loss path, and it needs its own confirmation.
        return {"ok": False, "action": "still_running", "exe": exe,
                "error": "rekordbox が終了しませんでした（確認のダイアログが出ている可能性があります）"}
    try:
        _force_quit()
    except Exception:
        pass
    if _wait_gone(6.0, 0.3):
        time.sleep(1.0)
        return {"ok": True, "action": "quit", "exe": exe, "forced": True}
    return {"ok": False, "action": "still_running", "exe": exe, "error": "rekordbox を終了できませんでした"}


def launch(remembered: str | None = None) -> dict:
    exe = find_exe(remembered)
    if not exe:
        return {"ok": False, "action": "no_exe", "launched": False,
                "error": "rekordbox の場所が分かりませんでした。手で起動してください"}
    try:
        _launch(exe)
    except Exception as e:                     # noqa: BLE001
        return {"ok": False, "action": "launch_failed", "exe": exe, "launched": False,
                "error": f"{type(e).__name__}: {e}"}
    return {"ok": True, "action": "launched", "exe": exe, "launched": True}


def restart(remembered: str | None = None, force: bool = False) -> dict:
    """Quit (if running) and relaunch rekordbox.

    Returns a plain dict:
      action: 'restarted' | 'launched' | 'still_running' | 'no_exe'
              | 'launch_failed' | 'unsupported'
      exe:    the path used (when known) -- caller may remember it
      ok:     True only when rekordbox is now (re)launched
    """
    exe = find_exe(remembered)                 # capture BEFORE we quit anything
    q = quit_app(force=force)
    if not q["ok"]:
        q.setdefault("exe", exe)
        q["launched"] = False
        q["was_running"] = True
        return q
    was_running = q["action"] == "quit"
    r = launch(q.get("exe") or exe)
    r["was_running"] = was_running
    if r["ok"]:
        r["action"] = "restarted" if was_running else "launched"
    return r
