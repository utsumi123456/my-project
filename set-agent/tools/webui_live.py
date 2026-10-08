"""The real panel, real bridge, in an ordinary browser -- for development only.

  python -m tools.webui_live [playlist] [port]

webui_harness answers the bridge from a frozen fixture, so it cannot exercise
flows that call new methods (the write-back sheet, backups, docking status).
This serves index.html through webui.remote's transport but answers *every*
call from a real Api, as the PC panel would (no phone allowlist), bound to
127.0.0.1 only. Point SETAGENT_MASTER_DB at a copy of the library before
trying a write; this tool refuses to start on the live library.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from setagent.rekordbox.library import default_master_db_candidates, find_master_db
from setagent.webui import remote
from setagent.webui.api import Api
from setagent.webui.app import index_path


class LiveServer(remote.RemoteServer):
    def __init__(self, api, index: Path):
        super().__init__(api, index)
        self.host = "127.0.0.1"

    def page(self) -> bytes:
        html = super().page().decode("utf-8")
        html = html.replace("window.SETAGENT_REMOTE = true;", "window.SETAGENT_REMOTE = false;", 1)
        html = html.replace("window.SETAGENT_CLIENT = me;", 'window.SETAGENT_CLIENT = "pc";', 1)
        return html.encode("utf-8")

    def call(self, name: str, args, client: str) -> dict:
        if name.startswith("_") or name in ("remote_start", "remote_stop", "claude_login"):
            return {"error": "webui_live では使えません"}
        fn = getattr(self.api, name, None)
        if fn is None or not callable(fn):
            return {"error": f"unknown call {name}"}
        token = self.api.origin.set("pc")
        try:
            return fn(*(args if isinstance(args, list) else []))
        except TypeError as e:
            return {"error": f"呼び出しの引数が不正です: {e}"}
        finally:
            self.api.origin.reset(token)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    mdb = find_master_db().resolve()
    live = {p.resolve() for p in default_master_db_candidates(include_env=False) if p.exists()}
    if mdb in live and "--allow-live" not in sys.argv:
        raise SystemExit("本物のライブラリでは起動しません。SETAGENT_MASTER_DB にコピーを指定してください")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    api = Api(args[0] if args else None)
    srv = LiveServer(api, Path(index_path()))
    srv.start()
    print(f"webui_live: {srv.url('127.0.0.1')}  (library: {mdb})", flush=True)
    try:
        srv._thread.join()
    except KeyboardInterrupt:
        srv.stop()


if __name__ == "__main__":
    main()
