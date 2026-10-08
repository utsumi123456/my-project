"""When and how a write-back runs (A): now, when rekordbox quits, or quit ->
write -> relaunch. The write itself is rekordbox.writeback.Writer; this module
only decides the moment and keeps the DJ informed.

Every job runs on its own background thread so the panel never freezes, and
reports through `status()` (polled by the view) and `notices` (shown once in
the agent drawer). Only one job at a time; a new one replaces a queued one.

A queued job lives only as long as this Set Agent process. A write the DJ asked
for last night must not fire by surprise tomorrow, so nothing is persisted.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from setagent.rekordbox.writeback import PublishPlan, PublishResult, Writer

HOW = ("now", "when_closed", "quit_write_relaunch")


@dataclass
class Job:
    plan: PublishPlan
    how: str
    force: bool = False
    state: str = "queued"          # queued | waiting | quitting | writing | relaunching | done | cancelled
    started: float = 0.0


class Publisher:
    def __init__(self, writer: Writer, master_db: Callable[[], Path], *,
                 running: Callable[[], bool] | None = None,
                 quit_app: Callable[..., dict] | None = None,
                 launch: Callable[..., dict] | None = None,
                 remembered_exe: Callable[[], str | None] = lambda: None,
                 poll_s: float = 2.0):
        from setagent.webui import rbrestart
        self.writer = writer
        self.master_db = master_db
        self.running = running or writer.running
        self.quit_app = quit_app or rbrestart.quit_app
        self.launch = launch or rbrestart.launch
        self.remembered_exe = remembered_exe
        self.poll_s = poll_s
        self.job: Job | None = None
        self.last: PublishResult | None = None
        self.last_exe: str | None = None
        self.needs_force = False                  # quit was refused by rekordbox (unsaved prompt)
        self.notices: deque[str] = deque(maxlen=8)
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------- control
    def submit(self, plan: PublishPlan, how: str, force: bool = False) -> dict:
        if how not in HOW:
            return {"ok": False, "error": f"不明な書き込み方法です: {how}"}
        with self._lock:
            if self.job and self.job.state in ("quitting", "writing", "relaunching"):
                return {"ok": False, "error": "書き込みの途中です。終わるまでお待ちください"}
            if self._thread and self._thread.is_alive():
                self._cancel.set()                 # a queued job gives way to the new one
                self._thread.join(timeout=self.poll_s * 2 + 1)
            self._cancel = threading.Event()
            self.needs_force = False
            self.job = Job(plan, how, force, started=time.monotonic())
            self._thread = threading.Thread(target=self._run, args=(self.job, self._cancel),
                                            name="setagent-publish", daemon=True)
            self._thread.start()
        return {"ok": True, **self.status()}

    def cancel(self) -> dict:
        with self._lock:
            j = self.job
            if j and j.state in ("queued", "waiting"):
                self._cancel.set()
                j.state = "cancelled"
                self.notices.append(f"「{j.plan.name}」の書き込み予約を取り消しました")
                return {"ok": True, **self.status()}
        return {"ok": False, "error": "取り消せる予約はありません", **self.status()}

    def wait(self, timeout: float = 30.0) -> bool:
        t = self._thread
        if t:
            t.join(timeout)
            return not t.is_alive()
        return True

    def status(self) -> dict:
        j = self.job
        active = bool(j and j.state not in ("done", "cancelled"))
        return {
            "active": active,
            "state": j.state if j else "idle",
            "how": j.how if j else "",
            "name": j.plan.name if j else "",
            "tracks": len(j.plan.track_ids) if j else 0,
            "needs_force": self.needs_force,
            "last": self.last.to_json() if self.last else None,
        }

    # ------------------------------------------------------------- worker
    def _run(self, job: Job, cancel: threading.Event) -> None:
        try:
            relaunch_exe = None
            if job.how == "when_closed":
                job.state = "waiting"
                # two clean polls in a row: rekordbox is gone, not mid-restart
                clear = 0
                while clear < 2:
                    if cancel.wait(self.poll_s):
                        return
                    clear = clear + 1 if not self.running() else 0
                time.sleep(1.0)                    # let the last file handle go
            elif job.how == "quit_write_relaunch":
                job.state = "quitting"
                q = self.quit_app(force=job.force)
                if not q.get("ok"):
                    self.needs_force = q.get("action") == "still_running"
                    self._finish(job, PublishResult(False, job.plan.name, error=q.get("error", "rekordbox を終了できませんでした")))
                    return
                relaunch_exe = q.get("exe") or self.remembered_exe()
                if relaunch_exe:
                    self.last_exe = relaunch_exe
            if cancel.is_set():
                return
            job.state = "writing"
            res = self.writer.publish(self.master_db(), job.plan)
            if job.how == "quit_write_relaunch":
                job.state = "relaunching"
                lr = self.launch(relaunch_exe)
                if not lr.get("ok") and res.ok:
                    res.error = "書き込みは完了しました。rekordbox は手で起動してください（" + lr.get("error", "") + "）"
            self._finish(job, res)
        except Exception as ex:                    # never let the thread die silently
            self._finish(job, PublishResult(False, job.plan.name, error=f"{type(ex).__name__}: {ex}"))

    def _finish(self, job: Job, res: PublishResult) -> None:
        self.last = res
        job.state = "done"
        if res.ok:
            verb = "上書きしました" if res.replaced else "作成しました"
            self.notices.append(f"rekordbox の「Set Agent」フォルダに「{res.name}」（{res.tracks} 曲）を{verb}。"
                                f"書き込み前のバックアップ: {res.backup_id}")
        else:
            self.notices.append(f"rekordbox への書き込みはできませんでした: {res.error}")
