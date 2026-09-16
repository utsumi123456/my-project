"""Quit and relaunch rekordbox on the DJ's behalf.

This is the one manual step of the XML import that can honestly be automated:
rekordbox reads a freshly exported XML only at startup, so a relaunch is what
makes new tracks appear under the "rekordbox xml" tree. The final merge into
the real collection still needs the DJ's explicit "add to collection? Yes" --
that stays manual by rekordbox's design, which is the boundary we want (B-2:
Set Agent never writes the collection itself).

Nothing here touches master.db. The destructive part -- force-terminating a
rekordbox that is showing an unsaved-changes prompt -- is NEVER done on our own
initiative: restart() refuses and returns 'still_running' unless the caller
passes force=True, which the UI only does after a second, explicit confirm.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

_PROC = "rekordbox.exe"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _run(args, timeout=15):
    return subprocess.run(args, capture_output=True, text=True, errors="replace",
                          timeout=timeout, creationflags=_NO_WINDOW)


def _is_running() -> bool:
    try:
        out = _run(["tasklist", "/FI", f"IMAGENAME eq {_PROC}", "/NH"]).stdout
        return _PROC.lower() in (out or "").lower()
    except Exception:
        return False


def running_exe_path() -> str | None:
    """Full path of the live rekordbox.exe, or None if not running / unknown.

    Several rekordbox.exe processes (helpers) usually share one ExecutablePath;
    the shortest path is the main install-dir binary.
    """
    if not sys.platform.startswith("win"):
        return None
    try:
        ps = ("Get-CimInstance Win32_Process -Filter \"name='rekordbox.exe'\" "
              "| Select-Object -ExpandProperty ExecutablePath")
        out = _run(["powershell", "-NoProfile", "-Command", ps]).stdout
        paths = sorted((ln.strip() for ln in (out or "").splitlines() if ln.strip()),
                       key=len)
        return paths[0] if paths else None
    except Exception:
        return None


def _candidates() -> list[Path]:
    """Every plausible rekordbox.exe, newest first.

    The real install nests a version folder: Program Files\\rekordbox\\
    rekordbox 7.2.14\\rekordbox.exe. So glob one and two levels deep rather
    than guessing exact folder names.
    """
    found: list[Path] = []
    seen: set[str] = set()
    for base in (os.environ.get("ProgramW6432"), os.environ.get("ProgramFiles"),
                 os.environ.get("ProgramFiles(x86)"), os.environ.get("LOCALAPPDATA")):
        if not base:
            continue
        b = Path(base)
        for pat in ("rekordbox*/rekordbox.exe",              # ...\rekordbox 7\
                    "rekordbox*/rekordbox*/rekordbox.exe"):  # ...\rekordbox\rekordbox 7.2.14\
            try:
                for p in b.glob(pat):
                    key = str(p).lower()
                    if p.is_file() and key not in seen:
                        seen.add(key)
                        found.append(p)
            except OSError:
                continue
    # newest install first (most recently modified exe)
    found.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    return found


def find_exe(remembered: str | None) -> str | None:
    if remembered and Path(remembered).is_file():
        return remembered
    live = running_exe_path()
    if live and Path(live).is_file():
        return live
    for p in _candidates():
        if p.is_file():
            return str(p)
    return None


def _launch(exe: str) -> None:
    flags = (getattr(subprocess, "DETACHED_PROCESS", 0)
             | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    subprocess.Popen([exe], close_fds=True, creationflags=flags,
                     cwd=str(Path(exe).parent))


def restart(remembered: str | None = None, force: bool = False) -> dict:
    """Quit (if running) and relaunch rekordbox.

    Returns a plain dict:
      action: 'restarted' | 'launched' | 'still_running' | 'no_exe'
              | 'launch_failed' | 'unsupported'
      exe:    the path used (when known) -- caller may remember it
      ok:     True only when rekordbox is now (re)launched
    """
    if not sys.platform.startswith("win"):
        return {"ok": False, "action": "unsupported", "launched": False,
                "error": "自動再起動は現在 Windows のみ対応"}

    exe = find_exe(remembered)                 # capture BEFORE we kill anything
    was_running = _is_running()

    if was_running:
        try:                                   # graceful: lets rekordbox flush
            _run(["taskkill", "/IM", _PROC])
        except Exception:
            pass
        for _ in range(16):                    # ~8s to close on its own
            if not _is_running():
                break
            time.sleep(0.5)
        if _is_running():
            if not force:
                # Probably an unsaved-changes prompt. Do NOT force here -- that
                # is the data-loss path, and it needs its own confirmation.
                return {"ok": False, "action": "still_running", "exe": exe,
                        "was_running": True, "launched": False,
                        "error": "rekordbox が終了しなかった（未保存の確認が出ている可能性）"}
            try:
                _run(["taskkill", "/IM", _PROC, "/F"])
            except Exception:
                pass
            for _ in range(12):
                if not _is_running():
                    break
                time.sleep(0.3)

    if not exe:
        return {"ok": False, "action": "no_exe", "was_running": was_running,
                "launched": False,
                "error": "rekordbox.exe の場所が分からなかった。手で起動してくれ"}

    time.sleep(0.8)                            # let the file lock release
    try:
        _launch(exe)
    except Exception as e:                     # noqa: BLE001
        return {"ok": False, "action": "launch_failed", "exe": exe,
                "was_running": was_running, "launched": False,
                "error": f"{type(e).__name__}: {e}"}
    return {"ok": True, "exe": exe, "was_running": was_running, "launched": True,
            "action": "restarted" if was_running else "launched"}
