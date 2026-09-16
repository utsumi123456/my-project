"""Build the distributable the team receives.

  python build.py           build exe + lay out dist/
  python build.py --skip    lay out only (reuse build/exe/SetAgent.exe)

Produces  dist/SetAgent.exe  (the one file to hand out; it is exactly the
exe that runs here) next to  dist/はじめに.md.  No zip: one file, double-click.
PyInstaller's own output goes under build/ so dist/ never holds two exes.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
DIST = ROOT / "dist"
WORK = ROOT / "build" / "exe"
EXE = WORK / "SetAgent.exe"


def build_exe() -> None:
    # index.html must ride along: it *is* the UI. webview.platforms.winforms is
    # imported lazily by pywebview, so PyInstaller cannot see it on its own.
    ui = ROOT / "setagent" / "webui" / "index.html"
    if not ui.exists():
        raise SystemExit(f"{ui} がありません。UI を同梱できません")
    cmd = [sys.executable, "-m", "PyInstaller", "--onefile", "--noconsole", "--clean",
           "--name", "SetAgent", "--paths", ".",
           "--distpath", str(WORK), "--workpath", str(ROOT / "build" / "pyinstaller"),
           "--add-data", f"{ui}{os.pathsep}setagent/webui",
           "--hidden-import", "tools.decrypt_masterdb",
           "--hidden-import", "webview.platforms.winforms",
           "--hidden-import", "clr_loader",
           "run_setagent.py"]
    print(" ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def package() -> Path:
    if not EXE.exists():
        raise SystemExit(f"{EXE} がありません。--skip を外して先にビルドしてください")
    DIST.mkdir(exist_ok=True)
    for old in DIST.glob("*"):
        if old.is_file():
            old.unlink()                        # dist/ is exactly what gets handed out
    out = DIST / EXE.name
    shutil.copy2(EXE, out)
    for f in sorted((ROOT / "dist_readme").glob("*")):
        shutil.copy2(f, DIST / f.name)
    print(f"{out}  ({out.stat().st_size / 1e6:.1f} MB)")
    return out


def main() -> int:
    r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"],
                       cwd=ROOT)
    if r.returncode:
        print("テストが失敗しています。配布物は作りません")
        return r.returncode
    if "--skip" not in sys.argv:
        build_exe()
    package()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
