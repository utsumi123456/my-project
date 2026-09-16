"""End-to-end smoke test on a real library, as a teammate would meet it.

  set SETAGENT_HOME=<empty dir>
  python -m tools.smoke_firstrun <out.png>

First run: open the workbench cold, change a couple of settings, close it properly.
Second run: reopen and check the settings came back. Prints PASS/FAIL per step so a
failure is readable without a debugger.
"""
from __future__ import annotations

import sys

import setagent.gui.timeline as T
from setagent.rekordbox.library import Library
from setagent.settings import Settings
from tools.winshot import settle, shoot

out = sys.argv[1] if len(sys.argv) > 1 else "firstrun.png"
ok = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok
    ok = ok and cond
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")


check("設定ファイルが未作成で始まる", not Settings.path().exists(), str(Settings.path()))

lib = Library.open()
check("ライブラリを開けた", True, f"playlists={len(lib.playlists())} warnings={len(lib.warnings)}")

app = T.App(lib)
settle(app)
check("プレイリストが選ばれた", app.pl_combo.current() >= 0, app.pl_combo.get())
check("状態表示が出ている", bool(app.status.get()), app.status.get()[:60])
check("エージェントが使える", app.agent is not None, app.agent.status()[:50])

# change things the way a user would, then close the window properly
app.target_entry.delete(0, "end"); app.target_entry.insert(0, "45:00")
app.preset.set("two_drop")
app.curve_var.set("peak_mid (中盤ピーク)"); app.apply_template()
app.level.set("proactive"); app.set_level()
app.load()
settle(app)
shoot(app, out)
app.on_close()

s = Settings.load()
check("設定が保存された", Settings.path().exists(), str(Settings.path()))
check("目標尺が残った", s.target == "45:00", s.target)
check("プリセットが残った", s.preset == "two_drop", s.preset)
check("カーブが残った", s.curve.startswith("peak_mid"), s.curve)
check("介入度が残った", s.level == "proactive", s.level)
saved_playlist = s.playlist

lib2 = Library.open()
app2 = T.App(lib2)
settle(app2)
check("再起動でプレイリストが復元された",
      app2.pl_combo.get().startswith(saved_playlist), f"{saved_playlist} -> {app2.pl_combo.get()}")
check("再起動で目標尺が復元された", app2.target_entry.get() == "45:00", app2.target_entry.get())
check("再起動でカーブが復元された", app2.curve_var.get().startswith("peak_mid"), app2.curve_var.get())
check("目標カーブが描かれる状態", app2.tools.curve is not None, str(app2.tools.curve is not None))
app2.destroy()

print("captured", out)
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
