"""Why isn't Set Agent following rekordbox? A step-by-step report.

  SetAgent --follow-check        (macOS: /Applications/SetAgent.app/Contents/MacOS/SetAgent --follow-check)
  python -m setagent.rekordbox.follow_check

Following has five links -- permission, finding rekordbox, reading its
accessibility tree, parsing the status line, matching it to a playlist -- and
the panel can only say which one failed, not why. This walks each link with
rekordbox open on a playlist and writes what it saw to follow-check.txt in the
app folder, so a DJ can send one file instead of describing the screen.
Read-only: nothing is clicked or written in rekordbox.
"""
from __future__ import annotations

import os
import platform
import sys
import time
import traceback
from pathlib import Path

from setagent.rekordbox import selection

MAX_NODES = 600
MAX_DEPTH = 8


class Out:
    def __init__(self):
        self.lines: list[str] = []

    def __call__(self, s: str = "") -> None:
        self.lines.append(s)
        print(s, flush=True)


def _short(v, n=70) -> str:
    s = str(v).replace("\n", " ")
    return s if len(s) <= n else s[:n] + "…"


def _mac(out: Out) -> str | None:
    try:
        import AppKit
        import ApplicationServices as AS
    except Exception as ex:
        out(f"[NG] pyobjc (AppKit / ApplicationServices) を読み込めません: {type(ex).__name__}: {ex}")
        return None
    out("[OK] pyobjc")
    try:
        b = AppKit.NSBundle.mainBundle()
        out(f"     bundle: {b.bundlePath()}  id={b.bundleIdentifier()}")
    except Exception:
        pass
    trusted = bool(AS.AXIsProcessTrusted())
    out(f"[{'OK' if trusted else 'NG'}] アクセシビリティの許可: {'あり' if trusted else 'なし'}")
    if not trusted:
        out("     システム設定 > プライバシーとセキュリティ > アクセシビリティ で SetAgent をオフ→オン"
            "（アプリを入れ替えると、オンのままでも効かなくなります）")

    apps = AppKit.NSWorkspace.sharedWorkspace().runningApplications()
    rb = [a for a in apps if "rekordbox" in str(a.localizedName() or "").lower()
          or "rekordbox" in str(a.bundleIdentifier() or "").lower()]
    for a in rb:
        out(f"     process: name={a.localizedName()!r} bundle={a.bundleIdentifier()!r} "
            f"pid={a.processIdentifier()} policy={a.activationPolicy()}")
    pids = selection.mac_rekordbox_pids(AppKit)
    out(f"[{'OK' if pids else 'NG'}] rekordbox のプロセス: {pids or '見つかりません'}")
    if not trusted or not pids:
        return None

    def attr(e, a):
        err, v = AS.AXUIElementCopyAttributeValue(e, a, None)
        return None if err else v

    for pid in pids:
        app = AS.AXUIElementCreateApplication(pid)
        t0 = time.monotonic()
        wins = attr(app, "AXWindows") or []
        out(f"     pid {pid}: AXWindows {len(wins)}  ({(time.monotonic() - t0) * 1000:.0f} ms)")
        # the tree, breadth-first, as find_status sees it (data views marked, not entered)
        level, n, hits = [(w, 0) for w in wins], 0, []
        t0 = time.monotonic()
        while level and n < MAX_NODES:
            nxt = []
            for e, d in level:
                n += 1
                role = attr(e, "AXRole")
                kids = attr(e, "AXChildren") or []
                val = attr(e, "AXValue") if role == "AXStaticText" else None
                title = attr(e, "AXTitle") or attr(e, "AXDescription") or ""
                mark = ""
                if role == "AXStaticText" and selection.is_status(val):
                    mark, _ = "  <== status line", hits.append(str(val))
                elif role in selection._SKIP_ROLES:
                    mark = "  (data view: not entered)"
                if d <= 4 or val is not None:
                    out(f"     {'  ' * d}{role} kids={len(kids)}"
                        f"{' title=' + _short(title) if title else ''}"
                        f"{' value=' + _short(val) if val is not None else ''}{mark}")
                if role not in selection._SKIP_ROLES and d < MAX_DEPTH:
                    nxt.extend((k, d + 1) for k in kids)
                if n >= MAX_NODES:
                    out(f"     … {MAX_NODES} 要素で打ち切り")
                    break
            level = nxt
        out(f"     tree walk: {n} elements, {(time.monotonic() - t0) * 1000:.0f} ms")
        if hits:
            return hits[0]
    return None


def run() -> Path:
    out = Out()
    out(f"Set Agent follow-check  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    out(f"     {platform.platform()}  python {sys.version.split()[0]}  frozen={getattr(sys, 'frozen', False)}")
    out(f"     executable: {sys.executable}")
    text = None
    try:
        if sys.platform == "darwin":
            text = _mac(out)
        else:
            t, why = selection.status_text(selection.WALK_POLL_S)
            out(f"[{'OK' if t else 'NG'}] status_text: why={why} text={t!r}")
            text = t
    except Exception:
        out("[NG] 例外:\n" + traceback.format_exc())

    t0 = time.monotonic()
    t, why = selection.status_text(selection.WALK_POLL_S)
    out(f"[{'OK' if t else 'NG'}] Set Agent が使う読み取り: why={why} ({(time.monotonic() - t0) * 1000:.0f} ms) text={t!r}")
    text = t or text
    st = selection.parse(text) if text else None
    out(f"[{'OK' if st else 'NG'}] ステータス行の解釈: {st and (st.tracks, st.minutes, round(st.size_mib, 1), st.size_step)}")

    if st:
        try:
            from setagent.rekordbox.library import Library
            lib = Library.open()
            fp = selection.Fingerprints.build(lib.db.con)
            hits = fp.match(st)
            out(f"[{'OK' if hits else 'NG'}] プレイリストとの照合: {[(h[0], h[1]) for h in hits] or '一致なし'}")
            if not hits:
                near = sorted(fp.rows, key=lambda r: (abs(r[2] - st.tracks), abs(r[3] / 60 - st.minutes)))[:5]
                for pid, name, cnt, secs, mib, _ in near:
                    out(f"     近い候補: {name!r} {cnt} 曲 {secs / 60:.1f} 分 {mib:.1f} MiB")
        except Exception:
            out("[NG] ライブラリ:\n" + traceback.format_exc())

    from setagent.settings import app_home
    path = app_home() / "follow-check.txt"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(out.lines) + "\n", encoding="utf-8")
        print(f"\n→ {path}")
    except OSError as ex:
        print(f"(書き出せません: {ex})")
    return path


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
