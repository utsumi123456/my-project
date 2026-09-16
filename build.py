"""Build the distributable and lay out the zip the team receives.

  python build.py           build exe + package
  python build.py --skip    package only (reuse dist/SetAgentTimeline.exe)

Produces  dist/SetAgent_<date>.zip  containing the exe and the readme, so a
teammate unzips one folder and double-clicks one file. dist/ holds only the
zips; the raw exe PyInstaller emits lives under build/exe/ (a work area) so
nobody hands out the wrong file.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent
DIST = ROOT / "dist"
WORK = ROOT / "build" / "exe"
EXE = WORK / "SetAgentTimeline.exe"
NAME = f"SetAgent_{date.today():%Y%m%d}"


def build_exe() -> None:
    # index.html must ride along: it *is* the UI. webview.platforms.winforms is
    # imported lazily by pywebview, so PyInstaller cannot see it on its own.
    ui = ROOT / "setagent" / "webui" / "index.html"
    if not ui.exists():
        raise SystemExit(f"{ui} がありません。UI を同梱できません")
    cmd = [sys.executable, "-m", "PyInstaller", "--onefile", "--noconsole", "--clean",
           "--name", "SetAgentTimeline", "--paths", ".",
           "--distpath", str(WORK), "--workpath", str(ROOT / "build" / "pyinstaller"),
           "--add-data", f"{ui}{os.pathsep}setagent/webui",
           "--hidden-import", "tools.decrypt_masterdb",
           "--hidden-import", "webview.platforms.winforms",
           "--hidden-import", "clr_loader",
           "run_timeline.py"]
    print(" ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def package() -> Path:
    if not EXE.exists():
        raise SystemExit(f"{EXE} がありません。--skip を外して先にビルドしてください")
    DIST.mkdir(exist_ok=True)
    out = DIST / f"{NAME}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(EXE, f"{NAME}/SetAgentTimeline.exe")
        for f in sorted((ROOT / "dist_readme").glob("*")):
            z.write(f, f"{NAME}/{f.name}")
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
